"""Isolated DATA-01 profile tests; no live provider or operational authority."""

import asyncio
import copy
from dataclasses import replace

import httpx
import pytest
from pydantic import ValidationError

from civicgate.adapters.usaspending import AdapterError
from civicgate.audit.trace import Trace
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from evals.data01.reference_v1 import answer
from evals.proposals.r022.faa_adapter_v1 import (
    DATASET_SHA256,
    FaaProfileFixtureAdapter,
    dataset_transport,
    fixture_body,
    load_records,
    validate_profile_result,
)
from evals.proposals.r022.faa_contract_v1 import (
    DOT,
    FAA,
    FAA_FY2026_PR_CONTRACT,
    PROFILE_ID,
    FaaFy2026PrReadV1,
    example_query,
)


class PermissiveSyntheticJudge:
    def __init__(self):
        self.calls = 0

    async def assess(self, request, proposal):
        self.calls += 1
        return JudgeSignal(
            available=True,
            classification="IN_SCOPE",
            confidence=0.99,
            flags=[],
            provider="R022_SYNTHETIC_NO_REAL_MODEL",
        )


def query(**changes):
    return FaaFy2026PrReadV1.model_validate(example_query(**changes))


@pytest.mark.parametrize("field", list(example_query()))
def test_every_fixed_scope_field_is_explicitly_required(field):
    value = example_query()
    del value[field]
    with pytest.raises(ValidationError):
        FaaFy2026PrReadV1.model_validate(value)


@pytest.mark.parametrize(
    "change",
    [
        {"profile_id": "legacy"},
        {"awarding_agency": DOT},
        {"agency_type": "funding"},
        {"agency_tier": "toptier"},
        {"agency_toptier_name": "Other Department"},
        {"fiscal_year": 2025},
        {"fiscal_year": "2026"},
        {"start_date": "2025-09-30"},
        {"end_date": "2026-10-01"},
        {"date_semantics": "new_awards_only"},
        {"state_code": "CA"},
        {"award_types": ["02"]},
        {"award_types": ["A", "A"]},
        {"award_types": []},
        {"page": 2},
        {"page": True},
        {"limit": True},
        {"limit": 0},
        {"limit": 21},
        {"subawards": True},
        {"subawards": 0},
        {"recipient_name": ""},
        {"unexpected": "unsupported"},
    ],
)
def test_scope_contradiction_and_downgrade_are_not_normalized(change):
    with pytest.raises(ValidationError):
        query(**change)


def test_payload_contains_complete_exact_scope_and_profile_binding():
    model = query()
    payload = model.payload()
    assert payload["filters"]["agencies"] == [
        {"type": "awarding", "tier": "subtier", "name": FAA, "toptier_name": DOT}
    ]
    assert payload["filters"]["place_of_performance_locations"] == [
        {"country": "USA", "state": "PR"}
    ]
    assert payload["filters"]["time_period"] == [
        {"start_date": "2025-10-01", "end_date": "2026-09-30"}
    ]
    assert model.model_dump(mode="json")["profile_id"] == PROFILE_ID
    assert "new_awards_only" not in model.wire_bytes().decode()
    with pytest.raises(ValidationError):
        model.limit = 1


def test_per_instance_registry_keeps_four_identities_and_three_legacy_schemas():
    assert set(FAA_FY2026_PR_CONTRACT.registry) == set(TOOLS)
    for name in TOOLS:
        if name != "find_federal_awards":
            assert FAA_FY2026_PR_CONTRACT.registry[name] is TOOLS[name]
    assert TOOLS["find_federal_awards"] is not FaaFy2026PrReadV1
    with pytest.raises(TypeError):
        FAA_FY2026_PR_CONTRACT.registry["unregistered"] = FaaFy2026PrReadV1


@pytest.mark.parametrize(
    "limit,types", [(20, ["A", "B", "C", "D"]), (5, ["A", "B", "C", "D"]), (20, ["B"]), (1, ["D"])]
)
def test_real_synthetic_adapter_matches_independent_sql_oracle(limit, types):
    scope = query(limit=limit, award_types=types)
    adapter = FaaProfileFixtureAdapter()
    call = asyncio.run(adapter.find_profile(scope))
    validate_profile_result(scope, call)
    expected = answer(
        load_records(),
        dict(
            kind="search",
            agency=DOT,
            subagency=FAA,
            start_date="2025-10-01",
            end_date="2026-09-30",
            state="PR",
            award_types=types,
            limit=limit,
        ),
    )
    assert [r["generated_internal_id"] for r in call.records] == expected["award_ids"]
    assert call.provenance.truncated == expected["has_next"]
    assert all(
        r["awarding_agency"] == DOT
        and r["awarding_sub_agency"] == FAA
        and r["performance_state"] == "PR"
        for r in call.records
    )
    assert call.outcome.attempts[0].retry_decision == "NONE"
    assert adapter.entries == adapter.http_attempts == 1


def test_valid_exact_recipient_empty_result_is_not_forged_empty():
    scope = query(recipient_name="Fictional No Matching Recipient LLC")
    call = asyncio.run(FaaProfileFixtureAdapter().find_profile(scope))
    validate_profile_result(scope, call)
    assert (
        call.records == []
        and call.provenance.records_returned == 0
        and not call.provenance.truncated
    )


