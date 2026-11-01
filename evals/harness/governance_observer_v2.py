"""Read-only observation of unchanged synchronous governance code.

This profiler is local evaluation instrumentation, not an authority issuer. It
never replaces the protected policy/boundary, edits frames or retains authority
objects. Durations include profiler overhead. A failed function return is unknown
unless another source records the actual exception.
"""

import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from types import CodeType, FrameType, TracebackType
from typing import Any, TextIO

from civicgate.governance.execution import (
    AuthorityEnvelope,
    ExecutionBinding,
    ExecutionBoundary,
    PolicyEvaluation,
)
from civicgate.governance.policy import evaluate
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import PolicyResult

OBSERVER_VERSION = "CIVICGATE-EVAL-GOVERNANCE-OBSERVER-V2"
MAX_EVENTS = 4096
MAX_IDENTIFIER_LENGTH = 256


class ReadOnlyGovernanceObserver:
    """A dedicated-process profiler; an existing profiler is never replaced.

    Evidence is reserved exclusively on entry and buffered until close. close()
    restores profiling and flushes/fsyncs records; it is idempotent. flush() is an
    explicit alias for close(), not an invitation to continue observing afterward.
    """

    def __init__(self, evidence_dir: Path, correlation_id: str) -> None:
        self.directory = evidence_dir.resolve(strict=True)
        if not self.directory.is_dir():
            raise ValueError("OBSERVER_EVIDENCE_DIRECTORY_REQUIRED")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", correlation_id):
            raise ValueError("OBSERVER_CORRELATION_ID_INVALID")
        self.correlation_id = correlation_id
        self.path = self.directory / "governance-observations.jsonl"
        self._targets = {
            evaluate.__code__: "policy",
            ExecutionBoundary.evaluate.__code__: "binding_issue",
            ExecutionBoundary.consume.__code__: "binding_consume",
        }
        self._gateway_code = Gateway._call.__code__
        self._boundary_evaluate_code = ExecutionBoundary.evaluate.__code__
        self._starts: dict[int, tuple[int, str, str | None, int]] = {}
        self._events: list[dict[str, Any]] = []
        self._failures: list[str] = []
        self._counts: Counter[str] = Counter()
        self._stream: TextIO | None = None
        self._entered = False
        self._closed = False
        self._callback = self._profile

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "ReadOnlyGovernanceObserver":
        if self._entered or self._closed:
            raise RuntimeError("OBSERVER_INSTANCE_NOT_REUSABLE")
        if sys.getprofile() is not None:
            raise RuntimeError("OBSERVER_EXISTING_PROFILER_UNSUPPORTED")
        self._stream = self.path.open("x", encoding="utf-8", newline="\n")
        self._entered = True
        try:
            sys.setprofile(self._callback)
        except BaseException:
            self._failures.append("PROFILE_INSTALLATION_FAILED")
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        if exc_type is not None and not self.closed:
            self._counts["context_exceptions"] += 1
        self.close()

    def _request_id(self, frame: FrameType) -> str | None:
        value = frame.f_locals.get("request_id")
        if value is None and frame.f_back is not None:
            value = frame.f_back.f_locals.get("request_id")
        if type(value) is str and 0 < len(value) <= MAX_IDENTIFIER_LENGTH:
            return value
        return None

    def _phase(self, frame: FrameType, target: str) -> str:
        if target != "policy":
            return target
        caller = frame.f_back
        if caller is not None and caller.f_code is self._boundary_evaluate_code:
            return "policy_issuance"
        if caller is not None and caller.f_code is self._gateway_code:
            if "preflight_policy" not in caller.f_locals:
                return "policy_preflight"
            facts = frame.f_locals.get("facts")
            if "envelope" in caller.f_locals and getattr(facts, "review_reason", None):
                return "policy_post_result"
        return "policy_other"

    def _append(self, event: dict[str, Any]) -> None:
        if len(self._events) >= MAX_EVENTS:
            if "EVENT_BUFFER_LIMIT_EXCEEDED" not in self._failures:
                self._failures.append("EVENT_BUFFER_LIMIT_EXCEEDED")
            return
        self._events.append(event)

    def _profile(self, frame: FrameType, event: str, result: Any) -> None:
        target = self._targets.get(frame.f_code)
        if target is None or event not in {"call", "return"}:
            return
        try:
            if event == "call":
                self._counts["matched_calls"] += 1
                index = self._counts["matched_calls"]
                self._starts[id(frame)] = (
                    perf_counter_ns(),
                    self._phase(frame, target),
                    self._request_id(frame),
                    index,
                )
                return
            started = self._starts.pop(id(frame), None)
            if started is None:
                self._failures.append("RETURN_WITHOUT_OBSERVED_CALL")
                return
            start, phase, request_id, index = started
            elapsed_ms = (perf_counter_ns() - start) / 1_000_000
            self._counts["matched_returns"] += 1
            self._counts[phase] += 1
            status = "UNKNOWN_OR_EXCEPTION"
            binding: dict[str, Any] | None = None
            policy: dict[str, Any] | None = None
            if target == "policy" and type(result) is PolicyResult:
                status = "RETURNED_POLICY"
                policy = {"decision": result.decision, "reasons": list(result.reasons)}
            elif target == "binding_issue" and type(result) is PolicyEvaluation:
                policy = {
                    "decision": result.policy.decision,
                    "reasons": list(result.policy.reasons),
                }
                if result.envelope is None:
                    status = "NO_BINDING"
                elif type(result.envelope) is AuthorityEnvelope:
                    status = "ISSUED"
                    binding = result.envelope.binding.audit_record()
            elif target == "binding_consume" and type(result) is ExecutionBinding:
                status = "VERIFIED_CONSUMED"
                binding = result.audit_record()
            if status == "UNKNOWN_OR_EXCEPTION":
                self._counts["unknown_or_exception_returns"] += 1
            self._append(
                {
                    "observer_version": OBSERVER_VERSION,
                    "provenance": "INSTRUMENT_OBSERVED",
                    "mechanism": "CPYTHON_PROFILE_EXACT_SYNCHRONOUS_CODE_OBJECT",
                    "correlation_id": self.correlation_id,
                    "event": "governance_return",
                    "call_index": index,
                    "phase": phase,
                    "elapsed_ms": elapsed_ms,
                    "status": status,
                    "request_id": request_id,
                    "binding": binding,
                    "policy": policy,
                }
            )
        except Exception as exc:
            # Observation must never grant or mutate execution authority. An
            # instrumentation error invalidates evidence rather than disappearing.
            failure = "OBSERVER_CALLBACK_ERROR_" + type(exc).__name__
            if failure not in self._failures:
                self._failures.append(failure)

    def _fingerprint(self, code: CodeType, target: str) -> dict[str, Any]:
        path = Path(code.co_filename).resolve()
        repo = Path(__file__).resolve().parents[2]
        relative = path.relative_to(repo).as_posix() if path.is_relative_to(repo) else None
        return {
            "target": target,
            "qualname": code.co_qualname,
            "source_relative_path": relative,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "code_sha256": hashlib.sha256(code.co_code).hexdigest(),
            "first_line": code.co_firstlineno,
        }

    def close(self) -> None:
        if self._closed:
            return
        if not self._entered:
            self._closed = True
            return
        intact = sys.getprofile() is self._callback
        if intact:
            # Entry required None, so restoring None preserves the previous hook.
            sys.setprofile(None)
        else:
            self._failures.append("PROFILER_CHANGED_DURING_OBSERVATION")
        if self._starts:
            self._failures.append("ACTIVE_TARGET_FRAMES_AT_CLOSE")
        if self._counts["matched_calls"] != self._counts["matched_returns"]:
            self._failures.append("CALL_RETURN_COUNT_MISMATCH")
        self._closed = True
        summary = {
            "observer_version": OBSERVER_VERSION,
            "provenance": "INSTRUMENT_OBSERVED",
            "correlation_id": self.correlation_id,
            "event": "observer_integrity",
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "status": "PASS" if not self._failures else "FAIL",
            "profiler_intact": intact,
            "matched_calls": self._counts["matched_calls"],
            "matched_returns": self._counts["matched_returns"],
            "active_frames_at_close": len(self._starts),
            "coverage": dict(self._counts),
            "failures": list(self._failures),
            "targets": [self._fingerprint(code, name) for code, name in self._targets.items()],
            "limitations": [
                "Profiled wall durations include instrumentation overhead.",
                "None return does not establish an exception type or confirmed nonexecution.",
                "Safe audit fingerprints describe observed bindings and grant no authority.",
                "Buffered observations require successful close for custody; not WORM storage.",
            ],
        }
        assert self._stream is not None
        try:
            for row in [*self._events, summary]:
                self._stream.write(
                    json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
                )
            self._stream.flush()
            os.fsync(self._stream.fileno())
        finally:
            self._stream.close()
            self._events.clear()
            self._starts.clear()

    def flush(self) -> None:
        """Close and preserve buffered observations; subsequent close is a no-op."""
        self.close()
