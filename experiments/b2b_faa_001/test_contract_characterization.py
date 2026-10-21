"""FAA contract characterization only. No FAA integration or live transport.

Passing tests describe existing behavior; they do NOT establish FAA subtier
support. The required property has a separate retained failing reproduction.
"""

import json
import os
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
from pydantic import ValidationError

from civicgate.adapters.usaspending import AdapterError, USAspending
from civicgate.audit.trace import Trace
from civicgate.governance.execution import ExecutionBoundary, ExecutionBoundaryError
from civicgate.governance.policy import PolicyFacts
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.provenance import fingerprint
from civicgate.models.requests import TOOLS, AwardType, Proposal, Search

FAA = "Federal Aviation Administration"
DOT = "Department of Transportation"
OTHER = "Federal Highway Administration"
CONTEXT = (True, True, 0.85, 0)


def arguments() -> dict[str, Any]:
    return {
        "awarding_agency": FAA,
        "start_date": "2024-10-01",
        "end_date": "2025-09-30",
        "award_types": ["A", "B", "C", "D"],
        "limit": 20,
    }


def response(subtier: str | None = FAA, funding: str | None = OTHER) -> dict[str, Any]:
    return {
        "results": [
            {
                "internal_id": 1,
                "generated_internal_id": "SYNTHETIC-FAA-001",
                "Award ID": "SYNTHETIC-001",
                "Recipient Name": "Synthetic Recipient",
                "Award Amount": 123,
                "Awarding Agency": DOT,
                "Awarding Sub Agency": subtier,
                "Funding Agency": DOT,
                "Funding Sub Agency": funding,
            }
        ],
        "page_metadata": {"page": 1, "hasNext": False},
    }


def expected_current_payload() -> dict[str, Any]:
    return {
        "filters": {
            "time_period": [{"start_date": "2024-10-01", "end_date": "2025-09-30"}],
            "award_type_codes": ["A", "B", "C", "D"],
            "agencies": [{"type": "awarding", "tier": "toptier", "name": FAA}],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "generated_internal_id",
        ],
        "page": 1,
        "limit": 20,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }


def observed(case: str, **data: Any) -> None:
    destination = os.environ.get("FAA_EVIDENCE")
    if destination:
        with (Path(destination) / "observations.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"case": case, **data}, ensure_ascii=False) + "\n")


class SyntheticJudge:
    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        return JudgeSignal(
            available=True,
            classification="IN_SCOPE",
            confidence=1,
            provider="synthetic-faa-contract",
            rationale="Synthetic permissive control only",
        )


class Capture:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.payloads: list[dict[str, Any]] = []
        self.adapter = USAspending(httpx.MockTransport(self.receive), fixture=True, max_attempts=1)

    def receive(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.usaspending.gov/api/v2/search/spending_by_award/"
        assert "authorization" not in request.headers
        self.payloads.append(json.loads(request.content))
        return httpx.Response(200, json=self.body)

    async def gateway(self, args: dict[str, Any], request: str | None = None) -> tuple[Any, Trace]:
        trace = Trace()
        gateway = Gateway(self.adapter, SyntheticJudge(), trace)
        result = await gateway.call(
            request or f'Get public awards for agency "{FAA}".',
            Proposal(tool="find_federal_awards", arguments=args),
        )
        return result, trace


async def test_actual_gateway_binds_name_but_translates_only_toptier() -> None:
    capture = Capture(response())
    envelope, trace = await capture.gateway(arguments())
    assert envelope.decision == "PERMIT"
    assert envelope.tool_executed
    assert capture.payloads == [expected_current_payload()]
    policy = next(event for event in trace.events if event["stage"] == "policy")
    completion = trace.events[-1]
    assert policy["binding_issued"] is True
    assert completion["pre_dispatch_verification"] == "PASS"
    assert json.loads(policy["facts"]["arguments_json"])["awarding_agency"] == FAA
    assert "agency_tier" not in json.loads(policy["facts"]["arguments_json"])
    observed(
        "CURRENT_TOP_TIER_NOT_FAA_INTEGRATION",
        payloads=capture.payloads,
        result=envelope.model_dump(mode="json"),
        trace=trace.events,
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"agency_tier": "subtier"},
        {"agency_type": "awarding"},
        {"agencies": [{"type": "awarding", "tier": "subtier", "name": FAA}]},
        {"funding_agency": FAA},
        {"page": 2},
        {"keywords": ["aviation"]},
        {"agency_tier": "subtier", "funding_agency": FAA},
    ],
)
async def test_unsupported_and_conflicting_scope_rejected_before_dispatch(
    extra: dict[str, Any],
) -> None:
    capture = Capture(response())
    with pytest.raises(ValidationError):
        Search.model_validate(arguments() | extra)
    result, trace = await capture.gateway(arguments() | extra)
    assert result.decision == "DENY"
    assert not result.tool_executed and not capture.payloads
    policy = next(event for event in trace.events if event["stage"] == "policy")
    assert not policy["binding_issued"]
    observed("UNREPRESENTABLE_SCOPE", extra=extra, decision=result.decision, dispatches=0)


