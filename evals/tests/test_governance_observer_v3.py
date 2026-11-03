"""Exact real caller resolution, with unchanged policy and strict admission."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from civicgate.governance.execution import ExecutionBoundary
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from evals.harness import governance_observer_v2 as facade
from evals.harness.backend_capture_admission_v3 import validate_backend_capture
from evals.harness.governance_observer_v3 import OBSERVER_VERSION, ReadOnlyGovernanceObserver
from evals.harness.synthetic_server import EvidenceLedger, SyntheticAdapter, SyntheticTrace
from evals.tests.test_eval_002b_r3_2_backend_v1 import (
    OBSERVATION,
    REQUEST,
    SEARCH,
    _admit,
    _capture,
    _Judge,
    _rows,
)

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_SHA = "0e71f86c8a70a110f9db18d00c8429e98890433deaac21199f27a4d9989add94"


def returns(directory):
    return [
        r
        for r in _rows(directory, "governance-observations.jsonl")
        if r["event"] == "governance_return"
    ]


def test_facade_is_explicitly_v3_and_original_v2_reference_is_exact():
    assert facade.ReadOnlyGovernanceObserver is ReadOnlyGovernanceObserver
    assert facade.OBSERVER_VERSION == OBSERVER_VERSION == "CIVICGATE-EVAL-GOVERNANCE-OBSERVER-V3"
    raw = (ROOT / "evals/harness/governance_observer_v2_reference.py").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == REFERENCE_SHA
    assert b"CIVICGATE-EVAL-GOVERNANCE-OBSERVER-V2" in raw


@pytest.mark.parametrize(
    "user_request,args,decision",
    [
        (REQUEST, SEARCH, "PERMIT"),
        ("Blacklist this contractor from future federal work.", SEARCH, "DENY"),
        (REQUEST, {"start_date": "2025-01-01", "end_date": "2025-02-01"}, "REVIEW_REQUIRED"),
    ],
)
def test_real_policy_phases_request_and_observation_correlate_once(
    tmp_path, user_request, args, decision
):
    directory = tmp_path / "capture"
    expected = _capture(directory, request=user_request, arguments=args)
    admitted = _admit(directory, expected)
    assert admitted["state"] == (
        "BOUND_BACKEND_CAPTURED" if decision == "PERMIT" else "PRE_DISPATCH_HELD"
    )
    events = returns(directory)
    assert all(r["request_id"] == expected["expected_request_id"] for r in events)
    assert all(r["correlation_id"] == OBSERVATION for r in events)
    assert all(r["observer_version"] == OBSERVER_VERSION for r in events)
    phases = [r["phase"] for r in events]
    assert (
        phases.count("policy_preflight")
        == phases.count("policy_issuance")
        == phases.count("binding_issue")
        == 1
    )
    assert phases.count("binding_consume") == int(decision == "PERMIT")
    assert "policy_other" not in phases
    assert sorted(r["call_index"] for r in events) == list(range(1, len(events) + 1))
    assert len({r["call_index"] for r in events}) == len(events)
    assert expected["expected_envelope"].decision == decision
    assert len(admitted["dispatch"]) == len(admitted["backend"]) == int(decision == "PERMIT")


def test_post_result_review_is_a_distinct_actual_policy_evaluation(tmp_path):
    directory = tmp_path / "capture"
    expected = _capture(
        directory, tool="resolve_federal_recipient", arguments={"recipient_name": "ACME"}
    )
    admitted = _admit(directory, expected)
    events = returns(directory)
    assert admitted["state"] == "BOUND_BACKEND_CAPTURED"
    assert expected["expected_envelope"].decision == "REVIEW_REQUIRED"
    assert len(admitted["dispatch"]) == 1
    assert [r["phase"] for r in events] == [
        "policy_preflight",
        "policy_issuance",
        "binding_issue",
        "binding_consume",
        "policy_post_result",
    ]
    assert events[0]["policy"]["decision"] == "REVIEW_REQUIRED"
    assert events[1]["policy"]["decision"] == "PERMIT"
    assert events[-1]["policy"]["decision"] == "REVIEW_REQUIRED"
    assert all(r["request_id"] == expected["expected_request_id"] for r in events)
    assert len({r["call_index"] for r in events}) == 5


def test_wrapper_is_context_not_an_extra_event_target(tmp_path):
    observer = ReadOnlyGovernanceObserver(tmp_path, "SYNTHETIC_CONTEXT")
    assert set(observer._targets) == {
        evaluate.__code__,
        ExecutionBoundary.evaluate.__code__,
        ExecutionBoundary.consume.__code__,
    }
    assert Gateway._evaluate.__code__ not in observer._targets


@pytest.mark.parametrize(
    "fault",
    [
        "unrecognized_wrapper",
        "wrong_outer_code",
        "different_gateway",
        "different_facts",
        "missing_gateway",
    ],
)
def test_context_resolver_rejects_inconsistent_or_unknown_frame_shapes(tmp_path, fault):
    observer = ReadOnlyGovernanceObserver(tmp_path, "SYNTHETIC_CONTEXT")
    gateway_object = object()
    facts = object()
    outer = SimpleNamespace(
        f_code=Gateway._call.__code__,
        f_locals={"self": gateway_object, "request_id": "EXISTING_REQUEST"},
        f_back=None,
    )
    wrapper = SimpleNamespace(
        f_code=Gateway._evaluate.__code__,
        f_locals={"self": gateway_object, "facts": facts},
        f_back=outer,
    )
    frame = SimpleNamespace(f_code=evaluate.__code__, f_locals={"facts": facts}, f_back=wrapper)
    if fault == "unrecognized_wrapper":
        wrapper.f_code = (lambda: None).__code__
    elif fault == "wrong_outer_code":
        outer.f_code = (lambda: None).__code__
    elif fault == "different_gateway":
        wrapper.f_locals["self"] = object()
    elif fault == "different_facts":
        wrapper.f_locals["facts"] = object()
    elif fault == "missing_gateway":
        wrapper.f_back = None
    assert observer._gateway_frame(frame) is None
    assert observer._phase(frame, "policy") == "policy_other"
    assert observer._request_id(frame) is None
    assert observer._events == []


def test_standalone_policy_is_never_promoted_to_gateway_preflight(tmp_path):
    facts = PolicyFacts(
        tool="find_federal_awards", text=REQUEST, request_text=REQUEST, bounded=True
    )
    with ReadOnlyGovernanceObserver(tmp_path, "SYNTHETIC_DIRECT"):
        result = evaluate(
            facts,
            JudgeSignal(classification="IN_SCOPE", available=True, confidence=0.99),
            KSignal(),
            0.85,
        )
    events = returns(tmp_path)
    assert len(events) == 1
    assert events[0]["phase"] == "policy_other"
    assert events[0]["request_id"] is None
    assert events[0]["policy"]["decision"] == result.decision
    assert sys.getprofile() is None


def test_actual_gateway_wrapper_outside_call_cannot_fabricate_preflight(tmp_path):
    observation = "SYNTHETIC_OUTSIDE_GATEWAY_CALL"
    ledger = EvidenceLedger(tmp_path)
    gateway = Gateway(SyntheticAdapter(ledger, "normal"), _Judge(), SyntheticTrace(ledger))
    facts = PolicyFacts(
        tool="find_federal_awards", text=REQUEST, request_text=REQUEST, bounded=True
    )
    with ReadOnlyGovernanceObserver(tmp_path, observation):
        gateway._evaluate(
            facts,
            JudgeSignal(classification="IN_SCOPE", available=True, confidence=0.99),
            KSignal(),
            0.85,
        )
    events = returns(tmp_path)
    assert len(events) == 1
    assert events[0]["phase"] == "policy_other" and events[0]["request_id"] is None
    assert events[0]["status"] == "RETURNED_POLICY"
    assert _rows(tmp_path, "dispatch.jsonl") == _rows(tmp_path, "http-attempts.jsonl") == []
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_OBSERVER_PHASE_INVALID"):
        validate_backend_capture(
            tmp_path, observation, _rows(tmp_path, "governance-observations.jsonl")
        )


def test_existing_profiler_is_preserved_without_observing(tmp_path):
    def previous(*args):
        return None

    observer = ReadOnlyGovernanceObserver(tmp_path, "SYNTHETIC_EXISTING")
    try:
        sys.setprofile(previous)
        with pytest.raises(RuntimeError, match="OBSERVER_EXISTING_PROFILER_UNSUPPORTED"):
            observer.__enter__()
        assert sys.getprofile() is previous
        assert not observer.path.exists()
    finally:
        sys.setprofile(None)


def test_close_flush_is_idempotent_and_capture_does_not_retain_frames(tmp_path):
    observer = ReadOnlyGovernanceObserver(tmp_path, "SYNTHETIC_EMPTY")
    with observer:
        pass
    before = observer.path.read_bytes()
    observer.close()
    observer.flush()
    assert observer.path.read_bytes() == before
    rows = [json.loads(line) for line in before.splitlines()]
    assert len(rows) == 1 and rows[0]["status"] == "PASS"
    assert observer._starts == {} and observer._events == []
    assert sys.getprofile() is None
