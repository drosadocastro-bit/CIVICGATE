"""Dormant exact public READ capture over the existing response-contract adapter.

No network on import/construction. The release gate is unconditionally closed in
host_gate71. A future reviewed host release must supply an exact current admission.
"""

import time
from pathlib import Path

import httpx

from . import host_gate71
from . import util71 as n
from . import util71 as p
from .public_read_v11.adapter import MAX_BYTES
from .public_read_v11.contract import ORIGIN, SEARCH_PATH
from .public_read_v11.response_contract_v2 import LIVE_PAYLOAD, SingleLiveReadV2


class _CaptureStream(httpx.AsyncByteStream):
    def __init__(self, response, owner, request_sha):
        self.response, self.owner, self.request_sha = response, owner, request_sha
        self.raw = bytearray()
        self.complete = False
        self.closed = False

    async def __aiter__(self):
        try:
            async for chunk in self.response.aiter_bytes():
                if len(self.raw) + len(chunk) > MAX_BYTES:
                    raise httpx.ReadError("PUBLIC_CAPTURE_SIZE_HOLD")
                self.raw.extend(chunk)
                yield chunk
            root = self.owner.capture_root
            body = bytes(self.raw)
            response_sha = n._write(root / "response.bin", body)
            n._write(
                root / "observed.json",
                p.canonical(
                    {
                        "state": "BODY_OBSERVED_NOT_VALIDATED",
                        "request_sha256": self.request_sha,
                        "response_sha256": response_sha,
                        "body_bytes": len(body),
                        "status_code": self.response.status_code,
                        "observed_ns": time.time_ns(),
                        "provenance": "HOST_PUBLIC_HTTP_CAPTURE",
                    }
                ),
            )
            self.complete = True
        finally:
            if not self.complete:
                self._unknown()

    def _unknown(self):
        root = self.owner.capture_root
        if (
            self.raw
            and not (root / "response.bin").exists()
            and not (root / "partial.bin").exists()
        ):
            n._write(root / "partial.bin", bytes(self.raw))
        if not (root / "unknown.json").exists():
            n._write(
                root / "unknown.json",
                p.canonical(
                    {
                        "state": "UNKNOWN_CONSUMED",
                        "retry_allowed": False,
                        "status_code": self.response.status_code,
                        "body_complete": False,
                    }
                ),
            )

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            if not self.complete:
                self._unknown()
        finally:
            await self.response.aclose()


class _CaptureTransport(httpx.AsyncBaseTransport):
    def __init__(self, delegate, owner):
        self.delegate, self.owner = delegate, owner
        self.used = False

    async def handle_async_request(self, request):
        owner = self.owner
        root = owner.capture_root
        if self.used:
            raise httpx.RequestError("PUBLIC_CAPTURE_ALREADY_CONSUMED")
        self.used = True
        try:
            owner._check_admission()
            p.require(
                request.method == "POST"
                and str(request.url) == ORIGIN + SEARCH_PATH
                and p.parse(request.content) == LIVE_PAYLOAD,
                "PUBLIC_EXACT_REQUEST_REQUIRED",
            )
            p.require(
                not any(
                    key.lower() in ("authorization", "proxy-authorization", "x-api-key", "api-key")
                    for key in request.headers
                ),
                "PUBLIC_AUTH_HEADER_FORBIDDEN",
            )
            request_sha = n._write(root / "request.bin", request.content)
            # This is the only dispatch, after durable reservation and exact bytes.
            response = await self.delegate.handle_async_request(request)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=_CaptureStream(response, owner, request_sha),
                request=request,
            )
        except BaseException:
            if not (root / "unknown.json").exists():
                n._write(
                    root / "unknown.json",
                    p.canonical(
                        {
                            "state": "UNKNOWN_CONSUMED",
                            "retry_allowed": False,
                            "body_complete": False,
                        }
                    ),
                )
            raise

    async def aclose(self):
        await self.delegate.aclose()


class CapturedPublicRead71(SingleLiveReadV2):
    def __init__(self, *, live_authorized=False, admission, capture_root):
        if not host_gate71.release_enabled():
            raise ValueError("LIVE_HOST_RELEASE_DISABLED")
        self.admission = admission
        self.capture_root = p.safe(Path(capture_root))
        p.require(self.capture_root.is_absolute(), "ABSOLUTE_CAPTURE_ROOT_REQUIRED")
        self.capture_root = self.capture_root.resolve()
        custody = p.safe(Path(admission.profile.custody_root)).resolve()
        p.require(
            self.capture_root.is_relative_to(custody) and self.capture_root != custody,
            "CAPTURE_CUSTODY_SCOPE_REQUIRED",
        )
        p.require(
            not self.capture_root.exists() and self.capture_root.parent.is_dir(),
            "FRESH_CAPTURE_DIRECTORY_REQUIRED",
        )
        self._check_admission()
        super().__init__(live_authorized=live_authorized)

    def _check_admission(self):
        if not host_gate71.release_enabled():
            raise ValueError("LIVE_HOST_RELEASE_DISABLED")
        self.admission.check()

    def _admit_request(self, path, payload):
        self._check_admission()
        return super()._admit_request(path, payload)

    def _make_transport(self):
        self._check_admission()
        self.capture_root.mkdir(exist_ok=False)
        n._write(
            self.capture_root / "reserved.json",
            p.canonical(
                {
                    "state": "CONSUMED_OUTCOME_UNKNOWN",
                    "endpoint": ORIGIN + SEARCH_PATH,
                    "query_sha256": p.sha(p.canonical(LIVE_PAYLOAD)),
                    "retry_allowed": False,
                    "provenance": "HOST_PUBLIC_HTTP_CAPTURE",
                }
            ),
        )
        try:
            return _CaptureTransport(super()._make_transport(), self)
        except BaseException:
            n._write(
                self.capture_root / "unknown.json",
                p.canonical(
                    {"state": "UNKNOWN_CONSUMED", "retry_allowed": False, "body_complete": False}
                ),
            )
            raise
