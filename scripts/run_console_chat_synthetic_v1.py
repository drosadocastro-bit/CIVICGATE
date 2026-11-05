"""Run one host-owned MINI10 chat turn through guarded synthetic A2/MCP."""

from __future__ import annotations

import argparse
import hashlib
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_GUARD = ROOT / "evals/demos/guarded_pytest_v2.py"
SELECTION = "evals/demos/test_mini10_chat_v1.py::test_governed_chat_prompt"
SOURCE_PATH_INVENTORY = "evals/manifests/mini08_cp11_console_sources_v1.json"
MINI10_SOURCES = (
    "src/civicgate/evidence_console/chat_execution_v1.py",
    "src/civicgate/evidence_console/chat_planner_v1.py",
    "evals/demos/mini10_chat_fixtures_v1.py",
    "evals/demos/test_mini10_chat_v1.py",
    "scripts/run_console_chat_synthetic_v1.py",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _save(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _candidate_sources() -> list[dict[str, Any]]:
    """Measure current candidate bytes for a bounded reviewed path set."""

    inventory = json.loads((ROOT / SOURCE_PATH_INVENTORY).read_bytes())
    rows = inventory.get("source_files")
    if (
        type(inventory) is not dict
        or inventory.get("version") != 1
        or not isinstance(rows, list)
        or len(rows) != 113
    ):
        raise ValueError("MINI10_SOURCE_PATH_INVENTORY_INVALID")
    names = [row.get("path") for row in rows]
    names.extend(MINI10_SOURCES)
    if not all(isinstance(name, str) for name in names) or len(names) != len(set(names)):
        raise ValueError("MINI10_SOURCE_PATH_INVENTORY_INVALID")
    result: list[dict[str, Any]] = []
    for name in sorted(names):
        relative = Path(name)
        source = ROOT / relative
        if relative.is_absolute() or ".." in relative.parts or not source.is_file():
            raise ValueError("MINI10_SOURCE_PATH_INVENTORY_INVALID")
        raw = source.read_bytes()
        result.append({"path": name, "bytes": len(raw), "sha256": _sha(raw)})
    return result


def _terminate(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is not None:
        return False
    try:
        if os.name == "nt":
            executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
            result = subprocess.run(
                [str(executable), "/PID", str(process.pid), "/T", "/F"],
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


def _strict_request(path: Path) -> dict[str, str]:
    raw = path.read_bytes()

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("MINI10_DUPLICATE_REQUEST_FIELD")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=unique)
    if type(value) is not dict or set(value) != {
        "host_owner",
        "planner_identity",
        "prompt",
        "prompt_sha256",
    }:
        raise ValueError("MINI10_REQUEST_FIELDS")
    if (
        value["host_owner"] != "CHANNEL_A_LOCAL_READ_V1"
        or value["planner_identity"] != "SCRIPTED_SYNTHETIC_FIXTURE_NOT_GRANITE"
        or type(value["prompt"]) is not str
        or _sha(value["prompt"].encode()) != value["prompt_sha256"]
    ):
        raise ValueError("MINI10_REQUEST_IDENTITY")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-file", type=Path, required=True)
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
    deadline = min(time.monotonic() + args.deadline_seconds, args.absolute_deadline) - 2
    job = args.job_root.resolve(strict=True)
    request_file = args.request_file.resolve(strict=True)
    if request_file.parent != job or job.is_relative_to(ROOT) or ROOT.is_relative_to(job):
        parser.error("request custody and source boundaries invalid")
    request = _strict_request(request_file)
    sources = _candidate_sources()
    capture = job / ("capture-" + job.name.removeprefix("chat-"))
    capture.mkdir(exist_ok=False)
    copy = capture / "pinned-copy"
    execution = capture / "execution"
    cases = execution / "cases"
    copy.mkdir()
    execution.mkdir()
    cases.mkdir()
    for row in sources:
        target = copy / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / row["path"]).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    guard = execution / "guarded_run.py"
    guard.write_bytes(ACTIVE_GUARD.read_bytes())
    guard_sha256 = _sha(guard.read_bytes())
    _save(execution / "guard-config.json", {"version": 1, "source_root": str(ROOT)})
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
        CIVICGATE_MINI10_REQUEST_PATH=str(request_file),
        CIVICGATE_MINI10_CASE_ROOT=str(cases),
    )
    command = [
        sys.executable,
        "-B",
        "-s",
        str(guard),
        "-p",
        "pytest_asyncio.plugin",
        "-p",
        "no:cacheprovider",
        "--asyncio-mode=auto",
        "--junitxml",
        str(execution / "junit.xml"),
        SELECTION,
    ]
    _save(
        execution / "command.json",
        {
            "argv": command,
            "cwd": str(copy),
            "environment_keys": sorted(env),
            "selection": [SELECTION],
            "source_files": sources,
            "guard_source": ACTIVE_GUARD.relative_to(ROOT).as_posix(),
            "guard_version": 2,
            "guard_sha256": guard_sha256,
            "host_owner": request["host_owner"],
            "planner_identity": request["planner_identity"],
            "no_live_configuration": True,
            "no_automatic_retry": True,
        },
    )
    started = datetime.now(UTC).isoformat()
    process: subprocess.Popen[bytes] | None = None
    timed_out = False
    cleanup: bool | None = None
    with (execution / "stdout.log").open("xb") as out, (execution / "stderr.log").open("xb") as err:
        if time.monotonic() >= deadline:
            code = 124
            timed_out = True
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
                cleanup = _terminate(process)
                code = 124
    junit_cases = []
    junit = execution / "junit.xml"
    if junit.is_file():
        for item in ET.parse(junit).getroot().findall(".//testcase"):
            outcome = (
                "FAIL"
                if item.find("failure") is not None
                else "ERROR"
                if item.find("error") is not None
                else "SKIP"
                if item.find("skipped") is not None
                else "PASS"
            )
            junit_cases.append({"name": item.attrib.get("name", "UNKNOWN"), "outcome": outcome})
    counts = {
        name: sum(item["outcome"] == name for item in junit_cases)
        for name in ("PASS", "FAIL", "ERROR", "SKIP")
    }
    source_unchanged = all(
        (ROOT / row["path"]).stat().st_size == row["bytes"]
        and _sha((ROOT / row["path"]).read_bytes()) == row["sha256"]
        and (copy / row["path"]).stat().st_size == row["bytes"]
        and _sha((copy / row["path"]).read_bytes()) == row["sha256"]
        for row in sources
    )
    projections = list(cases.glob("*/console-evidence-projection.json"))
    projection: dict[str, Any] | None = None
    projection_verified = False
    if len(projections) == 1:
        projection = json.loads(projections[0].read_bytes())
        projection_verified = (
            projection.get("request", {}).get("original_request") == request["prompt"]
            and projection.get("request", {}).get("sha256") == request["prompt_sha256"]
            and projection.get("source_identities", {}).get("planner_identity")
            == "SYNTHETIC_PROVIDER_FIXTURE_NOT_REAL_GRANITE"
            and projection.get("policy", {}).get("final_disposition")
            in {"PERMIT", "DENY", "REVIEW_REQUIRED"}
        )
    guard_verified = False
    guard_evidence = execution / "guard-evidence.json"
    if guard_evidence.is_file():
        spec = importlib.util.spec_from_file_location(
            "mini10_guard_verifier", ROOT / "scripts/run_console_synthetic_demo_v2.py"
        )
        if spec is not None and spec.loader is not None:
            verifier = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(verifier)
            facts = json.loads(guard_evidence.read_bytes())
            guard_verified = verifier.verify_guard_identity(
                facts, guard_sha256
            ) and verifier.verify_guard_facts(facts, copy, sources)
    ready = (
        code == 0
        and not timed_out
        and time.monotonic() <= deadline
        and counts == {"PASS": 1, "FAIL": 0, "ERROR": 0, "SKIP": 0}
        and source_unchanged
        and projection_verified
        and guard_verified
    )
    _save(
        capture / "run-result.json",
        {
            "record_type": "MINI10_FRESH_GOVERNED_CHAT_SYNTHETIC_RUN",
            "final_status": "MINI10_CHAT_TURN_VERIFIED" if ready else "MINI10_CHAT_TURN_HOLD",
            "capture_id": capture.name,
            "started_at_utc": started,
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "exit_code": code,
            "timed_out": timed_out,
            "owned_subtree_cleanup_confirmed": cleanup,
            "counts": counts,
            "cases": junit_cases,
            "prompt_sha256": request["prompt_sha256"],
            "source_unchanged": source_unchanged,
            "projection_verified": projection_verified,
            "guard_primary_evidence_verified": guard_verified,
            "automatic_retry": False,
            "host_owner": request["host_owner"],
            "planner_identity": request["planner_identity"],
            "write_execution": "DISABLED_NOT_COMPOSED",
            "external_provider_execution": "NOT_AUTHORIZED",
            "granite_effective_identity": "UNKNOWN_NOT_INVOKED",
        },
    )
    files = [
        {
            "path": path.relative_to(capture).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(capture.rglob("*"))
        if path.is_file() and path.name != "RUN_SHA256_MANIFEST.json"
    ]
    _save(
        capture / "RUN_SHA256_MANIFEST.json",
        {
            "self_excluded": True,
            "files": files,
            "provenance": "LOCALLY_GENERATED_SYNTHETIC_CHAT_NOT_MODEL_ACCURACY",
        },
    )
    print(json.dumps({"status": "READY" if ready else "HOLD"}), flush=True)
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
