"""Owned ephemeral-loopback HTTP fixtures for EVAL-002B; never model evidence.

An endpoint capability is valid only while its issuing server is active in this
process. It is deliberately not a URL configuration surface. Server receipts
are collected independently of the candidate transport's counters.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class SyntheticEndpointError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyntheticEndpoint:
    port: int
    path: str
    fixture_id: str

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self) -> str:
        return self.origin + self.path


_OWNED_ENDPOINTS: dict[int, SyntheticHTTPServer] = {}


def is_active_synthetic_origin(host: str, port: int) -> bool:
    """Read-only process-local helper for isolated test network guards."""
    return host == "127.0.0.1" and any(
        owner.active and owner.endpoint is not None and owner.endpoint.port == port
        for owner in _OWNED_ENDPOINTS.values()
    )


def require_owned_endpoint(endpoint: SyntheticEndpoint) -> None:
    owner = _OWNED_ENDPOINTS.get(id(endpoint))
    if (
        type(endpoint) is not SyntheticEndpoint
        or owner is None
        or not owner.active
        or owner.endpoint is not endpoint
        or owner._server is None
        or not owner._server.sockets
        or owner._server.sockets[0].getsockname() != ("127.0.0.1", endpoint.port)
        or not endpoint.path.startswith("/synthetic-http-v1/")
        or endpoint.port == 1234
    ):
        raise SyntheticEndpointError("ACTIVE_OWNED_SYNTHETIC_ENDPOINT_REQUIRED")


@dataclass(frozen=True)
class SyntheticReply:
    status_code: int = 200
    body: bytes = b"{}"
    headers: tuple[tuple[str, str], ...] = (("content-type", "application/json"),)
    chunk_size: int = 1024
    header_delay_seconds: float = 0.0
    chunk_delay_seconds: float = 0.0
    close_before_headers: bool = False
    truncate_after_bytes: int | None = None
    chunked: bool = False

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 200 <= self.status_code <= 599:
            raise ValueError("SYNTHETIC_FINAL_STATUS_REQUIRED")
        if type(self.body) is not bytes or len(self.body) > 2_000_000:
            raise ValueError("BOUNDED_SYNTHETIC_BYTES_REQUIRED")
        if type(self.chunk_size) is not int or not 1 <= self.chunk_size <= 8192:
            raise ValueError("BOUNDED_SYNTHETIC_CHUNK_REQUIRED")
        for delay in (self.header_delay_seconds, self.chunk_delay_seconds):
            if type(delay) not in (int, float) or not math.isfinite(delay) or not 0 <= delay <= 5:
                raise ValueError("BOUNDED_SYNTHETIC_DELAY_REQUIRED")
        if type(self.close_before_headers) is not bool or type(self.chunked) is not bool:
            raise ValueError("SYNTHETIC_BOOLEAN_REQUIRED")
        if self.truncate_after_bytes is not None and (
            type(self.truncate_after_bytes) is not int
            or not 0 <= self.truncate_after_bytes < len(self.body)
        ):
            raise ValueError("SYNTHETIC_TRUNCATION_REQUIRED")
        if type(self.headers) is not tuple:
            raise ValueError("IMMUTABLE_SYNTHETIC_HEADERS_REQUIRED")
        for pair in self.headers:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("SYNTHETIC_HEADER_PAIR_REQUIRED")
            name, value = pair
            if (
                type(name) is not str
                or type(value) is not str
                or not name
                or any(
                    c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-" for c in name
                )
                or any(c in value for c in "\r\n")
                or name.lower() in {"content-length", "transfer-encoding", "connection"}
            ):
                raise ValueError("SYNTHETIC_HEADER_INVALID")
            (name + value).encode("ascii")

    @classmethod
    def json(cls, value: Any, **kwargs: Any) -> SyntheticReply:
        return cls(
            body=json.dumps(value, separators=(",", ":"), allow_nan=False).encode(), **kwargs
        )


class SyntheticHTTPServer:
    """A real local socket server with synthetic responses and receipt custody.

    Receipts report observed request headers and complete/partial body facts;
    they do not assert that an OS socket send reached the server if it did not.
    Connections without complete headers are separately counted.
    """

    def __init__(self, reply: SyntheticReply | None = None) -> None:
        if reply is not None and type(reply) is not SyntheticReply:
            raise ValueError("EXACT_SYNTHETIC_REPLY_REQUIRED")
        self.reply = reply or SyntheticReply()
        self.endpoint: SyntheticEndpoint | None = None
        self.active = False
        self._server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task[Any]] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._receipts: list[dict[str, Any]] = []
        self._connections = 0
        self._errors: list[str] = []

    @property
    def receipts(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(MappingProxyType(dict(receipt)) for receipt in self._receipts)

    @property
    def connection_count(self) -> int:
        return self._connections

    @property
    def request_count(self) -> int:
        return len(self._receipts)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    async def __aenter__(self) -> SyntheticHTTPServer:
        if self.active or self._server is not None:
            raise SyntheticEndpointError("SYNTHETIC_SERVER_SINGLE_LIFETIME")
        self._server = await asyncio.start_server(self._receive, "127.0.0.1", 0, limit=16_384)
        port = self._server.sockets[0].getsockname()[1]
        if port == 1234:
            self._server.close()
            await self._server.wait_closed()
            raise SyntheticEndpointError("RESERVED_REAL_SERVICE_PORT_REJECTED")
        self.endpoint = SyntheticEndpoint(
            port,
            "/synthetic-http-v1/" + secrets.token_hex(12),
            "SYNTHETIC_HTTP1_" + secrets.token_hex(12),
        )
        self.active = True
        _OWNED_ENDPOINTS[id(self.endpoint)] = self
        return self

    async def __aexit__(self, *_args: Any) -> None:
        self.active = False
        if self.endpoint is not None:
            _OWNED_ENDPOINTS.pop(id(self.endpoint), None)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        for writer in tuple(self._writers):
            writer.close()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _receive(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        self._writers.add(writer)
        self._connections += 1
        receipt: dict[str, Any] | None = None
        try:
            async with asyncio.timeout(10):
                raw_headers = await reader.readuntil(b"\r\n\r\n")
                if len(raw_headers) > 16_384:
                    raise ValueError("SYNTHETIC_REQUEST_HEADERS_TOO_LARGE")
                lines = raw_headers[:-4].split(b"\r\n")
                method, path, version = lines[0].decode("ascii").split(" ")
                headers = tuple(tuple(line.decode("ascii").split(":", 1)) for line in lines[1:])
                normalized = {name.lower(): value.strip() for name, value in headers}
                length = int(normalized.get("content-length", "0"))
                receipt = {
                    "fixture_source": "SYNTHETIC_OWNED_LOOPBACK_HTTP1",
                    "request_index": len(self._receipts) + 1,
                    "headers_received": True,
                    "body_received": False,
                    "method": method,
                    "path": path,
                    "http_version": version,
                    "headers": tuple((name, value.strip()) for name, value in headers),
                    "declared_body_bytes": length,
                    "received_body_bytes": 0,
                    "request_sha256": None,
                }
                self._receipts.append(receipt)
                if not 0 <= length <= 200_000 or "transfer-encoding" in normalized:
                    raise ValueError("SYNTHETIC_REQUEST_FRAMING_REJECTED")
                body = bytearray()
                while len(body) < length:
                    part = await reader.read(min(8192, length - len(body)))
                    if not part:
                        raise ValueError("SYNTHETIC_REQUEST_BODY_INCOMPLETE")
                    body.extend(part)
                    receipt["received_body_bytes"] = len(body)
                receipt["body_received"] = True
                receipt["request_sha256"] = hashlib.sha256(body).hexdigest()
                assert self.endpoint is not None
                if method != "POST" or path != self.endpoint.path or version != "HTTP/1.1":
                    raise ValueError("SYNTHETIC_REQUEST_TARGET_REJECTED")
                if self.reply.close_before_headers:
                    return
                await asyncio.sleep(self.reply.header_delay_seconds)
                reply_headers = list(self.reply.headers)
                if self.reply.chunked:
                    reply_headers.append(("transfer-encoding", "chunked"))
                else:
                    reply_headers.append(("content-length", str(len(self.reply.body))))
                reply_headers.append(("connection", "close"))
                response = f"HTTP/1.1 {self.reply.status_code} Synthetic\r\n".encode("ascii")
                response += b"".join(
                    f"{name}: {value}\r\n".encode("ascii") for name, value in reply_headers
                )
                writer.write(response + b"\r\n")
                await writer.drain()
                end = self.reply.truncate_after_bytes
                payload = self.reply.body if end is None else self.reply.body[:end]
                for offset in range(0, len(payload), self.reply.chunk_size):
                    part = payload[offset : offset + self.reply.chunk_size]
                    if self.reply.chunked:
                        part = f"{len(part):x}\r\n".encode() + part + b"\r\n"
                    writer.write(part)
                    await writer.drain()
                    if self.reply.chunk_delay_seconds:
                        await asyncio.sleep(self.reply.chunk_delay_seconds)
                if self.reply.chunked and end is None:
                    writer.write(b"0\r\n\r\n")
                    await writer.drain()
        except asyncio.CancelledError:
            raise
        except (
            OSError,
            ValueError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            TimeoutError,
        ) as exc:
            self._errors.append(type(exc).__name__)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self._writers.discard(writer)
            self._tasks.discard(task)
