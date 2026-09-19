"""Reproducible component metrics. Fixtures are synthetic, never LLM validation."""

import asyncio
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from civicgate.adapters.usaspending import USAspending
from civicgate.agent.agent import CivicGateAgent
from civicgate.audit.trace import Trace
from civicgate.demo import SCENARIOS, fixture_adapter
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.provenance import utcnow
from civicgate.models.requests import TOOLS, Proposal
from civicgate.models.responses import Envelope

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixture_transports import build_transport  # noqa: E402


def assert_observed_receipt(expected: dict[str, Any], result: Envelope, trace: Trace) -> None:
    """Check only receipt fields observable by CivicGate, never hidden snapshots."""
    observed: dict[str, Any] = result.model_dump(mode="json")
    completed = next(
        (event for event in reversed(trace.events) if event.get("stage") == "completed"), {}
    )
    observed["attempts"] = completed.get("attempts", [])
    for key, expected_value in expected.items():
        if key == "attempts":
            actual_attempts = observed["attempts"]
            if len(actual_attempts) != len(expected_value):
                raise AssertionError(f"attempt count mismatch for observed_receipt: {key}")
            for index, partial in enumerate(expected_value):
                for field, value in partial.items():
                    if actual_attempts[index].get(field) != value:
                        raise AssertionError(
                            f"attempt {index} field {field!r}: "
                            f"expected {value!r}, got {actual_attempts[index].get(field)!r}"
                        )
        elif observed.get(key) != expected_value:
            raise AssertionError(
                f"observed_receipt field {key!r}: expected {expected_value!r}, got {observed.get(key)!r}"
            )


def ratio(passed: int, total: int, scope: str) -> dict[str, Any]:
    return {
        "numerator": passed,
        "denominator": total,
        "value": passed / total if total else None,
        "scope": scope,
    }


