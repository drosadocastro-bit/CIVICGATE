# Additive R3.2 derivative of evals/tests/test_eval_002b_r3_1_composition_v1.py; SHA-256 ec55be76934a439b7a31ac16898c8719a91cd1466393727e7f22ae27729993e1
# Additive R3.1 regression derivative; original SHA-256: ca5b0c9af1b2274709ec1d3176da5bbd679bde1e0d62f1675b7818a83fca4277
"""R3 positive composition and write-custody regressions; synthetic only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from evals.harness import eval_002b_composition_v4 as composition
from evals.harness.eval_002b_composition_v4 import run_synthetic_observation
from evals.harness.live_attempt_budget_v1 import (
    BudgetError,
    BudgetUnavailable,
    LiveAttemptBudget,
    RecoveryBlocked,
)
from evals.harness.live_composition_v3 import OfflineScenario
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy


def _run(tmp_path: Path, scenario: OfflineScenario) -> tuple[dict, LiveAttemptBudget]:
    database = tmp_path / "budget.sqlite"
    budget = LiveAttemptBudget.create(
        database, "SYNTHETIC_STDIO_RUN", liability_policy=SyntheticLiabilityPolicy(24)
    )
    summary = asyncio.run(
        run_synthetic_observation(
            database, budget.run_id, "SYNTHETIC_STDIO_OBSERVATION", tmp_path / "evidence", scenario
        )
    )
    return summary, budget


def test_real_stdio_graph_and_two_socket_roles_preserve_binding_boundary(tmp_path: Path) -> None:
    summary, budget = _run(tmp_path, OfflineScenario())
    assert summary["error"] is None
    assert summary["graph_status"] == "COMPLETED"
    assert summary["decision"] == "PERMIT"
    assert summary["context_preserved"] is True
    assert summary["attempt_reservations"] == summary["send_lease_consumptions"] == 2
    assert summary["server_request_receipts"] == summary["response_facts_acks"] == 2
    assert summary["mcp_logical_calls"] == 1
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 1
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 1
    assert summary["result_released"] is True
    assert summary["fence_close"] == "ACKNOWLEDGED"
    assert budget.snapshot()["counts"] == {"planner": 1, "judge": 1}
    for name, role in (("supervisor", "planner"), ("worker", "judge")):
        primary = json.loads((tmp_path / "evidence" / f"{name}-http-evidence.json").read_bytes())
        assert len(primary["server_receipts"]) == 1
        assert primary["server_receipts"][0]["body_received"] is True
        assert primary["roles"][role]["wire"]["header_emission_attempts"] == 1
        assert primary["roles"][role]["response_contract"]["contract"] == "PASS"


@pytest.mark.parametrize(
    "scenario,decision,judge_count",
    [
        (OfflineScenario(request="Blacklist this contractor from future federal work."), "DENY", 0),
        (OfflineScenario(judge_flags=("NONE",)), "REVIEW_REQUIRED", 1),
    ],
)
def test_deny_and_review_issue_no_binding_or_backend_dispatch(
    tmp_path: Path, scenario: OfflineScenario, decision: str, judge_count: int
) -> None:
    summary, budget = _run(tmp_path, scenario)
    assert summary["decision"] == decision
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 0
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 0
    assert summary["server_request_receipts"] == 1 + judge_count
    assert budget.snapshot()["counts"] == {"planner": 1, "judge": judge_count}


def test_invalid_backend_preserves_permit_read_but_never_releases_result(tmp_path: Path) -> None:
    summary, budget = _run(tmp_path, OfflineScenario(backend_mode="malformed"))
    assert summary["decision"] == "PERMIT"
    assert summary["verification_state"] == "FAILED_VALIDATION"
    assert summary["result_released"] is False
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 1
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 1
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    with pytest.raises(RecoveryBlocked):
        LiveAttemptBudget(budget.path, budget.run_id).ensure_recoverable()


def test_worker_response_identity_failure_blocks_dispatch_and_next_process(tmp_path: Path) -> None:
    summary, budget = _run(tmp_path, OfflineScenario(judge_mode="missing_model"))
    assert summary["decision"] == "REVIEW_REQUIRED"
    assert summary["result_released"] is False
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 0
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 0
    assert summary["budget_stopped"] is True
    assert summary["server_request_receipts"] == 2
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    with pytest.raises(BudgetError):
        LiveAttemptBudget(budget.path, budget.run_id).ensure_recoverable()


def test_lost_mcp_response_preserves_execution_and_blocks_automatic_reissue(tmp_path: Path) -> None:
    summary, budget = _run(tmp_path, OfflineScenario(drop_response=True))
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 1
    # Without the independently observed envelope, backend counts are reports,
    # not an admitted projection. Known execution and reservations still persist.
    assert summary["adapter_entries"] is summary["mock_backend_attempts"] is None
    assert (
        summary["reported_adapter_entry_records"] == summary["reported_mock_backend_records"] == 1
    )
    assert summary["primary_projection_verified"] is False
    assert summary["backend_capture_admission"] == {
        "decision": "REJECTED",
        "reason": "BACKEND_CAPTURE_OBSERVED_ENVELOPE_REQUIRED",
    }
    assert summary["result_released"] is False
    assert summary["mcp_logical_calls"] == 1
    assert summary["budget_stopped"] is True
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    before = budget.snapshot()
    with pytest.raises(BudgetError):
        asyncio.run(
            run_synthetic_observation(
                budget.path, budget.run_id, "SYNTHETIC_REISSUE_FORBIDDEN", tmp_path / "no-reissue"
            )
        )
    assert budget.snapshot()["counts"] == before["counts"]
    assert not (tmp_path / "no-reissue").exists()


def test_missing_initial_open_ack_starts_no_fixture_or_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "budget.sqlite"
    budget = LiveAttemptBudget.create(
        database, "SYNTHETIC_STDIO_RUN", liability_policy=SyntheticLiabilityPolicy(24)
    )
    starts = []

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise BudgetUnavailable("SYNTHETIC_INITIAL_OPEN_NO_ACK")

    async def forbidden_server(*args: Any) -> Any:
        starts.append(True)
        raise AssertionError("No server may start before OPEN ACK")

    monkeypatch.setattr(LiveAttemptBudget, "begin_observation", unavailable)
    monkeypatch.setattr(composition.fixtures.SyntheticHTTPServer, "__aenter__", forbidden_server)
    with pytest.raises(BudgetUnavailable):
        asyncio.run(
            run_synthetic_observation(
                database, budget.run_id, "NO_OPEN_ACK", tmp_path / "no-evidence"
            )
        )
    assert not starts
    assert not (tmp_path / "no-evidence").exists()
    assert budget.snapshot()["attempts"] == []
    assert budget.snapshot()["observation_fences"] == []


def test_final_snapshot_failure_returns_unknown_and_preserves_known_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_reader = composition.read_provider_capture
    original_snapshot = LiveAttemptBudget.snapshot
    final_phase = []

    def reader(path: Path) -> dict[str, Any]:
        result = original_reader(path)
        if path.name == "worker-http-evidence.json":
            final_phase.append(True)
        return result

    def snapshot(budget: LiveAttemptBudget) -> dict[str, Any]:
        if final_phase:
            raise BudgetUnavailable("SYNTHETIC_FINAL_SNAPSHOT_UNKNOWN")
        return original_snapshot(budget)

    monkeypatch.setattr(composition, "read_provider_capture", reader)
    monkeypatch.setattr(LiveAttemptBudget, "snapshot", snapshot)
    summary, budget = _run(tmp_path, OfflineScenario())
    assert summary["coordinator_snapshot_state"] == "UNKNOWN"
    assert summary["primary_projection_verified"] is False
    assert summary["decision"] == "PERMIT"
    assert (
        summary["binding_consumptions"]
        == summary["adapter_entries"]
        == summary["mock_backend_attempts"]
        == 1
    )
    assert summary["attempt_reservations"] is None
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    assert original_snapshot(budget)["observation_fences"][0]["state"] == "OPEN"


@pytest.mark.parametrize("stop_write_fails", [False, True])
def test_summary_write_failure_never_closes_or_reports_stop_without_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_write_fails: bool
) -> None:
    original_write = composition.write_new

    def write(path: Path, value: Any) -> None:
        if path.name == "synthetic-observation-summary.json":
            raise OSError("SYNTHETIC_SUMMARY_WRITE_FAILURE")
        original_write(path, value)

    def failed_stop(*args: Any, **kwargs: Any) -> None:
        raise BudgetUnavailable("SYNTHETIC_STOP_WRITE_UNKNOWN")

    monkeypatch.setattr(composition, "write_new", write)
    if stop_write_fails:
        monkeypatch.setattr(LiveAttemptBudget, "stop", failed_stop)
    summary, budget = _run(tmp_path, OfflineScenario())
    assert summary["summary_custody"] == "UNKNOWN_INCOMPLETE"
    assert summary["root_stop_attempted"] is True
    assert summary["root_stop_acknowledged"] is (not stop_write_fails)
    assert summary["primary_projection_verified"] is False
    assert summary["decision"] == "PERMIT" and summary["result_released"] is True
    assert (
        summary["binding_consumptions"]
        == summary["adapter_entries"]
        == summary["mock_backend_attempts"]
        == 1
    )
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    assert budget.snapshot()["observation_fences"][0]["state"] == "OPEN"
    assert budget.snapshot()["counts"] == {"planner": 1, "judge": 1}


@pytest.mark.parametrize("layer", ["outer", "typed"])
@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
def test_r31_composition_nonfinite_response_never_accepts_or_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layer: str, number: str
) -> None:
    """One owned synthetic planner socket, both JSON layers, no model inference.

    A coherent rejected provider response is still documentary evidence. This
    test does not equate primary projection with provider acceptance. It checks
    typed rejection, OPEN and unchanged reserved/consumed facts independently.
    """
    import hashlib

    original_reply = composition.synthetic_reply
    emitted: list[bytes] = []

    def reply(role: str, scenario: OfflineScenario) -> Any:
        original = original_reply(role, scenario)
        if role != "planner":
            return original
        body = json.loads(original.body)
        marker = "R31_NONFINITE_SENTINEL_ONLY"
        if layer == "outer":
            body["unused_nested_metadata"] = [{"number": marker}]
            raw = json.dumps(body, allow_nan=False).replace(json.dumps(marker), number).encode()
        else:
            content = json.loads(body["choices"][0]["message"]["content"])
            content["arguments"]["nested_numeric_metadata"] = [{"number": marker}]
            content_raw = json.dumps(content, allow_nan=False).replace(json.dumps(marker), number)
            body["choices"][0]["message"]["content"] = content_raw
            raw = json.dumps(body, allow_nan=False).encode()
        assert marker.encode() not in raw
        assert number.encode() in raw
        assert raw != original.body
        assert emitted == []
        emitted.append(raw)
        (tmp_path / "synthetic-nonfinite-response.bin").write_bytes(raw)
        return composition.fixtures.SyntheticReply(body=raw)

    monkeypatch.setattr(composition, "synthetic_reply", reply)
    run_id = "R31_NONFINITE_" + layer.upper()
    observation_id = "R31_NONFINITE_OBSERVATION_" + layer.upper()
    database = tmp_path / "budget.sqlite"
    budget = LiveAttemptBudget.create(
        database, run_id, liability_policy=SyntheticLiabilityPolicy(24)
    )
    summary = asyncio.run(
        run_synthetic_observation(
            database, run_id, observation_id, tmp_path / "evidence", OfflineScenario()
        )
    )
    state = budget.snapshot()
    primary = json.loads((tmp_path / "evidence" / "supervisor-http-evidence.json").read_bytes())
    facts = primary["roles"]["planner"]["response_contract"]
    raw = emitted[0]
    assert facts["contract"] == "FAIL"
    assert facts["body_bytes"] == len(raw)
    assert facts["body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert facts["http_status"] == 200
    if layer == "outer":
        assert "INVALID_OR_AMBIGUOUS_RESPONSE_JSON" in facts["errors"]
    else:
        assert "TYPED_RESPONSE_SCHEMA_REJECTED" in facts["errors"]
    assert primary["roles"]["planner"]["response_facts_acknowledged"] is True
    assert not any(
        event.get("event") == "ROLE_ACCEPTED" for event in primary["roles"]["planner"]["events"]
    )
    assert summary["graph_status"] == "PLANNING_FAILED"
    assert summary["result_released"] is False
    assert summary["mcp_logical_calls"] == 0
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 0
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 0
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    assert summary["attempt_reservations"] == summary["send_lease_consumptions"] == 1
    assert summary["response_facts_acks"] == 1
    assert summary["real_provider_requests"] == summary["real_backend_requests"] == 0
    assert state["counts"] == {"planner": 1, "judge": 0}
    assert len(state["attempts"]) == len(state["send_leases"]) == 1
    assert state["send_leases"][0]["state"] == "CONSUMED"
    assert state["observation_fences"][0]["state"] == "OPEN"
    assert len(state["response_facts"]) == 1
    before_recovery = budget.snapshot()
    with pytest.raises(BudgetError):
        LiveAttemptBudget(database, run_id).ensure_recoverable()
    assert budget.snapshot() == before_recovery
    report = {
        "candidate_module": composition.__name__,
        "candidate_path": composition.__file__,
        "candidate_sha256": hashlib.sha256(Path(composition.__file__).read_bytes()).hexdigest(),
        "layer": layer,
        "number": number,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "summary": summary,
        "provider_primary": primary,
        "coordinator": state,
        "recovery_blocked_without_new_operation": True,
        "no_retry_or_refund": True,
    }
    with (tmp_path / "r31-nonfinite-full-composition-result.json").open(
        "x", encoding="utf-8"
    ) as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
