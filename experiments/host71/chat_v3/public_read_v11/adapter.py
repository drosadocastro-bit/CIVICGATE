"""Bounded transport extension of the existing USAspending read adapter."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from civicgate.adapters.usaspending import AdapterError, AttemptRecord, RequestOutcome, USAspending
from civicgate.channel_b.faa_money_v1 import amount_text, decimal_token, integer_token
from civicgate.models.provenance import fingerprint
from civicgate.models.requests import Award, Search

from .contract import DOT, ORIGIN, SEARCH_PATH, digest

MAX_BYTES = 2_000_000
DEADLINE = 20.0
DETAIL = re.compile(r"/api/v2/awards/[A-Za-z0-9][A-Za-z0-9_.-]{0,199}/\Z")


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def invalid_constant(_value: str) -> None:
    raise ValueError("NONFINITE_NUMBER")


class PublicReadAdapter(USAspending):
    """One host-owned operation, no caller URL, retry, redirect, proxy or fallback.

    LIVE transport construction requires explicit host approval. Mock injection
    is accepted only in OFFLINE mode and is never labelled public data.
    """

    def __init__(
        self,
        *,
        mode: str = "OFFLINE",
        transport: httpx.MockTransport | None = None,
        live_authorized: bool = False,
    ) -> None:
        if mode == "LIVE":
            self._validate_live_construction()
        if mode not in {"OFFLINE", "LIVE"}:
            raise ValueError("HOST_MODE_INVALID")
        if mode == "LIVE" and (not live_authorized or transport is not None):
            raise ValueError("PUBLIC_API_LIVE_NOT_AUTHORIZED")
        if mode == "OFFLINE" and type(transport) is not httpx.MockTransport:
            raise ValueError("EXPLICIT_OFFLINE_FIXTURE_REQUIRED")
        super().__init__(transport=transport, fixture=mode == "OFFLINE", max_attempts=1)
        self.mode = mode
        self.observations: list[dict[str, Any]] = []
        self.entries = 0
        self.used = False

    def _validate_live_construction(self):
        raise ValueError("CANDIDATE08_OFFLINE_ONLY")

    async def search(self, request: Search) -> Any:
        if (
            request.limit > 20
            or request.award_types != ["A", "B", "C", "D"]
            or request.state_code != "PR"
            or request.recipient_name is not None
            or request.awarding_agency not in {None, DOT}
        ):
            raise AdapterError("MALFORMED_RESPONSE")
        self.entries += 1
        return await super().search(request)

    async def detail(self, request: Award) -> Any:
        if not DETAIL.fullmatch(f"/api/v2/awards/{request.award_id}/"):
            raise AdapterError("MALFORMED_RESPONSE")
        self.entries += 1
        return await super().detail(request)

    def _make_transport(self):
        return (
            self.transport
            if self.mode == "OFFLINE"
            else httpx.AsyncHTTPTransport(
                retries=0,
                trust_env=False,
                http2=False,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            )
        )

    async def _request(self, path: str, payload: dict[str, Any] | None = None) -> RequestOutcome:
        if not (
            (path == SEARCH_PATH and payload is not None)
            or (DETAIL.fullmatch(path) and payload is None)
        ):
            raise AdapterError("MALFORMED_RESPONSE")
        if self.used:
            raise AdapterError("UPSTREAM_UNAVAILABLE")
        self.used = True
        started = time.perf_counter_ns()
        query_sha = fingerprint({"endpoint": ORIGIN + path, "payload": payload})
        response: httpx.Response | None = None
        code: str | None = None
        raw: Any = None
        count = 0
        raw_sha: str | None = None
        failure: str | None = None
        try:
            # No SDK, mounts, auth, environment proxies or automatic transport retry.
            transport = self._make_transport()
            async with httpx.AsyncClient(
                transport=transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(15, connect=5, pool=5),
                headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            ) as client:
                async with asyncio.timeout(DEADLINE):
                    async with client.stream(
                        "POST" if payload is not None else "GET", ORIGIN + path, json=payload
                    ) as response:
                        if response.status_code != 200:
                            raise AdapterError(
                                "NOT_FOUND"
                                if response.status_code == 404
                                else "UPSTREAM_UNAVAILABLE"
                            )
                        if (
                            response.headers.get("content-type", "").split(";")[0].strip()
                            != "application/json"
                        ):
                            raise AdapterError("MALFORMED_RESPONSE")
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise AdapterError("MALFORMED_RESPONSE")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            count += len(chunk)
                            if count > MAX_BYTES:
                                raise AdapterError("MALFORMED_RESPONSE")
                            body.extend(chunk)
                        raw_sha = digest(bytes(body))
                        raw = json.loads(
                            body,
                            parse_float=decimal_token,
                            parse_int=integer_token,
                            parse_constant=invalid_constant,
                            object_pairs_hook=strict_object,
                        )
                        self._validate_raw(raw, payload)
                        if time.perf_counter_ns() - started >= int(DEADLINE * 1_000_000_000):
                            raise TimeoutError
        except asyncio.CancelledError:
            code, failure = "NETWORK_ERROR", "CancelledError"
            raise
        except (TimeoutError, httpx.TimeoutException):
            code, failure = "TIMEOUT", "Timeout"
        except httpx.HTTPError:
            code, failure = "NETWORK_ERROR", "RequestError"
        except AdapterError as error:
            code, failure = error.code, "AdapterError"
        except (ValueError, TypeError, KeyError, RecursionError):
            code, failure = "MALFORMED_RESPONSE", "ResponseValidationError"
        finally:
            attempt = AttemptRecord(
                1,
                1,
                (time.perf_counter_ns() - started) / 1_000_000,
                "REQUEST_CONFIRMED" if response is not None else "DISPATCH_UNKNOWN",
                "TRANSPORT_ERROR"
                if failure in {"Timeout", "RequestError", "CancelledError"}
                else "RESPONSE_RECEIVED"
                if response is not None
                else "NO_RESPONSE",
                failure,
                response.status_code if response is not None else None,
                response is not None,
                None,
                "NONE" if code is None else "RETRY_BLOCKED",
                "success" if code is None else code,
            )
            self.observations.append(
                {
                    "endpoint": ORIGIN + path,
                    "method": "POST" if payload else "GET",
                    "request_sha256": query_sha,
                    "body_bytes": count,
                    "body_sha256": raw_sha,
                    "outcome": code or "RESPONSE_VALIDATED",
                    "attempt": attempt.model_dump(),
                }
            )
        if code is not None:
            raise AdapterError(code, attempts=(attempt,), query_fingerprint=query_sha) from None
        return RequestOutcome(raw, query_sha, (attempt,))

    @staticmethod
    def _validate_raw(raw: Any, payload: dict[str, Any] | None) -> None:
        if (
            not isinstance(raw, dict)
            or raw.get("messages")
            or raw.get("warnings")
            or raw.get("errors")
        ):
            raise ValueError("UPSTREAM_SCHEMA_REJECTED")
        if payload is not None:
            rows = raw["results"]
            page = raw["page_metadata"]
            if (
                not isinstance(rows, list)
                or len(rows) > payload["limit"]
                or not isinstance(page, dict)
                or type(page.get("hasNext")) is not bool
            ):
                raise ValueError("INVALID_PAGE")
            agencies = payload["filters"].get("agencies")
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or type(row.get("internal_id")) is not int
                    or row["internal_id"] <= 0
                ):
                    raise ValueError("INVALID_ROW")
                for name in (
                    "generated_internal_id",
                    "Award ID",
                    "Recipient Name",
                    "Awarding Agency",
                ):
                    text = row.get(name)
                    if (
                        not isinstance(text, str)
                        or not 0 < len(text) <= 300
                        or any(ord(c) < 32 for c in text)
                    ):
                        raise ValueError("INVALID_ROW_FIELD")
                if agencies and row["Awarding Agency"] != DOT:
                    raise ValueError("AWARDING_TOP_TIER_MISMATCH")
                row["Award Amount"] = amount_text(row["Award Amount"])
        else:
            if type(raw.get("id")) is not int or raw["id"] <= 0:
                raise ValueError("INVALID_DETAIL_ID")
            raw["total_obligation"] = amount_text(raw["total_obligation"])
        # Retain only documented fields consumed by the inherited parser. Unknown
        # upstream additions are not interpreted, rendered or authority inputs.
        if payload is not None:
            page = raw["page_metadata"]
            raw.clear()
            raw.update(results=rows, page_metadata={"hasNext": page["hasNext"]})
            raw["results"] = [
                {
                    k: row[k]
                    for k in (
                        "internal_id",
                        "generated_internal_id",
                        "Award ID",
                        "Recipient Name",
                        "Award Amount",
                        "Awarding Agency",
                    )
                }
                for row in rows
            ]
        else:
            selected = {
                k: raw[k]
                for k in ("id", "generated_unique_award_id", "category", "total_obligation")
            }
            raw.clear()
            raw.update(selected)
