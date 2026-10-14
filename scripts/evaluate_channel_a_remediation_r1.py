"""Versioned offline R1 measurements; never overwrite the preserved v1 result."""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from civicgate.audit.trace import Trace
from civicgate.governance.agent_k import inspect
from civicgate.governance.authority import denied_reasons
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.governance.request_risk import assess_request_risk
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from scripts.evaluate_channel_a_semantics import (
    CountingReadAdapter,
    ScriptedJudge,
    lexical_summary,
    load_corpus,
    scripted_signal,
)

ROOT = Path(__file__).resolve().parents[1]
HELDOUT = ROOT / "tests/fixtures/channel_a_remediation_r1_heldout.json"
HELDOUT_SHA256 = "3ca1fd65273710a4f408c9f0ad7add1e53f86eb2080f186d5d19f2cd16173230"
R1_MODES = ("PERMISSIVE", "UNAVAILABLE", "CONFLICTING", "CAUTIOUS", "DISABLED")


def heldout_cases() -> list[dict[str, Any]]:
    raw = HELDOUT.read_bytes()
    if hashlib.sha256(raw).hexdigest() != HELDOUT_SHA256:
        raise ValueError("Held-out specification identity differs")
    return [
        {
            **case,
            "case_id": case["id"],
            "request_intent": {
                "HOLD": "PROHIBITED_GOVERNMENTAL_ACTION",
                "BENIGN": "BENIGN_PUBLIC_RESEARCH",
                "UNCERTAIN": "UNRESOLVED",
            }[case["expected_safety"]],
        }
        for case in json.loads(raw)["cases"]
    ]


def signal_for(case: dict[str, Any], mode: str) -> JudgeSignal:
    if mode == "CONFLICTING":
        return JudgeSignal(
            classification="IN_SCOPE",
            confidence=0.99,
            flags=["AUTHORITY_OVERREACH"],
            available=True,
            provider="synthetic-r1-conflicting",
        )
    if mode == "CAUTIOUS":
        return JudgeSignal(
            classification="AMBIGUOUS",
            confidence=0.5,
            available=True,
            provider="synthetic-r1-cautious",
        )
    legacy_mode = {"PERMISSIVE": "SCRIPTED_PERMISSIVE", "DISABLED": "JUDGE_DISABLED"}.get(
        mode, mode
    )
    return scripted_signal(case["request_intent"], legacy_mode)


async def measure_case(case: dict[str, Any], proposal: Proposal, mode: str) -> dict[str, Any]:
    signal = signal_for(case, mode)
    disabled = mode in {"DISABLED", "JUDGE_DISABLED"}
    request = case["request"]
    text = request + "\n" + json.dumps(proposal.model_dump(), ensure_ascii=False)
    agent_k = inspect(text, signal, denials=0, known_tool=True)
    facts = PolicyFacts(
        tool=proposal.tool,
        text=text,
        request_text=request,
        semantic_required=not disabled,
        arguments_json=TOOLS[proposal.tool].model_validate(proposal.arguments).model_dump_json(),
    )
    adapter = CountingReadAdapter()
    provider = ScriptedJudge(signal)
    trace = Trace()
    result = await Gateway(adapter, provider, trace, require_judge=not disabled).call(
        request, proposal
    )
    policy_event = next(event for event in trace.events if event["stage"] == "policy")
    return {
        "case_id": case["case_id"],
        "language": case["language"],
        "request_intent_specification": case["request_intent"],
        "mode": mode,
        "request_lexical_reasons": denied_reasons(request),
        "composed_gateway_lexical_reasons": denied_reasons(text),
        "independent_request_risk": assess_request_risk(request).__dict__,
        "scripted_judge_input": signal.model_dump(),
        "component_agent_k": agent_k.model_dump(),
        "component_policy": evaluate(facts, signal, agent_k).model_dump(),
        "actual_judge_provider_calls": provider.calls,
        "actual_gateway_judge_signal": result.governance.judge_signal.model_dump(),
        "actual_gateway_agent_k": result.governance.agent_k_signal.model_dump(),
        "actual_gateway_policy": policy_event["policy"],
        "actual_gateway_final_decision": result.decision,
        "backend_dispatch_count": len(adapter.calls),
        "backend_operation": "SYNTHETIC_READ_ONLY_AWARD_DETAIL" if adapter.calls else None,
        "tool_executed": result.tool_executed,
        "dispatch_state": result.dispatch_state,
        "verification_state": result.verification_state,
        "pre_dispatch_verification": trace.events[-1]["pre_dispatch_verification"],
        "audit_stages": [event["stage"] for event in trace.events],
        "judge_preflight_skipped": policy_event["judge_preflight_skipped"],
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        mode: {
            "decisions": dict(
                Counter(row["actual_gateway_final_decision"] for row in rows if row["mode"] == mode)
            ),
            "unsafe_permits": [
                row["case_id"]
                for row in rows
                if row["mode"] == mode
                and row["request_intent_specification"] != "BENIGN_PUBLIC_RESEARCH"
                and row["actual_gateway_final_decision"] == "PERMIT"
            ],
            "benign_hard_denials": [
                row["case_id"]
                for row in rows
                if row["mode"] == mode
                and row["request_intent_specification"] == "BENIGN_PUBLIC_RESEARCH"
                and row["actual_gateway_final_decision"] == "DENY"
            ],
            "benign_review_holds": [
                row["case_id"]
                for row in rows
                if row["mode"] == mode
                and row["request_intent_specification"] == "BENIGN_PUBLIC_RESEARCH"
                and row["actual_gateway_final_decision"] == "REVIEW_REQUIRED"
            ],
            "backend_dispatches": sum(
                row["backend_dispatch_count"] for row in rows if row["mode"] == mode
            ),
        }
        for mode in R1_MODES
    }


async def report() -> dict[str, Any]:
    original = load_corpus()
    heldout = heldout_cases()
    proposal = Proposal.model_validate(original["proposal"])
    original_rows = [
        await measure_case(case, proposal, mode) for case in original["cases"] for mode in R1_MODES
    ]
    heldout_rows = [
        await measure_case(case, proposal, mode) for case in heldout for mode in R1_MODES
    ]
    return {
        "evaluation_contract": "channel-a-security-remediation-r1",
        "baseline": "61ac3416af4a109a2e1fd3f58b6aab1415737e43",
        "original_corpus_sha256": "7a5f57332cab0de75e361c137d775bae2a812a1e3264089a476ec126d7feb371",
        "heldout_sha256": HELDOUT_SHA256,
        "limits": "Author-specified test labels, synthetic Judge inputs, no population accuracy or threshold calibration claim. Developers saw the independent held-out specification before implementation; it was frozen before evaluation.",
        "original_lexical_counts_unchanged": lexical_summary(original["cases"]),
        "original_current_policy": summarize(original_rows),
        "heldout_current_policy": summarize(heldout_rows),
        "original_measurements": original_rows,
        "heldout_measurements": heldout_rows,
        "implementation_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "src/civicgate/governance/request_risk.py",
                "src/civicgate/governance/policy.py",
                "src/civicgate/mcp/tools.py",
                "src/civicgate/mcp/server.py",
            )
        },
        "real_model_calls": 0,
        "live_api_calls": 0,
        "threshold_calibrated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(report())
    raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    with args.output.open("xb") as stream:
        stream.write(raw)
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"original_measurements", "heldout_measurements"}
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
