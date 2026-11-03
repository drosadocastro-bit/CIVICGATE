"""Bounded local scheduling of one fixed, guarded synthetic demonstration.

This is an execution-request/capture controller, not an authorization issuer.
Only the unchanged Gateway can issue an ExecutionBinding inside its subprocess.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .reader import EvidenceStore

SCENARIOS = ("permit", "deny", "review")
PUBLIC_FIELDS = (
    "id",
    "scenario",
    "status",
    "created_at_utc",
    "started_at_utc",
    "completed_at_utc",
    "error_code",
    "run_id",
    "observation_id",
    "evidence_url",
)


class DemoError(ValueError):
    def __init__(self, code: str, status_code: int):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_path(path: Path) -> Path:
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
        raise DemoError("INVALID_LOCAL_PATH", 503)
    try:
        for part in [*reversed(path.parents), path]:
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise DemoError("LINK_OR_REPARSE_POINT", 503)
        return path.resolve(strict=True)
    except OSError:
        raise DemoError("LOCAL_CONFIGURATION_UNAVAILABLE", 503) from None


def _write_new(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _terminate_tree(process: subprocess.Popen) -> bool:
    if process.poll() is not None:
        return False  # Parent exit alone does not establish descendant cleanup.
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


class DemoExecutor:
    """One active task, finite task count, exclusive fresh output custody.

    An existing output root is never resumed or cleared automatically. Select a
    fresh root after operator investigation; uncertain attempts are not retried.
    File/fsync acknowledgements are not universal power-loss certification.
    """

    def __init__(
        self,
        source_root: Path,
        output_root: Path,
        worker_python: Path,
        deadline_seconds: int = 90,
        max_jobs: int = 8,
        protected_roots: tuple[Path, ...] = (),
    ):
        if type(deadline_seconds) is not int or not 10 <= deadline_seconds <= 120:
            raise DemoError("INVALID_DEADLINE", 503)
        if type(max_jobs) is not int or not 1 <= max_jobs <= 8:
            raise DemoError("INVALID_TASK_LIMIT", 503)
        self.source_root = _safe_path(Path(source_root))
        self.worker_python = _safe_path(Path(worker_python))
        if not self.worker_python.is_file():
            raise DemoError("INVALID_WORKER", 503)
        output_root = Path(output_root)
        _safe_path(output_root.parent)
        if output_root.exists() or not output_root.is_absolute():
            raise DemoError("FRESH_OUTPUT_ROOT_REQUIRED", 503)
        resolved_output = output_root.parent.resolve() / output_root.name
        for protected in (self.source_root, *map(Path, protected_roots)):
            protected = _safe_path(protected)
            if resolved_output.is_relative_to(protected) or protected.is_relative_to(
                resolved_output
            ):
                raise DemoError("OUTPUT_ROOT_OVERLAPS_PROTECTED_SOURCE", 503)
        self.output_root = resolved_output
        self.deadline_seconds = deadline_seconds
        self.max_jobs = max_jobs
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._requests: dict[str, str] = {}
        self._active = False
        self._blocked = False
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._verify_worker_environment()
        try:
            self.output_root.mkdir(exist_ok=False)
            (self.output_root / "requests").mkdir()
            (self.output_root / "jobs").mkdir()
            _write_new(
                self.output_root / "owner.json",
                {
                    "record_type": "EXCLUSIVE_SYNTHETIC_CONSOLE_OUTPUT_OWNER",
                    "instance_id": uuid.uuid4().hex,
                    "created_at_utc": _now(),
                    "automatic_recovery": False,
                    "execution_authority": False,
                    "deadline_seconds": deadline_seconds,
                    "max_jobs": max_jobs,
                },
            )
        except OSError:
            raise DemoError("INITIAL_CUSTODY_UNCONFIRMED", 503) from None

    def _verify_worker_environment(self) -> None:
        command = [
            str(self.worker_python),
            "-B",
            "-s",
            "-c",
            "import importlib.metadata as m,json;print(json.dumps({k:m.version(k) for k in ['mcp','langgraph','httpx','pytest']}))",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=10, env=self._environment()
            )
            versions = json.loads(result.stdout)
            if (
                result.returncode
                or versions.get("mcp") != "1.30.0"
                or versions.get("langgraph") != "1.2.15"
            ):
                raise DemoError("SYNTHETIC_WORKER_ENVIRONMENT_UNVERIFIED", 503)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise DemoError("SYNTHETIC_WORKER_ENVIRONMENT_UNVERIFIED", 503) from None

    @staticmethod
    def _environment() -> dict[str, str]:
        env = {
            key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ
        }
        env.update(
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONUTF8="1",
            PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
            LANGSMITH_TRACING="false",
            LANGCHAIN_TRACING_V2="false",
        )
        return env

    def capabilities(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": not self._blocked,
                "mode": "SYNTHETIC_E2E_ONLY",
                "scenarios": list(SCENARIOS),
                "concurrency_limit": 1,
                "active": self._active,
                "remaining_jobs": self.max_jobs - len(self._jobs),
                "deadline_seconds": self.deadline_seconds,
                "automatic_retry": False,
                "external_provider_execution": "NOT_AUTHORIZED",
                "execution_authority": False,
            }

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {key: job.get(key) for key in PUBLIC_FIELDS}

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(job) for job in self._jobs.values()]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise DemoError("UNKNOWN_EXECUTION", 404)
            return self._public(self._jobs[job_id])

    def evidence_entries(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                dict(job["_entry"])
                for job in self._jobs.values()
                if job["status"] == "COMPLETE" and job.get("_entry")
            ]

    def _persist(self, job: dict[str, Any]) -> None:
        number = job["_state_number"]
        public = self._public(job)
        if job.get("_journal_candidate"):
            public["status"] = "EVIDENCE_CANDIDATE"
            public["candidate_process_outcome"] = "COMPLETE"
        _write_new(
            job["_directory"] / "states" / f"{number:04d}.json",
            {
                **public,
                "manifest_sha256": job.get("_entry", {}).get("manifest_sha256"),
                "meaning": "SYNTHETIC_EXECUTION_REQUEST_CUSTODY_NOT_POLICY_AUTHORITY",
            },
        )
        job["_state_number"] += 1

    def submit(self, scenario: str, idempotency_key: str) -> dict[str, Any]:
        absolute_deadline = time.monotonic() + self.deadline_seconds
        if scenario not in SCENARIOS or type(scenario) is not str:
            raise DemoError("UNSUPPORTED_SYNTHETIC_SCENARIO", 422)
        try:
            parsed = uuid.UUID(idempotency_key)
            if str(parsed) != idempotency_key or parsed.version != 4:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise DemoError("INVALID_IDEMPOTENCY_KEY", 422) from None
        with self._lock:
            if idempotency_key in self._requests:
                job = self._jobs[self._requests[idempotency_key]]
                if job["scenario"] != scenario:
                    raise DemoError("IDEMPOTENCY_CONFLICT", 409)
                return self._public(job)
            if self._blocked:
                raise DemoError("SYNTHETIC_EXECUTION_HOLD", 503)
            if self._active:
                raise DemoError("SYNTHETIC_EXECUTOR_BUSY", 429)
            if len(self._jobs) >= self.max_jobs:
                raise DemoError("SYNTHETIC_TASK_LIMIT", 429)
            job_id = "exec-" + uuid.uuid4().hex
            directory = self.output_root / "jobs" / job_id
            job = {
                "id": job_id,
                "scenario": scenario,
                "status": "RESERVED",
                "created_at_utc": _now(),
                "started_at_utc": None,
                "completed_at_utc": None,
                "error_code": None,
                "run_id": None,
                "observation_id": None,
                "evidence_url": None,
                "_directory": directory,
                "_state_number": 0,
                "_absolute_deadline": absolute_deadline,
            }
            try:
                directory.mkdir(exist_ok=False)
                (directory / "states").mkdir()
                _write_new(
                    self.output_root / "requests" / f"{idempotency_key}.json",
                    {
                        "idempotency_key": idempotency_key,
                        "job_id": job_id,
                        "scenario": scenario,
                        "reserved_at_utc": job["created_at_utc"],
                    },
                )
                self._persist(job)
            except OSError:
                self._blocked = True
                raise DemoError("RESERVATION_CUSTODY_UNCONFIRMED", 503) from None
            self._jobs[job_id] = job
            self._requests[idempotency_key] = job_id
            if time.monotonic() >= absolute_deadline:
                self._fail_job(job, "INITIAL_CUSTODY_ACK_AFTER_DEADLINE", unknown=True)
                return self._public(job)
            self._active = True
            thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
            self._thread = thread
            try:
                thread.start()
            except RuntimeError:
                self._active = False
                self._blocked = True
                job["status"] = "UNKNOWN"
                job["error_code"] = "DISPATCH_START_UNCONFIRMED"
                try:
                    self._persist(job)
                except OSError:
                    pass
            return self._public(job)

    def _run_job(self, job_id: str) -> None:
        process = None
        with self._lock:
            job = self._jobs[job_id]
            deadline = job["_absolute_deadline"]
            if self._blocked or time.monotonic() >= deadline:
                self._fail_job(job, "EXECUTION_DEADLINE_BEFORE_DISPATCH", unknown=True)
                self._active = False
                return
            job["status"] = "RUNNING"
            job["started_at_utc"] = _now()
            try:
                self._persist(job)
            except OSError:
                self._blocked = True
                self._active = False
                job["status"] = "UNKNOWN"
                job["error_code"] = "START_CUSTODY_UNCONFIRMED"
                return
            if time.monotonic() >= deadline:
                self._fail_job(job, "RUNNING_ACK_AFTER_DEADLINE", unknown=True)
                self._active = False
                return
        try:
            worker = self.source_root / "scripts/run_console_synthetic_demo_v2.py"
            command = [
                str(self.worker_python),
                "-B",
                "-s",
                str(worker),
                "--scenario",
                job["scenario"],
                "--job-root",
                str(job["_directory"]),
                "--deadline-seconds",
                str(max(0.001, deadline - time.monotonic())),
                "--absolute-deadline",
                str(deadline),
            ]
            _write_new(
                job["_directory"] / "worker-command.json",
                {
                    "argv": command,
                    "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
                    "environment_keys": sorted(self._environment()),
                    "automatic_retry": False,
                },
            )
            with (
                (job["_directory"] / "worker.stdout.log").open("xb") as out,
                (job["_directory"] / "worker.stderr.log").open("xb") as err,
            ):
                with self._lock:
                    if self._blocked or time.monotonic() >= deadline:
                        raise DemoError("EXECUTION_DEADLINE_BEFORE_SEND", 503)
                    process = subprocess.Popen(
                        command,
                        cwd=self.source_root,
                        env=self._environment(),
                        stdout=out,
                        stderr=err,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                        start_new_session=os.name != "nt",
                    )
                    self._process = process
                code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            if code != 0:
                raise DemoError("SYNTHETIC_WORKER_REJECTED", 503)
            if time.monotonic() > deadline:
                raise DemoError("EXECUTION_DEADLINE_EXCEEDED", 503)
            capture = job["_directory"] / ("capture-" + job["id"].removeprefix("exec-"))
            manifest = capture / "RUN_SHA256_MANIFEST.json"
            run_result = json.loads((capture / "run-result.json").read_bytes())
            if (
                run_result.get("final_status") != "A2_INTEGRATED_DEMO_READY"
                or run_result.get("counts") != {"PASS": 1, "FAIL": 0, "ERROR": 0, "SKIP": 0}
                or run_result.get("source_copy_unchanged") is not True
                or run_result.get("guard_primary_evidence_verified") is not True
                or run_result.get("automatic_retry") is not False
                or run_result.get("scenario") != job["scenario"]
            ):
                raise DemoError("FRESH_WORKER_RECEIPT_UNVERIFIED", 503)
            entry = {
                "id": "e2e-" + job_id.removeprefix("exec-"),
                "root": str(capture),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
            reader = EvidenceStore([entry])
            observed = reader.get_run(entry["id"])
            if observed["integrity"] != "VERIFIED" or len(observed["observations"]) != 1:
                raise DemoError("FRESH_EVIDENCE_ADMISSION_FAILED", 503)
            observation = observed["observations"][0]
            if (
                observation["case"] != job["scenario"]
                or observation["decision"]
                != {
                    "permit": "PERMIT",
                    "deny": "DENY",
                    "review": "REVIEW_REQUIRED",
                }[job["scenario"]]
            ):
                raise DemoError("FRESH_SCENARIO_CORRELATION_FAILED", 503)
            with self._lock:
                if self._blocked or time.monotonic() > deadline:
                    raise DemoError("EXECUTION_DEADLINE_OR_STOP", 503)
                candidate = dict(job)
                candidate.update(
                    status="COMPLETE",
                    completed_at_utc=_now(),
                    run_id=entry["id"],
                    observation_id=observation["id"],
                    _entry=entry,
                    _journal_candidate=True,
                )
                candidate["evidence_url"] = f"/runs/{entry['id']}/observations/{observation['id']}"
                self._persist(candidate)
                if time.monotonic() > deadline:
                    job["_state_number"] = candidate["_state_number"]
                    self._fail_job(job, "FINAL_CUSTODY_ACK_AFTER_DEADLINE", unknown=True)
                else:
                    candidate.pop("_journal_candidate")
                    job.update(candidate)
        except subprocess.TimeoutExpired:
            confirmed = _terminate_tree(process) if process is not None else False
            self._fail_job(
                job, "EXECUTION_DEADLINE_UNKNOWN", unknown=True, cleanup_confirmed=confirmed
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            DemoError,
            subprocess.SubprocessError,
        ) as exc:
            code = exc.code if isinstance(exc, DemoError) else "EXECUTION_OR_CUSTODY_UNCONFIRMED"
            if process is not None and process.poll() is None:
                _terminate_tree(process)
            self._fail_job(job, code, unknown=True)
        finally:
            with self._lock:
                self._active = False
                self._process = None

    def _fail_job(
        self,
        job: dict[str, Any],
        code: str,
        *,
        unknown: bool,
        cleanup_confirmed: bool | None = None,
    ) -> None:
        with self._lock:
            self._blocked = True
            job.update(
                status="UNKNOWN" if unknown else "HOLD",
                error_code=code,
                completed_at_utc=_now(),
                run_id=None,
                observation_id=None,
                evidence_url=None,
            )
            job.pop("_entry", None)
            try:
                self._persist(job)
                if cleanup_confirmed is not None:
                    _write_new(
                        job["_directory"] / "deadline-cleanup.json",
                        {
                            "owned_subtree_cleanup_confirmed": cleanup_confirmed,
                            "no_retry": True,
                            "dispatch_outcome": "UNKNOWN",
                        },
                    )
            except OSError:
                job["error_code"] = "TERMINAL_CUSTODY_UNKNOWN"

    def shutdown(self) -> None:
        with self._lock:
            self._blocked = True
            process = self._process
            thread = self._thread
            for job in self._jobs.values():
                if job["status"] in {"RESERVED", "RUNNING"}:
                    self._fail_job(job, "SHUTDOWN_OUTCOME_UNKNOWN", unknown=True)
        if process is not None:
            _terminate_tree(process)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=15)
