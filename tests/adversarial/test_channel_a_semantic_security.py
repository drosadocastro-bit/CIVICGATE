"""New request-level attacks and benign controls, all offline and synthetic.

R1 expectations are versioned separately; original source and results remain in
the byte-identical pre-remediation review ZIP. Lexical gaps remain unchanged.
Passing this suite does not mean the lexical detector is semantically complete or
that a real Judge is accurate. The labels precede measurement, and Judge outputs
are scripted variables rather than model observations.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from civicgate.audit.trace import Trace
from civicgate.governance.agent_k import inspect
from civicgate.governance.authority import denied_reasons
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal
from scripts.evaluate_channel_a_remediation_r1 import measure_case
from scripts.evaluate_channel_a_semantics import (
    MODES,
    CountingReadAdapter,
    ScriptedJudge,
    lexical_summary,
    load_corpus,
)

CORPUS = load_corpus()
CASES = CORPUS["cases"]
PROPOSAL = Proposal.model_validate(CORPUS["proposal"])
R1_EXPECTATIONS = json.loads(
    (Path(__file__).parents[1] / "fixtures/channel_a_remediation_r1_expectations.json").read_text(
        encoding="utf-8"
    )
)
LEXICALLY_DETECTED_CASES = {
    "p-en-06",
    "p-en-07",
    "p-es-06",
    "p-es-07",
    "b-en-01",
    "b-en-02",
    "b-en-03",
    "b-en-04",
    "b-en-05",
    "b-en-07",
    "b-es-01",
    "b-es-02",
    "b-es-03",
    "b-es-04",
    "b-es-07",
}


def test_frozen_request_specifications_have_balanced_language_and_intent() -> None:
    assert len(CASES) == 28
    assert len({case["case_id"] for case in CASES}) == 28
    assert Counter((case["language"], case["request_intent"]) for case in CASES) == {
        ("en", "PROHIBITED_GOVERNMENTAL_ACTION"): 7,
        ("es", "PROHIBITED_GOVERNMENTAL_ACTION"): 7,
        ("en", "BENIGN_PUBLIC_RESEARCH"): 7,
        ("es", "BENIGN_PUBLIC_RESEARCH"): 7,
    }
    assert "not independently adjudicated human ground truth" in CORPUS["label_basis"]
    assert "not a random sample" in CORPUS["measurement_limit"]


def test_characterizes_lexical_false_negatives_and_false_positives_separately() -> None:
    # Deliberate challenge-set counts, not general-population accuracy estimates.
    assert lexical_summary(CASES) == {"TP": 4, "FN": 10, "FP": 11, "TN": 3}
    assert lexical_summary([case for case in CASES if case["language"] == "en"]) == {
        "TP": 2,
        "FN": 5,
        "FP": 6,
        "TN": 1,
    }
    assert lexical_summary([case for case in CASES if case["language"] == "es"]) == {
        "TP": 2,
        "FN": 5,
        "FP": 5,
        "TN": 2,
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_characterizes_request_tripwires_and_dependent_agent_k(case) -> None:
    reasons = denied_reasons(case["request"])
    detected = case["case_id"] in LEXICALLY_DETECTED_CASES
    assert bool(reasons) is detected
    # Agent K shares the same lexical function; it is not an independent detector.
    signal = inspect(case["request"], JudgeSignal(), denials=0, known_tool=True)
    assert signal.containment is detected
    if detected:
        assert "CONTAINMENT_RECOMMENDED" in signal.signals
    else:
        assert signal.signals == ["NONE"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
async def test_characterizes_actual_gateway_under_controlled_judge_inputs(case, mode) -> None:
    row = await measure_case(case, PROPOSAL, mode)
    lexical_hit = case["case_id"] in LEXICALLY_DETECTED_CASES
    prohibited = case["request_intent"] == "PROHIBITED_GOVERNMENTAL_ACTION"
    expectation = R1_EXPECTATIONS["cases"][case["case_id"]][mode]
    expected = expectation["decision"]

    assert row["actual_gateway_policy"]["decision"] == expected
    assert row["actual_gateway_final_decision"] == expected
    assert row["component_policy"]["decision"] == expected
    assert row["request_lexical_reasons"] == row["composed_gateway_lexical_reasons"]
    assert row["actual_judge_provider_calls"] == int(not lexical_hit and mode != "JUDGE_DISABLED")
    assert row["judge_preflight_skipped"] is (lexical_hit and mode != "JUDGE_DISABLED")

    direct_signal = row["scripted_judge_input"]
    delivered_signal = row["actual_gateway_judge_signal"]
    if mode == "UNAVAILABLE":
        assert direct_signal["available"] is False
        assert direct_signal["classification"] == "INSUFFICIENT_INFORMATION"
        assert direct_signal["provider"] == "unavailable"
    else:
        assert direct_signal["available"] is True
        assert direct_signal["classification"] == (
            "POSSIBLE_AUTHORITY_OVERREACH"
            if mode == "SCRIPTED_LABEL_ALIGNED" and prohibited
            else "IN_SCOPE"
        )
        assert direct_signal["provider"] == "synthetic-channel-a-security"
    if mode == "JUDGE_DISABLED":
        assert delivered_signal["available"] is False
        assert delivered_signal["classification"] == "INSUFFICIENT_INFORMATION"
        assert delivered_signal["provider"] == "disabled"
        assert delivered_signal != direct_signal
    elif lexical_hit:
        # Even a scripted label-aligned/permissive input was never delivered to
        # the Gateway when deterministic preflight already required DENY.
        assert delivered_signal["available"] is False
        assert delivered_signal["classification"] == "INSUFFICIENT_INFORMATION"
        assert delivered_signal["provider"] == "unavailable"
        assert delivered_signal != direct_signal
    else:
        # Only this lane actually consulted the provider; preserve all delivered
        # fields, including unavailable input.
        assert delivered_signal == direct_signal

    permitted = expected == "PERMIT"
    assert row["backend_dispatch_count"] == int(permitted)
    assert row["tool_executed"] is permitted
    if permitted:
        assert row["backend_operation"] == "SYNTHETIC_READ_ONLY_AWARD_DETAIL"
        assert row["pre_dispatch_verification"] == "PASS"
        assert row["verification_state"] == "RESULT_VERIFIED"
        assert row["audit_stages"] == ["proposal", "policy", "execution_started", "completed"]
    else:
        assert row["backend_operation"] is None
        assert row["dispatch_state"] == "NOT_DISPATCHED"
        assert row["audit_stages"] == ["proposal", "policy", "completed"]

    if not lexical_hit and prohibited and mode == "SCRIPTED_LABEL_ALIGNED":
        # The semantic signal can hold a lexical miss even though Agent K has no
        # independent authority signal. It does not turn this into deterministic DENY.
        assert row["actual_gateway_agent_k"]["signals"] == ["NONE"]
        assert (
            row["actual_gateway_judge_signal"]["classification"] == "POSSIBLE_AUTHORITY_OVERREACH"
        )
        assert "SEMANTIC_REVIEW_REQUIRED" in row["actual_gateway_policy"]["reasons"]
    if not lexical_hit and prohibited and mode in {"SCRIPTED_PERMISSIVE", "JUDGE_DISABLED"}:
        # R1 independently holds the former semantic-policy gap.
        assert row["actual_gateway_agent_k"]["signals"] == ["NONE"]
        assert row["backend_operation"] is None
        assert row["independent_request_risk"]["reasons"]


@pytest.mark.parametrize(
    "signal,expected,expected_k",
    [
        (
            JudgeSignal(classification="IN_SCOPE", confidence=0.849999, available=True),
            "REVIEW_REQUIRED",
            ["NONE"],
        ),
        (
            JudgeSignal(classification="IN_SCOPE", confidence=0.85, available=True),
            "PERMIT",
            ["NONE"],
        ),
        (
            JudgeSignal(classification="IN_SCOPE", confidence=1.0, available=True),
            "PERMIT",
            ["NONE"],
        ),
        (
            JudgeSignal(classification="IN_SCOPE", confidence=1.0, available=False),
            "REVIEW_REQUIRED",
            ["NONE"],
        ),
        (
            JudgeSignal(classification="OUT_OF_SCOPE", confidence=1.0, available=True),
            "REVIEW_REQUIRED",
            ["NONE"],
        ),
        (
            JudgeSignal(classification="AMBIGUOUS", confidence=1.0, available=True),
            "REVIEW_REQUIRED",
            ["AMBIGUOUS_TARGET"],
        ),
        (
            JudgeSignal(
                classification="IN_SCOPE",
                confidence=1.0,
                available=True,
                flags=["AUTHORITY_OVERREACH"],
            ),
            "REVIEW_REQUIRED",
            ["NONE"],
        ),
    ],
    ids=[
        "below-threshold",
        "at-threshold",
        "high-confidence",
        "unavailable",
        "out-of-scope",
        "ambiguous",
        "authority-flag",
    ],
)
async def test_confidence_threshold_is_only_a_rule_not_evidence_of_calibration(
    signal, expected, expected_k
) -> None:
    adapter = CountingReadAdapter()
    provider = ScriptedJudge(signal)
    result = await Gateway(adapter, provider, Trace()).call(
        "Retrieve public award record 1.", PROPOSAL
    )
    assert result.decision == expected
    assert result.governance.agent_k_signal.signals == expected_k
    assert len(adapter.calls) == int(expected == "PERMIT")
    assert provider.calls == 1


async def test_semantic_provider_exception_fails_closed_on_lexical_miss() -> None:
    class FailingJudge:
        async def assess(self, request, proposal):
            raise RuntimeError("Synthetic provider failure")

    adapter = CountingReadAdapter()
    result = await Gateway(adapter, FailingJudge(), Trace()).call(CASES[0]["request"], PROPOSAL)
    assert result.decision == "REVIEW_REQUIRED"
    assert "SEMANTIC_FAILURE" in result.governance.policy_reasons
    assert result.governance.judge_signal.available is False
    assert adapter.calls == []
