"""Bounded host-owned synthetic Chat scheduling for MINI10.

The browser supplies only prompt text and an idempotency key.  This controller
selects a fixed READ owner and fixed scripted planner before the worker starts.
It has no Gateway, policy, binding issuer, adapter, WRITE owner, or fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .demo_execution_v1 import (
    DemoError,
    DemoExecutor,
    _now,
    _terminate_tree,
    _write_new,
)
from .reader import EvidenceStore

HOST_OWNER = "CHANNEL_A_LOCAL_READ_V1"
PLANNER_IDENTITY = "SCRIPTED_SYNTHETIC_FIXTURE_NOT_GRANITE"
CHAT_PUBLIC_FIELDS = (
    "id",
    "status",
    "created_at_utc",
    "started_at_utc",
    "completed_at_utc",
    "error_code",
    "original_request",
    "request_sha256",
    "planner_identity",
    "selected_tool",
    "canonical_arguments",
    "decision",
    "policy_reasons",
    "binding_issuances",
    "binding_consumptions",
    "backend_attempts",
    "result_state",
    "result",
    "stage_entry_deltas_ms",
    "run_id",
    "observation_id",
    "evidence_url",
)


class ChatExecutor(DemoExecutor):
    """One finite Chat turn at a time, using DemoExecutor custody mechanics."""

    def __init__(
        self,
        source_root: Path,
        output_root: Path,
        worker_python: Path,
        deadline_seconds: int = 90,
        max_jobs: int = 8,
        protected_roots: tuple[Path, ...] = (),
    ) -> None:
        super().__init__(
            source_root,
            output_root,
            worker_python,
            deadline_seconds=deadline_seconds,
            max_jobs=max_jobs,
            protected_roots=protected_roots,
        )
        try:
            _write_new(
                self.output_root / "chat-owner.json",
                {
                    "record_type": "MINI10_TRUSTED_HOST_CHAT_OWNER",
                    "host_owner": HOST_OWNER,
                    "planner_identity": PLANNER_IDENTITY,
                    "selected_before_discovery": True,
                    "legacy_fallback": False,
                    "faa_strict_owner_composed": False,
                    "write_owner_composed": False,
                    "browser_selectable": False,
                    "execution_authority": False,
                },
            )
        except OSError:
            self._blocked = True
            raise DemoError("CHAT_OWNER_CUSTODY_UNCONFIRMED", 503) from None

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        return {key: job.get(key) for key in CHAT_PUBLIC_FIELDS}

    def capabilities(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": not self._blocked,
                "mode": "SYNTHETIC_GOVERNED_CHAT_ONLY",
                "host_owner": HOST_OWNER,
                "planner_identity": PLANNER_IDENTITY,
                "planner_accuracy_claim": False,
                "granite_activation": "NOT_CONFIGURED_NOT_INVOKED",
                "write_execution": "DISABLED_NOT_COMPOSED",
                "faa_strict_owner": "SEPARATE_NOT_COMPOSED",
                "legacy_fallback": False,
                "concurrency_limit": 1,
                "active": self._active,
                "remaining_turns": self.max_jobs - len(self._jobs),
                "deadline_seconds": self.deadline_seconds,
                "automatic_retry": False,
                "external_provider_execution": "NOT_AUTHORIZED",
                "execution_authority": False,
            }

    def list_turns(self) -> list[dict[str, Any]]:
        return self.list_jobs()

    def get_turn(self, turn_id: str) -> dict[str, Any]:
        return self.get_job(turn_id)

    def submit_prompt(self, prompt: str, idempotency_key: str) -> dict[str, Any]:
        absolute_deadline = time.monotonic() + self.deadline_seconds
        if (
            type(prompt) is not str
            or not prompt.strip()
            or len(prompt) > 4000
            or len(prompt.encode("utf-8")) > 16_000
            or "\x00" in prompt
        ):
            raise DemoError("INVALID_CHAT_PROMPT", 422)
        try:
            parsed = uuid.UUID(idempotency_key)
            if str(parsed) != idempotency_key or parsed.version != 4:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise DemoError("INVALID_IDEMPOTENCY_KEY", 422) from None
        request_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
        with self._lock:
            if idempotency_key in self._requests:
                existing_job = self._jobs[self._requests[idempotency_key]]
                if (
                    existing_job["request_sha256"] != request_sha256
                    or existing_job["original_request"] != prompt
                ):
                    raise DemoError("IDEMPOTENCY_CONFLICT", 409)
                return self._public(existing_job)
            if self._blocked:
                raise DemoError("SYNTHETIC_CHAT_HOLD", 503)
            if self._active:
                raise DemoError("SYNTHETIC_CHAT_BUSY", 429)
            if len(self._jobs) >= self.max_jobs:
                raise DemoError("SYNTHETIC_CHAT_LIMIT", 429)
            job_id = "chat-" + uuid.uuid4().hex
            directory = self.output_root / "jobs" / job_id
            request_path = directory / "prompt.json"
            job: dict[str, Any] = {
                "id": job_id,
                "status": "RESERVED",
                "created_at_utc": _now(),
                "started_at_utc": None,
                "completed_at_utc": None,
                "error_code": None,
                "original_request": prompt,
                "request_sha256": request_sha256,
                "planner_identity": PLANNER_IDENTITY,
                "selected_tool": None,
                "canonical_arguments": None,
                "decision": None,
                "policy_reasons": None,
                "binding_issuances": None,
                "binding_consumptions": None,
                "backend_attempts": None,
                "result_state": "NOT_OBSERVED",
                "result": None,
                "stage_entry_deltas_ms": None,
                "run_id": None,
                "observation_id": None,
                "evidence_url": None,
                "_directory": directory,
                "_request_path": request_path,
                "_state_number": 0,
                "_absolute_deadline": absolute_deadline,
            }
            try:
                directory.mkdir(exist_ok=False)
                (directory / "states").mkdir()
                _write_new(
                    request_path,
                    {
                        "host_owner": HOST_OWNER,
                        "planner_identity": PLANNER_IDENTITY,
                        "prompt": prompt,
                        "prompt_sha256": request_sha256,
                    },
                )
                _write_new(
                    self.output_root / "requests" / f"{idempotency_key}.json",
                    {
                        "idempotency_key": idempotency_key,
                        "turn_id": job_id,
                        "prompt_sha256": request_sha256,
                        "reserved_at_utc": job["created_at_utc"],
                    },
                )
                self._persist(job)
            except OSError:
                self._blocked = True
                raise DemoError("CHAT_RESERVATION_CUSTODY_UNCONFIRMED", 503) from None
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

    @staticmethod
    def _entry_deltas(projection: dict[str, Any]) -> dict[str, float]:
        nodes = projection.get("graph", {}).get("node_entries", [])
        if not isinstance(nodes, list) or len(nodes) != 5:
            raise DemoError("CHAT_GRAPH_TIMING_INVALID", 503)
        values: list[tuple[str, int]] = []
        for row in nodes:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("node"), str)
                or type(row.get("parent_monotonic_ns")) is not int
            ):
                raise DemoError("CHAT_GRAPH_TIMING_INVALID", 503)
            values.append((row["node"], row["parent_monotonic_ns"]))
        if [name for name, _ in values] != ["intake", "discovery", "planner", "gateway", "result"]:
            raise DemoError("CHAT_GRAPH_TIMING_INVALID", 503)
        if [value for _, value in values] != sorted(value for _, value in values):
            raise DemoError("CHAT_GRAPH_TIMING_INVALID", 503)
        return {
            f"{values[index][0]}_to_{values[index + 1][0]}": round(
                (values[index + 1][1] - values[index][1]) / 1_000_000, 3
            )
            for index in range(len(values) - 1)
        }

    def _run_job(self, job_id: str) -> None:
        process: subprocess.Popen[bytes] | None = None
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
            worker = self.source_root / "scripts/run_console_chat_synthetic_v1.py"
            command = [
                str(self.worker_python),
                "-B",
                "-s",
                str(worker),
                "--request-file",
                str(job["_request_path"]),
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
                    "host_owner": HOST_OWNER,
                    "planner_identity": PLANNER_IDENTITY,
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
                        creationflags=(
                            subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                        ),
                        start_new_session=os.name != "nt",
                    )
                    self._process = process
                code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            if code != 0:
                raise DemoError("SYNTHETIC_CHAT_WORKER_REJECTED", 503)
            if time.monotonic() > deadline:
                raise DemoError("EXECUTION_DEADLINE_EXCEEDED", 503)
            capture = job["_directory"] / ("capture-" + job_id.removeprefix("chat-"))
            manifest = capture / "RUN_SHA256_MANIFEST.json"
            run_result = json.loads((capture / "run-result.json").read_bytes())
            if (
                run_result.get("final_status") != "MINI10_CHAT_TURN_VERIFIED"
                or run_result.get("counts") != {"PASS": 1, "FAIL": 0, "ERROR": 0, "SKIP": 0}
                or run_result.get("prompt_sha256") != job["request_sha256"]
                or run_result.get("source_unchanged") is not True
                or run_result.get("projection_verified") is not True
                or run_result.get("guard_primary_evidence_verified") is not True
                or run_result.get("automatic_retry") is not False
                or run_result.get("host_owner") != HOST_OWNER
                or run_result.get("write_execution") != "DISABLED_NOT_COMPOSED"
            ):
                raise DemoError("FRESH_CHAT_WORKER_RECEIPT_UNVERIFIED", 503)
            projections = list(
                (capture / "execution/cases").glob("*/console-evidence-projection.json")
            )
            if len(projections) != 1:
                raise DemoError("FRESH_CHAT_PROJECTION_MISSING", 503)
            projection = json.loads(projections[0].read_bytes())
            proposal = projection.get("proposal", {}).get("effective")
            policy = projection.get("policy", {})
            binding = projection.get("binding", {})
            backend = projection.get("backend", {})
            result = projection.get("result", {})
            if (
                projection.get("request", {}).get("original_request") != job["original_request"]
                or projection.get("request", {}).get("sha256") != job["request_sha256"]
                or not isinstance(proposal, dict)
                or set(proposal) != {"tool", "arguments"}
                or policy.get("final_disposition")
                not in {
                    "PERMIT",
                    "DENY",
                    "REVIEW_REQUIRED",
                }
                or type(binding.get("issued_count")) is not int
                or type(binding.get("consumed_count")) is not int
                or type(backend.get("mock_transport_attempts")) is not int
            ):
                raise DemoError("FRESH_CHAT_CORRELATION_FAILED", 503)
            entry = {
                "id": "chat-e2e-" + job_id.removeprefix("chat-"),
                "root": str(capture),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
            observed = EvidenceStore([entry]).get_run(entry["id"])
            if observed["integrity"] != "VERIFIED" or len(observed["observations"]) != 1:
                raise DemoError("FRESH_CHAT_EVIDENCE_ADMISSION_FAILED", 503)
            observation = observed["observations"][0]
            with self._lock:
                if self._blocked or time.monotonic() > deadline:
                    raise DemoError("EXECUTION_DEADLINE_OR_STOP", 503)
                candidate = dict(job)
                candidate.update(
                    status="COMPLETE",
                    completed_at_utc=_now(),
                    selected_tool=proposal["tool"],
                    canonical_arguments=proposal["arguments"],
                    decision=policy["final_disposition"],
                    policy_reasons=policy.get("reasons", []),
                    binding_issuances=binding["issued_count"],
                    binding_consumptions=binding["consumed_count"],
                    backend_attempts=backend["mock_transport_attempts"],
                    result_state=result.get("verification_state", "UNKNOWN"),
                    result=result.get("value"),
                    stage_entry_deltas_ms=self._entry_deltas(projection),
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
                job,
                "EXECUTION_DEADLINE_UNKNOWN",
                unknown=True,
                cleanup_confirmed=confirmed,
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            DemoError,
            subprocess.SubprocessError,
        ) as exc:
            error_code = (
                exc.code if isinstance(exc, DemoError) else "EXECUTION_OR_CUSTODY_UNCONFIRMED"
            )
            if process is not None and process.poll() is None:
                _terminate_tree(process)
            self._fail_job(job, error_code, unknown=True)
        finally:
            with self._lock:
                self._active = False
                self._process = None
