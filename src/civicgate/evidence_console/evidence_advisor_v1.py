"""Selected-evidence advisory analysis; no execution or authority dependencies.

The existing reader independently rechecks manifest identities and projections.
Model citations are resolved, never promoted to verified semantic conclusions.
Only fixed enum/count/boolean/hash facts leave the selected local evidence view.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .reader import SHA_RE, EvidenceStore, SafeEvidenceError, safe_text, valid_id

if TYPE_CHECKING:
    from .anthropic_advisor_v1 import ProviderConfig, ProviderReply


class _AdvisorProvider(Protocol):
    @property
    def mode(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def config(self) -> ProviderConfig: ...

    def analyze(self, payload: dict[str, Any]) -> ProviderReply: ...


CATEGORIES = {
    "DECISION_CONSISTENCY",
    "BINDING_INTEGRITY",
    "EXECUTION_EVIDENCE",
    "CUSTODY",
    "EVIDENCE_GAP",
    "SCOPE_LIMITATION",
}
KINDS = {"OBSERVED_FACT", "MODEL_INFERENCE", "UNKNOWN"}
SEVERITIES = {"INFO", "LOW", "MEDIUM", "HIGH"}
STATES = {"VERIFIED", "PARTIAL", "UNKNOWN", "OBSERVED"}
DECISIONS = {"PERMIT", "DENY", "REVIEW_REQUIRED"}
SOURCE_NAMES = {
    "audit.jsonl",
    "governance-observations.jsonl",
    "dispatch.jsonl",
    "http-attempts.jsonl",
    "components.jsonl",
    "coordinator.sqlite",
    "returned-summary.json",
    "synthetic-observation-summary.json",
}
LIMITATIONS = [
    "SYNTHETIC_ONLY",
    "NOT_AUTHORITY",
    "HISTORY_NOT_AUTHENTICATED",
    "CITATIONS_DO_NOT_VERIFY_NARRATIVE",
    "CLOSED_IS_NOT_HUMAN_ACCEPTANCE",
    "DURABLE_STOP_PARTIAL",
    "EXTERNAL_EXECUTION_NOT_AUTHORIZED",
]


class AdvisorError(ValueError):
    """A fixed code, without captured data, local paths or exception text."""

    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
        super().__init__(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _enum(value: Any, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 1000 else None


def build_payload(
    run: dict[str, Any], observation: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """No free-form source string is copied into the outbound request."""
    if run.get("integrity") not in {"VERIFIED", "PARTIAL"}:
        raise AdvisorError("ADVISOR_EVIDENCE_UNAVAILABLE", 409)
    if observation.get("integrity") not in {"VERIFIED", "PARTIAL", "UNKNOWN"}:
        raise AdvisorError("ADVISOR_EVIDENCE_UNAVAILABLE", 409)
    sources: list[dict[str, Any]] = []
    local_sources: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    for row in sorted(observation.get("artifacts", []), key=lambda row: row["path"]):
        path = row.get("path")
        if not isinstance(path, str) or path.rsplit("/", 1)[-1] not in SOURCE_NAMES:
            continue
        if not re.fullmatch(
            r"execution/cases/[A-Za-z0-9_-]{1,40}/(?:evidence/)?[A-Za-z0-9_.-]+", path
        ):
            raise AdvisorError("ADVISOR_SOURCE_REFERENCE_INVALID", 409)
        sha, size = row.get("sha256"), row.get("bytes")
        if (
            not isinstance(sha, str)
            or not SHA_RE.fullmatch(sha)
            or type(size) is not int
            or size < 0
        ):
            raise AdvisorError("ADVISOR_SOURCE_REFERENCE_INVALID", 409)
        name = path.rsplit("/", 1)[-1]
        if name in names:
            raise AdvisorError("ADVISOR_SOURCE_REFERENCE_INVALID", 409)
        source: dict[str, Any] = {"id": f"S{len(sources) + 1:03d}", "bytes": size, "sha256": sha}
        sources.append(source)
        names[name] = source["id"]
        # Local-only reference. This path never enters a provider request.
        local_sources.append({**source, "path": path})
    if not sources:
        raise AdvisorError("ADVISOR_EVIDENCE_UNAVAILABLE", 409)
    facts: list[dict[str, Any]] = []

    def add(name: str, value: object, *source_names: str) -> None:
        ids = [names[n] for n in source_names if n in names]
        # A missing source is uncertainty, never an unreferenced verified value.
        facts.append(
            {
                "id": f"F{len(facts) + 1:03d}",
                "name": name,
                "value": value if ids else None,
                "source_ids": ids,
            }
        )

    add("evidence.integrity", _enum(observation.get("integrity"), STATES), *names)
    for field in ("state", "initial_decision", "final_disposition"):
        add(
            "policy." + field,
            _enum(
                observation.get("policy", {}).get(field), STATES if field == "state" else DECISIONS
            ),
            "audit.jsonl",
        )
    judge = observation.get("judge", {})
    add("judge.state", _enum(judge.get("state"), STATES), "audit.jsonl", "coordinator.sqlite")
    add("judge.call_observed", _bool(judge.get("call_observed")), "coordinator.sqlite")
    add("judge.synthetic", _bool(judge.get("synthetic")), "audit.jsonl")
    signal = judge.get("signal")
    add(
        "judge.classification",
        _enum(
            signal.get("classification") if isinstance(signal, dict) else None,
            {
                "IN_SCOPE",
                "OUT_OF_SCOPE",
                "AMBIGUOUS",
                "POSSIBLE_AUTHORITY_OVERREACH",
                "CONSEQUENTIAL_INTERPRETATION",
                "INSUFFICIENT_INFORMATION",
            },
        ),
        "audit.jsonl",
    )
    binding = observation.get("binding", {})
    add("binding.state", _enum(binding.get("state"), STATES), "governance-observations.jsonl")
    for field in ("issued_count", "consumed_count"):
        add("binding." + field, _count(binding.get(field)), "governance-observations.jsonl")
    add(
        "binding.pre_dispatch_verification",
        _enum(
            binding.get("pre_dispatch_verification"),
            {"PASS", "FAIL", "NOT_REQUIRED", "PENDING_PRE_DISPATCH"},
        ),
        "audit.jsonl",
    )
    backend = observation.get("backend", {})
    add("backend.state", _enum(backend.get("state"), STATES), "components.jsonl", "audit.jsonl")
    add("backend.adapter_entries", _count(backend.get("adapter_entries")), "dispatch.jsonl")
    add(
        "backend.mock_transport_attempts",
        _count(backend.get("mock_transport_attempts")),
        "http-attempts.jsonl",
    )
    add(
        "backend.dispatch_state",
        _enum(
            backend.get("dispatch_state"),
            {"REQUEST_CONFIRMED", "NOT_DISPATCHED", "DISPATCH_ATTEMPTED", "DISPATCH_UNKNOWN"},
        ),
        "audit.jsonl",
        "dispatch.jsonl",
    )
    add(
        "backend.response_state",
        _enum(
            backend.get("response_state"), {"RESPONSE_RECEIVED", "NO_RESPONSE", "TRANSPORT_ERROR"}
        ),
        "audit.jsonl",
        "http-attempts.jsonl",
    )
    add(
        "backend.verified_absence",
        _bool(backend.get("verified_absence")),
        "dispatch.jsonl",
        "http-attempts.jsonl",
    )
    result = observation.get("result", {})
    add("result.state", _enum(result.get("state"), STATES), "audit.jsonl")
    add(
        "result.verification_state",
        _enum(
            result.get("verification_state"),
            {"RESULT_VERIFIED", "UNVERIFIED", "RESULT_UNKNOWN", "FAILED_VALIDATION"},
        ),
        "audit.jsonl",
    )
    custody = observation.get("custody", {})
    add("custody.state", _enum(custody.get("state"), STATES), "coordinator.sqlite")
    add(
        "custody.database_state",
        _enum(custody.get("database_state"), {"OPEN", "CLOSED"}),
        "coordinator.sqlite",
    )
    add(
        "custody.returned_close_ack",
        _enum(
            custody.get("returned_close_ack"),
            {"ACKNOWLEDGED", "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"},
        ),
        "returned-summary.json",
    )
    add("custody.restart_preserved", _bool(custody.get("restart_preserved")), "coordinator.sqlite")
    summary_sha = custody.get("persisted_summary_sha256")
    add(
        "custody.summary_sha256",
        summary_sha if isinstance(summary_sha, str) and SHA_RE.fullmatch(summary_sha) else None,
        "synthetic-observation-summary.json",
    )
    return (
        {
            "version": 1,
            "observation_id": "obs-1",
            "integrity": observation["integrity"],
            "facts": facts,
            "sources": sources,
            "limitations": list(LIMITATIONS),
        },
        local_sources,
    )


def _text(value: Any, *, nullable: bool = False, maximum: int = 1500) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
    if any(ord(c) < 32 for c in value) or safe_text(value, maximum) != value:
        raise AdvisorError("ADVISOR_REPORT_UNSAFE", 502)
    # Untrusted output is never markup or a link. Templates/JS also escape it.
    if re.search(
        r"[<>]|(?:file|javascript|data):|(?:^|\s)/(?:[^\s/]+/)+|[A-Za-z]:[\\/]", value, re.I
    ):
        raise AdvisorError("ADVISOR_REPORT_UNSAFE", 502)
    return value


def validate_report(report: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve citations exactly, without claiming narrative truth or authority."""
    if (
        not isinstance(report, dict)
        or set(report) != {"version", "summary", "findings", "limitations"}
        or type(report["version"]) is not int
        or report["version"] != 1
    ):
        raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
    _text(report["summary"])
    if not isinstance(report["limitations"], list) or not 1 <= len(report["limitations"]) <= 10:
        raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
    for value in report["limitations"]:
        _text(value, maximum=500)
    findings = report["findings"]
    if not isinstance(findings, list) or not 1 <= len(findings) <= 12:
        raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
    fact_map = {f["id"]: f for f in payload["facts"]}
    sources = {s["id"] for s in payload["sources"]}
    seen = set()
    fields = {
        "id",
        "category",
        "severity",
        "kind",
        "observation_id",
        "fact_ids",
        "source_ids",
        "explanation",
        "uncertainty",
        "investigation",
    }
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != fields:
            raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
        identity = finding["id"]
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"A[0-9]{3}", identity)
            or identity in seen
        ):
            raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
        seen.add(identity)
        if (
            not _enum(finding["category"], CATEGORIES)
            or not _enum(finding["severity"], SEVERITIES)
            or not _enum(finding["kind"], KINDS)
        ):
            raise AdvisorError("ADVISOR_REPORT_INVALID", 502)
        if finding["observation_id"] != payload["observation_id"]:
            raise AdvisorError("ADVISOR_CITATION_INVALID", 502)
        facts, refs = finding["fact_ids"], finding["source_ids"]
        if (
            not isinstance(facts, list)
            or not isinstance(refs, list)
            or not 1 <= len(facts) <= 25
            or not 1 <= len(refs) <= 8
        ):
            raise AdvisorError("ADVISOR_CITATION_INVALID", 502)
        if any(not isinstance(f, str) or f not in fact_map for f in facts) or any(
            not isinstance(s, str) or s not in sources for s in refs
        ):
            raise AdvisorError("ADVISOR_CITATION_INVALID", 502)
        if len(set(facts)) != len(facts) or len(set(refs)) != len(refs):
            raise AdvisorError("ADVISOR_CITATION_INVALID", 502)
        associated = {s for f in facts for s in fact_map[f]["source_ids"]}
        if set(refs) != associated:
            raise AdvisorError("ADVISOR_CITATION_INVALID", 502)
        if finding["kind"] == "OBSERVED_FACT" and (
            not facts or not refs or any(fact_map[f]["value"] is None for f in facts)
        ):
            raise AdvisorError("ADVISOR_CITATION_INVALID", 502)
        for key in ("explanation", "uncertainty"):
            _text(finding[key])
        _text(finding["investigation"], nullable=True)
    # Return a detached canonical value; providers cannot mutate a published view.
    detached = json.loads(canonical(report))
    # The report above is an object; canonical JSON preserves that outer shape.
    assert isinstance(detached, dict)
    return detached


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_root(path: Path) -> Path:
    if not path.is_absolute() or str(path).startswith(("//", "\\\\")):
        raise AdvisorError("ADVISOR_OUTPUT_INVALID", 503)
    try:
        for part in [*reversed(path.parents), path]:
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise AdvisorError("ADVISOR_OUTPUT_INVALID", 503)
        return path.resolve(strict=True)
    except OSError:
        raise AdvisorError("ADVISOR_OUTPUT_INVALID", 503) from None


