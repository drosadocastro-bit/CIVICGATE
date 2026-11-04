"""Actual A2/MCP/Gateway observations of an explicitly unapplied proposal copy."""

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from civicgate.models.responses import Envelope
from evals.data01.bridge_v1 import run_observation
from evals.data01.reference_v1 import answer
from evals.demos.observability_v1 import install_a2_capture, verify_a2_capture
from evals.harness.evidence import write_new
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_composition_v3 import OfflineScenario
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy
from evals.proposals.r021.preview_v1 import BASE_POLICY_SHA256
from evals.tests.test_data01_fullpath_v1 import result_matches

ROOT = Path.cwd()
CASES = json.loads((ROOT / "evals/data01/agency_scope_r021_cases_v1.json").read_bytes())["cases"]
REFERENCES = json.loads((ROOT / "evals/data01/agency_scope_r021_reference_v1.json").read_bytes())


def lines(path):
    return [json.loads(raw) for raw in path.read_bytes().splitlines()]


@pytest.mark.parametrize("case", CASES, ids=[row["case_id"] for row in CASES])
def test_proposed_review_only_scope_through_actual_authority_boundary(case, monkeypatch):
    policy = ROOT / "src/civicgate/governance/policy.py"
    assert hashlib.sha256(policy.read_bytes()).hexdigest() != BASE_POLICY_SHA256
    assert (ROOT / "src/civicgate/governance/agency_scope_v1.py").is_file()
    directory = ROOT.parent / "execution" / "scope-cases" / case["case_id"]
    directory.mkdir(parents=True, exist_ok=False)
    database = directory / "coordinator.sqlite"
    scenario = OfflineScenario(
        request=case["user_request"],
        proposal_tool=case["tool"],
        proposal_arguments_json=json.dumps(case["arguments"], sort_keys=True),
    )
    run, observation = "R021_" + uuid4().hex, "R021_OBS_" + uuid4().hex
    write_new(directory / "input.json", {"case": case, "proposal_only": True})
    install_a2_capture(monkeypatch, directory)
    LiveAttemptBudget.create(database, run, liability_policy=SyntheticLiabilityPolicy(24))
    returned = asyncio.run(
        run_observation(database, run, observation, directory / "evidence", scenario)
    )
    write_new(directory / "returned.json", returned)
    envelope = Envelope.model_validate(returned["observed_envelope"])
    audit = lines(directory / "evidence/audit.jsonl")
    graph = verify_a2_capture(directory, scenario, audit, returned)
    initial = next(row for row in audit if row["stage"] == "policy")
    events = lines(directory / "evidence/governance-observations.jsonl")
    issued = [r for r in events if r.get("status") == "ISSUED"]
    consumed = [r for r in events if r.get("status") == "VERIFIED_CONSUMED"]
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        state = {
            name: [dict(row) for row in db.execute("SELECT * FROM " + name)]
            for name in (
                "observation_fences",
                "attempts",
                "send_leases",
                "mcp_calls",
            )
        }
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    write_new(directory / "sqlite-readonly.json", state)
    expected = next(
        row["answer"] for row in REFERENCES["cases"] if row["case_id"] == case["case_id"]
    )
    data = json.loads((ROOT / "evals/data01/awards_v1.json").read_bytes())["records"]
    if case["reference_scope"] is not None:
        assert answer(data, case["reference_scope"]) == expected
    measured = {
        "case_id": case["case_id"],
        "run_id": run,
        "observation_id": observation,
        "expected": case["expected_final_policy"],
        "initial": initial["policy"]["decision"],
        "observed": envelope.decision,
        "reasons": envelope.governance.policy_reasons,
        "proposal_only_not_applied_to_worktree": True,
        "policy_sha256": hashlib.sha256(policy.read_bytes()).hexdigest(),
        "binding_issuances": len(issued),
        "binding_consumptions": len(consumed),
        "adapter_entries": returned["adapter_entries"],
        "mock_backend_attempts": returned["mock_backend_attempts"],
        "mcp_logical_calls": returned["mcp_logical_calls"],
        "actual_judge": initial["judge"],
        "primary_projection_verified": returned["primary_projection_verified"],
        "graph_nodes": graph["nodes"],
        "custody": state["observation_fences"][0],
        "fence_close_ack": returned["fence_close"],
        "observed_result": envelope.result,
        "reference_answer": expected,
        "functional_correct": result_matches(
            case["tool"],
            envelope.result,
            expected,
            envelope.provenance.truncated if envelope.provenance else None,
        )
        if expected is not None
        else None,
    }
    write_new(directory / "measurement.json", measured)
    assert returned["error"] is None and returned["primary_projection_verified"]
    assert initial["policy"]["decision"] == case["expected_initial_policy"]
    assert envelope.decision == case["expected_final_policy"]
    dispatch = int(case["expected_dispatch"])
    assert (
        len(issued),
        len(consumed),
        returned["adapter_entries"],
        returned["mock_backend_attempts"],
    ) == (dispatch,) * 4
    assert returned["mcp_logical_calls"] == 1
    assert returned["fence_close"] == "ACKNOWLEDGED"
    fence = state["observation_fences"][0]
    assert fence["state"] == "CLOSED"
    assert (
        fence["summary_sha256"]
        == hashlib.sha256(
            (directory / "evidence/synthetic-observation-summary.json").read_bytes()
        ).hexdigest()
    )
    assert all(row["retry_count"] == 0 for row in state["attempts"])
    assert all(row["state"] == "CONSUMED" for row in state["send_leases"])
    if dispatch:
        assert issued[0]["binding"] == consumed[0]["binding"]
        assert measured["functional_correct"] and envelope.verification_state == "RESULT_VERIFIED"
    else:
        assert envelope.result is None and not envelope.tool_executed
        assert envelope.dispatch_state == "NOT_DISPATCHED"
