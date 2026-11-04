"""DATA-01 observations through the existing R3.2/A2/MCP/Gateway path."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from mcp import ClientSession

from civicgate.models.responses import Envelope
from evals.data01.bridge_v1 import run_observation
from evals.data01.reference_v1 import references
from evals.demos.observability_v1 import install_a2_capture, verify_a2_capture
from evals.harness import eval_002b_composition_v4 as composition
from evals.harness.evidence import write_new
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_composition_v3 import OfflineScenario
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy

ROOT = Path.cwd()
HERE = ROOT / "evals/data01"
CASES = json.loads((HERE / "benchmark_v1.json").read_bytes())["cases"]
REFERENCE = json.loads((HERE / "reference_answers_v1.json").read_bytes())


def lines(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def result_matches(tool, result, expected, truncated=None):
    if result is None or expected is None:
        return False
    if "has_next" in expected and (
        type(truncated) is not bool or truncated != expected["has_next"]
    ):
        return False
    if tool == "summarize_federal_spending":
        return (
            result["scope"] == "RETURNED_PAGE_ONLY"
            and result["record_count"] == len(expected["award_ids"])
            and Decimal(result["returned_award_amount_total_usd"])
            == Decimal(expected["returned_page_amount_usd"])
        )
    records = result["records"]
    if tool == "resolve_federal_recipient":
        return [row["name"] for row in records] == expected["recipient_names"]
    if tool == "get_federal_award":
        return [row["generated_unique_award_id"] for row in records] == expected["award_ids"] and [
            int(Decimal(row["total_obligation"]) * 100) for row in records
        ] == expected["amount_cents"]
    return [row["generated_internal_id"] for row in records] == expected["award_ids"] and [
        int(Decimal(row["award_amount"]) * 100) for row in records
    ] == expected["amount_cents"]


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_data01_existing_fullpath(case, monkeypatch):
    assert references() == REFERENCE
    directory = ROOT.parent / "execution" / "cases" / case["case_id"]
    directory.mkdir(parents=True, exist_ok=False)
    dataset_before = hashlib.sha256((HERE / "awards_v1.json").read_bytes()).hexdigest()
    run_id = "DATA01_" + uuid4().hex
    observation_id = "DATA01_OBS_" + uuid4().hex
    database = directory / "coordinator.sqlite"
    evidence = directory / "evidence"
    scenario = OfflineScenario(
        request=case["user_request"],
        proposal_tool=case["proposal"]["tool"],
        proposal_arguments_json=json.dumps(case["proposal"]["arguments"], sort_keys=True),
    )
    write_new(directory / "case.json", {"benchmark": case, "scenario": asdict(scenario)})
    initialize = ClientSession.initialize
    discover = composition.ObservedTransport.discover

    async def capture_initialize(self, *args, **kwargs):
        value = await initialize(self, *args, **kwargs)
        write_new(directory / "mcp-initialize.json", value.model_dump(mode="json"))
        return value

    async def capture_discover(self, *args, **kwargs):
        value = await discover(self, *args, **kwargs)
        write_new(directory / "mcp-tools-list.json", [asdict(item) for item in value])
        return value

    monkeypatch.setattr(ClientSession, "initialize", capture_initialize)
    monkeypatch.setattr(composition.ObservedTransport, "discover", capture_discover)
    install_a2_capture(monkeypatch, directory)
    LiveAttemptBudget.create(database, run_id, liability_policy=SyntheticLiabilityPolicy(24))
    returned = asyncio.run(run_observation(database, run_id, observation_id, evidence, scenario))
    write_new(directory / "returned.json", returned)
    # Primary observations are saved before any expectation assertion.
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        state = {
            name: [dict(row) for row in db.execute("SELECT * FROM " + name)]
            for name in (
                "observation_fences",
                "mcp_calls",
                "attempts",
                "send_leases",
                "response_facts",
            )
        }
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    write_new(directory / "sqlite-readonly.json", state)
    envelope = Envelope.model_validate(returned["observed_envelope"])
    audit = lines(evidence / "audit.jsonl")
    policy = next(row for row in audit if row["stage"] == "policy")
    completed = next(row for row in audit if row["stage"] == "completed")
    primary = verify_a2_capture(directory, scenario, audit, returned)
    expected = next(
        row["answer"] for row in REFERENCE["cases"] if row["case_id"] == case["case_id"]
    )
    from civicgate.models.requests import TOOLS

    observed_proposal = primary["effective_proposal"]
    reference_args = case["reference_arguments"]
    try:
        effective_reference = (
            TOOLS[case["reference_tool"]].model_validate(reference_args).model_dump(mode="json")
        )
    except ValueError:
        effective_reference = None
    measured = {
        "case_id": case["case_id"],
        "run_id": run_id,
        "observation_id": observation_id,
        "synthetic": True,
        "planner_identity": "SCRIPTED_PROTOCOL_FIXTURE_NOT_GRANITE",
        "judge_identity": "PERMISSIVE_PROTOCOL_FIXTURE_NOT_LUNA",
        "initial_policy": policy["policy"]["decision"],
        "final_policy": envelope.decision,
        "policy_reasons": envelope.governance.policy_reasons,
        "tool_correct": observed_proposal["tool"] == case["reference_tool"],
        "arguments_correct": observed_proposal["arguments"] == effective_reference
        if effective_reference is not None
        else None,
        "argument_evaluable": effective_reference is not None,
        "functional_eligible": case["functional_eligible"],
        "query_result_correct": result_matches(
            envelope.tool,
            envelope.result,
            expected,
            envelope.provenance.truncated if envelope.provenance else None,
        )
        if case["functional_eligible"]
        else None,
        "reference_answer": expected,
        "returned_result": envelope.result,
        "result_released": envelope.result is not None,
        "verification_state": envelope.verification_state,
        "binding_issuances": returned["binding_issuances"],
        "binding_consumptions": returned["binding_consumptions"],
        "adapter_entries": returned["adapter_entries"],
        "mock_backend_attempts": returned["mock_backend_attempts"],
        "mcp_logical_calls": returned["mcp_logical_calls"],
        "primary_projection_verified": returned["primary_projection_verified"],
        "custody_state": state["observation_fences"][0]["state"],
        "fence_close_ack": returned["fence_close"],
        "graph_nodes": primary["nodes"],
        "judge": policy["judge"],
        "judge_preflight_skipped": policy["judge_preflight_skipped"],
        "pre_dispatch_verification": completed.get("pre_dispatch_verification"),
        "provenance": envelope.provenance.model_dump(mode="json") if envelope.provenance else None,
        "dataset_unchanged": hashlib.sha256((HERE / "awards_v1.json").read_bytes()).hexdigest()
        == dataset_before,
        "attempt_count": envelope.attempt_count,
        "dispatch_state": envelope.dispatch_state,
    }
    write_new(directory / "measurement.json", measured)
    assert returned["error"] is None
    assert measured["dataset_unchanged"] and returned["primary_projection_verified"]
    assert measured["initial_policy"] == case["expected_initial_policy"]
    assert measured["final_policy"] == case["expected_final_policy"]
    dispatch = int(case["expected_dispatch"])
    assert (
        returned["binding_issuances"],
        returned["binding_consumptions"],
        returned["adapter_entries"],
        returned["mock_backend_attempts"],
    ) == (dispatch,) * 4
    assert measured["custody_state"] == "CLOSED" and returned["fence_close"] == "ACKNOWLEDGED"
    assert state["mcp_calls"][0]["outcome"] == "CLIENT_RESPONSE_OBSERVED"
    assert all(row["retry_count"] == 0 for row in state["attempts"])
    assert (
        len(state["attempts"])
        == len(state["send_leases"])
        == (1 if case["expected_initial_policy"] == "DENY" else 2)
    )
    assert measured["mcp_logical_calls"] == 1
    tools = json.loads((directory / "mcp-tools-list.json").read_bytes())
    assert {row["name"] for row in tools} == set(TOOLS)
    if case["functional_eligible"]:
        assert measured["query_result_correct"]
        assert measured["provenance"]["source_type"] == "SYNTHETIC_TEST_FIXTURE"
    else:
        assert envelope.result is None and not envelope.tool_executed


def test_reference_and_result_negative_controls():
    assert result_matches(
        "find_federal_awards", {"records": []}, {"award_ids": [], "amount_cents": []}
    )
    assert not result_matches(
        "find_federal_awards", {"records": []}, {"award_ids": ["missing"], "amount_cents": [1]}
    )
    assert not result_matches(
        "find_federal_awards",
        {"records": []},
        {"award_ids": [], "amount_cents": [], "has_next": True},
        False,
    )
    assert not result_matches(
        "summarize_federal_spending",
        {
            "scope": "POPULATION_TOTAL",
            "record_count": 0,
            "returned_award_amount_total_usd": "0.00",
        },
        {"award_ids": [], "returned_page_amount_usd": "0.00"},
    )
