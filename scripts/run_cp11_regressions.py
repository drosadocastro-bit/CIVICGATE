"""Run the fixed CP1.1 regressions in a guarded, fresh pinned-copy layout.

No historical test, guard, expectation or authority implementation is rewritten.
The sibling execution/guard-config.json is required by the existing independent
restart helper; omitting it was a separate CP1 invocation defect.
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
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "r32": [
        "evals/tests/test_eval_002b_r3_2_backend_v1.py",
        "evals/tests/test_eval_002b_r3_2_composition_v1.py",
        "evals/tests/test_eval_002b_r3_2_cross_channel_v1.py",
        "evals/tests/test_eval_002b_r3_2_negative_v1.py",
        "evals/tests/test_eval_002b_r3_2_response_v1.py",
        "evals/tests/test_eval_002b_r3_2_terminal_fullpath_v1.py",
    ],
    "a2": [
        "tests/adversarial/test_a1_execution_boundary.py",
        "tests/mcp/test_discovery.py",
        "tests/adversarial/test_a2_orchestration.py",
        "tests/mcp/test_a2_stdio.py",
        "tests/mcp/test_stdio.py",
        "tests/mcp/test_security_compatibility.py",
        "tests/mcp/test_r1_semantic_stdio.py",
        "tests/mcp/test_r1_named_literal_stdio.py",
        "tests/mcp/test_r1_intent_argument_stdio.py",
        "tests/unit/test_mcp_client.py",
    ],
}
EXPECTED = {"r32": 373, "a2": 221}
# These six unchanged main tests extend the historical demo's three-file A2
# selection. Exact reviewed identities, never automatically promoted new pins.
A2_TEST_PINS = {
    "tests/mcp/test_discovery.py": "659f9e9da87c65322e7a6103802286057d762cea80ebe28ccb942ac658f8c369",
    "tests/mcp/test_stdio.py": "b590c8ce6854f483d7a0b7d8108670617b8d6f4ee4f24f0853cafa94fc03774d",
    "tests/mcp/test_security_compatibility.py": "0702490b82cecf4b063069739a1567663f6b4c372de22e8a57ecefccf5040498",
    "tests/mcp/test_r1_semantic_stdio.py": "eea9ec6bb3685447852627f0b448953ca23792d9760eba3a9fe736a43aa1ab9c",
    "tests/mcp/test_r1_named_literal_stdio.py": "736b9dec830598a9164ec82e9d5902c8e9231ef77da5e599c5e2c034589c4bf4",
    "tests/mcp/test_r1_intent_argument_stdio.py": "fad8e5b4435969567cd3af908d5dc7837f018c866caa0ce718a70c358884c6a2",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def save(path: Path, value: object) -> None:
    with path.open("xb") as stream:
        stream.write((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


def console_worker():
    spec = importlib.util.spec_from_file_location(
        "cp11_guarded_console_worker", ROOT / "scripts/run_console_synthetic_demo_v2.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("CP11_CONSOLE_WORKER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def suite_sources(suite: str) -> list[dict]:
    rows = [dict(row) for row in console_worker().manifest_sources()]
    names = {row["path"] for row in rows}
    if suite == "a2":
        for name, expected in A2_TEST_PINS.items():
            data = (ROOT / name).read_bytes()
            if sha(data) != expected:
                raise ValueError("CP11_SUPPLEMENTAL_TEST_IDENTITY_MISMATCH")
            if name not in names:
                rows.append({"path": name, "bytes": len(data), "sha256": expected})
    return sorted(rows, key=lambda row: row["path"])


def _junit(path: Path) -> tuple[dict, list[dict]]:
    records = []
    if path.is_file():
        for case in ET.parse(path).getroot().findall(".//testcase"):
            outcome = (
                "FAIL"
                if case.find("failure") is not None
                else "ERROR"
                if case.find("error") is not None
                else "SKIP"
                if case.find("skipped") is not None
                else "PASS"
            )
            records.append(
                {"module": case.get("classname"), "name": case.get("name"), "outcome": outcome}
            )
    return (
        {
            state: sum(row["outcome"] == state for row in records)
            for state in ("PASS", "FAIL", "ERROR", "SKIP")
        },
        records,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-synthetic", action="store_true", required=True)
    parser.add_argument("--suite", choices=tuple(SUITES), default="r32")
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.evidence_root.is_absolute() or str(args.evidence_root).startswith(("\\\\", "//")):
        parser.error("local absolute evidence root required")
    output = args.evidence_root.resolve()
    if output.is_relative_to(ROOT) or ROOT.is_relative_to(output):
        parser.error("evidence root and source checkout must be disjoint")
    rows = suite_sources(args.suite)
    capture_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    base = output / (args.suite + "-" + capture_id)
    base.mkdir(parents=True, exist_ok=False)
    copy, execution = base / "pinned-copy", base / "execution"
    execution.mkdir()
    for row in rows:
        target = copy / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / row["path"]).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    guard = execution / "guarded_run.py"
    guard_source = console_worker().ACTIVE_GUARD
    guard.write_bytes((ROOT / guard_source).read_bytes())
    guard_sha256 = sha(guard.read_bytes())
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
    command = [sys.executable, "-B", "-s", str(guard)]
    if args.suite == "a2":
        (copy / "checkpoint_test_fixtures.py").write_bytes(
            (copy / "tests/conftest.py").read_bytes()
        )
        command += ["-p", "checkpoint_test_fixtures"]
    command += ["-p", "pytest_asyncio.plugin", "--asyncio-mode=auto", *SUITES[args.suite]]
    save(
        execution / "command.json",
        {
            "argv": command,
            "cwd": str(copy),
            "environment": env,
            "source_files": rows,
            "selection": SUITES[args.suite],
            "expected_cases": EXPECTED[args.suite],
            "guard_source": guard_source,
            "guard_version": 2,
            "guard_sha256": guard_sha256,
            "historical_tests_unchanged": True,
            "restart_layout": "PINNED_COPY_WITH_SIBLING_EXECUTION_GUARD_CONFIG",
            "no_live_configuration": True,
            "no_automatic_retry": True,
        },
    )
    started = datetime.now(UTC).isoformat()
    timed_out = False
    with (
        (execution / "stdout.log").open("xb") as stdout,
        (execution / "stderr.log").open("xb") as stderr,
    ):
        process = subprocess.Popen(
            command,
            cwd=copy,
            env=env,
            stdout=stdout,
            stderr=stderr,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        try:
            exit_code = process.wait(timeout=1200)
        except subprocess.TimeoutExpired:
            timed_out = True
            console_worker().terminate_owned_process_tree(process)
            exit_code = 124
    counts, cases = _junit(execution / "junit.xml")
    unchanged = all(sha((copy / row["path"]).read_bytes()) == row["sha256"] for row in rows)
    loaded_verified = False
    guard_identity_verified = False
    guard_facts = None
    if (execution / "guard-evidence.json").is_file():
        guard_facts = json.loads((execution / "guard-evidence.json").read_bytes())
        guard_identity_verified = console_worker().verify_guard_identity(guard_facts, guard_sha256)
        expected = {row["path"]: row["sha256"] for row in rows}
        loaded_verified = bool(guard_facts.get("loaded_project_modules")) and all(
            Path(row["path"]).is_relative_to(copy)
            and expected.get(Path(row["path"]).relative_to(copy).as_posix()) == row["sha256"]
            for row in guard_facts.get("loaded_project_modules", {}).values()
        )
    ready = (
        exit_code == 0
        and counts == {"PASS": EXPECTED[args.suite], "FAIL": 0, "ERROR": 0, "SKIP": 0}
        and unchanged
        and loaded_verified
        and guard_identity_verified
    )
    result = {
        "suite": args.suite,
        "status": "REGRESSION_PASS" if ready else "REGRESSION_HOLD",
        "capture_id": capture_id,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "counts": counts,
        "cases": cases,
        "source_copy_unchanged": unchanged,
        "guard_loaded_sources_verified": loaded_verified,
        "guard_source": guard_source,
        "guard_version": 2,
        "guard_sha256": guard_sha256,
        "guard_identity_verified": guard_identity_verified,
        "blocked_network_attempts": sum(
            row.get("allowed") is False for row in guard_facts.get("network_events", [])
        )
        if guard_facts
        else None,
        "no_automatic_retry": True,
        "real_provider_requests": 0,
        "limitations": "Cooperative Python guard and synthetic fixtures, not OS isolation or production certification.",
    }
    save(base / "run-result.json", result)
    save(
        base / "RUN_SHA256_MANIFEST.json",
        {
            "self_excluded": True,
            "status": result["status"],
            "files": [
                {
                    "path": p.relative_to(base).as_posix(),
                    "bytes": p.stat().st_size,
                    "sha256": sha(p.read_bytes()),
                }
                for p in sorted(base.rglob("*"))
                if p.is_file()
            ],
        },
    )
    print(
        json.dumps(
            {
                "run_path": str(base),
                "status": result["status"],
                "counts": counts,
                "source_copy_unchanged": unchanged,
                "guard_loaded_sources_verified": loaded_verified,
            }
        ),
        flush=True,
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
