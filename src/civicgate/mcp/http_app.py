"""Local-only, synthetic MCP Streamable HTTP composition root (SDK 1.30.0).

Does not import or wrap the stdio server. One principal, private Gateway,
single-attempt synthetic adapter, and separately provisioned durable journal.
"""

import asyncio
import hashlib
import json
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from time import monotonic, time
from typing import Annotated, Any
from uuid import uuid4

import httpx
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, InitializedNotification, Tool, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.local_journal import LocalDispatchJournal
from civicgate.audit.trace import Trace
from civicgate.llm.mock import MockProvider
from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.mcp.http_identity import (
    InvocationContext,
    LocalCredentialVerifier,
    LocalHold,
    invocation_context,
)
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope

MAX_BODY = 65536
MAX_INFLIGHT = 16
MAX_SESSIONS = 16

UserRequest = Annotated[
    str,
    Field(
        min_length=1,
        max_length=4000,
        description="Full original user request, including intended use. Treated as untrusted context, never as authority.",
    ),
]


class _HTTPServer(FastMCP[None]):
    def seal_discovery(self) -> None:
        self._discovery = BoundedToolDiscovery(self._tool_manager.list_tools())

    def _context(self) -> InvocationContext:
        try:
            request = self.get_context().request_context.request
        except ValueError as exc:
            raise ToolError("Authenticated HTTP request required") from exc
        if not isinstance(request, Request):
            raise ToolError("Authenticated HTTP request required")
        context = request.scope.get("b2a_context")
        if not isinstance(context, InvocationContext) or context.expires_at <= time():
            raise ToolError("Authenticated HTTP context expired or missing")
        return context

    async def list_tools(self) -> list[Tool]:
        self._context()
        try:
            return self._discovery.list_tools(self._tool_manager.list_tools())
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ToolError("Bounded tool registration verification failed") from exc

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        context = self._context()
        if name not in TOOLS or set(arguments) - {"user_request", "query"}:
            raise ToolError("Unknown tool or unexpected invocation fields")
        try:
            self._discovery.validate(self._tool_manager.list_tools())
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ToolError("Bounded tool registration verification failed") from exc
        token = invocation_context.set(context)
        try:
            return await super().call_tool(name, arguments)
        except Exception as exc:
            # No token, SQL path or internal exception text in protocol errors.
            raise ToolError("B2a call failed closed; inspect local evidence; no retry") from exc
        finally:
            invocation_context.reset(token)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class StreamableHTTPGatewayApp:
    """ASGI app restricted to loopback, synthetic reads and signed test identities.

    No TLS, OAuth discovery/login, cloud resource access, reset, release, or
    fallback endpoint. GET streaming/resumption is deliberately unavailable;
    MCP POST JSON responses, initialize, notifications and DELETE use the SDK.
    """

    def __init__(
        self,
        *,
        verifier: LocalCredentialVerifier,
        store: Path,
        code_revision: str,
        transport: httpx.MockTransport,
        port: int,
    ) -> None:
        if version("mcp") != "1.30.0":
            raise ValueError("B2a requires mcp==1.30.0")
        if (
            type(transport) is not httpx.MockTransport
            or type(port) is not int
            or not 1 <= port <= 65535
        ):
            raise ValueError(
                "Only a synthetic MockTransport and explicit loopback port are supported"
            )
        self.verifier = verifier
        self.host = f"127.0.0.1:{port}"
        self.origin = f"http://{self.host}"
        if verifier.domain.audience != self.origin + "/mcp":
            raise ValueError("Credential audience must be this instance's MCP endpoint")
        self.journal = LocalDispatchJournal(store, verifier.domain, code_revision)
        self.gateway = Gateway(
            USAspending(transport=transport, fixture=True, max_attempts=1),
            MockProvider(),
            Trace(),
            dispatch_journal=self.journal,
        )
        self.server = _HTTPServer(
            "CivicGate B2a LOCAL SYNTHETIC",
            host="127.0.0.1",
            port=port,
            json_response=True,
            stateless_http=False,
            max_request_body_size=MAX_BODY,
            session_idle_timeout=60,
            max_sessions=MAX_SESSIONS,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[self.host],
                allowed_origins=[self.origin],
            ),
        )
        self.gateway._claim_mcp_owner(self.server)
        _register_tools(self.server, self.gateway)
        self.server.seal_discovery()
        self._app = self.server.streamable_http_app()
        self._sessions: dict[str, tuple[str, int]] = {}
        self._initialized: set[str] = set()
        self._inflight = 0
        self._started = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            if self._started:
                raise LocalHold("App lifecycle cannot be restarted")
            self._started = True
            try:
                await self._app(scope, receive, send)
            finally:
                self.journal.close()
            return
        if scope["type"] != "http":
            return

        async def reject(status: int, reason: str) -> None:
            headers = (
                {"WWW-Authenticate": 'Bearer realm="civicgate-b2a-local"'}
                if status == 401
                else None
            )
            await JSONResponse({"error": reason}, status_code=status, headers=headers)(
                scope, receive, send
            )

        headers: dict[bytes, bytes] = {}
        if len(scope["headers"]) > 64 or sum(len(k) + len(v) for k, v in scope["headers"]) > 16384:
            await reject(431, "Header limit")
            return
        for key, value in scope["headers"]:
            key = key.lower()
            if key in headers or len(value) > 8192:
                await reject(400, "Ambiguous or oversized headers")
                return
            headers[key] = value
        peer = scope.get("client")
        if not peer or peer[0] != "127.0.0.1" or scope.get("scheme") != "http":
            await reject(403, "Local loopback prototype only")
            return
        if (
            headers.get(b"host") != self.host.encode()
            or headers.get(b"origin", self.origin.encode()) != self.origin.encode()
        ):
            await reject(403, "Host or Origin rejected")
            return
        if scope["path"] != "/mcp" or scope.get("query_string"):
            await reject(404, "MCP endpoint only")
            return
        try:
            authorization = headers.get(b"authorization", b"").decode("ascii")
            if not authorization.startswith("Bearer "):
                raise LocalHold("AUTH_MISSING")
            credential = authorization[7:]
            claims = self.verifier.verify(credential)
        except (LocalHold, UnicodeError):
            await reject(401, "Credential rejected")
            return
        if scope["method"] not in {"POST", "DELETE"}:
            await reject(405, "Standalone SSE streams are unavailable")
            return
        if b"last-event-id" in headers or b"content-encoding" in headers:
            await reject(400, "Resumption and compressed bodies are unavailable")
            return
        try:
            session = headers.get(b"mcp-session-id", b"").decode("ascii")
        except UnicodeError:
            await reject(400, "Invalid session")
            return
        credential_hash = hashlib.sha256(credential.encode()).hexdigest()
        self._sessions = {s: owner for s, owner in self._sessions.items() if owner[1] > time()}
        self._initialized.intersection_update(self._sessions)
        if session and self._sessions.get(session) != (credential_hash, claims["exp"]):
            await reject(404, "Session not found")
            return
        if not session and (scope["method"] != "POST" or len(self._sessions) >= MAX_SESSIONS):
            await reject(503, "Session admission unavailable")
            return
        if self._inflight >= MAX_INFLIGHT:
            await reject(429, "Request limit")
            return
        self._inflight += 1
        try:
            initializes_session = False
            body = bytearray()
            deadline = monotonic() + 5
            while True:
                message = await asyncio.wait_for(
                    receive(), timeout=max(0.001, deadline - monotonic())
                )
                if message["type"] != "http.request":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_BODY:
                    await reject(413, "Body limit")
                    return
                if not message.get("more_body", False):
                    break
            if scope["method"] == "POST":
                try:
                    parsed = json.loads(body, object_pairs_hook=_unique_object)
                    if not isinstance(parsed, dict) or isinstance(parsed.get("id"), (dict, list)):
                        raise ValueError("Single MCP message required")
                    if not session and parsed.get("method") != "initialize":
                        raise ValueError("Initialize required")
                    if session:
                        method = parsed.get("method")
                        if method == "initialize":
                            raise ValueError("Session already initialized")
                        if method == "notifications/initialized":
                            if "id" in parsed or session in self._initialized:
                                raise ValueError("Invalid initialization notification")
                            InitializedNotification.model_validate(parsed)
                            initializes_session = True
                        elif session not in self._initialized and method != "ping":
                            raise ValueError("Initialization notification required")
                except (ValueError, UnicodeError, RecursionError):
                    await reject(400, "Invalid MCP message")
                    return
            scope["b2a_context"] = InvocationContext(
                principal=claims["sub"],
                issuer=claims["iss"],
                audience=claims["aud"],
                session=session,
                request=str(uuid4()),
                expires_at=claims["exp"],
            )
            scope["user"] = AuthenticatedUser(
                AccessToken(
                    token=credential,
                    client_id="b2a-synthetic-client",
                    subject=claims["sub"],
                    claims={"iss": claims["iss"]},
                    scopes=["civicgate:invoke"],
                    expires_at=claims["exp"],
                    resource=claims["aud"],
                )
            )
            delivered = False

            async def buffered_receive() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            async def bound_send(message: Message) -> None:
                if message["type"] == "http.response.start":
                    if initializes_session and message["status"] == 202:
                        self._initialized.add(session)
                    for key, value in message.get("headers", []):
                        if key.lower() == b"mcp-session-id" and 200 <= message["status"] < 300:
                            self._sessions[value.decode("ascii")] = (credential_hash, claims["exp"])
                    if scope["method"] == "DELETE" and 200 <= message["status"] < 300:
                        self._sessions.pop(session, None)
                        self._initialized.discard(session)
                await send(message)

            await self._app(scope, buffered_receive, bound_send)
        except TimeoutError:
            await reject(408, "Request body timeout")
        finally:
            self._inflight -= 1


