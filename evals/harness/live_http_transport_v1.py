"""EVAL-002B synthetic-only real HTTP/1.1 transport candidate.

The logical provider origin is a protocol label. From construction onward the
only wire destination is an active owned ephemeral-loopback fixture. There is
no fallback, proxy, redirect, alternate client, pool, TLS, or network retry.

HTTPCore's installed HTTP/1.1 protocol engine is reused over an owned socket
stream. The stream independently checks every outgoing byte against one fixed
header block and its body. Durable send consumption happens immediately before
the first header emission attempt. TCP segments and sock_sendall internals are
not extra HTTP requests; counters explicitly describe HTTP header boundaries.
These are Python process boundaries, not an OS security or real-time guarantee.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import socket
import time
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType, MethodType
from typing import Any, TypedDict

import h11
import httpcore
import httpx
from httpcore._async.http11 import AsyncHTTP11Connection

from evals.harness.synthetic_http_server_v1 import SyntheticEndpoint, require_owned_endpoint


class SyntheticHTTPTransportError(RuntimeError):
    """Fixed local failure, intentionally outside HTTPX retryable errors."""


_PINS = {
    "h11": ("0.16.0", "382292e3be0e7969474a3f4776425bd259110c13c25b30c5ddbbffc0b650342d"),
    "httpcore": ("1.0.9", "20e746966af52456d0f65c2eacfd1d65f49964672350431569ff354a99ed6cb1"),
    "httpx": ("0.28.1", "957117f6b78a3ecf2dfd73d490f60cf56a745e60303e7d276138df14d993bf5b"),
}
_LOGICAL_ORIGINS = {"planner": "http://127.0.0.1:1234", "judge": "https://api.openai.com"}


class _SendBinding(TypedDict):
    observation_id: str
    role: str
    request_sha256: str
    schema_sha256: str
    logical_origin: str
    wire_fixture_origin: str
    effective_invocation_sha256: str | None


def dependency_inventory() -> dict[str, dict[str, str]]:
    inventory = {}
    for module in (h11, httpcore, httpx):
        module_file = module.__file__
        if module_file is None:
            raise SyntheticHTTPTransportError("INSTALLED_HTTP_DEPENDENCY_SOURCE_UNAVAILABLE")
        root = Path(module_file).parent
        sources = {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*.py"))
        }
        tree = hashlib.sha256(
            json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        inventory[module.__name__] = {
            "version": module.__version__,
            "python_source_tree_sha256": tree,
        }
    return inventory


def _validate_dependencies() -> dict[str, dict[str, str]]:
    inventory = dependency_inventory()
    if any(
        (entry["version"], entry["python_source_tree_sha256"]) != _PINS[name]
        for name, entry in inventory.items()
    ):
        raise SyntheticHTTPTransportError("INSTALLED_HTTP_DEPENDENCY_PIN_MISMATCH")
    return inventory


class _OneRequestStream(httpcore.AsyncNetworkStream):
    """Lower network gate, independent of handle/delegate call accounting."""

    def __init__(
        self,
        sock: socket.socket,
        header_bytes: bytes,
        body: bytes,
        owner: LiveHTTPTransport,
        lease_binding: _SendBinding,
    ) -> None:
        self._socket = sock
        self._headers = header_bytes
        self._body = body
        self._owner = owner
        self._binding = lease_binding.copy()
        self._headers_emitted = False
        self._body_offset = 0
        self._closed = False
        self._write_lock = asyncio.Lock()

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        async with self._write_lock:
            self._owner.integrity()
            if self._closed:
                raise SyntheticHTTPTransportError("CLOSED_WIRE_STREAM")
            if not isinstance(buffer, bytes):
                raise SyntheticHTTPTransportError("WIRE_BYTES_REQUIRED")
            is_header = not self._headers_emitted
            if is_header:
                if buffer != self._headers:
                    self._owner._facts["blocked_write_count"] += 1
                    raise SyntheticHTTPTransportError("FIRST_HEADER_BYTES_MISMATCH")
                # Synchronous durable consumption returns before any header bytes
                # enter a socket. A failed/late ACK never permits a send.
                self._owner._facts["send_lease_custody"] = "UNKNOWN_PENDING_ACK"
                self._owner._consume_send_lease(**self._binding)
                self._owner._facts["send_lease_acknowledged"] = True
                self._owner._facts["send_lease_custody"] = "ACKNOWLEDGED_CONSUMED"
                self._owner._guard_send_deadline("LEASE_ACK")
                self._headers_emitted = True
                self._owner._facts["header_emission_attempts"] += 1
            else:
                remaining = self._body[self._body_offset :]
                if len(buffer) > len(remaining) or buffer != remaining[: len(buffer)]:
                    self._owner._facts["blocked_write_count"] += 1
                    raise SyntheticHTTPTransportError("ADDITIONAL_OR_CHANGED_HTTP_BYTES_BLOCKED")
                self._body_offset += len(buffer)
                self._owner._facts["body_emission_attempted_bytes"] = self._body_offset
            if not buffer:
                return
            self._owner._facts["socket_write_calls"] += 1
            try:
                async with asyncio.timeout(timeout):
                    await asyncio.get_running_loop().sock_sendall(self._socket, buffer)
            except BaseException:
                self._owner._facts["wire_completion_state"] = "SEND_COMPLETION_UNKNOWN"
                raise
            if is_header:
                self._owner._facts["headers_socket_write_completed"] = True

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        if self._closed:
            raise SyntheticHTTPTransportError("CLOSED_WIRE_STREAM")
        async with asyncio.timeout(timeout):
            part = await asyncio.get_running_loop().sock_recv(self._socket, min(max_bytes, 8192))
        self._owner._facts["socket_received_bytes"] += len(part)
        return part

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._socket.close()

    async def start_tls(self, *_args: Any, **_kwargs: Any) -> Any:
        raise SyntheticHTTPTransportError("SYNTHETIC_WIRE_TLS_FORBIDDEN")

    def get_extra_info(self, _info: str) -> Any:
        return None


class LiveHTTPTransport(httpx.AsyncBaseTransport):
    """One persistent-admission-bound synthetic HTTP request; no acceptance.

    The enclosing role transport binds/reserves/starts the exact request before
    entering this class. Contract-invalid HTTP responses remain observed raw
    responses. This class owns only wire/status/read facts, never typed success.
    """

    def __init__(
        self,
        budget: Any,
        endpoint: SyntheticEndpoint,
        *,
        observation_id: str,
        role: str,
        schema_sha256: str,
        logical_origin: str,
        effective_invocation_sha256: str | None = None,
        max_response_bytes: int = 200_000,
        max_request_bytes: int = 200_000,
        io_timeout_seconds: float = 1.0,
    ) -> None:
        from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget

        if type(budget) is not LiveAttemptBudget:
            raise SyntheticHTTPTransportError("EXACT_DURABLE_ADMISSION_REQUIRED")
        require_owned_endpoint(endpoint)
        if role not in _LOGICAL_ORIGINS or logical_origin != _LOGICAL_ORIGINS[role]:
            raise SyntheticHTTPTransportError("PINNED_LOGICAL_PROVIDER_ORIGIN_REQUIRED")
        if (
            type(schema_sha256) is not str
            or len(schema_sha256) != 64
            or any(c not in "0123456789abcdef" for c in schema_sha256)
        ):
            raise ValueError("SCHEMA_SHA256_REQUIRED")
        if any(
            type(size) is not int or not 1 <= size <= 200_000
            for size in (max_response_bytes, max_request_bytes)
        ):
            raise ValueError("BOUNDED_HTTP_BODY_SIZE_REQUIRED")
        if (
            type(io_timeout_seconds) not in (int, float)
            or not math.isfinite(io_timeout_seconds)
            or not 0 < io_timeout_seconds <= 5
        ):
            raise ValueError("BOUNDED_HTTP_IO_TIMEOUT_REQUIRED")
        self._dependency_pins = _validate_dependencies()
        self._budget = budget
        self._endpoint = endpoint
        self._pinned_endpoint = endpoint
        self._consume_send_lease = budget.consume_send_lease
        self._assert_send_admissible = budget.assert_send_admissible
        self._observation_id = observation_id
        self._role = role
        self._schema_sha256 = schema_sha256
        self._logical_origin = logical_origin
        self._effective_invocation_sha256 = effective_invocation_sha256
        self._max_response_bytes = max_response_bytes
        self._max_request_bytes = max_request_bytes
        self._timeout = io_timeout_seconds
        self._send_deadline: float | None = None
        self._entered = False
        self._closed = False
        self._wire_stream: _OneRequestStream | None = None
        self._connection: AsyncHTTP11Connection | None = None
        self._facts: dict[str, Any] = {
            "wire_source": "SYNTHETIC_OWNED_LOOPBACK_HTTP1",
            "routing_disposition": "EXPLICIT_SYNTHETIC_ROUTE_FROM_CONSTRUCTION",
            "logical_origin": logical_origin,
            "wire_fixture_origin": endpoint.origin,
            "fixture_id": endpoint.fixture_id,
            "acceptance_state": "NOT_DECIDED_BY_WIRE_TRANSPORT",
            "connection_attempts": 0,
            "header_emission_attempts": 0,
            "body_emission_attempted_bytes": 0,
            "socket_write_calls": 0,
            "blocked_write_count": 0,
            "send_lease_acknowledged": False,
            "send_lease_custody": "NOT_ATTEMPTED",
            "headers_socket_write_completed": False,
            "socket_received_bytes": 0,
            "response_observed": False,
            "response_retained_bytes": 0,
            "wire_completion_state": "NOT_STARTED",
            "cancellation_state": "NOT_CANCELLED",
            "network_retries": 0,
            "redirects_followed": 0,
            "proxy_used": False,
        }

    @property
    def endpoint(self) -> SyntheticEndpoint:
        return self._endpoint

    @property
    def facts(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self._facts))

    @property
    def dependency_pins(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {name: MappingProxyType(dict(value)) for name, value in self._dependency_pins.items()}
        )

    def arm_send_deadline(self, absolute_monotonic: float) -> None:
        """One-use real monotonic deadline supplied by the enclosing role.

        A final synchronous sample gates socket emission after custody returns;
        it cannot prevent OS descheduling immediately after that sample.
        """
        if self._entered or self._send_deadline is not None:
            raise SyntheticHTTPTransportError("SEND_DEADLINE_ALREADY_ARMED_OR_ENTERED")
        if (
            type(absolute_monotonic) not in (int, float)
            or not math.isfinite(absolute_monotonic)
            or absolute_monotonic <= 0
        ):
            raise ValueError("ABSOLUTE_MONOTONIC_SEND_DEADLINE_REQUIRED")
        self._send_deadline = absolute_monotonic

    def _guard_send_deadline(self, stage: str) -> None:
        if self._send_deadline is None:
            self._facts["wire_completion_state"] = "SEND_DEADLINE_UNARMED_NO_HEADERS"
            raise SyntheticHTTPTransportError("SEND_DEADLINE_NOT_ARMED")
        if time.monotonic() >= self._send_deadline:
            self._facts["wire_completion_state"] = stage + "_AFTER_SEND_DEADLINE_NO_HEADERS"
            raise SyntheticHTTPTransportError(stage + "_AFTER_SEND_DEADLINE_NO_HEADERS")

    def integrity(self) -> None:
        from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget

        if (
            type(self._budget) is not LiveAttemptBudget
            or self._endpoint is not self._pinned_endpoint
            or self._closed
            or not isinstance(self._consume_send_lease, MethodType)
            or not isinstance(self._assert_send_admissible, MethodType)
            or type(self._consume_send_lease.__self__) is not LiveAttemptBudget
            or self._consume_send_lease.__self__ is not self._budget
            or self._consume_send_lease.__func__ is not LiveAttemptBudget.consume_send_lease
            or self._assert_send_admissible.__self__ is not self._budget
            or self._assert_send_admissible.__func__ is not LiveAttemptBudget.assert_send_admissible
        ):
            raise SyntheticHTTPTransportError("SYNTHETIC_TRANSPORT_INTEGRITY_CHANGED")
        require_owned_endpoint(self._endpoint)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.integrity()
        if self._entered:
            raise SyntheticHTTPTransportError("DUPLICATE_HTTP_REQUEST_BLOCKED")
        self._entered = True
        if (
            request.method != "POST"
            or str(request.url) != self._logical_origin + "/v1/chat/completions"
        ):
            raise SyntheticHTTPTransportError("LOGICAL_REQUEST_ENDPOINT_OR_METHOD_MISMATCH")
        try:
            body = request.content
        except httpx.RequestNotRead:
            raise SyntheticHTTPTransportError("BOUNDED_PREBUFFERED_REQUEST_REQUIRED") from None
        if len(body) > self._max_request_bytes:
            raise SyntheticHTTPTransportError("REQUEST_BODY_TOO_LARGE_NO_SEND")
        binding: _SendBinding = {
            "observation_id": self._observation_id,
            "role": self._role,
            "request_sha256": hashlib.sha256(body).hexdigest(),
            "schema_sha256": self._schema_sha256,
            "logical_origin": self._logical_origin,
            "wire_fixture_origin": self._endpoint.origin,
            "effective_invocation_sha256": self._effective_invocation_sha256,
        }
        # Admission validation precedes even a local connection attempt. Durable
        # one-use consumption repeats those checks at the actual header boundary.
        self._assert_send_admissible(**binding)
        self._guard_send_deadline("PRE_CONNECT")
        self._facts["request_sha256"] = binding["request_sha256"]
        headers = [
            (b"Host", f"127.0.0.1:{self._endpoint.port}".encode()),
            (b"Content-Type", b"application/json"),
            (b"Content-Length", str(len(body)).encode()),
            (b"Connection", b"close"),
        ]
        generator = h11.Connection(h11.CLIENT)
        header_bytes = generator.send(
            h11.Request(method=b"POST", target=self._endpoint.path.encode(), headers=headers)
        )
        assert header_bytes is not None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        core_response = None
        try:
            self._facts["connection_attempts"] += 1
            async with asyncio.timeout(self._timeout):
                await asyncio.get_running_loop().sock_connect(
                    sock, ("127.0.0.1", self._endpoint.port)
                )
            self._wire_stream = _OneRequestStream(sock, header_bytes, body, self, binding)
            origin = httpcore.Origin(b"http", b"127.0.0.1", self._endpoint.port)
            self._connection = AsyncHTTP11Connection(origin, self._wire_stream, keepalive_expiry=0)
            # Header parsing retains at most this bound plus one 8192-byte read.
            self._connection._h11_state = h11.Connection(
                h11.CLIENT, max_incomplete_event_size=16_384
            )
            core_request = httpcore.Request(
                b"POST",
                httpcore.URL(
                    scheme=b"http",
                    host=b"127.0.0.1",
                    port=self._endpoint.port,
                    target=self._endpoint.path.encode(),
                ),
                headers=headers,
                content=body,
                extensions={"timeout": {"read": self._timeout, "write": self._timeout}},
            )
            core_response = await self._connection.handle_async_request(core_request)
            self._facts["response_observed"] = True
            self._facts["http_status"] = core_response.status
            self._facts["wire_completion_state"] = "HTTP_HEADERS_OBSERVED_BODY_PENDING"
            response_headers = core_response.headers
            if sum(len(name) + len(value) + 4 for name, value in response_headers) > 16_384:
                raise SyntheticHTTPTransportError("RESPONSE_HEADERS_TOO_LARGE")
            retained = bytearray()
            async for part in core_response.aiter_stream():
                if len(part) > self._max_response_bytes - len(retained):
                    self._facts["wire_completion_state"] = "BODY_LIMIT_REJECTED"
                    raise SyntheticHTTPTransportError("RESPONSE_BODY_TOO_LARGE")
                retained.extend(part)
                self._facts["response_retained_bytes"] = len(retained)
            self._facts["wire_completion_state"] = "HTTP_BODY_READ_COMPLETE"
            raw = bytes(retained)
            self._facts["raw_body_sha256"] = hashlib.sha256(raw).hexdigest()
            encodings = httpx.Headers(response_headers).get_list("content-encoding")
            if encodings and (len(encodings) != 1 or encodings[0].strip().lower() != "identity"):
                self._facts["wire_completion_state"] = "HTTP_BODY_OBSERVED_UNSUPPORTED_ENCODING"
                raise SyntheticHTTPTransportError("UNSUPPORTED_RESPONSE_CONTENT_ENCODING")
            return httpx.Response(
                core_response.status,
                headers=response_headers,
                stream=httpx.ByteStream(raw),
                extensions={"synthetic_wire_facts": dict(self._facts)},
            )
        except asyncio.CancelledError:
            self._facts["cancellation_state"] = "CANCELLED_NO_AUTOMATIC_RETRY"
            self._facts["wire_completion_state"] = "CANCELLED_COMPLETION_UNKNOWN"
            raise
        except SyntheticHTTPTransportError:
            raise
        except Exception as exc:
            self._facts["wire_completion_state"] = "COMPLETION_UNKNOWN_NO_AUTOMATIC_RETRY"
            self._facts["wire_error_type"] = type(exc).__name__
            raise SyntheticHTTPTransportError(
                "HTTP_COMPLETION_UNKNOWN_NO_AUTOMATIC_RETRY"
            ) from None
        finally:
            if core_response is not None:
                await core_response.aclose()
            if self._connection is not None:
                await self._connection.aclose()
            else:
                sock.close()

    async def aclose(self) -> None:
        self._closed = True
        if self._connection is not None:
            await self._connection.aclose()
        elif self._wire_stream is not None:
            await self._wire_stream.aclose()
