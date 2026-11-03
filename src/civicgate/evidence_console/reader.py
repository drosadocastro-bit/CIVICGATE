"""Bounded, manifest-pinned reader for preserved MINI07.1/07.2 evidence.

This module imports no Gateway, provider, planner, evaluation runner or policy.
VERIFIED describes the comparisons here, not authenticated origin or authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
from pathlib import Path, PurePosixPath
from typing import Any

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILES = 1000
MAX_ROWS = 256
MAX_RUNS = 12
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")
DECISIONS = ("PERMIT", "DENY", "REVIEW_REQUIRED")
NODES = ["intake", "discovery", "planner", "gateway", "result"]
TOOLS = {
    "find_federal_awards",
    "get_federal_award",
    "resolve_federal_recipient",
    "summarize_federal_spending",
}
TABLES = (
    "meta",
    "observation_fences",
    "attempts",
    "mcp_calls",
    "liability_reservations",
    "send_leases",
    "response_facts",
)
PROVENANCE_KEYS = (
    "source_system",
    "source_type",
    "retrieved_at",
    "query_fingerprint",
    "response_fingerprint",
    "records_returned",
    "truncated",
)
ARGUMENT_KEYS = {
    "start_date",
    "end_date",
    "state_code",
    "awarding_agency",
    "recipient_name",
    "award_types",
    "limit",
    "award_id",
    "recipient_id",
    "name",
}
RECORD_KEYS = {
    "award_amount",
    "award_id",
    "awarding_agency",
    "generated_internal_id",
    "internal_id",
    "recipient_name",
}


class SafeEvidenceError(ValueError):
    """A stable error code; never carries a filesystem path or captured value."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise SafeEvidenceError(code)


def valid_id(value: object) -> bool:
    return isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def strict_json(raw: bytes) -> Any:
    """No duplicate keys, non-finite numbers or unbounded nesting."""

    def reject_constant(_: str) -> None:
        raise SafeEvidenceError("NONFINITE_JSON")

    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject_constant)
        pending = [(value, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            _require(depth <= 32 and count <= 50_000, "JSON_COMPLEXITY_LIMIT")
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif isinstance(item, float):
                _require(math.isfinite(item), "NONFINITE_JSON")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, SafeEvidenceError):
            raise
        raise SafeEvidenceError("MALFORMED_JSON") from None


def safe_text(value: Any, limit: int = 1000) -> str | None:
    """Defense in depth; only selected fields reach this function."""
    if not isinstance(value, str):
        return None
    value = value[: max(limit * 4, 4096)]
    patterns = (
        r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)",
        r"(?i)\bBearer\s+[^\s,;\"<>]+",
        r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})",
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"""(?i)\b(?:api[_ -]?key|authorization|password|cookie|token)["']?\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;"<>]+)""",
        r"(?i)\b[A-Z]:[\\/][^\s\"<>]+",
        r'\\\\[^\\\s]+\\[^\s"<>]+',
        r"/(?:Users|home|mnt|var|tmp|private|opt|srv|etc|root)/[^\s\"<>]+",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"https?://[^\s\"<>]+",
    )
    for pattern in patterns:
        value = re.sub(pattern, "[REDACTED]", value)
    value = "".join(c for c in value if c in "\n\t" or ord(c) >= 32)
    return value[:limit] + ("…" if len(value) > limit else "")


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, str):
        return safe_text(value, 500)
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:100]]
    return None


def _safe_arguments(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: _safe_value(item) for key, item in value.items() if key in ARGUMENT_KEYS}


def _safe_proposal(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "tool": value.get("tool") if value.get("tool") in TOOLS else "UNKNOWN",
        "arguments": _safe_arguments(value.get("arguments")),
    }


def _no_links(path: Path) -> None:
    """Reject POSIX links and Windows reparse points, including ancestors."""
    _require(path.is_absolute() and not str(path).startswith(("\\\\", "//")), "UNSAFE_ROOT")
    parts = [*reversed(path.parents), path]
    try:
        for item in parts:
            info = item.lstat()
            _require(not stat.S_ISLNK(info.st_mode), "LINK_OR_REPARSE_POINT")
            _require(not getattr(info, "st_file_attributes", 0) & 0x400, "LINK_OR_REPARSE_POINT")
    except OSError:
        raise SafeEvidenceError("EVIDENCE_UNAVAILABLE") from None