@pytest.mark.parametrize(
    "mode",
    [
        "wrong_agency",
        "wrong_subagency",
        "wrong_geo",
        "wrong_date",
        "wrong_type",
        "funding_only",
        "forged_empty",
        "malformed",
        "timeout",
    ],
)
def test_bad_backend_evidence_rejects_after_one_attempt(mode):
    adapter = FaaProfileFixtureAdapter(dataset_transport(mode))
    with pytest.raises(AdapterError):
        asyncio.run(adapter.find_profile(query()))
    assert adapter.entries == adapter.http_attempts == 1


def test_projection_or_raw_outcome_tampering_is_rejected_at_gateway_validator():
    scope = query()
    call = asyncio.run(FaaProfileFixtureAdapter().find_profile(scope))
    changed = call.batch.model_copy(deep=True)
    changed.records[0]["performance_state"] = "CA"
    with pytest.raises(AdapterError):
        validate_profile_result(scope, replace(call, batch=changed))
    bad = replace(call.outcome, raw_response_bytes=b"{}")
    with pytest.raises(AdapterError):
        validate_profile_result(scope, replace(call, outcome=bad))


def test_exact_mock_transport_is_mandatory_and_cannot_be_swapped():
    with pytest.raises(ValueError):
        FaaProfileFixtureAdapter(httpx.AsyncHTTPTransport())
    adapter = FaaProfileFixtureAdapter()
    adapter.transport = dataset_transport()
    with pytest.raises(ValueError, match="R022_SYNTHETIC_TRANSPORT_INTEGRITY"):
        asyncio.run(adapter.find_profile(query()))
    assert adapter.http_attempts == 0


def test_payload_tier_or_geography_mutation_is_rejected_by_mock():
    async def run():
        transport = dataset_transport()
        async with httpx.AsyncClient(transport=transport) as client:
            body = query().payload()
            body["filters"]["agencies"][0]["tier"] = "toptier"
            with pytest.raises(ValueError):
                await client.post(
                    "https://api.usaspending.gov/api/v2/search/spending_by_award/", json=body
                )

    asyncio.run(run())


def test_valid_gateway_profile_uses_existing_deterministic_authority():
    adapter, judge, trace = FaaProfileFixtureAdapter(), PermissiveSyntheticJudge(), Trace()
    gateway = Gateway(adapter, judge, trace, contract=FAA_FY2026_PR_CONTRACT)
    result = asyncio.run(
        gateway.call(
            'Find public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2026.',
            Proposal(tool="find_federal_awards", arguments=example_query()),
        )
    )
    assert result.decision == "PERMIT" and result.verification_state == "RESULT_VERIFIED"
    assert len(result.result["records"]) == 16
    assert result.governance.authority_source == "DETERMINISTIC_POLICY_GATE"
    assert adapter.entries == adapter.http_attempts == 1


def test_missing_profile_on_find_is_not_a_legacy_fallback_in_profile_gateway():
    adapter, judge = FaaProfileFixtureAdapter(), PermissiveSyntheticJudge()
    gateway = Gateway(adapter, judge, Trace(), contract=FAA_FY2026_PR_CONTRACT)
    result = asyncio.run(
        gateway.call(
            'Find public awards for agency "Federal Aviation Administration".',
            Proposal(
                tool="find_federal_awards",
                arguments={
                    "start_date": "2025-10-01",
                    "end_date": "2026-09-30",
                    "state_code": "PR",
                    "awarding_agency": FAA,
                },
            ),
        )
    )
    assert result.decision == "DENY" and not result.tool_executed and adapter.entries == 0
    assert judge.calls == 0


def test_contract_alone_does_not_close_other_legacy_tool_path():
    original = dataset_transport()
    attempts = []

    async def observed(request):
        attempts.append(request)
        return await original.handle_async_request(request)

    adapter, judge, trace = (
        FaaProfileFixtureAdapter(httpx.MockTransport(observed)),
        PermissiveSyntheticJudge(),
        Trace(),
    )
    gateway = Gateway(adapter, judge, trace, contract=FAA_FY2026_PR_CONTRACT)
    result = asyncio.run(
        gateway.call(
            'Find public awards for agency "Federal Aviation Administration".',
            Proposal(
                tool="summarize_federal_spending",
                arguments={
                    "start_date": "2025-10-01",
                    "end_date": "2026-09-30",
                    "state_code": "PR",
                    "awarding_agency": FAA,
                },
            ),
        )
    )
    # Honest characterization: server-scoped intake must reject this route.
    # The full profile's find-handler was not invoked; the legacy adapter sent
    # a different payload which the strict synthetic fixture rejected.
    initial = next(row for row in trace.events if row["stage"] == "policy")
    completed = next(row for row in trace.events if row["stage"] == "completed")
    assert initial["policy"]["decision"] == "PERMIT" and initial["binding_issued"]
    assert completed["pre_dispatch_verification"] == "PASS"
    assert len(attempts) == 1
    assert result.decision == "REVIEW_REQUIRED" and result.tool_executed
    assert result.result is None and result.verification_state != "RESULT_VERIFIED"
    assert adapter.entries == 0


def test_fixture_truth_is_explicit_and_immutable():
    assert len(load_records()) == 40
    body = fixture_body(query())
    assert body["profile_id"] == PROFILE_ID and body["dataset_sha256"] == DATASET_SHA256
    old = copy.deepcopy(body)
    body["results"][0]["Awarding Sub Agency"] = "other"
    assert fixture_body(query()) == old
