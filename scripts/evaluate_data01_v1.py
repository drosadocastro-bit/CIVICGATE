"""Run new DATA-01 cases with the unchanged guarded A2/R3.2 evaluation path.

Only offline synthetic execution is exposed. All outputs are exclusive-create
and outside the source checkout. No credential/configuration loader is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def sources():
    spec = importlib.util.spec_from_file_location(
        "existing_console_worker", ROOT / "scripts/run_console_synthetic_demo_v2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = {r["path"]: r for r in module.manifest_sources()}
    extra = [p for p in (ROOT / "evals/data01").iterdir() if p.suffix in {".json", ".py"}]
    extra += list((ROOT / "evals/tests").glob("test_data01_*_v1.py"))
    extra += [ROOT / "scripts/evaluate_data01_v1.py"]
    for path in extra:
        name = path.relative_to(ROOT).as_posix()
        rows[name] = {"path": name, "bytes": path.stat().st_size, "sha256": sha(path)}
    return module, sorted(rows.values(), key=lambda row: row["path"])


def summarize(execution):
    cases = json.loads((ROOT / "evals/data01/benchmark_v1.json").read_bytes())["cases"]
    observations = [
        json.loads(p.read_bytes()) for p in sorted((execution / "cases").glob("*/measurement.json"))
    ]
    by_id = {r["case_id"]: r for r in observations}
    expected_ids = {case["case_id"] for case in cases}
    unexpected = sorted(set(by_id) - expected_ids)
    duplicates = sorted(
        {
            r["case_id"]
            for r in observations
            if sum(x["case_id"] == r["case_id"] for x in observations) > 1
        }
    )
    paired = [(case, by_id[case["case_id"]]) for case in cases if case["case_id"] in by_id]

    def metric(values):
        return {
            "correct": sum(values),
            "evaluated": len(values),
            "ratio": sum(values) / len(values) if values else None,
        }

    initial = [r["initial_policy"] == c["expected_initial_policy"] for c, r in paired]
    final = [r["final_policy"] == c["expected_final_policy"] for c, r in paired]
    return {
        "classification": "SCRIPTED_SYNTHETIC_IMPLEMENTATION_EVALUATION_NOT_MODEL_ACCURACY",
        "benchmark_definitions": len(cases),
        "primary_measurements": len(observations),
        "eligible_functional_definitions": sum(c["functional_eligible"] for c in cases),
        "unexpected_measurements": unexpected,
        "duplicate_measurements": duplicates,
        "measurement_inventory_exact": set(by_id) == expected_ids
        and not unexpected
        and not duplicates,
        "missing_measurements": [c["case_id"] for c in cases if c["case_id"] not in by_id],
        "tool_selection": metric(
            [r["tool_correct"] for c, r in paired if c["functional_eligible"]]
        ),
        "arguments": metric(
            [
                r["arguments_correct"]
                for c, r in paired
                if c["functional_eligible"] and r["argument_evaluable"]
            ]
        ),
        "query_result": metric(
            [r["query_result_correct"] for c, r in paired if c["functional_eligible"]]
        ),
        "adversarial_proposal_arguments": metric(
            [
                r["arguments_correct"]
                for c, r in paired
                if not c["functional_eligible"] and r["argument_evaluable"]
            ]
        ),
        "initial_policy": metric(initial),
        "final_policy": metric(final),
        "policy_unsupported_intent_contained": metric(
            [
                not r["adapter_entries"] and r["final_policy"] == "REVIEW_REQUIRED"
                for c, r in paired
                if c["expected_initial_policy"] == "REVIEW_REQUIRED"
            ]
        ),
        "unauthorized_dispatch_prevention": metric(
            [
                not r["adapter_entries"] and not r["binding_consumptions"]
                for c, r in paired
                if not c["expected_dispatch"]
            ]
        ),
        "binding_issuances": sum(r["binding_issuances"] for r in observations),
        "binding_consumptions": sum(r["binding_consumptions"] for r in observations),
        "adapter_entries": sum(r["adapter_entries"] for r in observations),
        "mock_backend_attempts": sum(r["mock_backend_attempts"] for r in observations),
        "mcp_logical_calls": sum(r["mcp_logical_calls"] for r in observations),
        "custody_closed_ack": sum(
            r["custody_state"] == "CLOSED" and r["fence_close_ack"] == "ACKNOWLEDGED"
            for r in observations
        ),
        "primary_projection_verified": sum(r["primary_projection_verified"] for r in observations),
        "initial_distribution": {
            d: sum(r["initial_policy"] == d for r in observations)
            for d in ("PERMIT", "DENY", "REVIEW_REQUIRED")
        },
        "final_distribution": {
            d: sum(r["final_policy"] == d for r in observations)
            for d in ("PERMIT", "DENY", "REVIEW_REQUIRED")
        },
        "functional_queries_not_executed": [
            c["case_id"] for c, r in paired if not c["functional_eligible"]
        ],
        "observations": observations,
        "historical_54_faa_definitions": "BLOCKED_SKIP_UNCHANGED_NOT_EXECUTED",
        "real_granite_or_luna_quality": "NOT_MEASURED",
        "planner_unsupported_intent_recognition": "NOT_MEASURED_SCRIPTED_PROPOSALS_NO_ABSTENTION",
        "planner_uncertainty_handling": "NOT_MEASURED_SCRIPTED_PROPOSALS",
        "human_acceptance": "NOT_GRANTED_BY_THIS_REPORT",
        "durable_stop": "PARTIAL",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-synthetic", action="store_true")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", choices=("all", "fullpath", "unit"), default="all")
    args = parser.parse_args()
    if not args.execute_synthetic:
        parser.error("explicit offline synthetic execution flag required")
    destination = args.evidence_root.resolve()
    if destination.is_relative_to(ROOT) or ROOT.is_relative_to(destination):
        parser.error("source and evidence must be disjoint")
    destination.mkdir(parents=True, exist_ok=False)
    copy, execution = destination / "pinned-copy", destination / "execution"
    execution.mkdir()
    existing, rows = sources()
    for row in rows:
        target = copy / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / row["path"]).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    guard = execution / "guarded_run.py"
    guard.write_bytes((ROOT / "evals/demos/guarded_pytest_v2.py").read_bytes())
    save(execution / "guard-config.json", {"version": 1, "source_root": str(ROOT)})
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(
        PYTHONPATH=str(copy / "src") + os.pathsep + str(copy),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        TEMP=str(execution),
        TMP=str(execution),
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    tests = sorted((copy / "evals/tests").glob("test_data01_*_v1.py"))
    selected = [
        p.relative_to(copy).as_posix()
        for p in tests
        if args.selection == "all" or ("fullpath" in p.name) == (args.selection == "fullpath")
    ]
    if not selected:
        raise ValueError("DATA01_EMPTY_SELECTION")
    command = [
        sys.executable,
        "-B",
        "-s",
        str(guard),
        "-p",
        "pytest_asyncio.plugin",
        "--asyncio-mode=auto",
        *selected,
    ]
    save(
        destination / "command.json",
        {
            "argv": command,
            "cwd": str(copy),
            "environment": env,
            "sources": rows,
            "started_utc": datetime.now(UTC).isoformat(),
            "no_live_configuration": True,
            "guard_sha256": sha(guard),
        },
    )
    with (execution / "stdout.log").open("xb") as out, (execution / "stderr.log").open("xb") as err:
        result = subprocess.run(command, cwd=copy, env=env, stdout=out, stderr=err, timeout=1200)
    counts = dict(PASS=0, FAIL=0, ERROR=0, SKIP=0)
    if (execution / "junit.xml").is_file():
        for case in ET.parse(execution / "junit.xml").getroot().findall(".//testcase"):
            label = next(
                (
                    label
                    for tag, label in (("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP"))
                    if case.find(tag) is not None
                ),
                "PASS",
            )
            counts[label] += 1
    facts = json.loads((execution / "guard-evidence.json").read_bytes())
    guard_verified = existing.verify_guard_identity(
        facts, sha(guard)
    ) and existing.verify_guard_facts(facts, copy, rows)
    unchanged = all(sha(copy / row["path"]) == row["sha256"] for row in rows)
    summary = summarize(execution)
    save(destination / "metrics.json", summary)
    status = {
        "exit_code": result.returncode,
        "counts": counts,
        "source_copy_unchanged": unchanged,
        "guard_verified": guard_verified,
        "measurement_inventory_exact": summary["measurement_inventory_exact"]
        if args.selection != "unit"
        else "NOT_EXECUTED_UNIT_ONLY",
        "finished_utc": datetime.now(UTC).isoformat(),
    }
    save(destination / "result.json", status)
    inventory = [
        {"path": p.relative_to(destination).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
        for p in sorted(destination.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    ]
    save(destination / "SHA256_INVENTORY.json", {"self_excluded": True, "files": inventory})
    print(json.dumps(status))
    complete = args.selection == "unit" or summary["measurement_inventory_exact"]
    return 0 if result.returncode == 0 and unchanged and guard_verified and complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
