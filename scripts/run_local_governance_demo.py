"""Run fixed offline synthetic selections against a verified, isolated source copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BUDGET_TEST = "evals/tests/test_eval_002b_admission_v1.py"
BUDGET_NODES = [
    "test_reservation_and_liability_and_lease_commit_together",
    "test_sql_failure_rolls_back_all_three_reservation_parts",
    "test_send_requires_started_and_first_headers_lease_is_one_use",
    "test_unknown_no_refund_and_no_automatic_retry",
    "test_failed_stop_after_open_still_fences_restart",
    "test_shared_exact_six_observations_and_twelve_attempts_per_role",
    "test_failed_response_facts_write_leaves_started_consumed_custody_unknown",
    "test_accepted_absolute_ceilings_cannot_be_raised",
]
SUITES = {
    "mini072": ["evals/demos/test_mini072_demo_v1.py"],
    "mini071": ["evals/demos/test_mini071_demo_v1.py"],
    "a2": [
        "tests/adversarial/test_a2_orchestration.py",
        "tests/mcp/test_a2_stdio.py",
        "tests/unit/test_mcp_client.py",
    ],
    "r32": [
        "evals/tests/test_eval_002b_r3_2_backend_v1.py",
        "evals/tests/test_eval_002b_r3_2_response_v1.py",
        "evals/tests/test_eval_002b_r3_2_negative_v1.py",
        "evals/tests/test_eval_002b_r3_2_composition_v1.py",
    ],
    "r32-ab": ["evals/tests/test_eval_002b_r3_2_cross_channel_v1.py"],
    "r32-terminal": ["evals/tests/test_eval_002b_r3_2_terminal_fullpath_v1.py"],
    "budget": [BUDGET_TEST + "::" + name for name in BUDGET_NODES],
    "portability": ["evals/demos/test_checkpoint_portability_v1.py"],
}
EXPECTED = {
    "mini072": 3,
    "mini071": 3,
    "a2": 89,
    "r32": 314,
    "r32-ab": 11,
    "r32-terminal": 48,
    "budget": 10,
    "portability": 11,
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def manifest_sources():
    manifest_path = ROOT / "evals/manifests/gsa_local_demo_checkpoint_v1.json"
    manifest = json.loads(manifest_path.read_bytes())
    seen = set()
    for row in manifest["source_files"]:
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or row["path"] in seen:
            raise ValueError("INVALID_SOURCE_INVENTORY")
        seen.add(row["path"])
        raw = (ROOT / relative).read_bytes()
        if len(raw) != row["bytes"] or sha(raw) != row["sha256"]:
            raise ValueError("CHECKPOINT_SOURCE_IDENTITY_MISMATCH")
    return manifest["source_files"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-synthetic", action="store_true", required=True)
    parser.add_argument("--suite", choices=SUITES, default="mini072")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(tempfile.gettempdir()) / "civicgate-offline-checkpoint",
    )
    args = parser.parse_args()
    sources = manifest_sources()
    output_root = args.evidence_root.resolve()
    if output_root.is_relative_to(ROOT) or ROOT.is_relative_to(output_root):
        raise ValueError("EVIDENCE_ROOT_MUST_BE_DISJOINT_FROM_REPOSITORY")
    capture_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    base = output_root / (args.suite + "-" + capture_id)
    base.mkdir(parents=True, exist_ok=False)
    copy = base / "pinned-copy"
    execution = base / "execution"
    execution.mkdir()
    for row in sources:
        target = copy / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / row["path"]).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    guard = execution / "guarded_run.py"
    guard.write_bytes((ROOT / "evals/demos/guarded_pytest_v1.py").read_bytes())
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
    cmd = [sys.executable, "-B", "-s", str(guard)]
    if args.suite == "a2":
        (copy / "checkpoint_test_fixtures.py").write_bytes(
            (copy / "tests/conftest.py").read_bytes()
        )
        cmd += ["-p", "checkpoint_test_fixtures"]
    cmd += ["-p", "pytest_asyncio.plugin", "--asyncio-mode=auto", *SUITES[args.suite]]
    save(
        execution / "command.json",
        {
            "argv": cmd,
            "cwd": str(copy),
            "environment": env,
            "selection": SUITES[args.suite],
            "guard_sha256": sha(guard.read_bytes()),
            "source_files": sources,
            "no_live_configuration": True,
            "no_automatic_retry": True,
        },
    )
    started = datetime.now(UTC).isoformat()
    timed_out = False
    with (execution / "stdout.log").open("xb") as out, (execution / "stderr.log").open("xb") as err:
        try:
            process_result = subprocess.run(
                cmd, cwd=copy, env=env, stdout=out, stderr=err, timeout=900
            )
            exit_code = process_result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
    cases = []
    if (execution / "junit.xml").exists():
        for case in ET.parse(execution / "junit.xml").getroot().findall(".//testcase"):
            state = (
                "FAIL"
                if case.find("failure") is not None
                else "ERROR"
                if case.find("error") is not None
                else "SKIP"
                if case.find("skipped") is not None
                else "PASS"
            )
            cases.append(
                {
                    "classname": case.attrib.get("classname"),
                    "name": case.attrib["name"],
                    "outcome": state,
                }
            )
    counts = {
        key: sum(case["outcome"] == key for case in cases)
        for key in ("PASS", "FAIL", "ERROR", "SKIP")
    }
    cards = []
    for name in ("permit", "deny", "review"):
        path = execution / "cases" / name / "verified-demo-card.json"
        if path.exists():
            cards.append(json.loads(path.read_bytes()))
    preserved = all(sha((copy / row["path"]).read_bytes()) == row["sha256"] for row in sources)
    ready = (
        exit_code == 0
        and counts == {"PASS": EXPECTED[args.suite], "FAIL": 0, "ERROR": 0, "SKIP": 0}
        and preserved
    )
    if args.suite in {"mini072", "mini071"}:
        ready = ready and len(cards) == 3
    status = (
        "A2_INTEGRATED_DEMO_READY"
        if ready and args.suite == "mini072"
        else "DEMO_READY_OFFLINE_SYNTHETIC"
        if ready and args.suite == "mini071"
        else "REGRESSION_PASS"
        if ready
        else "CHECKPOINT_HOLD"
    )
    result = {
        "selection": args.suite,
        "final_status": status,
        "run_path": str(base),
        "capture_id": capture_id,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "counts": counts,
        "cases": cases,
        "cards": cards,
        "source_copy_unchanged": preserved,
        "automatic_retry": False,
        "full_faa_contract_executed": False,
        "preserved_failure_requires_review": not ready,
    }
    save(base / "run-result.json", result)
    files = [
        {
            "path": path.relative_to(base).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha(path.read_bytes()),
        }
        for path in sorted(base.rglob("*"))
        if path.is_file()
    ]
    save(
        base / "RUN_SHA256_MANIFEST.json",
        {"self_excluded": True, "final_status": status, "files": files},
    )
    print(
        json.dumps(
            {
                "run_path": str(base),
                "final_status": status,
                "counts": counts,
                "source_copy_unchanged": preserved,
            }
        ),
        flush=True,
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
