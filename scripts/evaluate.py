"""Reproducible component metrics. Fixtures are synthetic, never LLM validation."""

import argparse
import asyncio
import hashlib
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
from civicgate.models.governance import JudgeSignal, KSignal, PolicyResult
from civicgate.models.provenance import utcnow
from civicgate.models.requests import TOOLS, Proposal
from civicgate.models.responses import Envelope

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fixture_transports import build_transport  # noqa: E402

ORIGINAL_FIXTURE_SHA256 = "28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc"
R1_PROJECTION_SHA256 = "8079b5610c2c9bf89a9b5441924cb295ee691d400596194000e7b2197d43d160"
R1_PROJECTION_ID = "channel-a-legacy-evaluation-r1"
R1_OVERRIDES = {
    "ambiguous-recipient": {"expected_status": "BLOCKED"},
    "benign-risk-term": {"expected_decision": "REVIEW_REQUIRED", "expected_status": "BLOCKED"},
    "ambiguous-recipient-name": {"expected_status": "BLOCKED"},
    "contradictory-semantic": {
        "expected_decision": "REVIEW_REQUIRED",
        "expected_status": "BLOCKED",
    },
    "timeout-provider": {"expected_decision": "REVIEW_REQUIRED", "expected_status": "BLOCKED"},
    "judge-semantic-disagreement": {
        "expected_decision": "REVIEW_REQUIRED",
        "expected_status": "BLOCKED",
    },
    "five-hundred-then-success": {"request": "Show public awards"},
    "timeout-then-changed-snapshot": {"request": "Show public awards"},
}


