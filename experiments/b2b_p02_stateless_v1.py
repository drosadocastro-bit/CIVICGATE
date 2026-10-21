"""Loopback-only S2 experiment, not a deployment entrypoint or admission coordinator.

Stateless SDK transports reuse a host-enrolled caller's unchanged Gateway/journal.
No public constructor provision, credential issuer, policy replacement, retry or
reset endpoint. The trusted host, verification keys and store paths are external
test dependencies; request headers never enroll an identity or clear containment.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.local_journal import LocalDispatchJournal
from civicgate.audit.trace import Trace
from civicgate.llm.mock import MockProvider
from civicgate.mcp.http_app import MAX_BODY, MAX_INFLIGHT, _HTTPServer, _register_tools
from civicgate.mcp.http_identity import (
    InvocationContext,
    LocalCredentialVerifier,
    LocalHold,
    invocation_context,
)
from civicgate.mcp.tools import Gateway


@dataclass(frozen=True)
class Enrollment:
    """Host configuration, never a JSON/MCP argument or a verified fixture claim."""

    verifier: LocalCredentialVerifier
    store: Path
    transport: httpx.MockTransport


class ObservedServer(_HTTPServer):
    """Reuse B2a's exact discovery, schemas and context cleanup; count entries only."""

    handler_entries: int = 0
    cleanup_checks: int = 0
    cleanup_failures: int = 0

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        self.handler_entries += 1
        previous = invocation_context.get()
        try:
            return await super().call_tool(name, arguments)
        finally:
            self.cleanup_checks += 1
            self.cleanup_failures += int(invocation_context.get() != previous)


@dataclass
class Caller:
    enrollment: Enrollment
    journal: LocalDispatchJournal
    gateway: Gateway
    server: ObservedServer
    app: Starlette


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate key")
        value[key] = item
    return value


def reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON")