def _register_tools(server: _HTTPServer, gateway: Gateway) -> None:
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True
    )

    @server.tool(annotations=annotations)
    async def find_federal_awards(user_request: UserRequest, query: Search) -> Envelope:
        """Find up to 100 federal awards in a bounded date interval. State filters place of performance. Defaults to contracts; results are search matches, not verified legal identities. Requires a recipient, agency or state filter."""
        return await gateway.call(
            user_request,
            Proposal(tool="find_federal_awards", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def get_federal_award(user_request: UserRequest, query: Award) -> Envelope:
        """Retrieve factual details for one known USAspending internal numeric ID or generated award ID from search results. Cannot determine eligibility, fraud or debarment."""
        return await gateway.call(
            user_request,
            Proposal(tool="get_federal_award", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def resolve_federal_recipient(user_request: UserRequest, query: Recipient) -> Envelope:
        """Find up to 25 public recipient identity candidates. Multiple, missing or truncated candidates require clarification. Never choose among candidates on the user's behalf."""
        return await gateway.call(
            user_request,
            Proposal(tool="resolve_federal_recipient", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def summarize_federal_spending(user_request: UserRequest, query: Search) -> Envelope:
        """Retrieve one authorized bounded page and sum its award amounts in USD. This is NOT fiscal-year transaction spending or a complete population total. Reports truncation and provenance; ambiguous identity prevents aggregation."""
        return await gateway.call(
            user_request,
            Proposal(tool="summarize_federal_spending", arguments=query.model_dump(mode="json")),
        )