def load_fixtures(
    *, projection: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Select an explicit pinned synthetic contract without rewriting source bytes."""
    fixture_path = Path("tests/fixtures/adversarial.json")
    original_raw = fixture_path.read_bytes()
    if projection is None:
        return json.loads(original_raw), None
    if projection != R1_PROJECTION_ID:
        raise ValueError("Unsupported evaluation projection")
    original_sha256 = hashlib.sha256(original_raw).hexdigest()
    if original_sha256 != ORIGINAL_FIXTURE_SHA256:
        raise ValueError("Original evaluation fixture SHA-256 mismatch")
    projection_path = Path("tests/fixtures/channel_a_legacy_evaluation_r1.json")
    projection_raw = projection_path.read_bytes()
    projection_sha256 = hashlib.sha256(projection_raw).hexdigest()
    if projection_sha256 != R1_PROJECTION_SHA256:
        raise ValueError("R1 evaluation projection SHA-256 mismatch")
    contract = json.loads(projection_raw)
    if (
        not isinstance(contract, dict)
        or set(contract) != {"contract_id", "original_fixture_sha256", "basis", "overrides"}
        or contract["contract_id"] != R1_PROJECTION_ID
        or contract["original_fixture_sha256"] != original_sha256
        or not isinstance(contract["basis"], str)
        or not contract["basis"].strip()
        or contract["overrides"] != R1_OVERRIDES
    ):
        raise ValueError("Invalid R1 evaluation projection contract")
    fixtures = json.loads(original_raw)
    if (
        not isinstance(fixtures, list)
        or len(fixtures) != 35
        or not all(isinstance(case, dict) and isinstance(case.get("id"), str) for case in fixtures)
    ):
        raise ValueError("Invalid original evaluation fixture cases")
    ids = [case["id"] for case in fixtures]
    if len(ids) != len(set(ids)) or not set(R1_OVERRIDES).issubset(ids):
        raise ValueError("Missing or duplicate evaluation fixture IDs")
    changes = {}
    for case in fixtures:
        override = contract["overrides"].get(case["id"], {})
        if not set(override).issubset(case):
            raise ValueError("R1 projection cannot add fixture fields")
        if override:
            changes[case["id"]] = {
                field: {"original": case[field], "effective": value}
                for field, value in override.items()
            }
            case.update(override)
    effective_raw = json.dumps(
        fixtures, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return fixtures, {
        "contract_id": R1_PROJECTION_ID,
        "original_fixture_path": fixture_path.as_posix(),
        "original_fixture_sha256": original_sha256,
        "projection_path": projection_path.as_posix(),
        "projection_sha256": projection_sha256,
        "effective_fixture_sha256": hashlib.sha256(effective_raw).hexdigest(),
        "effective_fixture_serialization": "UTF-8 JSON; sorted keys; compact; ensure_ascii=True",
        "basis": contract["basis"],
        "changes": changes,
    }


def semantic_outcome(result: Envelope, trace: Trace) -> str:
    """Classify only the reported request's recorded judge participation.

    Policy is recorded before adapter dispatch and may later escalate. Do not
    infer judge success/failure from the final decision or tool_executed.
    """
    events = [
        event
        for event in trace.events
        if event.get("stage") == "policy" and event.get("request_id") == result.request_id
    ]
    prefix = f"Judge accounting verification failed for request {result.request_id}: "
    if len(events) != 1:
        raise ValueError(prefix + "expected exactly one matching policy event")
    event = events[0]
    try:
        skipped = event["judge_preflight_skipped"]
        accounting = event["failure_accounting"]
        required = event["facts"]["semantic_required"]
        valid_input = event["facts"]["valid_input"]
        if not isinstance(event["judge"], dict) or not {
            "classification",
            "confidence",
            "available",
            "provider",
        }.issubset(event["judge"]):
            raise ValueError("incomplete judge evidence")
        judge = JudgeSignal.model_validate(event["judge"])
        policy = PolicyResult.model_validate(event["policy"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(prefix + "missing or invalid policy evidence") from exc
    if (
        type(skipped) is not bool
        or type(required) is not bool
        or type(valid_input) is not bool
        or not isinstance(accounting, list)
        or not all(isinstance(item, str) for item in accounting)
        or len(accounting) != len(set(accounting))
        or judge != result.governance.judge_signal
    ):
        raise ValueError(prefix + "invalid or inconsistent judge evidence")
    skip_recorded = "JUDGE_SKIPPED_PREFLIGHT_DENY" in accounting
    failed = "JUDGE_SEMANTIC_FAILURE" in accounting
    held = "GOVERNANCE_HELD" in accounting
    if skipped != skip_recorded or held != (policy.decision != "PERMIT"):
        raise ValueError(prefix + "contradictory policy accounting")
    if skipped:
        if (
            not required
            or failed
            or judge.available
            or judge.provider == "disabled"
            or policy.decision != "DENY"
            or result.decision != "DENY"
            or "SEMANTIC_FAILURE" in policy.reasons
        ):
            raise ValueError(prefix + "contradictory preflight skip")
        return "JUDGE_SKIPPED_PREFLIGHT_DENY"
    if not required:
        if (
            judge.provider != "disabled"
            or judge.available
            or failed
            or "SEMANTIC_FAILURE" in policy.reasons
        ):
            raise ValueError(prefix + "contradictory disabled judge")
        return "JUDGE_DISABLED"
    if not valid_input or policy.decision == "DENY" or judge.provider == "disabled":
        raise ValueError(prefix + "missing preflight skip or contradictory judge configuration")
    if failed:
        if judge.available or "SEMANTIC_FAILURE" not in policy.reasons or not held:
            raise ValueError(prefix + "contradictory semantic failure")
        # Preserve the existing failure label for an actually consulted judge.
        return "SEMANTIC_FAILURE / GOVERNANCE_HELD"
    if not judge.available or "SEMANTIC_FAILURE" in policy.reasons:
        raise ValueError(prefix + "unavailable judge without recorded semantic failure")
    if judge.provider != "mock":
        raise ValueError(prefix + "this synthetic reporter cannot classify a non-mock assessment")
    return "MOCK_SIGNAL_ONLY"


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


async def main(*, projection: str | None = None) -> None:
    fixtures, projection_evidence = load_fixtures(projection=projection)
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
                "semantic_outcome": semantic_outcome(result, trace),
                "judge_classification": result.governance.judge_signal.classification,
                "agent_k_signals": result.governance.agent_k_signal.signals,
                "attempts": completed_event.get("attempts", []),
                "response": result.model_dump(mode="json"),
            }
        )
        if projection_evidence is not None:
            changes = projection_evidence["changes"].get(case["id"], {})
            rows[-1].update(
                original_request=changes.get("request", {}).get("original", case["request"]),
                effective_request=case["request"],
                projection_changes=changes,
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
            sum(r["status"] == "OK" for r in valid),
            len(valid),
            "Synthetic R1 projected fixtures with historical valid category labels"
            if projection_evidence is not None
            else "Synthetic valid fixtures",
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
    output_path = Path("artifacts/evaluation.json")
    if projection_evidence is not None:
        output["projection"] = projection_evidence
        output["mode"] = "SYNTHETIC_R1_PROJECTED_FIXTURE"
        output["limitations"].extend(
            [
                "Fixture matches are not request success or availability",
                "Two transport controls use substituted clear-read requests, not original semantics",
                "Original fixtures, measurements and the previous CI failure remain historical",
            ]
        )
        output_path = Path("artifacts/evaluation.channel-a-legacy-r1.json")
    Path("artifacts").mkdir(exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"{output['fixture_matches']}/{len(rows)} expected fixture outcomes; {output_path}")
    if not all(r["matched"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projection", choices=[R1_PROJECTION_ID], default=None)
    args = parser.parse_args()
    asyncio.run(main(projection=args.projection))
