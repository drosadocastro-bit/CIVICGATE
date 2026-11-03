"""Synthetic documentary fixtures: no Gateway, provider or MCP invocation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from civicgate.evidence_console.reader import (
    NODES,
    TABLES,
    TOOLS,
    EvidenceStore,
    SafeEvidenceError,
    safe_text,
    strict_json,
)


def put(root: Path, name: str, value: object) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")


def jsonl(root: Path, name: str, rows: list[dict]) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def seal(root: Path) -> str:
    entries = [
        {
            "path": p.relative_to(root).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": digest(p.read_bytes()),
        }
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "RUN_SHA256_MANIFEST.json"
    ]
    put(root, "RUN_SHA256_MANIFEST.json", {"self_excluded": True, "files": entries})
    return digest((root / "RUN_SHA256_MANIFEST.json").read_bytes())


def fixture_run(root: Path, decision: str = "PERMIT", *, graph: bool = True) -> Path:
    root.mkdir()
    prefix = "execution/cases/example/"
    case = root / prefix
    obs, request_id, run_id = "SYNTHETIC_OBSERVATION", "synthetic-request", "SYNTHETIC_BUDGET"
    request = "Show public federal awards."
    arguments = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}
    proposal = {"tool": "find_federal_awards", "arguments": arguments}
    permit = decision == "PERMIT"
    result = (
        {
            "records": [
                {"award_id": "SYNTHETIC-1", "recipient_name": "EXAMPLE", "award_amount": "12.34"}
            ]
        }
        if permit
        else None
    )
    provenance = (
        {
            "source_system": "CIVICGATE_TEST_FIXTURE",
            "source_type": "SYNTHETIC_TEST_FIXTURE",
            "retrieved_at": "2026-11-01T00:00:00Z",
            "query_fingerprint": "a" * 64,
            "response_fingerprint": "b" * 64,
            "records_returned": 1,
            "truncated": False,
        }
        if permit
        else None
    )
    envelope = {
        "request_id": request_id,
        "tool": proposal["tool"],
        "decision": decision,
        "governance": {"authority_source": "DETERMINISTIC_POLICY_GATE"},
        "tool_executed": permit,
        "attempt_count": int(permit),
        "dispatch_state": "REQUEST_CONFIRMED" if permit else "NOT_DISPATCHED",
        "response_state": "RESPONSE_RECEIVED" if permit else "NO_RESPONSE",
        "result": result,
        "provenance": provenance,
        "verification_state": "RESULT_VERIFIED" if permit else "UNVERIFIED",
        "validation_lane": "NONE",
        "validation_reason": "NONE",
    }
    returned = {
        "observation_id": obs,
        "decision": decision,
        "observed_envelope": envelope,
        "adapter_entries": int(permit),
        "mock_backend_attempts": int(permit),
        "binding_issuances": int(permit),
        "binding_consumptions": int(permit),
        "fence_close": "ACKNOWLEDGED",
    }
    put(root, prefix + "returned-summary.json", returned)
    put(root, prefix + "scenario.json", {"synthetic": True, "scenario": {"request": request}})
    put(
        root,
        prefix + "evidence/synthetic-http-worker-config.json",
        {
            "observation_id": obs,
            "run_id": run_id,
            "mode": "SYNTHETIC_SOCKET_ONLY_NO_LIVE_AUTHORIZATION",
        },
    )
    policy = {
        "request_id": request_id,
        "stage": "policy",
        "policy": {"decision": decision, "reasons": ["SYNTHETIC_REASON"]},
        "binding_issued": permit,
        "judge": {
            "available": decision != "DENY",
            "classification": "IN_SCOPE",
            "confidence": 0.99,
            "flags": [],
            "rationale": "Synthetic advisory only.",
        },
    }
    jsonl(
        root,
        prefix + "evidence/audit.jsonl",
        [
            {
                "stage": "proposal",
                "request_id": request_id,
                "user_request": request,
                "proposal": proposal,
            },
            policy,
            {
                "stage": "completed",
                "request_id": request_id,
                "response": envelope,
                "tool_executed": permit,
                "pre_dispatch_verification": "PASS" if permit else "NOT_REQUIRED",
                "attempts": [
                    {
                        "attempt": 1,
                        "max_attempts": 1,
                        "exception_type": None,
                        "response_received": True,
                        "status_code": 200,
                        "retry_decision": "NONE",
                        "retry_reason": "success",
                        "dispatch_state": "REQUEST_CONFIRMED",
                        "response_state": "RESPONSE_RECEIVED",
                    }
                ]
                if permit
                else [],
            },
        ],
    )
    canonical_arguments = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    binding = {
        "request_id": request_id,
        "tool": proposal["tool"],
        "arguments_sha256": digest(canonical_arguments.encode()),
        "schema_sha256": "e" * 64,
        "policy_sha256": "f" * 64,
        "policy_facts_sha256": "c" * 64,
        "policy_context_sha256": "b" * 64,
        "operation_scope": "PUBLIC_SPENDING_RESEARCH",
        "policy_decision": "PERMIT",
    }
    binding["binding_sha256"] = digest(
        json.dumps(
            {**binding, "arguments_json": canonical_arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    observer = [
        {
            "event": "observer_integrity",
            "correlation_id": obs,
            "status": "PASS",
            "profiler_intact": True,
            "failures": [],
            "active_frames_at_close": 0,
        }
    ]
    if permit:
        observer += [
            {"status": "ISSUED", "correlation_id": obs, "call_index": 1, "binding": binding},
            {
                "status": "VERIFIED_CONSUMED",
                "correlation_id": obs,
                "call_index": 2,
                "binding": binding,
            },
        ]
    jsonl(root, prefix + "evidence/governance-observations.jsonl", observer)
    jsonl(
        root,
        prefix + "evidence/dispatch.jsonl",
        [{"phase": "entered", "synthetic": True, "query": arguments, "method": "search"}]
        if permit
        else [],
    )
    jsonl(
        root,
        prefix + "evidence/http-attempts.jsonl",
        [
            {
                "phase": "entered",
                "synthetic": True,
                "method": "POST",
                "request_path": "/api/v2/search/spending_by_award/",
            }
        ]
        if permit
        else [],
    )
    jsonl(
        root,
        prefix + "evidence/components.jsonl",
        [
            {"component": "adapter", "error_class": None, "synthetic": True, "phase": "finish"},
            {
                "component": "synthetic_http",
                "error_class": None,
                "status_code": 200,
                "synthetic": True,
                "phase": "finish",
            },
        ]
        if permit
        else [],
    )
    put(root, prefix + "mcp-tools-list.json", {"tools": [{"name": tool} for tool in sorted(TOOLS)]})
    if graph:
        request_hash = digest(request.encode())
        nodes = [
            {
                "event": "A2_NODE_ENTERED",
                "node": node,
                "ordinal": i + 1,
                "original_request": request,
                "request_sha256": request_hash,
                "observed_at_utc": "2026-11-01T00:00:00Z",
                "parent_monotonic_ns": i + 1,
                "proposal_json": json.dumps(proposal) if node == "gateway" else None,
            }
            for i, node in enumerate(NODES)
        ]
        jsonl(root, prefix + "a2-events.jsonl", nodes)
        put(
            root,
            prefix + "a2-orchestration-result.json",
            {
                "visited_nodes": NODES,
                "status": "COMPLETED",
                "context": {"original_request": request, "request_sha256": request_hash},
            },
        )
        put(root, prefix + "a2-mcp-client-input.json", {"request": request, "proposal": proposal})
    saved = {"fence_close": "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"}
    put(root, prefix + "evidence/synthetic-observation-summary.json", saved)
    saved_hash = digest((case / "evidence/synthetic-observation-summary.json").read_bytes())
    db = case / "coordinator.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE meta(id INTEGER,run_id TEXT)")
        conn.execute("INSERT INTO meta VALUES(1,?)", (run_id,))
        conn.execute(
            "CREATE TABLE observation_fences(observation_id TEXT,state TEXT,summary_sha256 TEXT,opened_at_utc TEXT,closed_at_utc TEXT)"
        )
        conn.execute(
            "INSERT INTO observation_fences VALUES(?,?,?,?,?)",
            (obs, "CLOSED", saved_hash, "2026-11-01T00:00:00Z", "2026-11-01T00:01:00Z"),
        )
        conn.execute("CREATE TABLE attempts(role TEXT,observation_id TEXT,reservation_json TEXT)")
        if decision != "DENY":
            conn.execute(
                "INSERT INTO attempts VALUES('judge',?,?)",
                (obs, json.dumps({"request_sha256": "a" * 64})),
            )
        for table in TABLES[3:]:
            conn.execute("CREATE TABLE " + table + "(id INTEGER)")
        conn.commit()
        conn.row_factory = sqlite3.Row
        tables = {
            table: [dict(row) for row in conn.execute("SELECT * FROM " + table)] for table in TABLES
        }
    put(
        root,
        prefix + "sqlite-readonly-before-restart.json",
        {"database_sha256": digest(db.read_bytes()), "integrity_check": "ok", "tables": tables},
    )
    put(root, prefix + "preservation-and-restart.json", {"database_unchanged": True})
    put(
        root,
        prefix + "restart-result.json",
        {"state_unchanged": True, "new_admission_or_dispatch_performed": False},
    )
    put(
        root,
        prefix + "evidence/worker-http-evidence.json",
        {
            "server_receipts": [{"request_sha256": "a" * 64, "body_received": True}]
            if decision != "DENY"
            else []
        },
    )
    return root


def store(root: Path, expected: str | None = None) -> EvidenceStore:
    return EvidenceStore(
        [{"id": "example", "root": str(root), "manifest_sha256": expected or seal(root)}]
    )


@pytest.mark.parametrize("decision", ["PERMIT", "DENY", "REVIEW_REQUIRED"])
def test_primary_decision_binding_dispatch_custody(tmp_path, decision):
    root = fixture_run(tmp_path / "run", decision)
    reader = store(root)
    run = reader.get_run("example")
    assert run["integrity"] == "VERIFIED"
    assert run["distribution"][decision] == 1
    obs = reader.get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["policy"]["initial_decision"] == obs["policy"]["final_disposition"] == decision
    assert (
        obs["binding"]["issued_count"]
        == obs["binding"]["consumed_count"]
        == int(decision == "PERMIT")
    )
    assert (
        obs["backend"]["adapter_entries"]
        == obs["backend"]["mock_transport_attempts"]
        == int(decision == "PERMIT")
    )
    assert obs["custody"]["database_state"] == "CLOSED"
    assert obs["custody"]["returned_close_ack"] == "ACKNOWLEDGED"
    assert obs["custody"]["persisted_summary_close_field"] == "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE"
    assert obs["judge"]["call_observed"] is (decision != "DENY")
    assert obs["result"]["verification_state"] == (
        "RESULT_VERIFIED" if decision == "PERMIT" else "UNVERIFIED"
    )


def test_mini071_never_fabricates_graph_history(tmp_path):
    reader = store(fixture_run(tmp_path / "run", graph=False))
    obs = reader.get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["integrity"] == "PARTIAL"
    assert obs["graph"]["state"] == "UNKNOWN"
    assert obs["graph"]["visited_nodes"] is None
    assert "GRAPH_HISTORY_NOT_AVAILABLE" in obs["issues"]
    assert obs["policy"]["initial_decision"] == "PERMIT"


def test_missing_primary_is_unknown_not_verified_zero(tmp_path):
    root = fixture_run(tmp_path / "run")
    (root / "execution/cases/example/evidence/dispatch.jsonl").unlink()
    reader = store(root)
    obs = reader.get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["integrity"] == "PARTIAL"
    assert obs["policy"]["initial_decision"] == "PERMIT"
    assert obs["backend"]["verified_absence"] is None
    assert obs["custody"]["database_state"] is None


def test_manifest_digest_not_promoted_from_modified_bytes(tmp_path):
    root = fixture_run(tmp_path / "run")
    pin = seal(root)
    (root / "RUN_SHA256_MANIFEST.json").write_text("{}")
    run = store(root, pin).get_run("example")
    assert run["integrity"] == "UNKNOWN"
    assert run["distribution"]["PERMIT"] is None
    assert run["issues"] == ["MANIFEST_DIGEST_MISMATCH"]


def test_artifact_tampering_is_unknown(tmp_path):
    root = fixture_run(tmp_path / "run")
    pin = seal(root)
    (root / "execution/cases/example/returned-summary.json").write_text("{}")
    assert store(root, pin).get_run("example")["issues"] == ["ARTIFACT_DIGEST_MISMATCH"]


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/private", "a\\b", "a//b", "a/./b"])
def test_manifest_path_traversal_rejected_before_read(tmp_path, name):
    root = tmp_path / "run"
    root.mkdir()
    put(
        root,
        "RUN_SHA256_MANIFEST.json",
        {"self_excluded": True, "files": [{"path": name, "bytes": 0, "sha256": digest(b"")}]},
    )
    run = store(root, digest((root / "RUN_SHA256_MANIFEST.json").read_bytes())).get_run("example")
    assert run["integrity"] == "UNKNOWN"
    assert run["issues"] == ["INVALID_MANIFEST_PATH"]


@pytest.mark.parametrize("identifier", ["../private", "a/b", "a\\b", "", "%2e%2e", "x" * 97])
def test_unknown_and_invalid_identifiers_do_not_resolve_paths(tmp_path, identifier):
    reader = store(fixture_run(tmp_path / "run"))
    with pytest.raises(SafeEvidenceError, match="UNKNOWN_RUN"):
        reader.get_run(identifier)
    with pytest.raises(SafeEvidenceError, match="UNKNOWN_OBSERVATION"):
        reader.get_observation("example", identifier)


@pytest.mark.parametrize(
    "payload", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b"{"]
)
def test_strict_json_rejects_malformed_ambiguous_or_nonfinite(payload):
    with pytest.raises(SafeEvidenceError):
        strict_json(payload)


def test_duplicate_manifest_paths_are_rejected(tmp_path):
    root = fixture_run(tmp_path / "run")
    seal(root)
    path = root / "RUN_SHA256_MANIFEST.json"
    data = json.loads(path.read_bytes())
    data["files"].append(data["files"][0])
    put(root, "RUN_SHA256_MANIFEST.json", data)
    assert store(root, digest(path.read_bytes())).get_run("example")["issues"] == [
        "DUPLICATE_MANIFEST_PATH"
    ]


def test_bool_manifest_length_is_not_an_integer(tmp_path):
    root = fixture_run(tmp_path / "run")
    seal(root)
    path = root / "RUN_SHA256_MANIFEST.json"
    data = json.loads(path.read_bytes())
    data["files"][0]["bytes"] = True
    put(root, "RUN_SHA256_MANIFEST.json", data)
    assert store(root, digest(path.read_bytes())).get_run("example")["issues"] == [
        "FILE_SIZE_LIMIT"
    ]


def test_sqlite_sidecar_causes_unknown_custody(tmp_path):
    root = fixture_run(tmp_path / "run")
    (root / "execution/cases/example/coordinator.sqlite-wal").write_bytes(b"synthetic")
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["custody"]["database_state"] is None
    assert "UNSTABLE_SQLITE_SNAPSHOT" in obs["issues"]


def test_observed_sqlite_and_saved_snapshot_must_match(tmp_path):
    root = fixture_run(tmp_path / "run")
    path = root / "execution/cases/example/sqlite-readonly-before-restart.json"
    data = json.loads(path.read_bytes())
    data["tables"]["observation_fences"][0]["state"] = "OPEN"
    path.write_text(json.dumps(data))
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["custody"]["database_state"] is None
    assert "SQLITE_RECORD_CONTRADICTION" in obs["issues"]


def test_projection_claims_do_not_override_primary_records(tmp_path):
    root = fixture_run(tmp_path / "run", "DENY")
    put(
        root,
        "execution/cases/example/console-evidence-projection.json",
        {"policy": {"initial_decision": "PERMIT"}, "binding": {"consumed_count": 9}},
    )
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["policy"]["initial_decision"] == "DENY"
    assert obs["binding"]["consumed_count"] == 0


def test_secret_path_and_url_redaction_is_bounded():
    raw = r"Bearer secret-value token=secret C:\Users\someone\private john@example.org https://example.org/?token=secret sk-abcdefghijklmnop"
    cleaned = safe_text(raw)
    assert all(
        value not in cleaned
        for value in [
            "secret-value",
            "token=secret",
            "C:\\Users",
            "john@example.org",
            "https://",
            "sk-abcdefghijklmnop",
        ]
    )
    assert len(safe_text("a" * 10000, 50)) <= 51


def test_repeated_reads_do_not_modify_any_evidence(tmp_path):
    root = fixture_run(tmp_path / "run")
    reader = store(root)
    before = {str(p): digest(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    for _ in range(3):
        reader.list_runs()
        reader.get_run("example")
        reader.get_observation("example", "SYNTHETIC_OBSERVATION")
    after = {str(p): digest(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
    assert before == after
    assert not list(root.rglob("*-journal"))
    assert not list(root.rglob("*-wal"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("exception_type", "ReadTimeout"),
        ("exception_type", 42),
        ("retry_decision", "RETRY_ALLOWED"),
        ("retry_decision", "INVALID_ENUM"),
        ("attempt", True),
        ("max_attempts", True),
    ],
)
def test_terminal_contradiction_retains_prior_policy_but_not_verified_dispatch(
    tmp_path, field, value
):
    root = fixture_run(tmp_path / "run")
    path = root / "execution/cases/example/evidence/audit.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[-1]["attempts"][0][field] = value
    jsonl(root, "execution/cases/example/evidence/audit.jsonl", rows)
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["integrity"] == "PARTIAL"
    assert obs["policy"]["initial_decision"] == "PERMIT"
    assert obs["binding"]["consumed_count"] == 1
    assert obs["backend"]["state"] == "UNKNOWN"
    assert obs["custody"]["database_state"] is None
    assert "TERMINAL_ATTEMPT_CONTRADICTION" in obs["issues"]


@pytest.mark.parametrize(
    "field",
    ["binding_issuances", "binding_consumptions", "adapter_entries", "mock_backend_attempts"],
)
def test_boolean_counts_never_become_verified_integers(tmp_path, field):
    root = fixture_run(tmp_path / "run")
    path = root / "execution/cases/example/returned-summary.json"
    value = json.loads(path.read_bytes())
    value[field] = True
    path.write_text(json.dumps(value))
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["integrity"] != "VERIFIED"
    assert obs["backend"]["state"] == "UNKNOWN"


def test_credential_quotes_unc_and_private_posix_paths_are_redacted():
    text = """password="private-one" api_key='private-two' "token":"private-three" \\\\server\\share\\private /mnt/private/file /etc/private/file"""
    value = safe_text(text)
    assert all(
        word not in value
        for word in ["private-one", "private-two", "private-three", "server", "/mnt/", "/etc/"]
    )


@pytest.mark.parametrize("name", ["a ", "a.", "a/b?", "a/secret:ads", "a/../b"])
def test_windows_alias_and_device_path_shapes_fail_closed(tmp_path, name):
    root = tmp_path / "run"
    root.mkdir()
    put(
        root,
        "RUN_SHA256_MANIFEST.json",
        {"self_excluded": True, "files": [{"path": name, "bytes": 0, "sha256": digest(b"")}]},
    )
    run = store(root, digest((root / "RUN_SHA256_MANIFEST.json").read_bytes())).get_run("example")
    assert run["integrity"] == "UNKNOWN"
    assert run["issues"] == ["INVALID_MANIFEST_PATH"]


def test_judge_signal_alone_does_not_prove_call(tmp_path):
    root = fixture_run(tmp_path / "run")
    put(root, "execution/cases/example/evidence/worker-http-evidence.json", {"server_receipts": []})
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["judge"]["call_observed"] is None
    assert obs["judge"]["state"] == "UNKNOWN"
    assert "JUDGE_CALL_EVIDENCE_CONTRADICTION" in obs["issues"]


def test_manifest_length_limit_before_opening_artifact(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    put(
        root,
        "RUN_SHA256_MANIFEST.json",
        {
            "self_excluded": True,
            "files": [{"path": "large", "bytes": 8 * 1024 * 1024 + 1, "sha256": "a" * 64}],
        },
    )
    run = store(root, digest((root / "RUN_SHA256_MANIFEST.json").read_bytes())).get_run("example")
    assert run["issues"] == ["FILE_SIZE_LIMIT"]


@pytest.mark.parametrize("decision", ["DENY", "REVIEW_REQUIRED"])
def test_empty_logs_do_not_prove_absence_if_terminal_attempt_exists(tmp_path, decision):
    root = fixture_run(tmp_path / "run", decision)
    path = root / "execution/cases/example/evidence/audit.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[-1]["attempts"] = [{"attempt": 1, "response_received": True, "status_code": 200}]
    jsonl(root, "execution/cases/example/evidence/audit.jsonl", rows)
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["policy"]["initial_decision"] == decision
    assert obs["backend"]["verified_absence"] is None
    assert obs["backend"]["state"] == "UNKNOWN"
    assert "NONDISPATCH_CONTRADICTION" in obs["issues"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_count", 1),
        ("attempt_count", False),
        ("response_state", "RESPONSE_RECEIVED"),
        ("tool_executed", True),
    ],
)
def test_held_envelope_cannot_contradict_verified_absence(tmp_path, field, value):
    root = fixture_run(tmp_path / "run", "DENY")
    path = root / "execution/cases/example/evidence/audit.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[-1]["response"][field] = value
    jsonl(root, "execution/cases/example/evidence/audit.jsonl", rows)
    returned_path = root / "execution/cases/example/returned-summary.json"
    returned = json.loads(returned_path.read_bytes())
    returned["observed_envelope"] = rows[-1]["response"]
    returned_path.write_text(json.dumps(returned))
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["policy"]["initial_decision"] == "DENY"
    assert obs["backend"]["verified_absence"] is None


def test_completed_executed_flag_must_match_dispatch(tmp_path):
    root = fixture_run(tmp_path / "run")
    path = root / "execution/cases/example/evidence/audit.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    rows[-1]["tool_executed"] = False
    jsonl(root, "execution/cases/example/evidence/audit.jsonl", rows)
    obs = store(root).get_observation("example", "SYNTHETIC_OBSERVATION")
    assert obs["binding"]["consumed_count"] == 1
    assert obs["backend"]["state"] == "UNKNOWN"
