"""Descriptive engineering metrics, never synthetic semantic accuracy."""

import math
import statistics
from collections import defaultdict
from typing import Any

from evals.harness.evidence import canonical, sha256
from evals.harness.models import EvaluationReport, MetricsRecord, Observation


def latency(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "n": len(values),
        "p50_ms": statistics.median(values) if values else None,
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1] if ordered else None,
        "method": "p50_median_p95_nearest_rank",
        "interpretation": "DESCRIPTIVE_SYNTHETIC_SAMPLE_NOT_MODEL_PERFORMANCE",
    }


def report(run_id: str, rows: list[Observation]) -> EvaluationReport:
    groups: dict[str, list[Observation]] = defaultdict(list)
    repeated: dict[str, list[Observation]] = defaultdict(list)
    for row in rows:
        groups[row.split + "/" + row.family + "/" + row.configuration_id].append(row)
        repeated[row.case_id].append(row)
    by_family = {
        name: {
            stage: latency([v for r in items if (v := r.latency_ms.get(stage)) is not None])
            for stage in {s for r in items for s in r.latency_ms}
        }
        for name, items in groups.items()
    }
    repeat_consistency: dict[str, Any] = {}
    for case_id, items in repeated.items():
        projections = [
            {
                k: r.model_dump()[k]
                for k in (
                    "planner_tool",
                    "planner_arguments_sha256",
                    "orchestration_status",
                    "initial_decision",
                    "final_decision",
                    "binding_issued",
                    "pre_dispatch_verification",
                    "adapter_dispatches",
                    "fixture_http_attempts",
                    "judge_classification",
                    "judge_flags",
                    "judge_confidence",
                    "verification_state",
                    "transport_status",
                    "error_category",
                )
            }
            for r in items
        ]
        distinct = len({sha256(canonical(p)) for p in projections})
        repeat_consistency[case_id] = {
            "n": len(items),
            "distinct_observed_signatures": distinct,
            "consistent": distinct == 1 if len(items) > 1 else None,
        }
    checks = [v for r in rows for v in r.engineering_checks.values()]
    return EvaluationReport(
        run_id=run_id,
        result="PASS" if checks and all(checks) else "FAIL",
        observations=rows,
        metrics=MetricsRecord.model_validate(
            {
                "observation_count": len(rows),
                "engineering_assertions": {
                    "checked": len(checks),
                    "passed": sum(checks),
                    "failed": checks.count(False),
                },
                "latency_by_split_family": by_family,
                "repeat_consistency": repeat_consistency,
                "policy_initial": {
                    s: sum(r.initial_decision == s for r in rows)
                    for s in ("PERMIT", "DENY", "REVIEW_REQUIRED")
                }
                | {"NOT_OBSERVED": sum(r.initial_decision is None for r in rows)},
                "policy_final": {
                    s: sum(r.final_decision == s for r in rows)
                    for s in ("PERMIT", "DENY", "REVIEW_REQUIRED")
                }
                | {"NOT_OBSERVED": sum(r.final_decision is None for r in rows)},
                "real_provider_attempts": 0,
                "tokens": {"value": None, "status": "NOT_APPLICABLE_SYNTHETIC"},
                "cost": {"value": None, "status": "NOT_APPLICABLE_SYNTHETIC"},
                "semantic_accuracy": {
                    "value": None,
                    "status": "NOT_SCORED_SYNTHETIC_OR_UNREVIEWED_REFERENCES",
                },
            }
        ),
        limitations=[
            "Synthetic planner/judge are not Granite/Luna accuracy or performance measurements.",
            "New author references await independent human review; holdout is reserved, author-known and unexecuted.",
            "Policy and execution-gate latency are not instrumented in protected core; null is not zero.",
            "Fresh process per case prevents implicit containment carryover; same-process sequences are separate future coverage.",
            "MCP failure alone does not establish zero dispatch; independent ledger counts may be unknown.",
            "Output injection fixture does not test a live planner's subsequent-turn response.",
            "Bindings are never accepted from the planner; existing private-binding attack tests remain separate evidence.",
        ],
    )