def _relative(name: object) -> str:
    _require(isinstance(name, str), "INVALID_MANIFEST_PATH")
    assert isinstance(name, str)
    parsed = PurePosixPath(name)
    _require(0 < len(name) <= 512 and "\\" not in name and ":" not in name, "INVALID_MANIFEST_PATH")
    _require(
        not parsed.is_absolute() and all(p not in {"", ".", ".."} for p in name.split("/")),
        "INVALID_MANIFEST_PATH",
    )
    _require(
        all(p == p.rstrip(" .") and not any(c in p for c in '<>"|?*\x00') for p in name.split("/")),
        "INVALID_MANIFEST_PATH",
    )
    return name


def _read_file(root: Path, name: str, cap: int = MAX_FILE_BYTES) -> bytes:
    path = root / _relative(name)
    _no_links(path)
    _require(path.resolve().is_relative_to(root.resolve()), "PATH_ESCAPE")
    try:
        before = path.stat()
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= cap, "FILE_SIZE_LIMIT")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        handle = os.open(path, flags)
        with os.fdopen(handle, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(
                (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
                "EVIDENCE_CHANGED_DURING_READ",
            )
            raw = stream.read(cap + 1)
            after = os.fstat(stream.fileno())
        _require(len(raw) <= cap and after.st_size == len(raw), "FILE_SIZE_LIMIT")
        _require(
            (opened.st_size, opened.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            "EVIDENCE_CHANGED_DURING_READ",
        )
        _no_links(path)
        return raw
    except OSError:
        raise SafeEvidenceError("EVIDENCE_UNAVAILABLE") from None


class _Snapshot:
    def __init__(self, root: Path, expected: str):
        self.root = root
        manifest_raw = _read_file(root, "RUN_SHA256_MANIFEST.json", MAX_MANIFEST_BYTES)
        _require(sha256(manifest_raw) == expected, "MANIFEST_DIGEST_MISMATCH")
        manifest = strict_json(manifest_raw)
        _require(
            isinstance(manifest, dict) and manifest.get("self_excluded") is True, "INVALID_MANIFEST"
        )
        rows = manifest.get("files")
        _require(isinstance(rows, list) and 0 < len(rows) <= MAX_FILES, "MANIFEST_LIMIT")
        self.files: dict[str, bytes] = {}
        self.rows: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        total = 0
        for row in rows:
            _require(
                isinstance(row, dict) and set(row) == {"path", "bytes", "sha256"},
                "INVALID_MANIFEST_ENTRY",
            )
            name = _relative(row["path"])
            _require(
                name.casefold() not in seen and name != "RUN_SHA256_MANIFEST.json",
                "DUPLICATE_MANIFEST_PATH",
            )
            seen.add(name.casefold())
            _require(
                type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_FILE_BYTES, "FILE_SIZE_LIMIT"
            )
            _require(
                isinstance(row["sha256"], str) and SHA_RE.fullmatch(row["sha256"]) is not None,
                "INVALID_DIGEST",
            )
            total += row["bytes"]
            _require(total <= MAX_TOTAL_BYTES, "TOTAL_SIZE_LIMIT")
            raw = _read_file(root, name)
            _require(
                len(raw) == row["bytes"] and sha256(raw) == row["sha256"],
                "ARTIFACT_DIGEST_MISMATCH",
            )
            self.files[name] = raw
            self.rows[name] = row

    def raw(self, name: str) -> bytes:
        _require(name in self.files, "MISSING_PRIMARY_EVIDENCE")
        return self.files[name]

    def json(self, name: str) -> Any:
        return strict_json(self.raw(name))

    def rows_json(self, name: str) -> list[dict[str, Any]]:
        lines = self.raw(name).splitlines()
        _require(len(lines) <= MAX_ROWS, "ROW_LIMIT")
        values = [strict_json(line) for line in lines]
        _require(all(isinstance(row, dict) for row in values), "INVALID_JSONL")
        return values


def _one(rows: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any]:
    matches = [row for row in rows if row.get(key) == value]
    _require(len(matches) == 1, "PRIMARY_CARDINALITY_MISMATCH")
    return matches[0]


def _sqlite(snapshot: _Snapshot, prefix: str) -> dict[str, Any]:
    name = prefix + "coordinator.sqlite"
    database = snapshot.root / name
    for suffix in ("-wal", "-shm", "-journal"):
        _require(
            not database.with_name(database.name + suffix).exists(), "UNSTABLE_SQLITE_SNAPSHOT"
        )
    _no_links(database)
    _require(_read_file(snapshot.root, name) == snapshot.raw(name), "EVIDENCE_CHANGED_DURING_READ")
    try:
        with sqlite3.connect(
            database.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=0.1
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_MANIFEST_BYTES)
            conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 4096)
            ticks = 0

            def progress() -> int:
                nonlocal ticks
                ticks += 1
                return int(ticks > 500)

            conn.set_progress_handler(progress, 1000)
            _require(
                conn.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok", "SQLITE_INTEGRITY"
            )
            result: dict[str, Any] = {}
            for table in TABLES:
                schema = conn.execute(
                    "SELECT type,sql FROM sqlite_schema WHERE name=?", (table,)
                ).fetchone()
                _require(
                    schema is not None
                    and schema["type"] == "table"
                    and "VIRTUAL" not in schema["sql"].upper(),
                    "UNSUPPORTED_SQLITE_SCHEMA",
                )
                rows = conn.execute(
                    "SELECT * FROM " + table + " ORDER BY rowid LIMIT 257"
                ).fetchall()
                _require(len(rows) <= MAX_ROWS, "ROW_LIMIT")
                result[table] = [dict(row) for row in rows]
    except sqlite3.Error:
        raise SafeEvidenceError("SQLITE_UNAVAILABLE") from None
    _require(_read_file(snapshot.root, name) == snapshot.raw(name), "EVIDENCE_CHANGED_DURING_READ")
    recorded = snapshot.json(prefix + "sqlite-readonly-before-restart.json")
    _require(
        recorded.get("database_sha256") == sha256(snapshot.raw(name))
        and recorded.get("integrity_check") == "ok"
        and recorded.get("tables") == result,
        "SQLITE_RECORD_CONTRADICTION",
    )
    return result


def _unknown_observation(
    run_id: str, capture_id: str, case: str, observation_id: str
) -> dict[str, Any]:
    return {
        "id": observation_id,
        "run_id": run_id,
        "capture_id": capture_id,
        "case": case,
        "budget_run_id": None,
        "gateway_request_id": None,
        "integrity": "UNKNOWN",
        "issues": [],
        "request": {"state": "UNKNOWN", "original_request": None, "sha256": None},
        "proposal": {"state": "UNKNOWN", "planner": None, "effective": None},
        "graph": {"state": "UNKNOWN", "visited_nodes": None, "node_entries": None, "status": None},
        "discovery": {"state": "UNKNOWN", "tools": None},
        "policy": {
            "state": "UNKNOWN",
            "initial_decision": None,
            "final_disposition": None,
            "reasons": None,
        },
        "judge": {"state": "UNKNOWN", "signal": None, "call_observed": None, "synthetic": True},
        "binding": {
            "state": "UNKNOWN",
            "issued_count": None,
            "consumed_count": None,
            "identities": None,
            "pre_dispatch_verification": None,
        },
        "backend": {
            "state": "UNKNOWN",
            "adapter_entries": None,
            "mock_transport_attempts": None,
            "dispatch_state": None,
            "response_state": None,
            "verified_absence": None,
        },
        "result": {
            "state": "UNKNOWN",
            "verification_state": None,
            "validation_lane": None,
            "validation_reason": None,
            "value": None,
            "provenance": None,
        },
        "custody": {
            "state": "UNKNOWN",
            "database_state": None,
            "opened_at_utc": None,
            "closed_at_utc": None,
            "persisted_summary_sha256": None,
            "persisted_summary_close_field": None,
            "returned_close_ack": None,
            "restart_preserved": None,
            "meaning": "DOCUMENTARY_CUSTODY_NOT_HUMAN_ACCEPTANCE",
        },
        "artifacts": [],
        "limitations": {
            "synthetic_only": True,
            "real_model_identity": "UNKNOWN",
            "live_execution": "HOLD",
            "durable_stop": "PARTIAL",
            "faa_definitions": "54_BLOCKED_SKIP",
            "origin_authentication": "NOT_ESTABLISHED",
            "os_isolation": "NOT_ESTABLISHED",
        },
    }


def _project(
    snapshot: _Snapshot, run_id: str, prefix: str, observation_id: str, view: dict[str, Any]
) -> dict[str, Any]:
    issues = view["issues"]
    returned = snapshot.json(prefix + "returned-summary.json")
    config = snapshot.json(prefix + "evidence/synthetic-http-worker-config.json")
    scenario = snapshot.json(prefix + "scenario.json")
    _require(
        returned.get("observation_id") == config.get("observation_id") == observation_id,
        "OBSERVATION_CORRELATION_MISMATCH",
    )
    _require(
        scenario.get("synthetic") is True
        and config.get("mode") == "SYNTHETIC_SOCKET_ONLY_NO_LIVE_AUTHORIZATION",
        "NON_SYNTHETIC_EVIDENCE",
    )
    _require(valid_id(config.get("run_id")), "INVALID_RUN_ID")
    view["budget_run_id"] = config["run_id"]
    audit = snapshot.rows_json(prefix + "evidence/audit.jsonl")
    proposal = _one(audit, "stage", "proposal")
    policy = _one(audit, "stage", "policy")
    completed = _one(audit, "stage", "completed")
    envelope = completed.get("response")
    _require(
        isinstance(envelope, dict) and envelope == returned.get("observed_envelope"),
        "ENVELOPE_CONTRADICTION",
    )
    request_id = envelope.get("request_id")
    _require(
        envelope.get("governance", {}).get("authority_source") == "DETERMINISTIC_POLICY_GATE",
        "AUTHORITY_SOURCE_CONTRADICTION",
    )
    _require(
        valid_id(request_id) and all(row.get("request_id") == request_id for row in audit),
        "REQUEST_CORRELATION_MISMATCH",
    )
    view["gateway_request_id"] = request_id
    request = proposal.get("user_request")
    _require(
        isinstance(request, str) and request == scenario.get("scenario", {}).get("request"),
        "ORIGINAL_REQUEST_CONTRADICTION",
    )
    request_hash = sha256(request.encode())
    view["request"] = {
        "state": "VERIFIED",
        "original_request": safe_text(request, 4000),
        "sha256": request_hash,
        "human_identity_authentication": "NOT_ESTABLISHED",
    }
    effective = proposal.get("proposal")
    _require(
        isinstance(effective, dict)
        and effective.get("tool") in TOOLS
        and envelope.get("tool") == effective.get("tool"),
        "TOOL_CORRELATION_MISMATCH",
    )
    initial = policy.get("policy", {}).get("decision")
    final = envelope.get("decision")
    _require(
        initial in DECISIONS and final in DECISIONS and returned.get("decision") == final,
        "POLICY_CONTRADICTION",
    )
    reasons = policy.get("policy", {}).get("reasons")
    _require(
        isinstance(reasons, list)
        and len(reasons) <= 20
        and all(isinstance(x, str) for x in reasons),
        "INVALID_POLICY_REASON",
    )
    view["policy"] = {
        "state": "VERIFIED",
        "initial_decision": initial,
        "final_disposition": final,
        "reasons": [safe_text(x, 200) for x in reasons],
        "authority_source": "DETERMINISTIC_POLICY_GATE",
    }
    # These graph facts are never reconstructed from graph_status=COMPLETED.
    if prefix + "a2-events.jsonl" in snapshot.files:
        try:
            graph = snapshot.json(prefix + "a2-orchestration-result.json")
            client = snapshot.json(prefix + "a2-mcp-client-input.json")
            events = snapshot.rows_json(prefix + "a2-events.jsonl")
            nodes = [row for row in events if row.get("event") == "A2_NODE_ENTERED"]
            _require(
                [row.get("node") for row in nodes] == graph.get("visited_nodes") == NODES
                and [row.get("ordinal") for row in nodes] == list(range(1, 6))
                and all(type(row.get("ordinal")) is int for row in nodes),
                "GRAPH_HISTORY_CONTRADICTION",
            )
            _require(
                graph.get("context")
                == {"original_request": request, "request_sha256": request_hash}
                and all(
                    row.get("original_request") == request
                    and row.get("request_sha256") == request_hash
                    for row in nodes
                ),
                "GRAPH_CONTEXT_CONTRADICTION",
            )
            _require(
                client.get("request") == request
                and client.get("proposal") == strict_json(nodes[3]["proposal_json"].encode()),
                "PLANNER_PROPOSAL_CONTRADICTION",
            )
            _require(
                client["proposal"]["tool"] == effective["tool"]
                and all(
                    effective["arguments"].get(k) == v
                    for k, v in client["proposal"]["arguments"].items()
                ),
                "EFFECTIVE_PROPOSAL_CONTRADICTION",
            )
            view["graph"] = {
                "state": "VERIFIED",
                "visited_nodes": NODES.copy(),
                "status": safe_text(graph.get("status"), 80),
                "node_entries": [
                    {
                        "node": row["node"],
                        "ordinal": row["ordinal"],
                        "observed_at_utc": safe_text(row.get("observed_at_utc"), 80),
                        "parent_monotonic_ns": row.get("parent_monotonic_ns")
                        if type(row.get("parent_monotonic_ns")) is int
                        else None,
                    }
                    for row in nodes
                ],
            }
            view["proposal"] = {
                "state": "VERIFIED",
                "planner": _safe_proposal(client["proposal"]),
                "effective": _safe_proposal(effective),
            }
        except (SafeEvidenceError, KeyError, TypeError, AttributeError) as exc:
            issues.append(
                exc.code if isinstance(exc, SafeEvidenceError) else "MALFORMED_GRAPH_EVIDENCE"
            )
    else:
        issues.append("GRAPH_HISTORY_NOT_AVAILABLE")
        view["proposal"] = {
            "state": "OBSERVED",
            "planner": None,
            "effective": _safe_proposal(effective),
        }
    tools = snapshot.json(prefix + "mcp-tools-list.json").get("tools")
    _require(
        isinstance(tools, list) and len(tools) == 4 and {row.get("name") for row in tools} == TOOLS,
        "DISCOVERY_CONTRADICTION",
    )
    view["discovery"] = {"state": "VERIFIED", "tools": sorted(TOOLS), "grants_authority": False}
    observations = snapshot.rows_json(prefix + "evidence/governance-observations.jsonl")
    observer = _one(observations, "event", "observer_integrity")
    _require(
        observer.get("status") == "PASS"
        and observer.get("profiler_intact") is True
        and observer.get("failures") == []
        and observer.get("active_frames_at_close") == 0,
        "OBSERVER_INTEGRITY_UNKNOWN",
    )
    _require(
        all(row.get("correlation_id") == observation_id for row in observations),
        "GOVERNANCE_CORRELATION_MISMATCH",
    )
    issued = [row for row in observations if row.get("status") == "ISSUED"]
    consumed = [row for row in observations if row.get("status") == "VERIFIED_CONSUMED"]
    _require(type(policy.get("binding_issued")) is bool, "INVALID_BINDING_ISSUANCE_TYPE")
    _require(
        len(issued) == len(consumed) == int(policy.get("binding_issued") is True),
        "BINDING_COUNT_CONTRADICTION",
    )
    if issued:
        _require(
            initial == "PERMIT"
            and len(issued) == 1
            and issued[0].get("binding") == consumed[0].get("binding")
            and type(issued[0].get("call_index")) is int
            and type(consumed[0].get("call_index")) is int
            and issued[0].get("call_index", 0) < consumed[0].get("call_index", 0),
            "BINDING_CONTRADICTION",
        )
        binding = issued[0]["binding"]
        _require(
            binding.get("request_id") == request_id
            and binding.get("tool") == effective["tool"]
            and SHA_RE.fullmatch(binding.get("binding_sha256", "")) is not None,
            "BINDING_CORRELATION_MISMATCH",
        )
        for key in (
            "binding_sha256",
            "arguments_sha256",
            "schema_sha256",
            "policy_sha256",
            "policy_facts_sha256",
            "policy_context_sha256",
        ):
            _require(
                isinstance(binding.get(key), str) and SHA_RE.fullmatch(binding[key]) is not None,
                "INVALID_BINDING_DIGEST",
            )
        canonical_arguments = json.dumps(
            effective["arguments"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        _require(
            binding["arguments_sha256"] == sha256(canonical_arguments.encode()),
            "BINDING_ARGUMENTS_CONTRADICTION",
        )
        binding_body = {key: value for key, value in binding.items() if key != "binding_sha256"}
        binding_body["arguments_json"] = canonical_arguments
        _require(
            binding["binding_sha256"]
            == sha256(
                json.dumps(
                    binding_body,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ),
            "BINDING_DIGEST_CONTRADICTION",
        )
    else:
        _require(initial != "PERMIT", "MISSING_PERMIT_BINDING")
    _require(
        type(returned.get("binding_issuances")) is int
        and type(returned.get("binding_consumptions")) is int
        and returned.get("binding_issuances") == len(issued)
        and returned.get("binding_consumptions") == len(consumed),
        "BINDING_SUMMARY_CONTRADICTION",
    )
    view["binding"] = {
        "state": "VERIFIED",
        "issued_count": len(issued),
        "consumed_count": len(consumed),
        "identities": [
            {
                key: row["binding"].get(key)
                for key in ("binding_sha256", "arguments_sha256", "schema_sha256", "policy_sha256")
            }
            for row in issued
        ],
        "pre_dispatch_verification": safe_text(completed.get("pre_dispatch_verification"), 80),
    }
    dispatch = snapshot.rows_json(prefix + "evidence/dispatch.jsonl")
    http = snapshot.rows_json(prefix + "evidence/http-attempts.jsonl")
    components = snapshot.rows_json(prefix + "evidence/components.jsonl")
    _require(
        all(
            row.get("phase") == "entered" and row.get("synthetic") is True
            for row in dispatch + http
        ),
        "BACKEND_CHANNEL_CONTRADICTION",
    )
    _require(
        type(returned.get("adapter_entries")) is int
        and type(returned.get("mock_backend_attempts")) is int
        and len(dispatch) == returned.get("adapter_entries")
        and len(http) == returned.get("mock_backend_attempts"),
        "BACKEND_COUNT_CONTRADICTION",
    )
    _require(
        len(dispatch) == len(http) == len(consumed)
        and envelope.get("tool_executed") is bool(dispatch)
        and completed.get("tool_executed") is bool(dispatch)
        and type(envelope.get("attempt_count")) is int
        and envelope.get("attempt_count") == len(http),
        "DISPATCH_BINDING_CONTRADICTION",
    )
    if dispatch:
        _require(
            completed.get("pre_dispatch_verification") == "PASS"
            and dispatch[0].get("query") == effective["arguments"]
            and envelope.get("dispatch_state") == "REQUEST_CONFIRMED",
            "DISPATCH_SCOPE_CONTRADICTION",
        )
        _require(
            len(components) == 2
            and {row.get("component") for row in components} == {"adapter", "synthetic_http"}
            and all(
                row.get("error_class") is None
                and row.get("synthetic") is True
                and row.get("phase") == "finish"
                for row in components
            ),
            "BACKEND_RESULT_CONTRADICTION",
        )
        _require(
            effective["tool"] == "find_federal_awards"
            and dispatch[0].get("method") == "search"
            and http[0].get("method") == "POST"
            and http[0].get("request_path") == "/api/v2/search/spending_by_award/",
            "UNSUPPORTED_OBSERVED_BACKEND_CONTRACT",
        )
        _require(
            _one(components, "component", "synthetic_http").get("status_code") == 200,
            "BACKEND_HTTP_CONTRADICTION",
        )
        attempts = completed.get("attempts")
        _require(isinstance(attempts, list) and len(attempts) == 1, "TERMINAL_ATTEMPT_UNKNOWN")
        attempt = attempts[0]
        _require(
            isinstance(attempt, dict)
            and type(attempt.get("attempt")) is int
            and attempt.get("attempt") == 1
            and type(attempt.get("max_attempts")) is int
            and attempt.get("max_attempts") == 1
            and attempt.get("exception_type") is None
            and attempt.get("response_received") is True
            and type(attempt.get("status_code")) is int
            and attempt.get("status_code") == 200
            and attempt.get("retry_decision") == "NONE"
            and attempt.get("retry_reason") == "success"
            and attempt.get("dispatch_state") == "REQUEST_CONFIRMED"
            and attempt.get("response_state") == "RESPONSE_RECEIVED",
            "TERMINAL_ATTEMPT_CONTRADICTION",
        )
    else:
        _require(
            not components
            and envelope.get("dispatch_state") == "NOT_DISPATCHED"
            and completed.get("attempts") == []
            and envelope.get("response_state") == "NO_RESPONSE"
            and envelope.get("verification_state") == "UNVERIFIED"
            and envelope.get("result") is None
            and envelope.get("provenance") is None,
            "NONDISPATCH_CONTRADICTION",
        )
    view["backend"] = {
        "state": "VERIFIED",
        "adapter_entries": len(dispatch),
        "mock_transport_attempts": len(http),
        "dispatch_state": safe_text(envelope.get("dispatch_state"), 80),
        "response_state": safe_text(envelope.get("response_state"), 80),
        "verified_absence": not dispatch,
    }
    value = envelope.get("result")
    provenance = envelope.get("provenance")
    if envelope.get("verification_state") == "RESULT_VERIFIED":
        _require(
            isinstance(value, dict)
            and isinstance(value.get("records"), list)
            and isinstance(provenance, dict)
            and provenance.get("source_type") == "SYNTHETIC_TEST_FIXTURE"
            and provenance.get("source_system") == "CIVICGATE_TEST_FIXTURE",
            "RESULT_SOURCE_CONTRADICTION",
        )
        result_value = {
            "records": [
                {k: _safe_value(v) for k, v in row.items() if k in RECORD_KEYS}
                for row in value["records"][:100]
                if isinstance(row, dict)
            ]
        }
        result_provenance = {k: _safe_value(provenance.get(k)) for k in PROVENANCE_KEYS}
    else:
        result_value = None
        result_provenance = None
    view["result"] = {
        "state": "OBSERVED",
        "verification_state": safe_text(envelope.get("verification_state"), 80),
        "validation_lane": safe_text(envelope.get("validation_lane"), 80),
        "validation_reason": safe_text(envelope.get("validation_reason"), 120),
        "value": result_value,
        "provenance": result_provenance,
    }
    try:
        tables = _sqlite(snapshot, prefix)
        _require(
            len(tables["meta"]) == 1 and tables["meta"][0].get("run_id") == config["run_id"],
            "DATABASE_RUN_CONTRADICTION",
        )
        fence = _one(tables["observation_fences"], "observation_id", observation_id)
        _require(fence.get("state") in {"OPEN", "CLOSED"}, "INVALID_CUSTODY_STATE")
        saved_raw = snapshot.raw(prefix + "evidence/synthetic-observation-summary.json")
        saved = strict_json(saved_raw)
        _require(fence.get("summary_sha256") == sha256(saved_raw), "CUSTODY_SUMMARY_CONTRADICTION")
        restart = snapshot.json(prefix + "preservation-and-restart.json")
        receipt = snapshot.json(prefix + "restart-result.json")
        _require(
            restart.get("database_unchanged") is True
            and receipt.get("state_unchanged") is True
            and receipt.get("new_admission_or_dispatch_performed") is False,
            "RESTART_CUSTODY_UNKNOWN",
        )
        view["custody"] = {
            "state": "VERIFIED",
            "database_state": fence["state"],
            "opened_at_utc": safe_text(fence.get("opened_at_utc"), 80),
            "closed_at_utc": safe_text(fence.get("closed_at_utc"), 80),
            "persisted_summary_sha256": fence.get("summary_sha256"),
            "persisted_summary_close_field": safe_text(saved.get("fence_close"), 120),
            "returned_close_ack": safe_text(returned.get("fence_close"), 120),
            "restart_preserved": True,
            "meaning": "DOCUMENTARY_CUSTODY_NOT_HUMAN_ACCEPTANCE",
        }
        judge_attempts = [
            row
            for row in tables["attempts"]
            if row.get("role") == "judge" and row.get("observation_id") == observation_id
        ]
        _require(len(judge_attempts) <= 1, "JUDGE_ATTEMPT_CONTRADICTION")
        judge = policy.get("judge")
        _require(isinstance(judge, dict), "MISSING_JUDGE_RECORD")
        judge_capture = snapshot.json(prefix + "evidence/worker-http-evidence.json")
        judge_receipts = judge_capture.get("server_receipts")
        _require(
            isinstance(judge_receipts, list) and len(judge_receipts) == len(judge_attempts),
            "JUDGE_CALL_EVIDENCE_CONTRADICTION",
        )
        if judge_attempts:
            reservation = strict_json(judge_attempts[0]["reservation_json"].encode())
            request_digest = reservation.get("request_sha256")
            _require(
                isinstance(request_digest, str)
                and SHA_RE.fullmatch(request_digest) is not None
                and judge_receipts[0].get("request_sha256") == request_digest
                and judge_receipts[0].get("body_received") is True,
                "JUDGE_RECEIPT_CORRELATION_MISMATCH",
            )
        view["judge"] = {
            "state": "OBSERVED",
            "synthetic": True,
            "signal": {
                k: _safe_value(judge.get(k))
                for k in ("available", "classification", "confidence", "flags", "rationale")
            },
            "call_observed": bool(judge_attempts),
            "call_evidence": "COORDINATOR_ATTEMPT_AND_MATCHING_SYNTHETIC_SERVER_RECEIPT",
        }
    except (SafeEvidenceError, KeyError, TypeError, AttributeError) as exc:
        issues.append(
            exc.code if isinstance(exc, SafeEvidenceError) else "MALFORMED_CUSTODY_EVIDENCE"
        )
    view["integrity"] = "PARTIAL" if issues else "VERIFIED"
    return view


class EvidenceStore:
    """Explicit operator catalog, refreshed and rehashed for every read."""

    def __init__(self, config_entries: list[dict[str, Any]]):
        _require(
            isinstance(config_entries, list) and len(config_entries) <= MAX_RUNS, "INVALID_CATALOG"
        )
        self._entries: dict[str, dict[str, Any]] = {}
        for entry in config_entries:
            _require(
                isinstance(entry, dict) and set(entry) == {"id", "root", "manifest_sha256"},
                "INVALID_CATALOG",
            )
            _require(
                valid_id(entry["id"]) and entry["id"] not in self._entries, "INVALID_CATALOG_ID"
            )
            _require(isinstance(entry["root"], (str, Path)), "INVALID_CATALOG_ROOT")
            root = Path(entry["root"])
            _require(
                root.is_absolute() and not str(root).startswith(("\\\\", "//")),
                "INVALID_CATALOG_ROOT",
            )
            _require(
                isinstance(entry["manifest_sha256"], str)
                and SHA_RE.fullmatch(entry["manifest_sha256"]) is not None,
                "INVALID_CATALOG_DIGEST",
            )
            self._entries[entry["id"]] = {"root": root, "manifest_sha256": entry["manifest_sha256"]}

    def _run(self, run_id: str) -> dict[str, Any]:
        if not valid_id(run_id) or run_id not in self._entries:
            raise SafeEvidenceError("UNKNOWN_RUN")
        entry = self._entries[run_id]
        result: dict[str, Any] = {
            "id": run_id,
            "capture_id": safe_text(entry["root"].name, 96),
            "integrity": "UNKNOWN",
            "issues": [],
            "manifest_sha256": entry["manifest_sha256"],
            "artifact_count": None,
            "observations": [],
            "distribution": dict.fromkeys((*DECISIONS, "UNKNOWN"), 0),
            "inventory_scope": "PINNED_MANIFEST_LISTED_FILES_ONLY",
            "_details": {},
        }
        try:
            snapshot = _Snapshot(entry["root"], entry["manifest_sha256"])
            result["artifact_count"] = len(snapshot.files)
            prefixes = sorted(
                {
                    name.rsplit("/", 1)[0] + "/"
                    for name in snapshot.files
                    if re.fullmatch(r"execution/cases/[A-Za-z0-9_-]{1,40}/scenario\.json", name)
                }
            )
            _require(0 < len(prefixes) <= 32, "NO_BOUNDED_OBSERVATIONS")
            for prefix in prefixes:
                case = prefix.split("/")[2]
                configuration = snapshot.json(prefix + "evidence/synthetic-http-worker-config.json")
                observation_id = configuration.get("observation_id")
                _require(
                    valid_id(observation_id) and observation_id not in result["_details"],
                    "INVALID_OBSERVATION_ID",
                )
                observation = _unknown_observation(
                    run_id, result["capture_id"], case, observation_id
                )
                try:
                    observation = _project(snapshot, run_id, prefix, observation_id, observation)
                except (SafeEvidenceError, KeyError, TypeError, AttributeError) as exc:
                    observation["issues"].append(
                        exc.code
                        if isinstance(exc, SafeEvidenceError)
                        else "MALFORMED_PRIMARY_EVIDENCE"
                    )
                    observation["integrity"] = (
                        "PARTIAL" if observation["policy"]["state"] == "VERIFIED" else "UNKNOWN"
                    )
                observation["artifacts"] = [
                    dict(row)
                    for name, row in snapshot.rows.items()
                    if name.startswith(prefix)
                    and name.rsplit("/", 1)[-1]
                    in {
                        "audit.jsonl",
                        "governance-observations.jsonl",
                        "dispatch.jsonl",
                        "http-attempts.jsonl",
                        "components.jsonl",
                        "coordinator.sqlite",
                        "a2-events.jsonl",
                        "a2-orchestration-result.json",
                        "returned-summary.json",
                        "synthetic-observation-summary.json",
                        "mcp-tools-list.json",
                    }
                ]
                result["_details"][observation_id] = observation
                decision = observation["policy"]["final_disposition"]
                result["distribution"][decision if decision in DECISIONS else "UNKNOWN"] += 1
                result["observations"].append(
                    {
                        "id": observation_id,
                        "case": case,
                        "decision": decision or "UNKNOWN",
                        "integrity": observation["integrity"],
                        "custody_state": observation["custody"]["database_state"],
                        "policy": observation["policy"],
                    }
                )
            result["integrity"] = "VERIFIED"
            if any(row["integrity"] != "VERIFIED" for row in result["observations"]):
                result["integrity"] = "PARTIAL"
        except (SafeEvidenceError, KeyError, TypeError, AttributeError) as exc:
            result["issues"] = [
                exc.code if isinstance(exc, SafeEvidenceError) else "MALFORMED_EVIDENCE"
            ]
            result["observations"] = []
            result["_details"] = {}
            result["distribution"] = dict.fromkeys((*DECISIONS, "UNKNOWN"), None)
        return result

    def list_runs(self) -> list[dict[str, Any]]:
        return [self.get_run(run_id) for run_id in self._entries]

    def get_run(self, run_id: str) -> dict[str, Any]:
        value = self._run(run_id)
        value.pop("_details")
        return value

    def get_observation(self, run_id: str, observation_id: str) -> dict[str, Any]:
        if not valid_id(observation_id):
            raise SafeEvidenceError("UNKNOWN_OBSERVATION")
        run = self._run(run_id)
        if observation_id not in run["_details"]:
            raise SafeEvidenceError("UNKNOWN_OBSERVATION")
        return run["_details"][observation_id]
