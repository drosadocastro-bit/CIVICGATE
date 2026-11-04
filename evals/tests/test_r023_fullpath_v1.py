"""Actual fixed-host MCP paths; synthetic data, not global host isolation."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from evals.data01.reference_v1 import answer
from evals.harness.evidence import write_new
from evals.proposals.r022.faa_contract_v1 import DOT, FAA, PROFILE_ID
from evals.proposals.r022.observation_v1 import observe_case as legacy_host_control
from evals.proposals.r023.host_v1 import HOST_FIXED_MODULE
from evals.proposals.r023.observation_v1 import observe_case

ROOT = Path.cwd()
DOCUMENT = json.loads((ROOT / "evals/data01/r023_cases_v1.json").read_bytes())
CASES = DOCUMENT["cases"]


@pytest.mark.parametrize("case", CASES, ids=[row["case_id"] for row in CASES])
def test_fixed_host_real_mcp_and_adversarial_routes(case, monkeypatch):
    directory = ROOT.parent / "execution" / "r023-cases" / case["case_id"]
    result = asyncio.run(observe_case(case, directory, monkeypatch))
    write_new(directory / "assertion-input.json", {"case": case, "observation": result})
    assert result["host_path_verified"] is True
    assert result["legacy_routes_offered_to_agent"] == []
    assert result["fixed_target_module"] == HOST_FIXED_MODULE
    assert result["host_requested_profile"] == PROFILE_ID
    assert result["transport_status"] == case["expected_status"]
    assert result["final_policy"] == case["expected_policy"]
    assert (
        result["binding_issuances"] == result["binding_consumptions"] == case["expected_bindings"]
    )
    assert (
        result["adapter_entries"]
        == result["mock_backend_attempts"]
        == case["expected_backend_attempts"]
    )
    assert result["real_provider_requests"] == result["live_backend_requests"] == 0

    if case.get("startup_mutation"):
        assert result["startup_refusal_verified_no_gateway_projection"] is True
        assert result["host_selection_verified"] is False
        assert result["server_selected_profile"] is None
        assert result["primary_projection_verified"] is False
        assert result["observed_envelope"] is None
        assert result["actual_sdk_tool_calls"] == result["mcp_logical_calls"] == 0
        assert result["custody_state"] == "OPEN" and result["budget_stopped"]
        return

    assert result["primary_projection_verified"] is True
    assert result["host_selection_verified"] is True
    assert result["server_selected_profile"] == PROFILE_ID
    assert result["startup_refusal_verified_no_gateway_projection"] is False
    assert result["mcp_logical_calls"] == 1
    assert result["actual_sdk_tool_calls"] == 1 + bool(case.get("after_call"))
    assert result["manual_adversarial_replay_calls"] == bool(case.get("after_call"))
    if case.get("after_call"):
        replay = json.loads((directory / "replay-result.json").read_bytes())
        assert replay["isError"] is True
    if case.get("after_call") == "reinitialize_then_repeat":
        assert result["protocol_reinitializations"] == 1
        second = json.loads((directory / "reinitialized-tools.json").read_bytes())
        assert {row["name"] for row in second["tools"]} == {
            "find_federal_awards",
            "get_federal_award",
            "resolve_federal_recipient",
            "summarize_federal_spending",
        }

    if case["expected_status"] == "MCP_TOOL_ERROR":
        assert result["initial_policy"] is None
        assert result["observed_envelope"] is None
        assert result["custody_state"] == "OPEN"
        return
    envelope = result["observed_envelope"]
    if case["expected_result_count"] is None:
        assert envelope["result"] is None
    else:
        query = case["host_query"]
        scope = {
            "kind": "search",
            "agency": DOT,
            "subagency": FAA,
            "start_date": query["start_date"],
            "end_date": query["end_date"],
            "state": "PR",
            "award_types": query["award_types"],
            "limit": query["limit"],
            "recipient": query.get("recipient_name"),
        }
        original = json.loads((ROOT / "evals/data01/awards_v1.json").read_bytes())["records"]
        reference = answer(original, scope)
        records = envelope["result"]["records"]
        assert len(records) == case["expected_result_count"]
        assert [row["generated_internal_id"] for row in records] == reference["award_ids"]
        assert [int(Decimal(row["award_amount"]) * 100) for row in records] == reference[
            "amount_cents"
        ]
        assert envelope["provenance"]["truncated"] == reference["has_next"]
        assert envelope["verification_state"] == "RESULT_VERIFIED"
        write_new(directory / "functional-reference.json", {"scope": scope, "answer": reference})

    if case["backend_mode"] == "normal":
        assert result["custody_state"] == "CLOSED"
    else:
        assert result["initial_policy"] == "PERMIT"
        assert result["custody_state"] == "OPEN"
        assert envelope["verification_state"] == "FAILED_VALIDATION"


def test_separate_host_legacy_control_is_not_an_agent_route(monkeypatch):
    """The test host independently composes legacy; FAA agent never receives it."""
    original = json.loads((ROOT / "evals/data01/r022_cases_v1.json").read_bytes())["cases"]
    case = next(row for row in original if row["case_id"] == "R022-023")
    case = {**case, "case_id": DOCUMENT["separate_legacy_control_case_id"]}
    directory = ROOT.parent / "execution" / "r023-cases" / case["case_id"]
    observed = asyncio.run(legacy_host_control(case, directory, monkeypatch))
    assert observed["primary_projection_verified"]
    assert observed["initial_policy"] == observed["final_policy"] == "PERMIT"
    assert observed["observed_envelope"]["result"]["records"] == []
    assert observed["binding_issuances"] == observed["binding_consumptions"] == 1
    assert observed["adapter_entries"] == observed["mock_backend_attempts"] == 1
    write_new(
        directory / "separate-host-disposition.json",
        {
            "legacy_behavior": "PRESERVED_WITH_KNOWN_SEMANTIC_LIMITATION",
            "agent_route": False,
            "independently_host_composed_control": True,
            "legacy_false_permit_is_not_faa_semantic_success": True,
        },
    )