async def main() -> None:
    fixtures = json.loads(Path("tests/fixtures/adversarial.json").read_text())
    rows = []
    for case in fixtures:
        adapter = fixture_adapter()
        if case.get("transport_factory"):
            adapter = USAspending(build_transport(case["transport_factory"]), fixture=True)
        elif case.get("adapter") == "malformed":
            adapter = USAspending(
                httpx.MockTransport(lambda r: httpx.Response(200, json={})), fixture=True
            )
        judge = UnavailableProvider() if case.get("judge_failure") else MockProvider()
        trace = Trace()
        gateway = Gateway(adapter, judge, trace)
        proposal = Proposal(tool=case["tool"], arguments=case["arguments"])
        if case.get("repeated"):
            for _ in range(2):
                await gateway.call("blacklist contractor", proposal)
        start = time.perf_counter()
        result = await gateway.call(case["request"], proposal)
        if case.get("observed_receipt"):
            assert_observed_receipt(case["observed_receipt"], result, trace)
        elapsed = (time.perf_counter() - start) * 1000
        well_formed = Envelope.model_validate_json(result.model_dump_json()) == result
        completed_event = next(
            (event for event in reversed(trace.events) if event.get("stage") == "completed"), {}
        )
        schema_valid = False
        if proposal.tool in TOOLS:
            try:
                TOOLS[proposal.tool].model_validate(proposal.arguments)
                schema_valid = True
            except ValueError:
                pass
        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected_decision": case["expected_decision"],
                "decision": result.decision,
                "status": result.status,
                "expected_status": case["expected_status"],
                "matched": result.decision == case["expected_decision"]
                and result.status == case["expected_status"],
                "schema_valid": schema_valid,
                "well_formed": well_formed,
                "provenance_complete": result.provenance is not None,
                "latency_ms": elapsed,
                "semantic_outcome": "MOCK_SIGNAL_ONLY"
                if result.governance.judge_signal.available
                else "NOT_RUN_INVALID_INPUT"
                if "INVALID_INPUT" in result.governance.policy_reasons
                else "SEMANTIC_FAILURE / GOVERNANCE_HELD"
                if not result.tool_executed
                else "SEMANTIC_FAILURE / GOVERNANCE_FAILED",
                "judge_classification": result.governance.judge_signal.classification,
                "agent_k_signals": result.governance.agent_k_signal.signals,
                "attempts": completed_event.get("attempts", []),
                "response": result.model_dump(mode="json"),
            }
        )
    agent = CivicGateAgent(MockProvider(), Gateway(fixture_adapter(), MockProvider(), Trace()))
    selected = [await agent.run(text) for text in SCENARIOS]
    expected = ["find_federal_awards", "find_federal_awards", "resolve_federal_recipient"]
    valid = [r for r in rows if r["category"] == "valid"]
    out = [r for r in rows if r["category"] == "out_of_scope"]
    ambiguity = [r for r in rows if r["category"] == "ambiguity"]
    malformed = [r for r in rows if r["category"] == "malformed_adapter"]
    returned = [r for r in rows if r["response"]["result"] is not None]
    facts = PolicyFacts(tool="find_federal_awards", text="public awards")
    signal = JudgeSignal(classification="IN_SCOPE", confidence=1, available=True)
    deterministic = (
        len({evaluate(facts, signal, KSignal()).model_dump_json() for _ in range(100)}) == 1
    )
    metrics = {
        "tool_selection_accuracy": ratio(
            sum(r.tool == t for r, t in zip(selected, expected, strict=True)),
            3,
            "Three explicit mock planner fixtures, not real LLM accuracy",
        ),
        "schema_validity": ratio(
            sum(r["schema_valid"] for r in rows),
            len(rows),
            "Submitted fixtures including intentionally invalid inputs",
        ),
        "valid_request_success_rate": ratio(
            sum(r["status"] == "OK" for r in valid), len(valid), "Synthetic valid fixtures"
        ),
        "provenance_completeness": ratio(
            sum(r["provenance_complete"] for r in returned),
            len(returned),
            "Responses with released data",
        ),
        "out_of_scope_denial_rate": ratio(
            sum(r["decision"] == "DENY" for r in out), len(out), "Listed tripwire fixtures only"
        ),
        "ambiguity_escalation_rate": ratio(
            sum(r["decision"] == "REVIEW_REQUIRED" for r in ambiguity),
            len(ambiguity),
            "Synthetic ambiguity fixtures",
        ),
        "deterministic_decision_consistency": ratio(
            100 if deterministic else 0, 100, "Identical normalized facts repeated"
        ),
        "malformed_adapter_response_containment": ratio(
            sum(r["status"] == "ERROR" and r["response"]["result"] is None for r in malformed),
            len(malformed),
            "Synthetic malformed responses",
        ),
        "judge_agreement": {
            "value": None,
            "status": "NOT_MEASURED_REAL_MODEL_UNCONFIGURED",
            "mock_classifications": {r["id"]: r["judge_classification"] for r in rows},
        },
        "agent_k_detection_rate": ratio(
            sum("NONE" not in r["agent_k_signals"] for r in out),
            len(out),
            "Expected out-of-scope fixture detections",
        ),
        "latency_ms": {
            "median": statistics.median(r["latency_ms"] for r in rows),
            "max": max(r["latency_ms"] for r in rows),
            "scope": "Offline fixture execution only",
        },
        "response_well_formedness": ratio(
            sum(r["well_formed"] for r in rows), len(rows), "Pydantic envelope roundtrip"
        ),
    }
    output = {
        "generated_at": utcnow().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mode": "SYNTHETIC_TEST_FIXTURE",
        "metrics": metrics,
        "cases": rows,
        "fixture_matches": sum(r["matched"] for r in rows),
        "fixture_count": len(rows),
        "limitations": [
            "No real-model semantic accuracy measured",
            "No population safety score",
            "No historical PRAETOR evidence transferred",
        ],
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/evaluation.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(
        f"{output['fixture_matches']}/{len(rows)} expected fixture outcomes; artifacts/evaluation.json"
    )
    if not all(r["matched"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