@pytest.mark.parametrize(
    "change",
    [
        {"start_date": "2025-10-01"},
        {"end_date": "2026-09-30"},
        {"start_date": "not-a-date"},
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"award_types": []},
        {"award_types": ["IDV_A"]},
        {"award_types": ["07"]},
        {"award_types": ["UNKNOWN"]},
        {"awarding_agency": ["Federal Aviation Administration", "Department of Transportation"]},
    ],
)
def test_existing_input_bounds(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Search.model_validate(arguments() | change)


@pytest.mark.parametrize("code", list(get_args(AwardType)))
async def test_only_existing_permitted_award_types_project_unchanged(code: str) -> None:
    capture = Capture({"results": [], "page_metadata": {"page": 1, "hasNext": False}})
    result = await capture.adapter.search(
        Search.model_validate(arguments() | {"award_types": [code]})
    )
    assert capture.payloads[0]["filters"]["award_type_codes"] == [code]
    assert result.records == []
    assert set(TOOLS) == {
        "find_federal_awards",
        "get_federal_award",
        "resolve_federal_recipient",
        "summarize_federal_spending",
    }


@pytest.mark.parametrize("has_next", [False, True])
async def test_empty_page_and_truncation_never_auto_paginate(has_next: bool) -> None:
    capture = Capture({"results": [], "page_metadata": {"page": 1, "hasNext": has_next}})
    result = await capture.adapter.search(Search.model_validate(arguments()))
    assert len(capture.payloads) == 1
    assert capture.payloads[0]["page"] == 1
    assert result.records == []
    assert result.provenance.truncated is has_next
    assert result.provenance.source_type == "SYNTHETIC_TEST_FIXTURE"
    assert result.provenance.query_fingerprint == fingerprint(
        {
            "method": "POST",
            "url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
            "body": capture.payloads[0],
        }
    )
    observed("EMPTY_PAGE", has_next=has_next, provenance=result.provenance.model_dump(mode="json"))


async def test_nonempty_truncated_page_is_one_page_not_total_spending() -> None:
    body = response()
    body["page_metadata"]["hasNext"] = True
    capture = Capture(body)
    result, _ = await capture.gateway(arguments())
    assert len(capture.payloads) == 1 and result.tool_executed
    assert result.provenance is not None and result.provenance.truncated
    observed("TRUNCATED_PAGE", result=result.model_dump(mode="json"), calls=len(capture.payloads))


@pytest.mark.parametrize("awarding,funding", [(FAA, OTHER), (OTHER, FAA), (None, FAA)])
async def test_current_parser_cannot_certify_subtier_or_funding_attribution(
    awarding: str | None,
    funding: str | None,
) -> None:
    capture = Capture(response(awarding, funding))
    result = await capture.adapter.search(Search.model_validate(arguments()))
    assert result.records[0]["awarding_agency"] == DOT
    assert "Awarding Sub Agency" not in result.records[0]
    assert "Funding Sub Agency" not in result.records[0]
    assert "awarding_sub_agency" not in result.records[0]
    observed(
        "ATTRIBUTION_UNAVAILABLE",
        supplied_awarding_subtier=awarding,
        supplied_funding_subtier=funding,
        returned=result.model_dump(mode="json"),
    )


async def test_wrong_top_agency_is_not_verified_by_existing_parser() -> None:
    body = response(OTHER, FAA)
    body["results"][0]["Awarding Agency"] = "Unrelated Department"
    capture = Capture(body)
    result = await capture.adapter.search(Search.model_validate(arguments()))
    assert result.records[0]["awarding_agency"] == "Unrelated Department"
    observed("WRONG_AGENCY_ACCEPTED_BY_BASELINE", returned=result.model_dump(mode="json"))


async def test_conflicting_explicit_request_name_is_held_not_rewritten() -> None:
    capture = Capture(response())
    result, _ = await capture.gateway(arguments() | {"awarding_agency": OTHER})
    assert result.decision == "REVIEW_REQUIRED"
    assert not result.tool_executed and not capture.payloads
    observed("NAME_CONFLICT", decision=result.decision, dispatches=0)


async def test_excess_rows_fail_validation() -> None:
    body = response()
    body["results"] *= 2
    capture = Capture(body)
    with pytest.raises(AdapterError, match="MALFORMED_RESPONSE"):
        await capture.adapter.search(Search.model_validate(arguments() | {"limit": 1}))
    assert len(capture.payloads) == 1


@pytest.mark.parametrize("change", [{"agency_tier": "subtier"}, {"awarding_agency": OTHER}])
def test_existing_binding_rejects_name_mutation_and_scope_injection(change: dict[str, Any]) -> None:
    boundary = ExecutionBoundary(TOOLS)
    args = Search.model_validate(arguments()).model_dump(mode="json")
    evaluation = boundary.evaluate(
        request_id="synthetic-faa-boundary",
        facts=PolicyFacts(tool="find_federal_awards", text="public awards"),
        judge=JudgeSignal(
            available=True, classification="IN_SCOPE", confidence=1, provider="synthetic-faa"
        ),
        agent_k=KSignal(),
        threshold=0.85,
        arguments=args,
        policy_context=CONTEXT,
    )
    assert evaluation.envelope is not None
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(
            evaluation.envelope,
            request_id="synthetic-faa-boundary",
            tool="find_federal_awards",
            arguments=args | change,
            policy_context=CONTEXT,
        )
