"""Stateless Channel B discovery-only composition. No execution capability.

Cloud metadata is not caller authentication. No Gateway, adapter, journal,
credential reader, authority issuer, recovery or execution-enabling option exists.
"""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Annotated, Any, Protocol

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, Tool
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.models.requests import Award, Recipient, Search
from civicgate.models.responses import Envelope

MAX_BODY = 65536
DISABLED = "EXECUTION_DISABLED: caller identity and acknowledged durable intent are unavailable"
UserRequest = Annotated[str, Field(min_length=1, max_length=4000)]


class LocalTestAdmission(Protocol):
    """Only a trusted local test host supplies this; never an execution grant."""

    principals: tuple[str, ...]

    def authenticate(self, headers: dict[bytes, bytes]) -> str: ...


@dataclass(frozen=True)
class Limits:
    total: int = 8
    per_caller: int = 2
    body_seconds: float = 2
    request_seconds: float = 5

    def __post_init__(self) -> None:
        if (
            type(self.total) is not int
            or not 2 <= self.total <= 8
            or type(self.per_caller) is not int
            or not 1 <= self.per_caller < self.total
            or not 0 < self.body_seconds <= 2
            or not 0 < self.request_seconds <= 5
        ):
            raise ValueError("Bounded local resource limits required")


class _MetadataServer(FastMCP):
    def seal(self) -> None:
        self._bounded = BoundedToolDiscovery(self._tool_manager.list_tools())

    async def list_tools(self) -> list[Tool]:
        return self._bounded.list_tools(self._tool_manager.list_tools())

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        self._bounded.validate(self._tool_manager.list_tools())
        raise ToolError(DISABLED)


def _register(server: _MetadataServer) -> None:
    # Preserve existing public schemas; wrappers themselves also cannot execute.
    @server.tool()
    async def find_federal_awards(user_request: UserRequest, query: Search) -> Envelope:
        """Generic public award metadata only; invocation disabled."""
        raise ToolError(DISABLED)

    @server.tool()
    async def get_federal_award(user_request: UserRequest, query: Award) -> Envelope:
        """Public award detail metadata only; invocation disabled."""
        raise ToolError(DISABLED)

    @server.tool()
    async def resolve_federal_recipient(user_request: UserRequest, query: Recipient) -> Envelope:
        """Recipient candidate metadata only; invocation disabled."""
        raise ToolError(DISABLED)

    @server.tool()
    async def summarize_federal_spending(user_request: UserRequest, query: Search) -> Envelope:
        """Returned-page summary metadata only; invocation disabled."""
        raise ToolError(DISABLED)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate key")
        obj[key] = value
    return obj


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON")