def _write_new(path: Path, value: Any) -> None:
    with path.open("xb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


class AdvisorService:
    """One optional mock analysis worker; never imports or calls the Gateway.

    New exclusive output only. Uncertainty blocks later analysis; restarting with
    an existing root is rejected. This is local custody, not exactly-once proof.
    """

    def __init__(
        self,
        store_factory: Callable[[], EvidenceStore],
        provider: _AdvisorProvider,
        output_root: Path,
        *,
        max_jobs: int = 8,
        protected_roots: Iterable[Path | str] = (),
    ) -> None:
        if type(max_jobs) is not int or not 1 <= max_jobs <= 32:
            raise AdvisorError("ADVISOR_LIMIT_INVALID", 503)
        if getattr(provider, "mode", None) != "MOCK_ONLY":
            raise AdvisorError("ADVISOR_LIVE_NOT_AUTHORIZED", 503)
        root = Path(output_root)
        parent = _safe_root(root.parent)
        if root.exists() or not root.is_absolute():
            raise AdvisorError("ADVISOR_FRESH_OUTPUT_REQUIRED", 503)
        root = parent / root.name
        for protected in (Path(__file__).resolve().parents[3], *map(Path, protected_roots)):
            protected = _safe_root(protected)
            if root.is_relative_to(protected) or protected.is_relative_to(root):
                raise AdvisorError("ADVISOR_OUTPUT_OVERLAP", 503)
        self.output_root, self.provider = root, provider
        self._store_factory = store_factory
        self.max_jobs = max_jobs
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._requests: dict[str, str] = {}
        self._active = self._blocked = self._closed = False
        self._thread: threading.Thread | None = None
        try:
            root.mkdir(exist_ok=False)
            _write_new(
                root / "owner.json",
                {
                    "version": 1,
                    "mode": "MOCK_ONLY",
                    "created_at_utc": _now(),
                    "automatic_retry": False,
                    "execution_authority": False,
                    "max_jobs": max_jobs,
                },
            )
        except OSError:
            raise AdvisorError("ADVISOR_CUSTODY_UNCONFIRMED", 503) from None

    def capabilities(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": not self._blocked and not self._closed,
                "mode": "MOCK_ONLY",
                "model": self.provider.model,
                "active": self._active,
                "remaining_jobs": self.max_jobs - len(self._jobs),
                "execution_authority": False,
                "live_api": "NOT_AUTHORIZED",
                "automatic_retry": False,
            }

    @staticmethod
    def _public(job: dict[str, Any]) -> dict[str, Any]:
        detached = json.loads(canonical({k: v for k, v in job.items() if not k.startswith("_")}))
        assert isinstance(detached, dict)
        return detached

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise AdvisorError("ADVISOR_UNKNOWN_ANALYSIS", 404)
            return self._public(self._jobs[job_id])

    def _selection(
        self, run_id: str, observation_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
        try:
            store: EvidenceStore = self._store_factory()
            run = store.get_run(run_id)
            observation = store.get_observation(run_id, observation_id)
            payload, local_sources = build_payload(run, observation)
            # Pin every selected projection plus catalog manifest, not just model fields.
            binding = digest({"manifest": run["manifest_sha256"], "observation": observation})
            return payload, local_sources, binding
        except SafeEvidenceError:
            raise AdvisorError("ADVISOR_OBSERVATION_UNAVAILABLE", 404) from None

    def submit(self, run_id: str, observation_id: str, idempotency_key: str) -> dict[str, Any]:
        if not valid_id(run_id) or not valid_id(observation_id):
            raise AdvisorError("ADVISOR_OBSERVATION_UNAVAILABLE", 404)
        try:
            parsed = uuid.UUID(idempotency_key)
            if parsed.version != 4 or str(parsed) != idempotency_key:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise AdvisorError("ADVISOR_IDEMPOTENCY_REQUIRED") from None
        with self._lock:
            if idempotency_key in self._requests:
                job = self._jobs[self._requests[idempotency_key]]
                if (job["run_id"], job["observation_id"]) != (run_id, observation_id):
                    raise AdvisorError("ADVISOR_IDEMPOTENCY_CONFLICT", 409)
                return self._public(job)
            if self._closed or self._blocked:
                raise AdvisorError("ADVISOR_SESSION_BLOCKED", 503)
            if self._active:
                raise AdvisorError("ADVISOR_BUSY", 409)
            if len(self._jobs) >= self.max_jobs:
                raise AdvisorError("ADVISOR_BUDGET_EXHAUSTED", 429)
            payload, local_sources, binding = self._selection(run_id, observation_id)
            identity = "analysis-" + uuid.uuid4().hex
            job = {
                "id": identity,
                "run_id": run_id,
                "observation_id": observation_id,
                "status": "RUNNING",
                "created_at_utc": _now(),
                "completed_at_utc": None,
                "mode": "MOCK_ONLY",
                "provider": "SYNTHETIC_ANTHROPIC_MESSAGES",
                "model": self.provider.model,
                "integrity": payload["integrity"],
                "request_sha256": digest(payload),
                "evidence_binding_sha256": binding,
                "report": None,
                "error_code": None,
                "reference_validation": "NOT_PERFORMED",
                "sources": [],
                "facts": [],
                "evidence_url": f"/runs/{run_id}/observations/{observation_id}",
                "semantic_verification": "NOT_ESTABLISHED",
                "execution_authority": False,
            }
            self._jobs[identity] = job
            self._requests[idempotency_key] = identity
            self._active = True
            try:
                _write_new(
                    self.output_root / (identity + "-request.json"),
                    {
                        k: job[k]
                        for k in (
                            "id",
                            "run_id",
                            "observation_id",
                            "mode",
                            "model",
                            "created_at_utc",
                            "request_sha256",
                            "evidence_binding_sha256",
                        )
                    },
                )
            except OSError:
                self._blocked, self._active = True, False
                job.update(status="FAILED", error_code="ADVISOR_CUSTODY_UNCONFIRMED")
                raise AdvisorError("ADVISOR_CUSTODY_UNCONFIRMED", 503) from None
            self._thread = threading.Thread(
                target=self._analyze, args=(identity, payload, local_sources, binding), daemon=True
            )
            try:
                self._thread.start()
            except RuntimeError:
                self._blocked, self._active = True, False
                job.update(status="FAILED", error_code="ADVISOR_START_UNCONFIRMED")
                raise AdvisorError("ADVISOR_START_UNCONFIRMED", 503) from None
            return self._public(job)

    def _analyze(
        self,
        identity: str,
        payload: dict[str, Any],
        local_sources: list[dict[str, Any]],
        binding: str,
    ) -> None:
        started = time.monotonic()
        try:
            reply = self.provider.analyze(json.loads(canonical(payload)))
            if reply.model != self.provider.model:
                raise AdvisorError("ADVISOR_MODEL_MISMATCH", 502)
            usage = reply.usage
            if usage is not None and (
                not isinstance(usage, dict)
                or set(usage) != {"input_tokens", "output_tokens"}
                or any(type(v) is not int or not 0 <= v <= 1_000_000 for v in usage.values())
            ):
                raise AdvisorError("ADVISOR_USAGE_INVALID", 502)
            report = validate_report(reply.report, payload)
            with self._lock:
                job = self._jobs[identity]
                if self._closed:
                    raise AdvisorError("ADVISOR_SHUTDOWN_RESULT_UNKNOWN", 503)
                if time.monotonic() - started > self.provider.config.timeout_seconds:
                    raise AdvisorError("ADVISOR_DEADLINE_EXCEEDED", 504)
                current, sources, current_binding = self._selection(
                    job["run_id"], job["observation_id"]
                )
                if (
                    current_binding != binding
                    or canonical(current) != canonical(payload)
                    or sources != local_sources
                ):
                    raise AdvisorError("ADVISOR_EVIDENCE_CHANGED", 409)
                completed = {
                    **job,
                    "status": "COMPLETE",
                    "completed_at_utc": _now(),
                    "report": report,
                    "sources": local_sources,
                    "facts": payload["facts"],
                    "usage": usage,
                    "reference_validation": "RESOLVED_NOT_SEMANTIC_VERIFICATION",
                }
                # Persist before publishing. ACK itself is part of the deadline.
                _write_new(
                    self.output_root / (identity + "-analysis.json"),
                    {**completed, "status": "ANALYSIS_CANDIDATE"},
                )
                if (
                    self._closed
                    or time.monotonic() - started > self.provider.config.timeout_seconds
                ):
                    raise AdvisorError("ADVISOR_DEADLINE_EXCEEDED", 504)
                job.update(completed)
        except Exception as exc:
            # Stable allowlisted codes only; provider exception strings stay private.
            code = getattr(exc, "code", "ADVISOR_ANALYSIS_FAILED")
            if not isinstance(code, str) or not re.fullmatch(r"ADVISOR_[A-Z0-9_]{1,64}", code):
                code = "ADVISOR_ANALYSIS_FAILED"
            with self._lock:
                self._blocked = True
                self._jobs[identity].update(
                    status="FAILED", error_code=code, completed_at_utc=_now(), report=None
                )
                try:
                    _write_new(
                        self.output_root / (identity + "-failure.json"),
                        {
                            "id": identity,
                            "status": "FAILED",
                            "error_code": code,
                            "automatic_retry": False,
                        },
                    )
                except OSError:
                    self._jobs[identity]["error_code"] = "ADVISOR_CUSTODY_UNCONFIRMED"
        finally:
            with self._lock:
                self._active = False

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            if self._active:
                self._blocked = True
        if self._thread is not None:
            self._thread.join(timeout=2)