class StatelessExperiment:
    """Finite, explicitly enrolled synthetic callers, each with a private owner.

    The synthetic adapter is restricted to exact MockTransport instances.
    Auth/session/request IDs do not create authority; the reused Gateway evaluates
    policy and consumes its private ExecutionBinding immediately before dispatch.
    No method starts an HTTP listener: the test host must bind loopback explicitly.
    """

    def __init__(
        self, *, enrollments: tuple[Enrollment, ...], port: int, code_revision: str
    ) -> None:
        if version("mcp") != "1.30.0":
            raise ValueError("Pinned SDK required")
        if type(port) is not int or not 1 <= port <= 65535 or not 1 <= len(enrollments) <= 4:
            raise ValueError("Explicit bounded loopback configuration required")
        self.host = f"127.0.0.1:{port}"
        self.origin = f"http://{self.host}"
        principals = [e.verifier.domain.principal for e in enrollments]
        stores = [e.store.resolve() for e in enrollments]
        if len(set(principals)) != len(principals) or len(set(stores)) != len(stores):
            raise ValueError("Distinct pre-enrolled principals and stores required")
        for enrollment in enrollments:
            domain = enrollment.verifier.domain
            if (
                type(enrollment.verifier) is not LocalCredentialVerifier
                or type(enrollment.transport) is not httpx.MockTransport
                or domain.audience != self.origin + "/mcp"
                or not domain.issuer.startswith("https://synthetic.")
                or not domain.issuer.endswith(".invalid")
                or not domain.principal.startswith("synthetic-")
                or not domain.service_identity.startswith("synthetic-")
            ):
                raise ValueError("Synthetic externally configured identity/adapter required")
        self.callers: list[Caller] = []
        self._inflight = 0
        self._started = False
        try:
            for enrollment in enrollments:
                journal = LocalDispatchJournal(
                    enrollment.store, enrollment.verifier.domain, code_revision
                )
                try:
                    gateway = Gateway(
                        USAspending(transport=enrollment.transport, fixture=True, max_attempts=1),
                        MockProvider(),
                        Trace(),
                        dispatch_journal=journal,
                    )
                    server = ObservedServer(
                        "CivicGate P0.2 SYNTHETIC ONLY",
                        host="127.0.0.1",
                        port=port,
                        json_response=True,
                        stateless_http=True,
                        max_request_body_size=MAX_BODY,
                        transport_security=TransportSecuritySettings(
                            enable_dns_rebinding_protection=True,
                            allowed_hosts=[self.host],
                            allowed_origins=[self.origin],
                        ),
                    )
                    gateway._claim_mcp_owner(server)
                    _register_tools(server, gateway)
                    server.seal_discovery()
                    self.callers.append(
                        Caller(enrollment, journal, gateway, server, server.streamable_http_app())
                    )
                except BaseException:
                    journal.close()
                    raise
        except BaseException:
            for caller in self.callers:
                caller.journal.close()
            raise
        self._lifespan_app = Starlette(lifespan=self._lifespan)

    @asynccontextmanager
    async def _lifespan(self, app: Starlette) -> AsyncIterator[None]:
        if self._started:
            raise LocalHold("Experiment lifecycle cannot restart")
        self._started = True
        try:
            async with AsyncExitStack() as stack:
                for caller in self.callers:
                    await stack.enter_async_context(caller.app.router.lifespan_context(caller.app))
                yield
        finally:
            for caller in self.callers:
                caller.journal.close()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan_app(scope, receive, send)
            return
        if scope["type"] != "http":
            return

        async def reject(status: int, reason: str) -> None:
            await JSONResponse({"error": reason}, status_code=status)(scope, receive, send)

        headers: dict[bytes, bytes] = {}
        if len(scope["headers"]) > 64 or sum(len(k) + len(v) for k, v in scope["headers"]) > 16384:
            await reject(431, "Header limit")
            return
        for key, value in scope["headers"]:
            key = key.lower()
            if key in headers or len(value) > 8192:
                await reject(400, "Ambiguous headers")
                return
            headers[key] = value
        peer = scope.get("client")
        if (
            not peer
            or peer[0] != "127.0.0.1"
            or scope.get("scheme") != "http"
            or headers.get(b"host") != self.host.encode()
            or headers.get(b"origin", self.origin.encode()) != self.origin.encode()
        ):
            await reject(403, "Loopback Host/Origin required")
            return
        if scope["path"] != "/mcp" or scope.get("query_string"):
            await reject(404, "MCP endpoint only")
            return
        try:
            authorization = headers.get(b"authorization", b"").decode("ascii")
            if not authorization.startswith("Bearer "):
                raise LocalHold("Missing credential")
            credential = authorization[7:]
            # Bounded enrollment table. Never route using an unverified sub/header.
            verified: list[tuple[Caller, dict[str, Any]]] = []
            for caller in self.callers:
                try:
                    verified.append((caller, caller.enrollment.verifier.verify(credential)))
                except LocalHold:
                    continue
            if len(verified) != 1:
                raise LocalHold("Identity not uniquely verified")
            caller, claims = verified[0]
        except (LocalHold, UnicodeError):
            await reject(401, "Credential rejected")
            return
        if b"content-encoding" in headers or b"last-event-id" in headers:
            await reject(400, "Compression/resumption unavailable")
            return
        if self._inflight >= MAX_INFLIGHT:
            await reject(429, "Request limit")
            return
        self._inflight += 1
        try:
            body = bytearray()
            if scope["method"] == "POST":
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
                try:
                    parsed = json.loads(
                        body, object_pairs_hook=unique_object, parse_constant=reject_constant
                    )
                    if not isinstance(parsed, dict):
                        raise ValueError("Single message required")
                except (ValueError, UnicodeError, RecursionError):
                    await reject(400, "Invalid MCP JSON")
                    return
            # This context travels on the actual request, not in the shared ASGI
            # lifespan task context. B2a's existing call wrapper sets/resets the
            # ContextVar; its journal rechecks expiry after queueing and at intent.
            scope["b2a_context"] = InvocationContext(
                principal=claims["sub"],
                issuer=claims["iss"],
                audience=claims["aud"],
                session="",
                request=str(uuid4()),
                expires_at=claims["exp"],
            )
            scope["user"] = AuthenticatedUser(
                AccessToken(
                    token=credential,
                    client_id="p02-synthetic",
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
                if scope["method"] == "POST" and not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await caller.app(scope, buffered_receive, send)
        except TimeoutError:
            await reject(408, "Body timeout")
        finally:
            self._inflight -= 1
