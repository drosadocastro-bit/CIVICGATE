"""Controller boundary tests; no model, MCP or Gateway invocation in unit controls."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from civicgate.evidence_console import demo_execution_v1 as module
from civicgate.evidence_console.demo_execution_v1 import DemoError, DemoExecutor

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def make_executor(tmp_path, monkeypatch):
    monkeypatch.setattr(DemoExecutor, "_verify_worker_environment", lambda self: None)

    def make(**options):
        return DemoExecutor(
            ROOT, tmp_path / ("output-" + uuid.uuid4().hex), Path(sys.executable), **options
        )

    return make


def key():
    return str(uuid.uuid4())


def no_dispatch(executor, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocked(job_id):
        entered.set()
        release.wait(10)

    monkeypatch.setattr(executor, "_run_job", blocked)
    return entered, release


@pytest.mark.parametrize("scenario", ["url", "live", "", None, {"scenario": "permit"}, "PERMIT"])
def test_scenario_allowlist_has_no_provider_fallback(make_executor, scenario):
    executor = make_executor()
    with pytest.raises(DemoError) as caught:
        executor.submit(scenario, key())
    assert caught.value.code == "UNSUPPORTED_SYNTHETIC_SCENARIO"
    assert executor.list_jobs() == []
    assert list((executor.output_root / "requests").iterdir()) == []


@pytest.mark.parametrize(
    "request_key", ["", "abc", str(uuid.uuid1()), str(uuid.uuid4()).upper(), None]
)
def test_request_identity_must_be_canonical_uuid4(make_executor, request_key):
    executor = make_executor()
    with pytest.raises(DemoError) as caught:
        executor.submit("permit", request_key)
    assert caught.value.code == "INVALID_IDEMPOTENCY_KEY"
    assert executor.list_jobs() == []


def test_durable_reservation_precedes_dispatch_and_duplicate_is_not_resent(
    make_executor, monkeypatch
):
    executor = make_executor()
    entered, release = no_dispatch(executor, monkeypatch)
    request_key = key()
    try:
        first = executor.submit("permit", request_key)
        assert entered.wait(2)
        claim = executor.output_root / "requests" / (request_key + ".json")
        assert json.loads(claim.read_bytes())["job_id"] == first["id"]
        states = executor.output_root / "jobs" / first["id"] / "states"
        assert json.loads((states / "0000.json").read_bytes())["status"] == "RESERVED"
        duplicate = executor.submit("permit", request_key)
        assert duplicate["id"] == first["id"]
        assert len(executor.list_jobs()) == 1
        with pytest.raises(DemoError) as caught:
            executor.submit("review", request_key)
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    finally:
        release.set()


def test_concurrent_requests_can_reserve_only_one_dispatch_slot(make_executor, monkeypatch):
    executor = make_executor()
    entered, release = no_dispatch(executor, monkeypatch)

    def submit(_):
        try:
            return executor.submit("deny", key())
        except DemoError as exc:
            return exc.code

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            values = list(pool.map(submit, range(24)))
        assert entered.wait(2)
        assert sum(isinstance(item, dict) for item in values) == 1
        assert values.count("SYNTHETIC_EXECUTOR_BUSY") == 23
        assert len(list((executor.output_root / "requests").iterdir())) == 1
    finally:
        release.set()


def test_get_snapshots_never_schedule_or_write(make_executor, monkeypatch):
    executor = make_executor()
    before = {str(p): p.read_bytes() for p in executor.output_root.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("GET dispatched")
    )
    for _ in range(4):
        assert executor.list_jobs() == []
        assert executor.evidence_entries() == []
        assert executor.capabilities()["active"] is False
        with pytest.raises(DemoError):
            executor.get_job("unknown")
    after = {str(p): p.read_bytes() for p in executor.output_root.rglob("*") if p.is_file()}
    assert before == after


def test_initial_reservation_failure_prevents_start_and_fences_new_requests(
    make_executor, monkeypatch
):
    executor = make_executor()
    calls = []
    monkeypatch.setattr(executor, "_run_job", lambda job_id: calls.append(job_id))
    monkeypatch.setattr(module, "_write_new", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(DemoError) as caught:
        executor.submit("permit", key())
    assert caught.value.code == "RESERVATION_CUSTODY_UNCONFIRMED"
    assert calls == [] and executor.capabilities()["enabled"] is False
    with pytest.raises(DemoError) as caught:
        executor.submit("deny", key())
    assert caught.value.code == "SYNTHETIC_EXECUTION_HOLD"


def test_thread_start_failure_retains_uncertain_reservation(make_executor, monkeypatch):
    executor = make_executor()
    monkeypatch.setattr(
        module.threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError())
    )
    value = executor.submit("permit", key())
    assert value["status"] == "UNKNOWN"
    assert value["error_code"] == "DISPATCH_START_UNCONFIRMED"
    assert len(list((executor.output_root / "requests").iterdir())) == 1
    assert executor.capabilities()["enabled"] is False
    assert executor.evidence_entries() == []


def test_existing_output_cannot_be_resumed_or_reset(make_executor):
    executor = make_executor()
    with pytest.raises(DemoError) as caught:
        DemoExecutor(ROOT, executor.output_root, Path(sys.executable))
    assert caught.value.code == "FRESH_OUTPUT_ROOT_REQUIRED"
    assert (executor.output_root / "owner.json").is_file()


@pytest.mark.parametrize("deadline", [0, 9, 121, True, "90"])
def test_deadline_bounds_are_trusted_configuration(make_executor, deadline):
    with pytest.raises(DemoError) as caught:
        make_executor(deadline_seconds=deadline)
    assert caught.value.code == "INVALID_DEADLINE"


def test_output_cannot_overlap_historical_evidence(tmp_path, monkeypatch):
    historical = tmp_path / "historical"
    historical.mkdir()
    monkeypatch.setattr(DemoExecutor, "_verify_worker_environment", lambda self: None)
    with pytest.raises(DemoError) as caught:
        DemoExecutor(ROOT, historical / "new", Path(sys.executable), protected_roots=(historical,))
    assert caught.value.code == "OUTPUT_ROOT_OVERLAPS_PROTECTED_SOURCE"
    assert list(historical.iterdir()) == []


def test_http_and_provider_environment_credentials_are_not_forwarded(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "CIVICGATE_OPENAI_JUDGE_API_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "CIVICGATE_AGENT_PROVIDER",
    ):
        monkeypatch.setenv(name, "SYNTHETIC_TEST_VALUE")
    env = DemoExecutor._environment()
    assert set(env) <= {
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUTF8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
    }
    assert "SYNTHETIC_TEST_VALUE" not in env.values()


def test_worker_metadata_requires_exact_mcp_and_langgraph(tmp_path, monkeypatch):
    class Result:
        stdout = b'{"mcp":"2.3.0","langgraph":"1.2.15"}'
        returncode = 0

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(DemoError) as caught:
        DemoExecutor(ROOT, tmp_path / "output", Path(sys.executable))
    assert caught.value.code == "SYNTHETIC_WORKER_ENVIRONMENT_UNVERIFIED"
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "event,expected",
    [
        (
            {"event": "socket.bind", "kind": "denied", "address": "('::1', 0)", "allowed": False},
            True,
        ),
        (
            {
                "event": "socket.bind",
                "kind": "denied",
                "address": "('127.0.0.1', 0)",
                "allowed": False,
            },
            True,
        ),
        (
            {
                "event": "socket.connect",
                "kind": "denied",
                "address": "('192.0.2.1', 443)",
                "allowed": False,
            },
            False,
        ),
        (
            {
                "event": "socket.getaddrinfo",
                "host": "example.invalid",
                "port": 443,
                "allowed": False,
            },
            False,
        ),
        (
            {
                "event": "socket.bind",
                "kind": "denied",
                "address": "('0.0.0.0', 0)",
                "allowed": False,
            },
            False,
        ),
        (
            {
                "event": "socket.connect",
                "kind": "owned_synthetic_fixture",
                "address": "('192.0.2.1', 443)",
                "allowed": True,
            },
            False,
        ),
        (
            {
                "event": "socket.connect",
                "kind": "owned_synthetic_fixture",
                "address": "('127.0.0.1', 40000)",
                "allowed": True,
            },
            True,
        ),
        (
            {"event": "socket.getaddrinfo", "host": "127.0.0.1", "port": "40000", "allowed": True},
            True,
        ),
        ({"event": "socket.sendto", "allowed": False}, False),
    ],
)
def test_guard_receipt_accepts_only_known_owned_or_blocked_loopback_paths(
    tmp_path, event, expected
):
    # Exercise the worker selected by the CP1.1 controller, with identical checks.
    script = ROOT / "scripts/run_console_synthetic_demo_v2.py"
    spec = importlib.util.spec_from_file_location("console_worker_receipt_test", script)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    copy = tmp_path / "pinned-copy"
    facts = {
        "loaded_project_modules": {
            "civicgate": {"path": str(copy / "source.py"), "sha256": "a" * 64}
        },
        "network_events": [event],
    }
    assert (
        worker.verify_guard_facts(facts, copy, [{"path": "source.py", "sha256": "a" * 64}])
        is expected
    )


def test_shutdown_preserves_unknown_without_scheduling_retry(make_executor, monkeypatch):
    executor = make_executor()
    entered, release = no_dispatch(executor, monkeypatch)
    requested = executor.submit("permit", key())
    assert entered.wait(2)
    release.set()
    executor.shutdown()
    value = executor.get_job(requested["id"])
    assert value["status"] == "UNKNOWN"
    assert value["error_code"] == "SHUTDOWN_OUTCOME_UNKNOWN"
    assert executor.capabilities()["enabled"] is False
    assert executor.evidence_entries() == []
    assert len(list((executor.output_root / "requests").iterdir())) == 1


def test_running_custody_failure_prevents_popen(make_executor, monkeypatch):
    executor = make_executor()
    original = executor._persist
    calls = []

    def persist(job):
        if job["status"] == "RUNNING":
            raise OSError("synthetic injected custody failure")
        return original(job)

    monkeypatch.setattr(executor, "_persist", persist)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: calls.append(a))
    requested = executor.submit("permit", key())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and executor.get_job(requested["id"])["status"] == "RESERVED":
        time.sleep(0.01)
    assert executor.get_job(requested["id"])["status"] == "UNKNOWN"
    assert calls == []
    assert executor.capabilities()["enabled"] is False
    assert executor.evidence_entries() == []


@pytest.mark.parametrize("phase", ["RESERVED", "RUNNING", "worker-command"])
def test_expired_custody_ack_never_starts_provider_worker(make_executor, monkeypatch, phase):
    executor = make_executor(deadline_seconds=10)
    clock = {"value": 0.0}
    original_persist = executor._persist
    original_write = module._write_new
    sends = []

    def persist(job):
        original_persist(job)
        if job["status"] == phase:
            clock["value"] = 11.0

    def write(path, value):
        original_write(path, value)
        if phase == "worker-command" and path.name == "worker-command.json":
            clock["value"] = 11.0

    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(executor, "_persist", persist)
    monkeypatch.setattr(module, "_write_new", write)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: sends.append(a))
    requested = executor.submit("permit", key())
    for _ in range(200):
        value = executor.get_job(requested["id"])
        if value["status"] == "UNKNOWN":
            break
        threading.Event().wait(0.01)
    assert value["status"] == "UNKNOWN"
    assert sends == []
    assert executor.capabilities()["enabled"] is False
    assert executor.evidence_entries() == []
    assert len(list((executor.output_root / "requests").iterdir())) == 1


def test_delayed_thread_cannot_reset_absolute_deadline(make_executor, monkeypatch):
    executor = make_executor(deadline_seconds=10)
    clock = {"value": 0.0}
    original_run = executor._run_job
    sends = []

    def delayed(job_id):
        clock["value"] = 11.0
        original_run(job_id)

    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(executor, "_run_job", delayed)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: sends.append(a))
    requested = executor.submit("permit", key())
    for _ in range(200):
        value = executor.get_job(requested["id"])
        if value["status"] == "UNKNOWN":
            break
        threading.Event().wait(0.01)
    assert value["status"] == "UNKNOWN"
    assert value["error_code"] == "EXECUTION_DEADLINE_BEFORE_DISPATCH"
    assert sends == [] and executor.capabilities()["enabled"] is False


def test_worker_setup_expiry_prevents_inner_pytest_dispatch(tmp_path, monkeypatch):
    # The legacy V1 source inventory is frozen; this deadline guards the V2 worker.
    script = ROOT / "scripts/run_console_synthetic_demo_v2.py"
    spec = importlib.util.spec_from_file_location("console_worker_deadline_test", script)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    job = tmp_path / ("exec-" + uuid.uuid4().hex)
    job.mkdir()
    clock_values = iter([0.0, 11.0])
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock_values, 11.0))
    monkeypatch.setattr(
        worker.sys,
        "argv",
        [
            str(script),
            "--scenario",
            "permit",
            "--job-root",
            str(job),
            "--deadline-seconds",
            "10",
            "--absolute-deadline",
            "10",
        ],
    )
    sends = []
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: sends.append(a))
    assert worker.main() == 1
    assert sends == []
    result = json.loads(next(job.rglob("run-result.json")).read_bytes())
    assert result["timed_out"] is True and result["counts"]["PASS"] == 0


def test_timeout_with_unconfirmed_cleanup_remains_unknown_and_cannot_retry(
    make_executor, monkeypatch
):
    executor = make_executor()
    calls = []

    class Process:
        pid = 987654  # Synthetic sentinel; no operating-system process is signaled.

        def __init__(self, *args, **kwargs):
            calls.append(args)

        def wait(self, timeout):
            raise module.subprocess.TimeoutExpired("synthetic", timeout)

        def poll(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(module, "_terminate_tree", lambda process: False)
    requested = executor.submit("permit", key())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        value = executor.get_job(requested["id"])
        if value["status"] == "UNKNOWN":
            break
        time.sleep(0.01)
    assert value["status"] == "UNKNOWN"
    assert value["error_code"] == "EXECUTION_DEADLINE_UNKNOWN"
    assert len(calls) == 1 and executor.evidence_entries() == []
    with pytest.raises(DemoError) as caught:
        executor.submit("permit", key())
    assert caught.value.code == "SYNTHETIC_EXECUTION_HOLD"
    assert len(calls) == 1
    assert len(list((executor.output_root / "requests").iterdir())) == 1


def test_late_final_ack_and_failed_unknown_write_never_persist_complete(make_executor, monkeypatch):
    from test_reader import fixture_run, seal

    executor = make_executor(deadline_seconds=10)
    clock = {"value": 0.0}
    original_persist = executor._persist
    original_write = module._write_new
    original_fail = executor._fail_job
    diagnostics = []

    class Process:
        def __init__(self, command, **kwargs):
            job_root = Path(command[command.index("--job-root") + 1])
            fixture = fixture_run(job_root / "documentary-fixture-source")
            capture = job_root / ("capture-" + job_root.name.removeprefix("exec-"))
            shutil.copytree(fixture / "execution/cases/example", capture / "execution/cases/permit")
            module._write_new(
                capture / "run-result.json",
                {
                    "final_status": "A2_INTEGRATED_DEMO_READY",
                    "counts": {"PASS": 1, "FAIL": 0, "ERROR": 0, "SKIP": 0},
                    "source_copy_unchanged": True,
                    "guard_primary_evidence_verified": True,
                    "automatic_retry": False,
                    "scenario": "permit",
                },
            )
            seal(capture)

        def wait(self, timeout):
            return 0

        def poll(self):
            return 0

    def persist(job):
        original_persist(job)
        if job.get("_journal_candidate"):
            clock["value"] = 11.0

            def fail_unknown(path, value):
                if isinstance(value, dict) and value.get("status") == "UNKNOWN":
                    raise OSError("synthetic unavailable STOP write")
                return original_write(path, value)

            monkeypatch.setattr(module, "_write_new", fail_unknown)

    monkeypatch.setattr(module.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(module.subprocess, "Popen", Process)
    monkeypatch.setattr(executor, "_persist", persist)

    def diagnostic_fail(*args, **kwargs):
        diagnostics.append(repr(sys.exc_info()[1]))
        return original_fail(*args, **kwargs)

    monkeypatch.setattr(executor, "_fail_job", diagnostic_fail)
    requested = executor.submit("permit", key())
    # Use Event waits: the monotonic fault affects module.time globally.
    for _ in range(200):
        value = executor.get_job(requested["id"])
        if value["status"] == "UNKNOWN":
            break
        threading.Event().wait(0.01)
    assert value["status"] == "UNKNOWN"
    assert value["error_code"] == "TERMINAL_CUSTODY_UNKNOWN", diagnostics
    assert executor.evidence_entries() == [] and executor.capabilities()["enabled"] is False
    journal = executor.output_root / "jobs" / requested["id"] / "states"
    records = [json.loads(path.read_bytes()) for path in sorted(journal.glob("*.json"))]
    assert records[-1]["status"] == "EVIDENCE_CANDIDATE"
    assert not any(record["status"] == "COMPLETE" for record in records)


@pytest.mark.parametrize("scenario", ["permit", "deny", "review"])
def test_actual_guarded_synthetic_worker_produces_fresh_primary_evidence(tmp_path, scenario):
    configured = os.environ.get("CIVICGATE_SYNTHETIC_WORKER_PYTHON")
    if not configured:
        pytest.skip("Explicit existing synthetic MCP worker environment not configured")
    executor = DemoExecutor(ROOT, tmp_path / "fresh-output", Path(configured))
    requested = executor.submit(scenario, key())
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        value = executor.get_job(requested["id"])
        if value["status"] not in {"RESERVED", "RUNNING"}:
            break
        time.sleep(0.05)
    assert value["status"] == "COMPLETE", value
    assert value["run_id"].startswith("e2e-")
    assert value["observation_id"].startswith("MINI072_OBS_" + scenario.upper() + "_")
    assert executor.evidence_entries()[0]["id"] == value["run_id"]
    capture = Path(executor.evidence_entries()[0]["root"])
    assert (capture / "execution/cases" / scenario / "coordinator.sqlite").is_file()
    assert (capture / "execution/junit.xml").is_file()
    assert (capture / "execution/guard-evidence.json").is_file()
    assert not any(
        name.startswith(("civicgate.mcp", "civicgate.governance", "evals.harness"))
        for name in sys.modules
    )
