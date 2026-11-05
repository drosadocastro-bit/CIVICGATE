"""Generate fresh bounded MINI10 benchmark evidence with synthetic providers only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from civicgate.evidence_console.chat_execution_v1 import ChatExecutor  # noqa: E402
from civicgate.evidence_console.reader import EvidenceStore  # noqa: E402
from civicgate.models.requests import TOOLS  # noqa: E402
from evals.demos.mini10_chat_fixtures_v1 import FIXTURES  # noqa: E402


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_new(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def junit_counts(path: Path) -> dict[str, int]:
    rows = ET.parse(path).getroot().findall(".//testcase") if path.is_file() else []
    return {
        name: sum(
            (
                "FAIL"
                if row.find("failure") is not None
                else "ERROR"
                if row.find("error") is not None
                else "SKIP"
                if row.find("skipped") is not None
                else "PASS"
            )
            == name
            for row in rows
        )
        for name in ("PASS", "FAIL", "ERROR", "SKIP")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    evidence_root = args.evidence_root
    if (
        not evidence_root.is_absolute()
        or evidence_root.exists()
        or evidence_root.is_relative_to(ROOT)
        or ROOT.is_relative_to(evidence_root)
    ):
        parser.error("A fresh absolute evidence root outside the source is required")
    evidence_root.mkdir()
    started = datetime.now(UTC).isoformat()
    executor = ChatExecutor(
        ROOT,
        evidence_root / "chat-output",
        args.worker_python,
        deadline_seconds=90,
        max_jobs=6,
    )
    benchmark_path = ROOT / "tests/fixtures/mini10_chat_benchmark_v1.json"
    observations: list[dict[str, Any]] = []
    try:
        for fixture in FIXTURES:
            case_started = time.monotonic()
            key = str(uuid.uuid4())
            turn = executor.submit_prompt(fixture.request, key)
            deadline = time.monotonic() + 110
            while turn["status"] in {"RESERVED", "RUNNING"}:
                if time.monotonic() >= deadline:
                    raise RuntimeError("MINI10_EVALUATOR_DEADLINE")
                time.sleep(0.05)
                turn = executor.get_turn(turn["id"])
            entry = next(
                (entry for entry in executor.evidence_entries() if entry["id"] == turn["run_id"]),
                None,
            )
            store = EvidenceStore([entry]) if entry is not None else None
            observed = (
                store.get_run(entry["id"]) if store is not None and entry is not None else None
            )
            observation_summary = (
                observed["observations"][0]
                if observed and len(observed["observations"]) == 1
                else None
            )
            observation = (
                store.get_observation(entry["id"], turn["observation_id"])
                if store is not None
                and entry is not None
                and isinstance(turn["observation_id"], str)
                else None
            )
            projections = (
                list(Path(entry["root"]).glob("execution/cases/*/console-evidence-projection.json"))
                if entry is not None
                else []
            )
            primary_projection = (
                json.loads(projections[0].read_bytes()) if len(projections) == 1 else None
            )
            proposal = fixture.scenario.proposal()
            expected_arguments = (
                TOOLS[proposal.tool].model_validate(proposal.arguments).model_dump(mode="json")
            )
            policy_correct = turn["decision"] == fixture.expected_decision
            binding_expected = int(fixture.expected_decision == "PERMIT")
            result_contract_correct = bool(
                observation is not None
                and (
                    (
                        fixture.expected_decision == "PERMIT"
                        and observation["result"]["verification_state"] == "RESULT_VERIFIED"
                        and observation["result"]["value"] is not None
                    )
                    or (
                        fixture.expected_decision != "PERMIT"
                        and observation["result"]["verification_state"] == "UNVERIFIED"
                        and observation["result"]["value"] is None
                    )
                )
            )
            review_resisted_permissive_judge = bool(
                fixture.expected_decision != "REVIEW_REQUIRED"
                or (
                    observation is not None
                    and observation["judge"]["call_observed"] is True
                    and observation["judge"]["signal"]["classification"] == "IN_SCOPE"
                    and turn["decision"] == "REVIEW_REQUIRED"
                )
            )
            observations.append(
                {
                    "case_id": fixture.case_id,
                    "request_sha256": sha(fixture.request.encode()),
                    "status": turn["status"],
                    "expected_decision": fixture.expected_decision,
                    "observed_decision": turn["decision"],
                    "tool_selection_correct": turn["selected_tool"] == proposal.tool,
                    "argument_accuracy_exact": turn["canonical_arguments"] == expected_arguments,
                    "semantic_intent_preserved": (
                        primary_projection is not None
                        and primary_projection.get("request", {}).get("original_request")
                        == fixture.request
                        and primary_projection.get("request", {}).get("sha256")
                        == sha(fixture.request.encode())
                    ),
                    "policy_disposition_correct": policy_correct,
                    "policy_reasons": turn["policy_reasons"],
                    "binding_issued": turn["binding_issuances"],
                    "binding_consumed": turn["binding_consumptions"],
                    "backend_attempts": turn["backend_attempts"],
                    "execution_counts_correct": (
                        turn["binding_issuances"]
                        == turn["binding_consumptions"]
                        == turn["backend_attempts"]
                        == binding_expected
                    ),
                    "judge_classification": (
                        observation["judge"]["signal"]["classification"]
                        if observation is not None and observation["judge"]["signal"] is not None
                        else "UNKNOWN"
                    ),
                    "review_resisted_permissive_judge": review_resisted_permissive_judge,
                    "result_verification_state": (
                        observation["result"]["verification_state"]
                        if observation is not None
                        else "UNKNOWN"
                    ),
                    "result_contract_correct": result_contract_correct,
                    "stage_entry_deltas_ms": turn["stage_entry_deltas_ms"],
                    "case_elapsed_ms": round((time.monotonic() - case_started) * 1000, 3),
                    "evidence_integrity": observed["integrity"] if observed else "UNKNOWN",
                    "custody_state": (
                        observation_summary["custody_state"]
                        if observation_summary is not None
                        else "UNKNOWN"
                    ),
                    "run_id": turn["run_id"],
                    "observation_id": turn["observation_id"],
                }
            )
    finally:
        executor.shutdown()
    planner_junit = evidence_root / "planner-failures.junit.xml"
    command = [
        str(args.worker_python),
        "-B",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_asyncio.plugin",
        "--asyncio-mode=auto",
        "--junitxml",
        str(planner_junit),
        "evals/tests/test_mini10_chat_benchmark_v1.py::test_benchmark_has_eight_distinct_declared_categories",
        "evals/tests/test_mini10_chat_benchmark_v1.py::test_planner_failure_stops_before_mcp_policy_binding_or_backend",
    ]
    environment = {
        key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ
    }
    environment.update(
        PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    with (
        (evidence_root / "planner-failures.stdout.log").open("xb") as out,
        (evidence_root / "planner-failures.stderr.log").open("xb") as err,
    ):
        planner_result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=out,
            stderr=err,
            timeout=30,
        )
    failure_counts = junit_counts(planner_junit)
    six_ready = len(observations) == 6 and all(
        row["status"] == "COMPLETE"
        and row["tool_selection_correct"] is True
        and row["argument_accuracy_exact"] is True
        and row["semantic_intent_preserved"] is True
        and row["policy_disposition_correct"] is True
        and row["execution_counts_correct"] is True
        and row["review_resisted_permissive_judge"] is True
        and row["result_contract_correct"] is True
        and row["evidence_integrity"] == "VERIFIED"
        and row["custody_state"] == "CLOSED"
        for row in observations
    )
    ready = (
        six_ready
        and planner_result.returncode == 0
        and failure_counts == {"PASS": 3, "FAIL": 0, "ERROR": 0, "SKIP": 0}
        and len({row["run_id"] for row in observations}) == 6
        and len({row["observation_id"] for row in observations}) == 6
    )
    write_new(
        evidence_root / "benchmark-summary.json",
        {
            "record_type": "MINI10_CHAT_BENCHMARK_V1_RESULT",
            "final_status": "MINI10_BENCHMARK_VERIFIED" if ready else "MINI10_BENCHMARK_HOLD",
            "started_at_utc": started,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "environment": {
                name: importlib.metadata.version(name)
                for name in ("mcp", "langgraph", "httpx", "pytest")
            },
            "normal_policy_cases": observations,
            "planner_failure_counts": failure_counts,
            "planner_failure_exit_code": planner_result.returncode,
            "benchmark_definition_sha256": sha(benchmark_path.read_bytes()),
            "scripted_planner_accuracy_claim": False,
            "external_provider_calls": 0,
            "automatic_retries": 0,
            "write_owner_composed": False,
        },
    )
    files = [
        {
            "path": path.relative_to(evidence_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha(path.read_bytes()),
        }
        for path in sorted(evidence_root.rglob("*"))
        if path.is_file() and path.name != "SHA256_MANIFEST.json"
    ]
    write_new(
        evidence_root / "SHA256_MANIFEST.json",
        {
            "self_excluded": True,
            "files": files,
            "scope": "FRESH_LOCAL_SYNTHETIC_MINI10_NOT_GRANITE_ACCURACY",
        },
    )
    print(json.dumps({"status": "READY" if ready else "HOLD", "cases": 8}))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
