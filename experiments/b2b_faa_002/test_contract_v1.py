"""Synthetic candidate-contract tests only; no policy admission or live transport."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, get_args

import httpx
import pytest
from pydantic import ValidationError

from civicgate.models.provenance import Provenance, fingerprint
from civicgate.models.requests import AwardType
from experiments.b2b_faa_002.contract_v1 import (
    DOT,
    ENDPOINT,
    FAA,
    FIELDS,
    MAX_BYTES,
    VERSION,
    CandidateValidationError,
    FaaScopeV1,
    canonical,
    sha256,
    validate_synthetic_page,
)


def scope_values() -> dict[str, Any]:
    return {
        "contract_version": VERSION,
        "method": "POST",
        "endpoint": ENDPOINT,
        "awarding_agency": FAA,
        "agency_type": "awarding",
        "agency_tier": "subtier",
        "agency_toptier_name": DOT,
        "fiscal_year": 2025,
        "start_date": "2024-10-01",
        "end_date": "2025-09-30",
        "date_semantics": "AWARD_SEARCH_DEFAULT_OVERLAP",
        "award_types": ["A", "B", "C", "D"],
        "page": 1,
        "limit": 20,
        "subawards": False,
        "response_fields": list(FIELDS),
        "sort": "Award Amount",
        "order": "desc",
    }


def scope() -> FaaScopeV1:
    return FaaScopeV1.model_validate(scope_values())


def row() -> dict[str, Any]:
    return {
        "internal_id": 1,
        "generated_internal_id": "SYNTHETIC-FAA-002",
        "Award ID": "SYNTHETIC-002",
        "Recipient Name": "Synthetic Recipient",
        "Award Amount": "123.45",
        "Awarding Agency": DOT,
        "Awarding Sub Agency": FAA,
        "Funding Agency": DOT,
        "Funding Sub Agency": "Federal Highway Administration",
    }


def body() -> dict[str, Any]:
    return {
        "spending_level": "awards",
        "limit": 20,
        "results": [row()],
        "page_metadata": {"page": 1, "hasNext": False},
    }


def provenance(obj: dict[str, Any], query: FaaScopeV1 | None = None) -> Provenance:
    query = query or scope()
    return Provenance(
        source_system="CIVICGATE_TEST_FIXTURE",
        source_type="SYNTHETIC_TEST_FIXTURE",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        query_fingerprint=query.query_fingerprint(),
        response_fingerprint=fingerprint(obj),
        endpoint=ENDPOINT,
        records_returned=len(obj["results"]) if isinstance(obj.get("results"), list) else 0,
        truncated=obj.get("page_metadata", {}).get("hasNext", False) is True,
    )


def check(obj: dict[str, Any]) -> Any:
    return validate_synthetic_page(
        scope(),
        canonical(obj).encode(),
        provenance(obj),
        status_code=200,
        content_type="application/json",
    )


def test_explicit_wire_query_and_exact_mocktransport_serialization() -> None:
    query = scope()
    expected = {
        "filters": {
            "time_period": [{"start_date": "2024-10-01", "end_date": "2025-09-30"}],
            "award_type_codes": ["A", "B", "C", "D"],
            "agencies": [{"type": "awarding", "tier": "subtier", "name": FAA, "toptier_name": DOT}],
        },
        "fields": list(FIELDS),
        "page": 1,
        "limit": 20,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    requests = []
    raw = canonical(body()).encode()

    def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST" and str(request.url) == ENDPOINT
        assert request.content == canonical(expected).encode()
        assert "authorization" not in request.headers
        return httpx.Response(200, content=raw, headers={"content-type": "application/json"})

    # Test-only MockTransport: this is NOT a production client or an authorized Gateway.
    with httpx.Client(transport=httpx.MockTransport(receive)) as client:
        response = client.post(
            ENDPOINT, content=query.wire_bytes(), headers={"content-type": "application/json"}
        )
    result = validate_synthetic_page(
        query,
        response.content,
        provenance(body()),
        status_code=response.status_code,
        content_type=response.headers["content-type"],
    )
    assert len(requests) == 1
    assert result.records[0].awarding_sub_agency == FAA
    assert result.records[0].funding_sub_agency == "Federal Highway Administration"
    assert result.records[0].award_amount == Decimal("123.45")
    assert result.verified_scope == "SYNTHETIC_PROFILE_ONLY"
    assert not result.population_total_established
    assert result.raw_response_sha256 == sha256(raw)
    assert json.loads(result.scope_json) == query.model_dump(mode="json")


@pytest.mark.parametrize("field", list(scope_values()))
def test_every_scope_field_is_required(field: str) -> None:
    values = scope_values()
    del values[field]
    with pytest.raises(ValidationError):
        FaaScopeV1.model_validate(values)


@pytest.mark.parametrize(
    "change",
    [
        {"contract_version": "v2"},
        {"method": "GET"},
        {"endpoint": ENDPOINT + "other"},
        {"awarding_agency": DOT},
        {"awarding_agency": [FAA]},
        {"agency_type": "funding"},
        {"agency_tier": "toptier"},
        {"agency_toptier_name": "Other Department"},
        {"funding_agency": FAA},
        {"agencies": []},
        {"keywords": ["aviation"]},
        {"state_code": "PR"},
        {"recipient_name": "Other Recipient"},
        {"fiscal_year": True},
        {"fiscal_year": 2007},
        {"fiscal_year": 10000},
        {"fiscal_year": 2026},
        {"start_date": "2025-01-01"},
        {"end_date": "2025-09-29"},
        {"start_date": "20241001"},
        {"start_date": 1727740800},
        {"start_date": datetime(2024, 10, 1, tzinfo=UTC)},
        {"end_date": "2025-09-30T00:00:00Z"},
        {"date_semantics": "FISCAL_YEAR_TOTAL_OBLIGATIONS"},
        {"award_types": []},
        {"award_types": ["A", "A"]},
        {"award_types": ["IDV_A"]},
        {"award_types": ["07"]},
        {"award_types": "A"},
        {"award_types": [1]},
        {"page": 0},
        {"page": 2},
        {"page": True},
        {"limit": 0},
        {"limit": 101},
        {"limit": "20"},
        {"limit": True},
        {"subawards": True},
        {"subawards": 0},
        {"subawards": "false"},
        {"response_fields": list(FIELDS[:-1])},
        {"sort": "Recipient Name"},
        {"order": "asc"},
    ],
)
def test_conflicting_or_unbounded_scope_rejected(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FaaScopeV1.model_validate(scope_values() | change)


@pytest.mark.parametrize("code", list(get_args(AwardType)))
def test_each_existing_award_type_remains_available(code: str) -> None:
    query = FaaScopeV1.model_validate(scope_values() | {"award_types": [code]})
    assert query.payload()["filters"]["award_type_codes"] == [code]


@pytest.mark.parametrize("year", [2008, 2024, 2025, 9999])
def test_fiscal_year_is_explicit_including_leap_year(year: int) -> None:
    query = FaaScopeV1.model_validate(
        scope_values()
        | {
            "fiscal_year": year,
            "start_date": f"{year - 1}-10-01",
            "end_date": f"{year}-09-30",
        }
    )
    assert query.fiscal_year == year
    assert query.payload()["filters"]["time_period"] == [
        {"start_date": f"{year - 1}-10-01", "end_date": f"{year}-09-30"}
    ]


def test_frozen_scope_and_detached_payload_cannot_silently_substitute() -> None:
    values = scope_values()
    query = FaaScopeV1.model_validate(values)
    original = query.wire_bytes()
    values["award_types"].append("02")
    payload = query.payload()
    payload["filters"]["agencies"][0]["tier"] = "toptier"
    payload["fields"].clear()
    assert query.wire_bytes() == original
    with pytest.raises(ValidationError):
        query.agency_tier = "toptier"  # type: ignore[assignment]
    unchecked = query.model_copy(update={"agency_tier": "toptier"})
    with pytest.raises(ValidationError):
        unchecked.wire_bytes()


@pytest.mark.parametrize(
    "change",
    [
        {"limit": 1},
        {"award_types": ["A"]},
        {"fiscal_year": 2024, "start_date": "2023-10-01", "end_date": "2024-09-30"},
    ],
)
def test_effective_changes_change_query_identity(change: dict[str, Any]) -> None:
    query = FaaScopeV1.model_validate(scope_values() | change)
    assert query.query_fingerprint() != scope().query_fingerprint()


@pytest.mark.parametrize("field", list(row()))
def test_missing_attribution_or_award_identity_fails(field: str) -> None:
    obj = body()
    del obj["results"][0][field]
    with pytest.raises(CandidateValidationError):
        check(obj)


@pytest.mark.parametrize(
    "field",
    [
        "Awarding Agency",
        "Awarding Sub Agency",
        "Funding Agency",
        "Funding Sub Agency",
    ],
)
@pytest.mark.parametrize("invalid", [None, "", " ", 1, [], " FAA ", "FAA\n"])
def test_malformed_attribution_fails(field: str, invalid: Any) -> None:
    obj = body()
    obj["results"][0][field] = invalid
    with pytest.raises(CandidateValidationError):
        check(obj)


@pytest.mark.parametrize(
    "changes",
    [
        {"Awarding Agency": "Unrelated Department"},
        {"Awarding Sub Agency": "Federal Highway Administration", "Funding Sub Agency": FAA},
        {"Awarding Agency": FAA, "Awarding Sub Agency": FAA},
        {"Awarding Sub Agency": FAA.lower()},
        {"Funding Agency": "Unrelated Department", "Funding Sub Agency": FAA},
    ],
)
def test_funding_never_substitutes_for_awarding_or_parent(changes: dict[str, Any]) -> None:
    obj = body()
    obj["results"][0].update(changes)
    with pytest.raises(CandidateValidationError):
        check(obj)


def test_faa_can_be_both_awarding_and_funding_but_roles_stay_separate() -> None:
    obj = body()
    obj["results"][0]["Funding Sub Agency"] = FAA
    result = check(obj)
    assert result.records[0].awarding_sub_agency == FAA
    assert result.records[0].funding_sub_agency == FAA
    assert result.attribution == "FAA_AWARDED_PAGE"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", True, None, {}, "abc"])
def test_invalid_amount_not_repaired(amount: Any) -> None:
    obj = body()
    obj["results"][0]["Award Amount"] = amount
    with pytest.raises(CandidateValidationError):
        check(obj)


@pytest.mark.parametrize("amount", [0, -50, "0.01", 12.5])
def test_finite_amounts_are_evidence_not_spending_totals(amount: Any) -> None:
    obj = body()
    obj["results"][0]["Award Amount"] = amount
    result = check(obj)
    assert not result.population_total_established


def test_empty_page_is_not_a_verified_record_or_population_claim() -> None:
    obj = body()
    obj["results"] = []
    result = check(obj)
    assert result.attribution == "EMPTY_PAGE" and result.records == ()
    assert not result.population_total_established and not result.truncated


def test_truncated_page_keeps_limit_and_never_auto_paginates() -> None:
    obj = body()
    obj["page_metadata"]["hasNext"] = True
    result = check(obj)
    assert result.truncated and result.page == 1 and result.limit == 20
    assert not result.population_total_established


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 19},
        {"limit": "20"},
        {"limit": True},
        {"page_metadata": {"page": 2, "hasNext": False}},
        {"page_metadata": {"page": True, "hasNext": False}},
        {"page_metadata": {"page": 1, "hasNext": "false"}},
        {"page_metadata": {"page": 1}},
        {"results": None},
        {"results": {}},
        {"spending_level": "subawards"},
        {"messages": ["Warning: incomplete agency filter"]},
        {"unexpected": "metadata"},
    ],
)
def test_page_contract_and_warnings_fail_closed(changes: dict[str, Any]) -> None:
    with pytest.raises(CandidateValidationError):
        check(body() | changes)


def test_empty_truncated_and_duplicate_and_excess_rows_fail() -> None:
    obj = body()
    obj["results"] = []
    obj["page_metadata"]["hasNext"] = True
    with pytest.raises(CandidateValidationError):
        check(obj)
    obj = body()
    obj["results"] *= 2
    with pytest.raises(CandidateValidationError):
        check(obj)
    obj["results"] = [
        row() | {"internal_id": i, "generated_internal_id": f"SYNTHETIC-{i}"} for i in range(21)
    ]
    with pytest.raises(CandidateValidationError):
        check(obj)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"[]",
        b"null",
        b'{"results":[],"results":[]}',
        b'{"amount": NaN}',
        b"\xff",
        b" " * (MAX_BYTES + 1),
    ],
    ids=["empty", "incomplete", "array", "null", "duplicate", "nonfinite", "encoding", "oversized"],
)
def test_malformed_raw_bytes_rejected(raw: bytes) -> None:
    with pytest.raises(CandidateValidationError):
        validate_synthetic_page(
            scope(), raw, provenance(body()), status_code=200, content_type="application/json"
        )


@pytest.mark.parametrize(
    "status,content_type",
    [
        (201, "application/json"),
        (500, "application/json"),
        (True, "application/json"),
        (200, "text/html"),
    ],
)
def test_http_status_or_media_mismatch_fails(status: int, content_type: str) -> None:
    with pytest.raises(CandidateValidationError):
        validate_synthetic_page(
            scope(),
            canonical(body()).encode(),
            provenance(body()),
            status_code=status,
            content_type=content_type,
        )


@pytest.mark.parametrize(
    "change",
    [
        {"endpoint": ENDPOINT + "other"},
        {"query_fingerprint": "0" * 64},
        {"response_fingerprint": "0" * 64},
        {"records_returned": 2},
        {"truncated": True},
        {"source_system": "USAspending"},
        {"source_type": "PUBLIC_GOVERNMENT_API"},
        {"retrieved_at": "2026-01-01T00:00:00"},
    ],
)
def test_inconsistent_or_live_provenance_rejected(change: dict[str, Any]) -> None:
    claimed = provenance(body()).model_copy(update=change)
    with pytest.raises(CandidateValidationError):
        validate_synthetic_page(
            scope(),
            canonical(body()).encode(),
            claimed,
            status_code=200,
            content_type="application/json",
        )


def test_result_is_immutable_and_fingerprint_does_not_authenticate_source() -> None:
    result = check(body())
    with pytest.raises(FrozenInstanceError):
        result.truncated = True
    with pytest.raises(ValidationError):
        result.records[0].funding_sub_agency = "Changed"
    # A self-consistent synthetic fiction can pass. No origin/identity proof is claimed.
    fiction = body()
    fiction["results"][0]["Recipient Name"] = "Invented Synthetic Record"
    assert check(fiction).verified_scope == "SYNTHETIC_PROFILE_ONLY"
    assert not hasattr(result, "execute") and not hasattr(result, "authority")
