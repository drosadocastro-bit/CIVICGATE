"""Unit and direct-wrapper scope controls, separate from real stdio evidence."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter
from evals.proposals.r022.faa_contract_v1 import PROFILE_ID, example_query
from evals.proposals.r022.stdio_v1 import (
    CANONICAL_REQUEST,
    NATURAL_REQUEST,
    ProfileAdmissionError,
    ScopedFaaGateway,
    TrustedFaaIntake,
    accepted_request_templates,
    create_scoped_server,
)


class Judge:
    def __init__(self):
        self.calls = 0

    async def assess(self, request, proposal):
        self.calls += 1
        return JudgeSignal(
            available=True,
            classification="IN_SCOPE",
            confidence=0.99,
            flags=[],
            provider="SYNTHETIC_R022_JUDGE",
        )


def prepared(query=None, request=CANONICAL_REQUEST):
    values = example_query() if query is None else query
    intake = TrustedFaaIntake(request, json.dumps(values))
    adapter, judge, trace = FaaProfileFixtureAdapter(), Judge(), Trace()
    return ScopedFaaGateway(adapter, judge, trace, intake=intake), adapter, judge, trace


def assert_not_entered(adapter, judge, trace):
    assert adapter.entries == adapter.http_attempts == judge.calls == 0
    assert trace.events == []


@pytest.mark.parametrize(
    "request_text",
    [
        "Show public awards.",
        'Find public awards for agency "Department of Transportation" in Puerto Rico during FY2026.',
        'Find public awards for agency "Federal Highway Administration" in Puerto Rico during FY2026.',
        'Find public awards for agency "FAA" in Puerto Rico during FY2026.',
        'Find public awards for agency "Federal Aviation Administration" in California during FY2026.',
        'Find public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2025.',
    ],
)
def test_host_cannot_silently_select_faa_for_other_or_ambiguous_original_intent(request_text):
    with pytest.raises(ProfileAdmissionError, match="ORIGINAL_INTENT_UNSUPPORTED_BY_PROFILE"):
        TrustedFaaIntake(request_text, json.dumps(example_query()))


@pytest.mark.parametrize(
    "query",
    [
        {},
        dict(example_query(), profile_id="LEGACY"),
        dict(example_query(), agency_tier="toptier"),
        dict(example_query(), state_code="CA"),
        dict(example_query(), fiscal_year=2025),
    ],
)
def test_missing_or_conflicting_profile_context_cannot_become_an_intake(query):
    with pytest.raises(ProfileAdmissionError, match="PROFILE_QUERY_CONTEXT_INVALID"):
        TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(query))


@pytest.mark.parametrize("raw", ["not JSON", "[]", '{"profile_id":1,"profile_id":2}', "NaN", ""])
def test_malformed_context_never_falls_back_to_legacy(raw):
    with pytest.raises(ProfileAdmissionError, match="PROFILE_QUERY_CONTEXT_INVALID"):
        TrustedFaaIntake(CANONICAL_REQUEST, raw)


def test_trusted_intake_is_immutable_and_canonical_not_authority():
    intake = TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query()))
    assert intake.profile_id == PROFILE_ID
    assert json.loads(intake.expected_query_json)["recipient_name"] is None
    assert len(intake.intake_sha256) == len(intake.request_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        intake.original_request = "Show public awards."
    with pytest.raises(FrozenInstanceError):
        intake.expected_query_json = "{}"


def test_missing_host_intake_is_an_error_not_an_unscoped_gateway():
    with pytest.raises(ProfileAdmissionError, match="TRUSTED_INTAKE_REQUIRED"):
        ScopedFaaGateway(FaaProfileFixtureAdapter(), Judge(), Trace(), intake=None)


def test_unsupported_adapter_is_rejected_at_startup_before_authority():
    intake = TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query()))
    with pytest.raises(ProfileAdmissionError, match="PROFILE_ADAPTER_REQUIRED"):
        ScopedFaaGateway(USAspending(), Judge(), Trace(), intake=intake)


@pytest.mark.parametrize(
    "tool",
    [
        "summarize_federal_spending",
        "get_federal_award",
        "resolve_federal_recipient",
        "unregistered_admin",
    ],
)
async def test_an_agent_cannot_choose_another_tool_to_downgrade_the_owner(tool):
    gateway, adapter, judge, trace = prepared()
    with pytest.raises(ProfileAdmissionError, match="TOOL_OUTSIDE_SELECTED_PROFILE"):
        await gateway.call(CANONICAL_REQUEST, Proposal(tool=tool, arguments={}))
    assert_not_entered(adapter, judge, trace)


@pytest.mark.parametrize(
    "request_text", ["Show public awards.", NATURAL_REQUEST, CANONICAL_REQUEST + " "]
)
async def test_mcp_user_request_cannot_rewrite_host_intake(request_text):
    gateway, adapter, judge, trace = prepared()
    with pytest.raises(ProfileAdmissionError, match="ORIGINAL_REQUEST_MISMATCH"):
        await gateway.call(
            request_text, Proposal(tool="find_federal_awards", arguments=example_query())
        )
    assert_not_entered(adapter, judge, trace)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"limit": 5}, "EXPECTED_QUERY_MISMATCH"),
        ({"award_types": ["A"]}, "EXPECTED_QUERY_MISMATCH"),
        ({"recipient_name": "Fictional Faro Technical Services LLC"}, "EXPECTED_QUERY_MISMATCH"),
        ({"state_code": "CA"}, "PROFILE_QUERY_INVALID_OR_DOWNGRADED"),
        ({"profile_id": "legacy"}, "PROFILE_QUERY_INVALID_OR_DOWNGRADED"),
    ],
)
async def test_planner_cannot_rewrite_preapproved_effective_query(change, code):
    gateway, adapter, judge, trace = prepared()
    with pytest.raises(ProfileAdmissionError, match=code):
        await gateway.call(
            CANONICAL_REQUEST,
            Proposal(tool="find_federal_awards", arguments=example_query(**change)),
        )
    assert_not_entered(adapter, judge, trace)


async def test_valid_scope_reaches_original_authority_and_one_fixture_attempt():
    gateway, adapter, judge, trace = prepared()
    result = await gateway.call(
        CANONICAL_REQUEST, Proposal(tool="find_federal_awards", arguments=example_query())
    )
    assert result.decision == "PERMIT" and result.tool_executed
    assert result.verification_state == "RESULT_VERIFIED"
    assert len(result.result["records"]) == 16
    assert adapter.entries == adapter.http_attempts == judge.calls == 1
    policy = next(row for row in trace.events if row["stage"] == "policy")
    complete = next(row for row in trace.events if row["stage"] == "completed")
    assert policy["binding_issued"]
    assert complete["pre_dispatch_verification"] == "PASS"


async def test_natural_intent_is_preserved_not_rewritten_to_force_permission():
    gateway, adapter, judge, trace = prepared(request=NATURAL_REQUEST)
    result = await gateway.call(
        NATURAL_REQUEST, Proposal(tool="find_federal_awards", arguments=example_query())
    )
    assert result.decision == "REVIEW_REQUIRED" and not result.tool_executed
    assert adapter.entries == adapter.http_attempts == 0
    policy = next(row for row in trace.events if row["stage"] == "policy")
    assert policy["facts"]["request_text"] == NATURAL_REQUEST
    assert not policy["binding_issued"]


async def test_optional_recipient_with_faa_token_does_not_change_agency_intent():
    query = example_query(recipient_name="Fictional FAA Systems LLC", limit=5)
    request = 'Show 5 public awards for agency "Federal Aviation Administration" for recipient "Fictional FAA Systems LLC" in Puerto Rico during FY2026.'
    gateway, adapter, judge, trace = prepared(query=query, request=request)
    result = await gateway.call(request, Proposal(tool="find_federal_awards", arguments=query))
    assert result.decision == "PERMIT" and result.result == {"records": []}
    assert adapter.entries == adapter.http_attempts == 1


async def test_discovery_has_four_tools_and_one_explicit_versioned_query_schema():
    gateway, adapter, judge, trace = prepared()
    server = create_scoped_server(gateway)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == set(TOOLS)
    find = next(t for t in tools if t.name == "find_federal_awards")
    query_ref = find.inputSchema["properties"]["query"]["$ref"].split("/")[-1]
    model = find.inputSchema["$defs"][query_ref]
    assert "profile_id" in model["required"] and "state_code" in model["required"]
    assert model["properties"]["agency_tier"]["const"] == "subtier"
    assert_not_entered(adapter, judge, trace)


async def test_sdk_schema_rejection_does_not_create_a_gateway_policy_record():
    gateway, adapter, judge, trace = prepared()
    server = create_scoped_server(gateway)
    legacy_query = {
        "start_date": "2025-10-01",
        "end_date": "2026-09-30",
        "state_code": "PR",
        "awarding_agency": "Federal Aviation Administration",
    }
    with pytest.raises(ToolError):
        await server.call_tool(
            "find_federal_awards", {"user_request": CANONICAL_REQUEST, "query": legacy_query}
        )
    assert_not_entered(adapter, judge, trace)


@pytest.mark.parametrize(
    "tool,query",
    [
        ("get_federal_award", {"award_id": "SYN-FAA-PR-026"}),
        ("resolve_federal_recipient", {"recipient_name": "Fictional Aurora Systems LLC"}),
        (
            "summarize_federal_spending",
            {"start_date": "2025-10-01", "end_date": "2026-09-30", "state_code": "PR"},
        ),
    ],
)
async def test_direct_legacy_wrappers_are_refused_by_the_same_scoped_gateway(tool, query):
    gateway, adapter, judge, trace = prepared()
    server = create_scoped_server(gateway)
    with pytest.raises(
        ToolError, match="FAA_PROFILE_ADMISSION_REJECTED:TOOL_OUTSIDE_SELECTED_PROFILE"
    ):
        await server.call_tool(tool, {"user_request": CANONICAL_REQUEST, "query": query})
    assert_not_entered(adapter, judge, trace)


def test_supported_subset_or_alias_cannot_silently_change_intake_template():
    from evals.proposals.r022.faa_contract_v1 import FaaFy2026PrReadV1

    assert (
        accepted_request_templates(
            FaaFy2026PrReadV1.model_validate(example_query(award_types=["A"]))
        )
        == ()
    )
    with pytest.raises(ProfileAdmissionError):
        TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query(award_types=["A"])))
