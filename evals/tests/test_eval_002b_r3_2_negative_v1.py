# Additive R3.2 derivative of evals/tests/test_eval_002b_r3_1_negative_v1.py; SHA-256 5513014c508ce71df74f2c97a30b78ad765730c218f12cb9dc66cd98e4e23cb6
# Additive R3.1 regression derivative; original SHA-256: 91478a81c5c2c1b43d0aa1155c68e9d8654cef66a594b0117f80e45b5828cfaa
"""Independent R3 faults against real synthetic stdio observations.

Only newly generated fixture captures are altered. Historical tests, source,
datasets, providers and authority remain outside this test's mutation scope.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals.harness import eval_002b_composition_v4 as composition
from evals.harness.live_attempt_budget_v1 import BudgetError, BudgetUnavailable, LiveAttemptBudget
from evals.harness.live_composition_v3 import OfflineScenario
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy
from evals.harness.provider_response_admission_v2 import evaluate_response

RUN = "R3_INDEPENDENT_SYNTHETIC_ONLY"
OBS = "R3_INDEPENDENT_OBSERVATION"
MODEL = "SYNTHETIC_GRANITE_CONTRACT_STUB"


def _save(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _budget(tmp_path: Path) -> LiveAttemptBudget:
    return LiveAttemptBudget.create(
        tmp_path / "budget.sqlite", RUN, liability_policy=SyntheticLiabilityPolicy(24)
    )


def _observe(
    tmp_path: Path, budget: LiveAttemptBudget, scenario: OfflineScenario | None = None
) -> dict[str, Any]:
    return asyncio.run(
        composition.run_synthetic_observation(
            budget.path, RUN, OBS, tmp_path / "evidence", scenario or OfflineScenario()
        )
    )


def _assert_known_permit(summary: dict[str, Any], state: dict[str, Any]) -> None:
    assert summary["decision"] == "PERMIT"
    assert summary["result_released"] is True
    assert summary["supervisor_server_request_receipts"] == 1
    assert summary["mcp_logical_calls"] == 1
    assert summary["attempt_reservations"] == summary["send_lease_consumptions"] == 2
    assert summary["response_facts_acks"] == 2
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 1
    assert state["counts"] == {"planner": 1, "judge": 1}
    assert len(state["attempts"]) == len(state["liability_reservations"]) == 2
    assert state["reserved_liability_units"] == 2
    assert {row["state"] for row in state["send_leases"]} == {"CONSUMED"}
    assert {row["state"] for row in state["mcp_calls"]} == {"TERMINAL"}
    assert summary["real_provider_requests"] == summary["real_backend_requests"] == 0
    assert summary["live_authorization"] == "HOLD"


def _assert_open_and_no_replay(
    tmp_path: Path, summary: dict[str, Any], budget: LiveAttemptBudget
) -> None:
    before = budget.snapshot()
    assert summary["primary_projection_verified"] is False
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    assert summary["error"] is not None
    assert before["observation_fences"][0]["state"] == "OPEN"
    with pytest.raises(BudgetError):
        asyncio.run(
            composition.run_synthetic_observation(
                budget.path, RUN, "R3_FORBIDDEN_REPLAY", tmp_path / "forbidden-replay"
            )
        )
    assert not (tmp_path / "forbidden-replay").exists()
    assert budget.snapshot() == before


def _inject_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
    alteration: Any,
) -> list[dict[str, Any]]:
    original = composition._json_lines
    injected: list[dict[str, Any]] = []

    def read(path: Path) -> list[dict[str, Any]]:
        if not injected:
            victim = path.parent / target
            raw = victim.read_bytes()
            (tmp_path / "preserved-original-capture.bin").write_bytes(raw)
            replacement = alteration(raw)
            if replacement is None:
                victim.unlink()
            else:
                victim.write_bytes(replacement)
                (tmp_path / "injected-capture.bin").write_bytes(replacement)
            injected.append(
                {
                    "target": target,
                    "original_bytes": len(raw),
                    "original_sha256": hashlib.sha256(raw).hexdigest(),
                    "replacement_bytes": len(replacement) if replacement is not None else None,
                    "replacement_sha256": hashlib.sha256(replacement).hexdigest()
                    if replacement is not None
                    else None,
                }
            )
        return original(path)

    monkeypatch.setattr(composition, "_json_lines", read)
    return injected


def _stream_fault(raw: bytes, fault: str) -> bytes | None:
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == 1 and rows[0]["phase"] == "entered"
    if fault == "missing":
        return None
    if fault == "empty":
        return b""
    if fault == "empty-object":
        return b"{}\n"
    if fault == "truncated":
        return raw[:-1]
    if fault == "duplicate":
        return raw + raw
    row = rows[0]
    if fault == "wrong-method":
        row["method"] = "GET" if "attempt_index" in row else "get_award"
    elif fault == "wrong-query":
        row["query"]["state_code"] = "ZZ"
    elif fault == "wrong-path":
        row["request_path"] = "/api/v2/recipient/"
    elif fault == "wrong-body-hash":
        row["request_body_sha256"] = "f" * 64
    elif fault == "wrong-mode":
        row["mode"] = "timeout"
    else:
        raise AssertionError(fault)
    return json.dumps(row, allow_nan=False).encode() + b"\n"


@pytest.mark.parametrize(
    "target,fault",
    [
        ("dispatch.jsonl", "empty"),
        ("http-attempts.jsonl", "empty"),
        ("http-attempts.jsonl", "empty-object"),
        ("dispatch.jsonl", "missing"),
        ("dispatch.jsonl", "empty-object"),
        ("dispatch.jsonl", "truncated"),
        ("dispatch.jsonl", "duplicate"),
        ("dispatch.jsonl", "wrong-method"),
        ("dispatch.jsonl", "wrong-query"),
        ("http-attempts.jsonl", "missing"),
        ("http-attempts.jsonl", "truncated"),
        ("http-attempts.jsonl", "duplicate"),
        ("http-attempts.jsonl", "wrong-method"),
        ("http-attempts.jsonl", "wrong-path"),
        ("http-attempts.jsonl", "wrong-body-hash"),
        ("http-attempts.jsonl", "wrong-mode"),
    ],
)
def test_permit_capture_fault_preserves_facts_and_blocks_closure_replay_and_refund(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str, fault: str
) -> None:
    budget = _budget(tmp_path)
    injected = _inject_capture(monkeypatch, tmp_path, target, lambda raw: _stream_fault(raw, fault))
    summary = _observe(tmp_path, budget)
    state = budget.snapshot()
    _save(
        tmp_path / "independent-result.json",
        {"fault": fault, "injected": injected, "summary": summary, "ledger": state},
    )
    assert injected
    _assert_known_permit(summary, state)
    assert summary["server_request_receipts"] == 2
    _assert_open_and_no_replay(tmp_path, summary, budget)


def _worker_fault(raw: bytes, fault: str) -> bytes | None:
    body = json.loads(raw)
    assert set(body["roles"]) == {"planner", "judge"}
    assert len(body["server_receipts"]) == 1
    if fault == "missing":
        return None
    if fault == "roles-only":
        return b'{"roles":{}}\n'
    if fault == "empty-object":
        return b"{}\n"
    if fault == "list-root":
        return b"[]\n"
    if fault == "null-root":
        return b"null\n"
    if fault == "invalid-json":
        return b"not-json\n"
    if fault == "truncated-json":
        return raw[: len(raw) // 2]
    if fault == "roles-list":
        body["roles"] = []
    elif fault == "missing-judge":
        body["roles"].pop("judge")
    elif fault == "null-events":
        body["roles"]["judge"]["events"] = None
    elif fault == "wrong-event-type":
        body["roles"]["judge"]["events"] = ["ROLE_ACCEPTED"]
    elif fault == "receipt-type":
        body["server_receipts"] = ["received"]
    elif fault == "receipt-missing-field":
        body["server_receipts"][0].pop("request_sha256")
    elif fault == "boolean-connections":
        body["server_connections"] = True
    else:
        raise AssertionError(fault)
    return json.dumps(body, allow_nan=False).encode() + b"\n"


@pytest.mark.parametrize(
    "fault",
    [
        "roles-only",
        "empty-object",
        "list-root",
        "null-root",
        "roles-list",
        "missing-judge",
        "null-events",
        "wrong-event-type",
        "receipt-type",
        "receipt-missing-field",
        "boolean-connections",
        "invalid-json",
        "truncated-json",
        "missing",
    ],
)
def test_worker_malformed_capture_returns_incomplete_without_erasing_known_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    budget = _budget(tmp_path)
    injected = _inject_capture(
        monkeypatch, tmp_path, "worker-http-evidence.json", lambda raw: _worker_fault(raw, fault)
    )
    summary = _observe(tmp_path, budget)
    state = budget.snapshot()
    _save(
        tmp_path / "independent-result.json",
        {"fault": fault, "injected": injected, "summary": summary, "ledger": state},
    )
    assert injected
    _assert_known_permit(summary, state)
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 1
    assert summary["worker_capture_state"] == "UNKNOWN_INCOMPLETE"
    assert summary["supervisor_capture_state"] == "VALIDATED"
    assert summary["server_request_receipts"] is None
    supervisor = json.loads((tmp_path / "evidence" / "supervisor-http-evidence.json").read_bytes())
    assert len(supervisor["server_receipts"]) == supervisor["server_connections"] == 1
    assert supervisor["server_receipts"][0]["body_received"] is True
    _assert_open_and_no_replay(tmp_path, summary, budget)


@pytest.mark.parametrize(
    "scenario,decision,judge_count,backend_count",
    [
        (OfflineScenario(), "PERMIT", 1, 1),
        (
            OfflineScenario(request="Blacklist this contractor from future federal work."),
            "DENY",
            0,
            0,
        ),
        (OfflineScenario(judge_flags=("NONE",)), "REVIEW_REQUIRED", 1, 0),
    ],
)
def test_complete_permit_deny_and_review_have_reconciled_observation_local_counts(
    tmp_path: Path, scenario: OfflineScenario, decision: str, judge_count: int, backend_count: int
) -> None:
    budget = _budget(tmp_path)
    summary = _observe(tmp_path, budget, scenario)
    state = budget.snapshot()
    _save(tmp_path / "independent-result.json", {"summary": summary, "ledger": state})
    assert summary["decision"] == decision
    assert summary["error"] is None
    assert summary["primary_projection_verified"] is True
    assert summary["fence_close"] == "ACKNOWLEDGED"
    assert summary["binding_issuances"] == summary["binding_consumptions"] == backend_count
    assert summary["adapter_entries"] == summary["mock_backend_attempts"] == backend_count
    assert summary["server_request_receipts"] == 1 + judge_count
    assert state["counts"] == {"planner": 1, "judge": judge_count}
    assert state["reserved_liability_units"] == 1 + judge_count
    assert state["observation_fences"][0]["state"] == "CLOSED"


@pytest.mark.parametrize(
    "scenario",
    [
        OfflineScenario(backend_mode="malformed"),
        OfflineScenario(backend_mode="timeout"),
        OfflineScenario(drop_response=True),
    ],
)
def test_invalid_or_lost_result_retains_consumed_work_and_open_fence(
    tmp_path: Path, scenario: OfflineScenario
) -> None:
    budget = _budget(tmp_path)
    summary = _observe(tmp_path, budget, scenario)
    state = budget.snapshot()
    _save(tmp_path / "independent-result.json", {"summary": summary, "ledger": state})
    assert summary["binding_issuances"] == summary["binding_consumptions"] == 1
    if scenario.drop_response:
        assert summary["adapter_entries"] is summary["mock_backend_attempts"] is None
        assert (
            summary["reported_adapter_entry_records"]
            == summary["reported_mock_backend_records"]
            == 1
        )
        assert summary["primary_projection_verified"] is False
        assert summary["backend_capture_admission"] == {
            "decision": "REJECTED",
            "reason": "BACKEND_CAPTURE_OBSERVED_ENVELOPE_REQUIRED",
        }
    else:
        assert summary["adapter_entries"] == summary["mock_backend_attempts"] == 1
    assert summary["result_released"] is False
    assert summary["fence_close"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    assert state["observation_fences"][0]["state"] == "OPEN"
    assert state["counts"] == {"planner": 1, "judge": 1}
    assert state["reserved_liability_units"] == 2
    before = budget.snapshot()
    with pytest.raises(BudgetError):
        asyncio.run(
            composition.run_synthetic_observation(
                budget.path, RUN, "R3_NO_REPLAY", tmp_path / "forbidden-replay"
            )
        )
    assert budget.snapshot() == before
    assert not (tmp_path / "forbidden-replay").exists()


def test_capture_failure_with_unacknowledged_stop_stays_open_and_retains_reservations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _budget(tmp_path)
    stops: list[str] = []

    def unavailable_stop(_budget: LiveAttemptBudget, reason: str) -> None:
        stops.append(reason)
        raise BudgetUnavailable("R3_SYNTHETIC_STOP_CUSTODY_UNAVAILABLE")

    injected = _inject_capture(
        monkeypatch, tmp_path, "http-attempts.jsonl", lambda raw: _stream_fault(raw, "empty")
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(LiveAttemptBudget, "stop", unavailable_stop)
        summary = _observe(tmp_path, budget)
    state = budget.snapshot()
    _save(
        tmp_path / "independent-result.json",
        {"summary": summary, "ledger": state, "stops": stops, "injected": injected},
    )
    assert stops and state["stopped"] is False
    _assert_known_permit(summary, state)
    _assert_open_and_no_replay(tmp_path, summary, budget)


def _response(content: str, outer_extra: str = "") -> bytes:
    return (
        '{"model":'
        + json.dumps(MODEL)
        + ',"choices":[{"finish_reason":"stop","message":{"content":'
        + json.dumps(content)
        + '}}],"usage":{"prompt_tokens":7,"completion_tokens":5,"total_tokens":12}'
        + outer_extra
        + "}"
    ).encode()


@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("location", ["typed-nested", "ignored-outer-nested"])
def test_nonfinite_numbers_fail_recursively_and_preserve_original_response_facts(
    tmp_path: Path, number: str, location: str
) -> None:
    content = '{"tool":"find_federal_awards","arguments":{"nested":[{"x":' + number + "}]}}"
    raw = (
        _response(content)
        if location == "typed-nested"
        else _response(
            '{"tool":"find_federal_awards","arguments":{}}',
            ',"metadata":{"nested":[{"x":' + number + "}]}",
        )
    )
    facts = evaluate_response(200, raw, requested_model=MODEL, role="planner")
    _save(
        tmp_path / "independent-response.json",
        {"facts": facts, "raw_sha256": hashlib.sha256(raw).hexdigest()},
    )
    assert len(facts) == 11
    assert facts["http_status"] == 200
    assert facts["body_bytes"] == len(raw)
    assert facts["body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert facts["contract"] == "FAIL" and facts["errors"]
    if location == "typed-nested":
        assert facts["model_identity"] == "MATCH"
        assert facts["usage"] == "KNOWN"
        assert facts["completion"] == "COMPLETE"
        assert facts["typed_schema"] == "FAIL"


@pytest.mark.parametrize("location", ["outer", "typed"])
def test_bounded_deep_json_never_escapes_structured_reporting(
    tmp_path: Path, location: str
) -> None:
    nested = "[" * 10_000 + "0" + "]" * 10_000
    raw = (
        ('{"nested":' + nested + "}").encode()
        if location == "outer"
        else _response('{"tool":"find_federal_awards","arguments":{"nested":' + nested + "}}")
    )
    assert len(raw) < 200_000
    facts = evaluate_response(200, raw, requested_model=MODEL, role="planner")
    _save(tmp_path / "independent-response.json", {"facts": facts})
    assert facts["contract"] == "FAIL" and facts["errors"]
    assert facts["http_status"] == 200
    assert facts["body_bytes"] == len(raw)
    assert facts["body_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("number", ["1.25", "1e308", "-1e308"])
def test_finite_json_numbers_are_not_rejected_by_nonfinite_remediation(number: str) -> None:
    raw = _response(
        '{"tool":"find_federal_awards","arguments":{"nested":[{"x":' + number + "}]}}",
        ',"metadata":{"x":' + number + "}",
    )
    facts = evaluate_response(200, raw, requested_model=MODEL, role="planner")
    assert facts["contract"] == facts["typed_schema"] == "PASS"
