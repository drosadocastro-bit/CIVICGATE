"""DATA-01-only FAA adapter/validator; exact MockTransport, one send, no live mode.

The fixture response projection includes explicit date/geography/type fields and
is not claimed to be a verified operational USAspending response schema.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Self

import httpx
from pydantic import Field, field_validator, model_validator

from civicgate.adapters.usaspending import (
    AdapterCall,
    AdapterError,
    AttemptRecord,
    DataBatch,
    USAspending,
)
from civicgate.channel_b.faa_adapter_v1 import FaaResponseOutcome
from civicgate.channel_b.faa_money_v1 import canonical_response_bytes, response_fingerprint
from civicgate.channel_b.faa_profile_v1 import (
    AwardRowV1,
    FrozenContract,
    PageMetadataV1,
    parse_response_bytes,
)
from civicgate.models.provenance import Provenance, utcnow
from evals.data01.generator import validate_dataset
from evals.proposals.r022.faa_contract_v1 import (
    DOT,
    ENDPOINT,
    FAA,
    FIELDS,
    PROFILE_ID,
    FaaFy2026PrReadV1,
)

DATASET_SHA256 = "7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d"
MAX_BYTES = 2_000_000
MODES = frozenset(
    {
        "normal",
        "wrong_agency",
        "wrong_subagency",
        "wrong_geo",
        "wrong_date",
        "wrong_type",
        "funding_only",
        "forged_empty",
        "malformed",
        "timeout",
    }
)


def load_records() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[2] / "data01/awards_v1.json"
    raw = path.read_bytes()
    if len(raw) != 31704 or hashlib.sha256(raw).hexdigest() != DATASET_SHA256:
        raise ValueError("R022_DATASET_IDENTITY_MISMATCH")
    document = parse_response_bytes(raw)
    validate_dataset(document)
    return document["records"]


def selected_records(scope: FaaFy2026PrReadV1) -> list[dict[str, Any]]:
    """Fixture selector, deliberately separate from the independent SQL oracle."""
    scope = FaaFy2026PrReadV1.model_validate(scope.model_dump(mode="json"))
    rows = [
        r
        for r in load_records()
        if r["awarding_agency"] == DOT
        and r["awarding_subagency"] == FAA
        and scope.start_date <= r["award_date"] <= scope.end_date
        and r["fiscal_year"] == 2026
        and r["place_of_performance_state"] == "PR"
        and r["award_type"] in scope.award_types
        and (scope.recipient_name is None or r["recipient_name"] == scope.recipient_name)
    ]
    return sorted(rows, key=lambda r: (-Decimal(r["award_amount"]), r["award_id"]))


def row_projection(record: dict[str, Any]) -> dict[str, Any]:
    ids = {r["award_id"]: i + 1 for i, r in enumerate(load_records())}
    return {
        "internal_id": ids[record["award_id"]],
        "generated_internal_id": record["award_id"],
        "Award ID": record["award_id"],
        "Recipient Name": record["recipient_name"],
        "Award Amount": record["award_amount"],
        "Awarding Agency": record["awarding_agency"],
        "Awarding Sub Agency": record["awarding_subagency"],
        "Funding Agency": record["funding_agency"],
        "Funding Sub Agency": record["funding_subagency"],
        "Award Date": record["award_date"],
        "Fiscal Year": record["fiscal_year"],
        "Place of Performance State Code": record["place_of_performance_state"],
        "Award Type": record["award_type"],
    }


class ProfileRow(AwardRowV1):
    award_date: str = Field(alias="Award Date")
    fiscal_year: Literal[2026] = Field(alias="Fiscal Year")
    performance_state: Literal["PR"] = Field(alias="Place of Performance State Code")
    award_type: Literal["A", "B", "C", "D"] = Field(alias="Award Type")

    @field_validator("fiscal_year", mode="before")
    @classmethod
    def exact_fiscal_year(cls, value: Any) -> int:
        if type(value) is not int:
            raise ValueError("Exact fiscal year required")
        return value

    @model_validator(mode="after")
    def in_fiscal_year(self) -> Self:
        parsed = date.fromisoformat(self.award_date)
        if (
            parsed.isoformat() != self.award_date
            or not "2025-10-01" <= self.award_date <= "2026-09-30"
        ):
            raise ValueError("Record date is not in FY2026")
        return self


class ProfilePage(FrozenContract):
    profile_id: Literal["FAA_FY2026_PR_READ_v1"]
    dataset_sha256: Literal["7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d"]
    spending_level: Literal["awards"]
    limit: int = Field(ge=1, le=20)
    results: tuple[ProfileRow, ...] = Field(max_length=20)
    page_metadata: PageMetadataV1

    @field_validator("results", mode="before")
    @classmethod
    def explicit_sequence(cls, value: Any) -> tuple[Any, ...]:
        if type(value) not in {list, tuple}:
            raise ValueError("Explicit response rows required")
        return tuple(value)


def fixture_body(scope: FaaFy2026PrReadV1, mode: str = "normal") -> dict[str, Any]:
    selected = selected_records(scope)
    result = [row_projection(row) for row in selected[: scope.limit]]
    body = {
        "profile_id": PROFILE_ID,
        "dataset_sha256": DATASET_SHA256,
        "spending_level": "awards",
        "limit": scope.limit,
        "results": result,
        "page_metadata": {"page": 1, "hasNext": len(selected) > scope.limit},
    }
    if mode == "forged_empty":
        body["results"] = []
        body["page_metadata"]["hasNext"] = False
    elif mode == "malformed":
        return {"malformed": True}
    elif result:
        if mode == "wrong_agency":
            result[0]["Awarding Agency"] = "Other Department"
        if mode == "wrong_subagency":
            result[0]["Awarding Sub Agency"] = "Federal Highway Administration"
        if mode == "wrong_geo":
            result[0]["Place of Performance State Code"] = "CA"
        if mode == "wrong_date":
            result[0]["Award Date"] = "2025-09-30"
        if mode == "wrong_type":
            result[0]["Award Type"] = "02"
        if mode == "funding_only":
            funded_only = next(r for r in load_records() if r["award_id"] == "SYN-DOT-PR-018")
            result[0] = row_projection(funded_only)
    return body


def dataset_transport(mode: str = "normal") -> httpx.MockTransport:
    if mode not in MODES:
        raise ValueError("R022_UNSUPPORTED_FIXTURE_MODE")

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or str(request.url) != ENDPOINT:
            raise ValueError("R022_FIXED_READ_ENDPOINT_REQUIRED")
        payload = parse_response_bytes(request.content)
        if type(payload) is not dict or set(payload) != {
            "filters",
            "fields",
            "page",
            "limit",
            "sort",
            "order",
            "subawards",
        }:
            raise ValueError("R022_PAYLOAD_SCOPE_INVALID")
        # The body must be a complete rendering of one allowed profile. No tier,
        # role, geography or time substitution occurs after authorization.
        filters = payload["filters"]
        if type(filters) is not dict or set(filters) - {
            "time_period",
            "award_type_codes",
            "agencies",
            "place_of_performance_locations",
            "recipient_search_text",
        }:
            raise ValueError("R022_FILTER_SCOPE_INVALID")
        recipient = filters.get("recipient_search_text", [None])
        if type(recipient) is not list or len(recipient) != 1:
            raise ValueError("R022_RECIPIENT_SCOPE_INVALID")
        from evals.proposals.r022.faa_contract_v1 import example_query

        scope = FaaFy2026PrReadV1.model_validate(
            example_query(
                limit=payload["limit"],
                award_types=filters.get("award_type_codes"),
                recipient_name=recipient[0],
            )
        )
        if payload != scope.payload() or payload["fields"] != list(FIELDS):
            raise ValueError("R022_PAYLOAD_SCOPE_MISMATCH")
        if mode == "timeout":
            raise httpx.ReadTimeout("R022_SYNTHETIC_TIMEOUT", request=request)
        return httpx.Response(200, json=fixture_body(scope, mode))

    return httpx.MockTransport(respond)


def validate_page(scope: FaaFy2026PrReadV1, raw: bytes, provenance: Provenance) -> ProfilePage:
    scope = FaaFy2026PrReadV1.model_validate(scope.model_dump(mode="json"))
    obj = parse_response_bytes(raw)
    page = ProfilePage.model_validate(obj)
    expected = fixture_body(scope)
    if canonical_response_bytes(obj) != canonical_response_bytes(expected):
        raise ValueError("R022_RESPONSE_DOES_NOT_MATCH_IMMUTABLE_DATASET_SCOPE")
    if page.limit != scope.limit or page.page_metadata.page != 1 or len(page.results) > scope.limit:
        raise ValueError("R022_RESPONSE_PAGE_SCOPE_MISMATCH")
    if (
        provenance.source_system != "CIVICGATE_TEST_FIXTURE"
        or provenance.source_type != "SYNTHETIC_TEST_FIXTURE"
        or provenance.endpoint != ENDPOINT
        or provenance.query_fingerprint != scope.query_fingerprint()
        or provenance.response_fingerprint != response_fingerprint(obj)
        or provenance.records_returned != len(page.results)
        or provenance.truncated != page.page_metadata.hasNext
    ):
        raise ValueError("R022_RESPONSE_PROVENANCE_MISMATCH")
    if any(
        row.award_type not in scope.award_types
        or (scope.recipient_name is not None and row.recipient_name != scope.recipient_name)
        for row in page.results
    ):
        raise ValueError("R022_RESPONSE_FILTER_MISMATCH")
    return page


class FaaProfileFixtureAdapter(USAspending):
    def __init__(self, transport: httpx.MockTransport | None = None) -> None:
        transport = dataset_transport() if transport is None else transport
        if type(transport) is not httpx.MockTransport:
            raise ValueError("R022_EXACT_MOCK_TRANSPORT_REQUIRED")
        super().__init__(transport=transport, fixture=True, max_attempts=1)
        self._retained_transport = transport
        self.entries = 0
        self.http_attempts = 0
        self.seen_requests: list[dict[str, Any]] = []

    async def find_profile(self, scope: FaaFy2026PrReadV1) -> AdapterCall:
        self.entries += 1
        scope = FaaFy2026PrReadV1.model_validate(scope.model_dump(mode="json"))
        if (
            type(self.transport) is not httpx.MockTransport
            or self.transport is not self._retained_transport
            or self.fixture is not True
            or self.max_attempts != 1
        ):
            raise ValueError("R022_SYNTHETIC_TRANSPORT_INTEGRITY")
        started, response, raw = monotonic(), None, b""

        def attempt(exc=None):
            return AttemptRecord(
                attempt=1,
                max_attempts=1,
                elapsed_ms=(monotonic() - started) * 1000,
                dispatch_state="REQUEST_CONFIRMED" if response is not None else "DISPATCH_UNKNOWN",
                response_state="RESPONSE_RECEIVED" if response is not None else "TRANSPORT_ERROR",
                exception_type=type(exc).__name__ if exc else None,
                status_code=response.status_code if response is not None else None,
                response_received=response is not None,
                retry_after_seconds=None,
                retry_decision="RETRY_BLOCKED" if exc else "NONE",
                retry_reason="single synthetic profile attempt; no retry" if exc else "success",
            )

        try:
            self.http_attempts += 1
            self.seen_requests.append(scope.payload())
            async with httpx.AsyncClient(
                transport=self.transport, trust_env=False, follow_redirects=False, timeout=10
            ) as client:
                async with client.stream(
                    "POST",
                    ENDPOINT,
                    content=scope.wire_bytes(),
                    headers={"Content-Type": "application/json"},
                ) as observed:
                    response = observed
                    if (
                        response.status_code != 200
                        or response.headers.get("content-type", "").split(";")[0].strip()
                        != "application/json"
                    ):
                        raise ValueError("R022_HTTP_RESPONSE_INVALID")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_BYTES:
                            raise ValueError("R022_RESPONSE_TOO_LARGE")
                    raw = bytes(chunks)
            obj = parse_response_bytes(raw)
            provenance = Provenance(
                source_system="CIVICGATE_TEST_FIXTURE",
                source_type="SYNTHETIC_TEST_FIXTURE",
                retrieved_at=utcnow(),
                query_fingerprint=scope.query_fingerprint(),
                response_fingerprint=response_fingerprint(obj),
                endpoint=ENDPOINT,
                records_returned=len(obj.get("results", [])),
                truncated=obj.get("page_metadata", {}).get("hasNext", False),
            )
            page = validate_page(scope, raw, provenance)
            return AdapterCall(
                batch=DataBatch(
                    records=[r.model_dump(mode="json", exclude_unset=True) for r in page.results],
                    provenance=provenance,
                ),
                outcome=FaaResponseOutcome(
                    raw=obj,
                    query_fingerprint=scope.query_fingerprint(),
                    attempts=(attempt(),),
                    retry_class="UNSAFE",
                    raw_response_bytes=raw,
                ),
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AdapterError(
                "TIMEOUT",
                attempts=(attempt(exc),),
                query_fingerprint=scope.query_fingerprint(),
                retry_class="UNSAFE",
            ) from exc
        except httpx.RequestError as exc:
            raise AdapterError(
                "NETWORK_ERROR",
                attempts=(attempt(exc),),
                query_fingerprint=scope.query_fingerprint(),
                retry_class="UNSAFE",
            ) from exc
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AdapterError(
                "CONFLICTING_SOURCE_RESULTS",
                attempts=(attempt(exc),),
                query_fingerprint=scope.query_fingerprint(),
                retry_class="UNSAFE",
            ) from exc


def validate_profile_result(scope: FaaFy2026PrReadV1, call: AdapterCall) -> None:
    try:
        if type(call.outcome) is not FaaResponseOutcome:
            raise ValueError("R022_RAW_RESPONSE_BYTES_REQUIRED")
        obj = parse_response_bytes(call.outcome.raw_response_bytes)
        if canonical_response_bytes(obj) != canonical_response_bytes(call.outcome.raw):
            raise ValueError("R022_RAW_PROJECTION_MISMATCH")
        page = validate_page(scope, call.outcome.raw_response_bytes, call.provenance)
        if (
            call.records != [r.model_dump(mode="json", exclude_unset=True) for r in page.results]
            or call.outcome.query_fingerprint != scope.query_fingerprint()
        ):
            raise ValueError("R022_ADAPTER_PROJECTION_MISMATCH")
        if len(call.outcome.attempts) != 1:
            raise ValueError("R022_EXACTLY_ONE_ATTEMPT_RECORD_REQUIRED")
        last = call.outcome.attempts[0]
        if (
            last.attempt != last.max_attempts
            or last.attempt != 1
            or last.status_code != 200
            or not last.response_received
            or last.exception_type is not None
            or last.retry_decision != "NONE"
            or last.dispatch_state != "REQUEST_CONFIRMED"
            or last.response_state != "RESPONSE_RECEIVED"
        ):
            raise ValueError("R022_ATTEMPT_EVIDENCE_MISMATCH")
    except (ValueError, TypeError, AttributeError) as exc:
        raise AdapterError(
            "CONFLICTING_SOURCE_RESULTS",
            attempts=call.outcome.attempts,
            query_fingerprint=call.outcome.query_fingerprint,
            retry_class="UNSAFE",
        ) from exc
