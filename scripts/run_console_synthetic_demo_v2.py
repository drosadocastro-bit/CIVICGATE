"""CP1.1 synthetic execution using versioned observer compatibility sources."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import math
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ("permit", "deny", "review")
ACTIVE_GUARD = "evals/demos/guarded_pytest_v2.py"


def manifest_sources():
    """CP1.1 pins the V3 observer bridge; both historical inventories stay intact."""
    import hashlib

    raw = (ROOT / "evals/manifests/mini08_cp11_console_sources_v1.json").read_bytes()
    inventory = json.loads(raw)
    if (
        type(inventory.get("version")) is not int
        or inventory.get("version") != 1
        or inventory.get("baseline") != "601e65ed77630bbad43eec2bcdce17c25ca65349"
    ):
        raise ValueError("CP11_SOURCE_INVENTORY_INVALID")
    historical = ROOT / "evals/manifests/gsa_local_demo_checkpoint_v1.json"
    if hashlib.sha256(historical.read_bytes()).hexdigest() != inventory.get(
        "historical_manifest_sha256"
    ):
        raise ValueError("HISTORICAL_SOURCE_INVENTORY_CHANGED")
    cp1 = ROOT / "evals/manifests/mini08_cp1_console_sources_v1.json"
    if hashlib.sha256(cp1.read_bytes()).hexdigest() != inventory.get("cp1_manifest_sha256"):
        raise ValueError("CP1_SOURCE_INVENTORY_CHANGED")
    rows = inventory.get("source_files")
    if not isinstance(rows, list) or len(rows) != 113:
        raise ValueError("CP11_SOURCE_INVENTORY_INVALID")
    historical_names = {row["path"] for row in json.loads(historical.read_bytes())["source_files"]}
    if {row["path"] for row in rows} != historical_names | {
        "src/civicgate/channel_b/invocation_contract_v1.py",
        "evals/harness/governance_observer_v3.py",
        "evals/harness/governance_observer_v2_reference.py",
    }:
        raise ValueError("CP11_SOURCE_INVENTORY_INVALID")
    seen = set()
    for row in rows:
        name = row["path"]
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in seen:
            raise ValueError("CP11_SOURCE_INVENTORY_INVALID")
        seen.add(name)
        data = (ROOT / relative).read_bytes()
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("CP11_SOURCE_IDENTITY_MISMATCH")
    return rows


def verify_guard_identity(facts, expected_sha256: str) -> bool:
    """Measured guard identity; not external authority or a historical pin."""
    return (
        isinstance(facts, dict)
        and type(facts.get("guard_version")) is int
        and facts["guard_version"] == 2
        and type(facts.get("guard_sha256")) is str
        and facts["guard_sha256"] == expected_sha256
    )


def verify_guard_facts(facts, copy: Path, sources) -> bool:
    """Known guard decisions only; unexpected denied external attempts hold."""
    if not isinstance(facts, dict):
        return False
    expected = {row["path"]: row["sha256"] for row in sources}
    loaded = facts.get("loaded_project_modules")
    network = facts.get("network_events")
    if not isinstance(loaded, dict) or not loaded or not isinstance(network, list):
        return False
    for event in network:
        if not isinstance(event, dict) or type(event.get("allowed")) is not bool:
            return False
        if event["allowed"] is False:
            # The unchanged Windows guard denies an IPv6 self-pipe bind probe
            # before asyncio falls back to its separately permitted socketpair.
            try:
                address = ast.literal_eval(event.get("address", ""))
            except (ValueError, SyntaxError):
                return False
            if not (
                event.get("event") == "socket.bind"
                and event.get("kind") == "denied"
                and address in (("::1", 0), ("127.0.0.1", 0))
            ):
                return False
        elif event.get("event") == "socketpair.call":
            if (
                type(facts.get("guard_version")) is not int
                or facts["guard_version"] != 2
                or event.get("api") not in {"public", "native"}
                or event.get("kind") != "asyncio_socketpair"
            ):
                return False
        elif event.get("event") == "socketpair.result":
            if (
                type(facts.get("guard_version")) is not int
                or facts["guard_version"] != 2
                or event.get("kind") != "asyncio_socketpair"
                or event.get("peer_verified") is not True
                or type(event.get("family")) is not int
                or event["family"] not in {1, 2}
            ):
                return False
        elif event.get("event") in {"socket.bind", "socket.connect", "socket.connect_ex"}:
            if event.get("kind") not in {"owned_synthetic_fixture", "asyncio_socketpair"}:
                return False
            try:
                address = ast.literal_eval(event.get("address", ""))
            except (ValueError, SyntaxError):
                return False
            if not (
                isinstance(address, tuple)
                and len(address) == 2
                and address[0] == "127.0.0.1"
                and type(address[1]) is int
                and 0 <= address[1] <= 65535
            ):
                return False
        elif event.get("event") == "socket.getaddrinfo":
            if (
                event.get("host") != "127.0.0.1"
                or not isinstance(event.get("port"), str)
                or not event["port"].isdecimal()
                or not 1 <= int(event["port"]) <= 65535
            ):
                return False
        else:
            return False
    for observed in loaded.values():
        if not isinstance(observed, dict) or not isinstance(observed.get("path"), str):
            return False
        path = Path(observed["path"])
        if not path.is_absolute() or not path.is_relative_to(copy):
            return False
        if expected.get(path.relative_to(copy).as_posix()) != observed.get("sha256"):
            return False
    return True


def terminate_owned_process_tree(process: subprocess.Popen) -> bool:
    """Best-effort termination of this Popen subtree; no OS isolation claim."""
    if process.poll() is not None:
        return False  # A finished parent is not proof that every descendant exited.
    try:
        if os.name == "nt":
            command = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
            result = subprocess.run(
                [str(command), "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
            process.wait(timeout=10)
            return result.returncode == 0 and process.poll() is not None
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        return process.poll() is not None
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--job-root", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=float, required=True)
    parser.add_argument("--absolute-deadline", type=float, required=True)
    args = parser.parse_args()
    if (
        not 0 < args.deadline_seconds <= 120
        or not math.isfinite(args.absolute_deadline)
        or args.absolute_deadline <= 0
    ):
        parser.error("deadline outside fixed synthetic bounds")
    # Both interpreters use the same local host monotonic clock. The inherited
    # absolute deadline prevents setup/custody delay from resetting the budget.
    deadline = min(time.monotonic() + args.deadline_seconds, args.absolute_deadline) - 2
    job = args.job_root.resolve(strict=True)
    if job.is_relative_to(ROOT) or ROOT.is_relative_to(job):
        parser.error("job and source must be disjoint")
    spec = importlib.util.spec_from_file_location(
        "checkpoint_synthetic_runner", ROOT / "scripts/run_local_governance_demo.py"
    )
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sources = manifest_sources()
    capture = job / ("capture-" + job.name.removeprefix("exec-"))
    capture.mkdir(exist_ok=False)
    copy = capture / "pinned-copy"
    execution = capture / "execution"
    execution.mkdir()
    for row in sources:
        target = copy / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / row["path"]).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    guard = execution / "guarded_run.py"
    guard.write_bytes((ROOT / ACTIVE_GUARD).read_bytes())
    guard_sha256 = runner.sha(guard.read_bytes())
    runner.save(execution / "guard-config.json", {"version": 1, "source_root": str(ROOT)})
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
    selection = f"evals/demos/test_mini072_demo_v1.py::test_local_synthetic_demo[{args.scenario}]"
    command = [
        sys.executable,
        "-B",
        "-s",
        str(guard),
        "-p",
        "pytest_asyncio.plugin",
        "--asyncio-mode=auto",
        selection,
    ]
    runner.save(
        execution / "command.json",
        {
            "argv": command,
            "cwd": str(copy),
            "environment": env,
            "selection": [selection],
            "source_files": sources,
            "guard_source": ACTIVE_GUARD,
            "guard_version": 2,
            "guard_sha256": guard_sha256,
            "no_live_configuration": True,
            "no_automatic_retry": True,
            "scenario": args.scenario,
        },
    )
    started = datetime.now(UTC).isoformat()
    timed_out = False
    cleanup = None
    with (execution / "stdout.log").open("xb") as out, (execution / "stderr.log").open("xb") as err:
        if time.monotonic() >= deadline:
            timed_out = True
            code = 124
        else:
            process = subprocess.Popen(
                command,
                cwd=copy,
                env=env,
                stdout=out,
                stderr=err,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            try:
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup = terminate_owned_process_tree(process)
                code = 124
    cases = []
    junit = execution / "junit.xml"
    if junit.is_file():
        for case in ET.parse(junit).getroot().findall(".//testcase"):
            outcome = (
                "FAIL"
                if case.find("failure") is not None
                else "ERROR"
                if case.find("error") is not None
                else "SKIP"
                if case.find("skipped") is not None
                else "PASS"
            )
            cases.append({"name": case.attrib["name"], "outcome": outcome})
    counts = {
        key: sum(row["outcome"] == key for row in cases)
        for key in ("PASS", "FAIL", "ERROR", "SKIP")
    }
    preserved = all(
        runner.sha((copy / row["path"]).read_bytes()) == row["sha256"] for row in sources
    )
    guard_evidence = execution / "guard-evidence.json"
    guard_verified = False
    if guard_evidence.is_file():
        facts = json.loads(guard_evidence.read_bytes())
        guard_verified = verify_guard_identity(facts, guard_sha256) and verify_guard_facts(
            facts, copy, sources
        )
    card = execution / "cases" / args.scenario / "verified-demo-card.json"
    ready = (
        code == 0
        and not timed_out
        and time.monotonic() <= deadline
        and counts == {"PASS": 1, "FAIL": 0, "ERROR": 0, "SKIP": 0}
        and card.is_file()
        and preserved
        and guard_verified
    )
    runner.save(
        capture / "run-result.json",
        {
            "record_type": "FRESH_INTERACTIVE_SYNTHETIC_E2E_RUN",
            "scenario": args.scenario,
            "final_status": "A2_INTEGRATED_DEMO_READY" if ready else "INTEGRATION_HOLD",
            "capture_id": capture.name,
            "started_at_utc": started,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "exit_code": code,
            "timed_out": timed_out,
            "owned_subtree_cleanup_confirmed": cleanup,
            "counts": counts,
            "cases": cases,
            "source_copy_unchanged": preserved,
            "guard_primary_evidence_verified": guard_verified,
            "guard_source": ACTIVE_GUARD,
            "guard_version": 2,
            "guard_sha256": guard_sha256,
            "automatic_retry": False,
            "human_acceptance": "NOT_GRANTED",
            "external_provider_execution": "NOT_AUTHORIZED",
            "full_faa_contract_executed": False,
        },
    )
    files = [
        {
            "path": path.relative_to(capture).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": runner.sha(path.read_bytes()),
        }
        for path in sorted(capture.rglob("*"))
        if path.is_file()
    ]
    runner.save(
        capture / "RUN_SHA256_MANIFEST.json",
        {
            "self_excluded": True,
            "files": files,
            "provenance": "LOCALLY_GENERATED_SYNTHETIC_CAPTURE_NOT_EXTERNAL_ENDORSEMENT",
        },
    )
    print(
        json.dumps({"status": "READY" if ready else "HOLD", "scenario": args.scenario}), flush=True
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