class CloudSmokeApp:
    """Finite metadata service; all callers have zero execution capability.

    Local test admission optionally attributes resource slots to verified
    synthetic callers. Cloud mode has only one anonymous metadata budget.
    Counters are process-local resource bounds, not durable execution evidence.
    """

    def __init__(
        self,
        *,
        hosts: tuple[str, ...],
        local_test: LocalTestAdmission | None = None,
        limits: Limits | None = None,
    ) -> None:
        limits = limits if limits is not None else Limits()
        if version("mcp") != "1.30.0":
            raise ValueError("mcp==1.30.0 required")
        if (
            type(hosts) is not tuple
            or not 1 <= len(hosts) <= 3
            or any(
                not h
                or len(h) > 253
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-:" for c in h)
                for h in hosts
            )
        ):
            raise ValueError("Explicit bounded hosts required; no wildcard")
        if local_test is not None and (
            not 1 <= len(local_test.principals) <= 4
            or len(set(local_test.principals)) != len(local_test.principals)
        ):
            raise ValueError("Finite distinct local synthetic enrollment required")
        self._hosts, self._local_test, self._limits = hosts, local_test, limits
        self._counts = dict.fromkeys(
            local_test.principals if local_test else ("anonymous-metadata",), 0
        )
        self._inflight = 0
        self._started = False
        self.server = _MetadataServer(
            "CIVICGATE B2B-MVP-002 DISCOVERY ONLY",
            json_response=True,
            stateless_http=True,
            streamable_http_path="/mcp",
            max_request_body_size=MAX_BODY,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=list(hosts),
                allowed_origins=[f"{s}://{h}" for s in ("http", "https") for h in hosts],
            ),
        )
        _register(self.server)
        self.server.seal()
        self._app = self.server.streamable_http_app()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            if self._started:
                raise RuntimeError("Lifecycle cannot restart")
            self._started = True
            await self._app(scope, receive, send)
            return
        if scope["type"] != "http":
            return

        async def reject(status: int, reason: str) -> None:
            await JSONResponse(
                {"error": reason, "execution_enabled": False, "retry_authorized": False},
                status_code=status,
            )(scope, receive, send)

        headers: dict[bytes, bytes] = {}
        if len(scope["headers"]) > 64 or sum(len(k) + len(v) for k, v in scope["headers"]) > 16384:
            await reject(431, "Header bound")
            return
        for key, value in scope["headers"]:
            key = key.lower()
            if key in headers or len(value) > 8192:
                await reject(400, "Ambiguous headers")
                return
            headers[key] = value
        if headers.get(b"host", b"").decode("ascii", errors="replace") not in self._hosts:
            await reject(403, "Host rejected")
            return
        if b"origin" in headers and headers[b"origin"].decode("ascii", errors="replace") not in {
            f"{s}://{h}" for s in ("http", "https") for h in self._hosts
        }:
            await reject(403, "Origin rejected")
            return
        if scope.get("query_string"):
            await reject(404, "No query route")
            return
        if scope["path"] == "/health" and scope["method"] == "GET":
            await JSONResponse(
                {
                    "status": "alive",
                    "profile": "DISCOVERY_ONLY",
                    "execution_enabled": False,
                    "caller_identity_verified": False,
                    "durable_execution_ready": False,
                }
            )(scope, receive, send)
            return
        if scope["path"] != "/mcp":
            await reject(404, "Explicit /mcp route required")
            return
        if scope["method"] != "POST":
            await reject(405, "No streaming, resumption or session deletion")
            return
        if any(h in headers for h in (b"mcp-session-id", b"last-event-id", b"content-encoding")):
            await reject(400, "Session, recovery and compression unavailable")
            return
        principal = "anonymous-metadata"
        if self._local_test is not None:
            peer = scope.get("client")
            if not peer or peer[0] != "127.0.0.1":
                await reject(403, "Synthetic identity tests are loopback-only")
                return
            try:
                principal = self._local_test.authenticate(headers)
                if principal not in self._counts:
                    raise ValueError("Not enrolled")
            except (ValueError, RuntimeError, UnicodeError):
                await reject(401, "Synthetic credential rejected")
                return
        # In cloud mode, Authorization/x-forwarded-* are deliberately never
        # parsed, used to partition callers, logged or interpreted as authority.
        if (
            self._inflight >= self._limits.total
            or self._counts[principal] >= self._limits.per_caller
        ):
            await reject(429, "Metadata capacity reached")
            return
        self._inflight += 1
        self._counts[principal] += 1
        started = False

        async def observed_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            body = bytearray()
            async with asyncio.timeout(self._limits.body_seconds):
                while True:
                    message = await receive()
                    if message["type"] != "http.request":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > MAX_BODY:
                        await reject(413, "Body bound")
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
            try:
                obj = json.loads(body, object_pairs_hook=_pairs, parse_constant=_constant)
                if not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0":
                    raise ValueError("Single JSON-RPC object required")
            except (ValueError, UnicodeError, RecursionError):
                await reject(400, "Invalid JSON-RPC")
                return
            # Explicit finite public surface; SDK still performs protocol/schema validation.
            if type(obj.get("method")) is not str or obj.get("method") not in {
                "initialize",
                "notifications/initialized",
                "ping",
                "tools/list",
                "tools/call",
            }:
                await reject(400, "Unsupported method")
                return
            delivered = False

            async def buffered_receive() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            async with asyncio.timeout(self._limits.request_seconds):
                await self._app(scope, buffered_receive, observed_send)
        except TimeoutError:
            if not started:
                await reject(408, "Bounded request timeout")
            # A response already started is never replaced by fabricated success.
        finally:
            self._counts[principal] -= 1
            self._inflight -= 1


def create_cloud_smoke(hosts: tuple[str, ...]) -> CloudSmokeApp:
    """Only metadata. No trust/store configuration or execution switch is accepted."""
    return CloudSmokeApp(hosts=hosts)
