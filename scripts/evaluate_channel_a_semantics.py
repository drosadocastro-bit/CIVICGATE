"""Bounded offline request-semantics characterization; no real-model accuracy claim.

The corpus labels are fixed separately from detector observations. Scripted Judge
signals are controlled inputs to the real policy/Gateway, not semantic predictions.
All backend calls use a synthetic HTTP transport and the registered read-only tool.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from civicgate.adapters.usaspending import AdapterCall, USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.governance.agent_k import inspect
from civicgate.governance.authority import denied_reasons
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Award, Proposal

CORPUS = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "channel_a_semantic_security_v1.json"
)
CORPUS_SHA256 = "7a5f57332cab0de75e361c137d775bae2a812a1e3264089a476ec126d7feb371"
MODES = ("SCRIPTED_LABEL_ALIGNED", "SCRIPTED_PERMISSIVE", "UNAVAILABLE", "JUDGE_DISABLED")


def load_corpus() -> dict[str, Any]:
    raw = CORPUS.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORPUS_SHA256:
        raise ValueError("The independently specified corpus identity changed")
    return json.loads(raw)


def scripted_signal(intent: str, mode: str) -> JudgeSignal:
    """Return an explicitly scripted signal, never an inferred model judgment."""
    if mode == "UNAVAILABLE":
        return JudgeSignal(rationale="Offline unavailable-provider test scenario")
    prohibited = intent == "PROHIBITED_GOVERNMENTAL_ACTION"
    is_aligned = mode == "SCRIPTED_LABEL_ALIGNED" and prohibited
    return JudgeSignal(
        classification="POSSIBLE_AUTHORITY_OVERREACH" if is_aligned else "IN_SCOPE",
        confidence=0.99,
        flags=["AUTHORITY_OVERREACH"] if is_aligned else [],
        rationale="Controlled synthetic signal; not a real-model semantic assessment",
        available=True,
        provider="synthetic-channel-a-security",
    )


class ScriptedJudge:
    def __init__(self, signal: JudgeSignal) -> None:
        self.signal = signal
        self.calls = 0

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        self.calls += 1
        return self.signal.model_copy(deep=True)


class CountingReadAdapter(USAspending):
    def __init__(self) -> None:
        super().__init__(transport=fixture_transport(), fixture=True)
        self.calls: list[dict[str, Any]] = []

    async def detail(self, request: Award) -> AdapterCall:
        self.calls.append(request.model_dump(mode="json"))
        return await super().detail(request)


def lexical_summary(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter({"TP": 0, "FN": 0, "FP": 0, "TN": 0})
    for case in cases:
        detected = bool(denied_reasons(case["request"]))
        prohibited = case["request_intent"] == "PROHIBITED_GOVERNMENTAL_ACTION"
        counts[("TP" if detected else "FN") if prohibited else ("FP" if detected else "TN")] += 1
    return dict(counts)


async def measure_case(case: dict[str, Any], proposal: Proposal, mode: str) -> dict[str, Any]:
    signal = scripted_signal(case["request_intent"], mode)
    text = case["request"] + "\n" + json.dumps(proposal.model_dump(), ensure_ascii=False)
    # Component evaluation receives the scripted signal even when Gateway preflight
    # would skip its provider. The report keeps those two measurements distinct.
    agent_k = inspect(text, signal, denials=0, known_tool=True)
    facts = PolicyFacts(tool=proposal.tool, text=text, semantic_required=mode != "JUDGE_DISABLED")
    component_policy = evaluate(facts, signal, agent_k)
    adapter = CountingReadAdapter()
    provider = ScriptedJudge(signal)
    trace = Trace()
    gateway = Gateway(adapter, provider, trace, require_judge=mode != "JUDGE_DISABLED")
    result = await gateway.call(case["request"], proposal)
    policy_event = next(event for event in trace.events if event["stage"] == "policy")
    completed = trace.events[-1]
    return {
        "case_id": case["case_id"],
        "language": case["language"],
        "request_intent_specification": case["request_intent"],
        "mode": mode,
        "request_lexical_reasons": denied_reasons(case["request"]),
        "composed_gateway_lexical_reasons": denied_reasons(text),
        "scripted_judge_input": signal.model_dump(),
        "component_agent_k": agent_k.model_dump(),
        "component_policy": component_policy.model_dump(),
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
        "pre_dispatch_verification": completed["pre_dispatch_verification"],
        "audit_stages": [event["stage"] for event in trace.events],
        "judge_preflight_skipped": policy_event["judge_preflight_skipped"],
    }


async def evaluate_corpus() -> dict[str, Any]:
    corpus = load_corpus()
    cases = corpus["cases"]
    proposal = Proposal.model_validate(corpus["proposal"])
    rows = [await measure_case(case, proposal, mode) for case in cases for mode in MODES]
    return {
        "corpus_id": corpus["corpus_id"],
        "corpus_sha256": CORPUS_SHA256,
        "case_count": len(cases),
        "gateway_calls": len(rows),
        "real_model_calls": 0,
        "live_api_calls": 0,
        "label_basis": corpus["label_basis"],
        "measurement_limit": corpus["measurement_limit"],
        "judge_measurement": "Controlled synthetic inputs only; no real Judge accuracy measured",
        "threshold": 0.85,
        "threshold_calibrated": False,
        "lexical_request_counts": lexical_summary(cases),
        "lexical_request_counts_by_language": {
            language: lexical_summary([case for case in cases if case["language"] == language])
            for language in ("en", "es")
        },
        "gateway_outcomes_by_mode": {
            mode: dict(
                Counter(row["actual_gateway_final_decision"] for row in rows if row["mode"] == mode)
            )
            for mode in MODES
        },
        "gateway_dispatches_by_mode": {
            mode: sum(row["backend_dispatch_count"] for row in rows if row["mode"] == mode)
            for mode in MODES
        },
        "measurements": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate_corpus())
    raw = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if args.output:
        # Do not overwrite a prior measurement or historical verification result.
        with args.output.open("xb") as handle:
            handle.write(raw)
        summary = {key: value for key, value in report.items() if key != "measurements"}
        summary["report_path"] = str(args.output.resolve())
        summary["report_sha256"] = hashlib.sha256(raw).hexdigest()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(raw.decode(), end="")


if __name__ == "__main__":
    main()
