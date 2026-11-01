"""R3.2 full-path terminal contract and coherence safety regressions.

Every case uses actual composition v4, MCP stdio, unchanged Gateway/adapter,
fresh SQLite and a recovery-only subprocess. Historical Mini03 is untouched.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from civicgate.models.responses import Envelope
from evals.harness import eval_002b_composition_v4 as composition
from evals.harness.backend_capture_admission_v3 import validate_backend_capture
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_composition_v3 import OfflineScenario
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy

COPY = Path.cwd().resolve()
HERE = COPY / "evals/tests"
TERMINAL_FIELDS = (
    "attempt",
    "max_attempts",
    "elapsed_ms",
    "dispatch_state",
    "response_state",
    "exception_type",
    "status_code",
    "response_received",
    "retry_after_seconds",
    "retry_decision",
    "retry_reason",
)


def fault(field, value, reason, contract, *, remove=False):
    return {
        "field": field,
        "value": value,
        "reason": "BACKEND_CAPTURE_" + reason,
        "contract": contract,
        "operation": "REMOVE" if remove else "REPLACE",
    }


FAULTS = {
    "c_readtimeout": fault(
        "exception_type",
        "ReadTimeout",
        "TERMINAL_EXCEPTION_CONTRADICTION",
        "successful terminal HTTP attempt must have null exception",
    ),
    "c_adaptererror": fault(
        "exception_type",
        "AdapterError",
        "TERMINAL_EXCEPTION_CONTRADICTION",
        "successful terminal HTTP attempt must have null exception",
    ),
    "c_oserror": fault(
        "exception_type",
        "OSError",
        "TERMINAL_EXCEPTION_CONTRADICTION",
        "successful terminal HTTP attempt must have null exception",
    ),
    "c_invalid_type": fault(
        "exception_type",
        42,
        "TERMINAL_EXCEPTION_TYPE_INVALID",
        "exception is null or exact string; no number coercion",
    ),
    "d_retry_allowed": fault(
        "retry_decision",
        "RETRY_ALLOWED",
        "TERMINAL_RETRY_CAPACITY_CONTRADICTION",
        "retry cannot be allowed at exhausted attempt=max=1",
    ),
    "d_invalid_enum": fault(
        "retry_decision",
        "INVALID_ENUM",
        "TERMINAL_RETRY_DECISION_INVALID",
        "retry decision is exact declared enum",
    ),
}
for _field in TERMINAL_FIELDS:
    FAULTS["missing_" + _field] = fault(
        _field,
        None,
        "TERMINAL_FIELD_SET_INVALID",
        "every existing AttemptRecord.model_dump field is required, including nullable fields",
        remove=True,
    )

WRONG_TYPES = {
    "attempt": True,
    "max_attempts": True,
    "elapsed_ms": "1.5",
    "dispatch_state": [],
    "response_state": {},
    "exception_type": 42,
    "status_code": True,
    "response_received": 1,
    "retry_after_seconds": "0.0",
    "retry_decision": 0,
    "retry_reason": None,
}
for _field, _value in WRONG_TYPES.items():
    FAULTS["wrong_type_" + _field] = fault(
        _field,
        _value,
        "TERMINAL_" + _field.upper() + "_INVALID",
        "exact producer field type; bool is not an integer or number",
    )
FAULTS.update(
    {
        "near_exception_other": fault(
            "exception_type",
            "ValueError",
            "TERMINAL_EXCEPTION_CONTRADICTION",
            "exception contradiction is independent of exception name",
        ),
        "near_retry_blocked_success": fault(
            "retry_decision",
            "RETRY_BLOCKED",
            "TERMINAL_RETRY_OUTCOME_CONTRADICTION",
            "valid enum is incompatible with successful terminal outcome",
        ),
        "near_success_reason_timeout": fault(
            "retry_reason",
            "timeout",
            "TERMINAL_EXCEPTION_CONTRADICTION",
            "failed attempt reason requires an actual terminal exception",
        ),
        "near_success_retry_after": fault(
            "retry_after_seconds",
            1.0,
            "TERMINAL_RETRY_AFTER_CONTRADICTION",
            "successful terminal producer records null retry-after",
        ),
        "near_exception_object": fault(
            "exception_type", {}, "TERMINAL_EXCEPTION_TYPE_INVALID", "exception cannot be an object"
        ),
        "near_exception_list": fault(
            "exception_type", [], "TERMINAL_EXCEPTION_TYPE_INVALID", "exception cannot be a list"
        ),
        "near_exception_bool": fault(
            "exception_type",
            True,
            "TERMINAL_EXCEPTION_TYPE_INVALID",
            "exception cannot be a boolean",
        ),
        "near_dispatch_enum": fault(
            "dispatch_state",
            "INVALID_ENUM",
            "TERMINAL_DISPATCH_STATE_INVALID",
            "dispatch is one of the producer enum values",
        ),
        "near_response_enum": fault(
            "response_state",
            "INVALID_ENUM",
            "TERMINAL_RESPONSE_STATE_INVALID",
            "response is one of the producer enum values",
        ),
        "near_elapsed_negative": fault(
            "elapsed_ms",
            -1.0,
            "TERMINAL_ELAPSED_MS_INVALID",
            "elapsed time is finite and nonnegative",
        ),
        "near_retry_after_negative": fault(
            "retry_after_seconds",
            -1.0,
            "TERMINAL_RETRY_AFTER_SECONDS_INVALID",
            "retry-after is null or finite nonnegative number",
        ),
        "near_ordinal_zero": fault(
            "attempt", 0, "TERMINAL_ATTEMPT_BOUNDS_INVALID", "attempt ordinal starts at one"
        ),
        "near_effective_max_two": fault(
            "max_attempts",
            2,
            "AUDIT_ATTEMPT_MISMATCH",
            "harness effective immutable max_attempts remains one",
        ),
    }
)
STREAM_CONTROLS = {"received_timeout": "timeout", "received_readerror": "readerror"}
CASES = (
    "valid_permit",
    *FAULTS,
    "backend_timeout",
    "backend_malformed",
    "pre_deny",
    "pre_review",
    *STREAM_CONTROLS,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def json_rows(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def sql_state(database):
    with sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        names = (
            "meta",
            "observation_fences",
            "attempts",
            "mcp_calls",
            "liability_reservations",
            "send_leases",
            "response_facts",
        )
        return {
            name: [
                dict(row) for row in connection.execute("SELECT * FROM " + name + " ORDER BY rowid")
            ]
            for name in names
        }


def leaves(left, right, path=()):
    if type(left) is dict and type(right) is dict:
        changes = []
        for key in sorted(set(left) | set(right)):
            target = "/" + "/".join((*path, str(key)))
            if key not in right:
                changes.append({"path": target, "operation": "REMOVE", "before": left[key]})
            elif key not in left:
                changes.append({"path": target, "operation": "ADD", "after": right[key]})
            else:
                changes.extend(leaves(left[key], right[key], path + (str(key),)))
        return changes
    if type(left) is list and type(right) is list and len(left) == len(right):
        return [
            change
            for i, (a, b) in enumerate(zip(left, right, strict=True))
            for change in leaves(a, b, path + (str(i),))
        ]
    return (
        []
        if type(left) is type(right) and left == right
        else [{"path": "/" + "/".join(path), "before": left, "after": right}]
    )


@pytest.mark.parametrize("case", CASES)
def test_terminal_record_fullpath_safety(tmp_path, monkeypatch, case):
    suffix = sha(str(tmp_path.resolve()).encode())[:16]
    run_id = "MINI04_TERMINAL_" + case.upper() + "_" + suffix
    observation = "MINI04_TERMINAL_OBSERVATION_" + case.upper() + "_" + suffix
    database = tmp_path / "coordinator.sqlite"
    directory = tmp_path / "evidence"
    LiveAttemptBudget.create(database, run_id, liability_policy=SyntheticLiabilityPolicy(24))
    scenario = OfflineScenario()
    if case == "backend_timeout":
        scenario = OfflineScenario(backend_mode="timeout")
    if case == "backend_malformed":
        scenario = OfflineScenario(backend_mode="malformed")
    if case == "pre_deny":
        scenario = OfflineScenario(request="Blacklist this contractor from future federal work.")
    if case == "pre_review":
        scenario = OfflineScenario(judge_flags=("NONE",))
    original_reader = composition._json_lines
    original_stdio = composition.stdio_client
    original_validate = composition.validate_backend_capture
    exited = []
    injections = []
    admissions = []
    observed_envelopes = []

    @asynccontextmanager
    async def stdio(*args, **kwargs):
        if case in STREAM_CONTROLS:
            params = args[0].model_copy(deep=True)
            original_args = list(params.args)
            assert original_args[:3] == ["-B", "-m", "evals.harness.eval_002b_composition_v4"]
            params.args = (
                original_args[:2]
                + [
                    "evals.tests.mini04_stream_worker_v1",
                    "--mini04-stream-fault",
                    STREAM_CONTROLS[case],
                ]
                + original_args[3:]
            )
            save(
                tmp_path / "worker-fixture-command.json",
                {
                    "original_args": original_args,
                    "fixture_args": params.args,
                    "actual_composition_module": "evals.harness.eval_002b_composition_v4",
                    "scope": "tests-only owned synthetic response stream",
                },
            )
            args = (params, *args[1:])
        async with original_stdio(*args, **kwargs) as streams:
            yield streams
        exited.append(True)

    def capture_before_admission(path):
        if not injections:
            assert path.name == "governance-observations.jsonl"
            assert exited and (directory / "worker-http-evidence.json").is_file()
            originals = tmp_path / "original-capture"
            originals.mkdir()
            original_hashes = {}
            for source in sorted(directory.rglob("*")):
                if source.is_file():
                    relative = source.relative_to(directory)
                    target = originals / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    raw = source.read_bytes()
                    original_hashes[relative.as_posix()] = {"bytes": len(raw), "sha256": sha(raw)}
            shutil.copyfile(database, tmp_path / "original-pre-admission.sqlite")
            save(tmp_path / "original-pre-admission-sql.json", sql_state(database))
            record = {
                "case": case,
                "stdio_context_exited": True,
                "original_files": original_hashes,
                "changes": [],
                "target": None,
            }
            if case in FAULTS:
                target = directory / "audit.jsonl"
                before = target.read_bytes()
                lines = before.splitlines(keepends=True)
                parsed_before = [json.loads(line) for line in lines]
                indices = [
                    i for i, row in enumerate(parsed_before) if row.get("stage") == "completed"
                ]
                assert len(indices) == 1
                index = indices[0]
                row = parsed_before[index]
                assert len(row["attempts"]) == 1
                terminal = row["attempts"][0]
                assert terminal["attempt"] == terminal["max_attempts"] == 1
                assert terminal["exception_type"] is None
                assert (
                    terminal["retry_decision"] == "NONE" and terminal["retry_reason"] == "success"
                )
                assert terminal["status_code"] == 200 and terminal["response_received"] is True
                assert terminal["dispatch_state"] == "REQUEST_CONFIRMED"
                assert (
                    row["response"]["status"] == "OK"
                    and row["response"]["verification_state"] == "RESULT_VERIFIED"
                )
                assert row["response"]["result"] is not None and row["response"]["errors"] == []
                parts = json_rows(directory / "components.jsonl")
                assert len(parts) == 2 and all(p["error_class"] is None for p in parts)
                assert parts[0]["component"] == "synthetic_http" and parts[0]["status_code"] == 200
                spec = FAULTS[case]
                field, value = spec["field"], spec["value"]
                previous = terminal[field]
                old_token = json.dumps(previous, allow_nan=False).encode()
                pattern = rb'("' + field.encode() + rb'"\s*:\s*)' + re.escape(old_token)
                attempts_region = re.search(rb'"attempts"\s*:\s*\[', lines[index])
                assert attempts_region is not None
                matches = list(re.compile(pattern).finditer(lines[index], attempts_region.end()))
                assert len(matches) == 1
                match = matches[0]
                original_line = lines[index]
                begin, end = match.start(), match.end()
                if spec["operation"] == "REMOVE":
                    if original_line[:begin].endswith(b", "):
                        begin -= 2
                    else:
                        assert original_line[end : end + 2] == b", "
                        end += 2
                    replacement = b""
                    expected = [
                        {
                            "path": f"/{index}/attempts/0/" + field,
                            "operation": "REMOVE",
                            "before": previous,
                        }
                    ]
                else:
                    replacement = match[1] + json.dumps(value, allow_nan=False).encode()
                    expected = [
                        {
                            "path": f"/{index}/attempts/0/" + field,
                            "before": previous,
                            "after": value,
                        }
                    ]
                lines[index] = original_line[:begin] + replacement + original_line[end:]
                assert lines[index][:begin] == original_line[:begin]
                assert lines[index][begin + len(replacement) :] == original_line[end:]
                record["contract_violation"] = {
                    "field": field,
                    "constraint": spec["contract"],
                    "expected_reason": spec["reason"],
                    "operation": spec["operation"],
                }
                record["byte_replacement"] = {
                    "line_index": index,
                    "start": begin,
                    "old_end": end,
                    "old_bytes_hex": original_line[begin:end].hex(),
                    "new_bytes_hex": replacement.hex(),
                    "surrounding_bytes_unchanged": True,
                }
                altered = b"".join(lines)
                parsed_after = [json.loads(line) for line in altered.splitlines()]
                differences = leaves(parsed_before, parsed_after)
                assert sorted(differences, key=lambda x: x["path"]) == sorted(
                    expected, key=lambda x: x["path"]
                )
                target.write_bytes(altered)
                with (tmp_path / "mutated-target-copy.bin").open("xb") as stream:
                    stream.write(altered)
                record.update(
                    target=target.name,
                    changes=differences,
                    before_sha256=sha(before),
                    after_sha256=sha(altered),
                )
            for relative, pinned in original_hashes.items():
                current = (directory / relative).read_bytes()
                if relative != record["target"]:
                    assert sha(current) == pinned["sha256"]
            injections.append(record)
            save(tmp_path / "mutation-integrity.json", record)
        return original_reader(path)

    def admitted(*args, **kwargs):
        actual = kwargs.get("expected_envelope")
        observed_envelopes.append(actual.model_dump(mode="json") if actual is not None else None)
        try:
            value = original_validate(*args, **kwargs)
        except Exception as exc:
            admissions.append(
                {"decision": "REJECTED", "reason": str(exc), "exception_type": type(exc).__name__}
            )
            raise
        admissions.append(
            {"decision": "ADMITTED", "reason": value["state"], "request_id": value["request_id"]}
        )
        return value

    monkeypatch.setattr(composition, "stdio_client", stdio)
    monkeypatch.setattr(composition, "_json_lines", capture_before_admission)
    monkeypatch.setattr(composition, "validate_backend_capture", admitted)
    error = None
    summary = None
    try:
        summary = asyncio.run(
            composition.run_synthetic_observation(
                database, run_id, observation, directory, scenario
            )
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "reason": str(exc)}
    after = sql_state(database)
    snapshot = LiveAttemptBudget(database, run_id).snapshot()
    audit = json_rows(directory / "audit.jsonl")
    completed = [row for row in audit if row.get("stage") == "completed"]
    request_id = completed[0]["request_id"] if completed else None
    direct = None
    try:
        value = validate_backend_capture(
            directory,
            observation,
            original_reader(directory / "governance-observations.jsonl"),
            expected_request=scenario.request,
            expected_tool=scenario.proposal_tool,
            expected_arguments=scenario.proposal().arguments,
            expected_request_id=request_id,
            expected_envelope=Envelope.model_validate(summary["observed_envelope"])
            if summary and summary["observed_envelope"]
            else None,
        )
        direct = {
            "decision": "ADMITTED",
            "reason": value["state"],
            "request_id": value["request_id"],
        }
    except Exception as exc:
        direct = {"decision": "REJECTED", "reason": str(exc), "exception_type": type(exc).__name__}
    captures_before_restart = {
        p.relative_to(directory).as_posix(): sha(p.read_bytes())
        for p in directory.rglob("*")
        if p.is_file()
    }
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(
        PYTHONPATH=str(COPY / "src") + os.pathsep + str(COPY),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        TEMP=str(tmp_path),
        TMP=str(tmp_path),
    )
    restart_path = tmp_path / "restart-result.json"
    cmd = [
        sys.executable,
        "-B",
        "-s",
        str(HERE / "eval_002b_r3_1_restart_v1.py"),
        str(database),
        run_id,
        str(restart_path),
    ]
    restarted = subprocess.run(cmd, cwd=COPY, env=env, capture_output=True, text=True, timeout=30)
    save(
        tmp_path / "restart-command.json",
        {"argv": cmd, "cwd": str(COPY), "environment": env, "exit_code": restarted.returncode},
    )
    (tmp_path / "restart-stdout.log").write_text(restarted.stdout, encoding="utf-8")
    (tmp_path / "restart-stderr.log").write_text(restarted.stderr, encoding="utf-8")
    restart = json.loads(restart_path.read_bytes()) if restarted.returncode == 0 else None
    after_restart = sql_state(database)
    captures_after_restart = {
        p.relative_to(directory).as_posix(): sha(p.read_bytes())
        for p in directory.rglob("*")
        if p.is_file()
    }
    fence = (
        after["observation_fences"][0]["state"]
        if len(after["observation_fences"]) == 1
        else "UNKNOWN"
    )
    summary_file = directory / "synthetic-observation-summary.json"
    saved_bytes = summary_file.read_bytes() if summary_file.is_file() else None
    fence_row = after["observation_fences"][0] if len(after["observation_fences"]) == 1 else None
    close_hash_valid = bool(
        fence_row and saved_bytes is not None and fence_row["summary_sha256"] == sha(saved_bytes)
    )
    classification = "CONTROL"
    if case in FAULTS:
        classification = "INCONCLUSIVE"
        if error is None and len(injections) == len(admissions) == 1 and summary is not None:
            admitted = admissions[-1]["decision"] == "ADMITTED"
            if (
                admitted
                and summary["primary_projection_verified"] is True
                and fence == "CLOSED"
                and summary["fence_close"] == "ACKNOWLEDGED"
                and close_hash_valid
            ):
                classification = "CONFIRMED_END_TO_END"
            elif (
                admitted
                and fence == "OPEN"
                and summary["fence_close"] != "ACKNOWLEDGED"
                and restart
                and restart["ensure_recoverable_allowed"] is False
            ):
                classification = "VALIDATOR_ONLY"
            elif (
                not admitted
                and summary["primary_projection_verified"] is False
                and fence == "OPEN"
                and summary["fence_close"] != "ACKNOWLEDGED"
                and restart
                and restart["ensure_recoverable_allowed"] is False
            ):
                classification = "REJECTED_END_TO_END"
    record = {
        "case": case,
        "classification": classification,
        "client_observed_envelopes": observed_envelopes,
        "saved_summary_sha256": sha(saved_bytes) if saved_bytes is not None else None,
        "close_summary_hash_valid": close_hash_valid,
        "safety_test_not_human_acceptance": True,
        "required_constraint": FAULTS.get(case),
        "capture_hashes_before_restart": captures_before_restart,
        "capture_hashes_after_restart": captures_after_restart,
        "exception": error,
        "scenario": scenario.__dict__,
        "injection": injections,
        "composition_backend_admission": admissions,
        "postrun_backend_admission": direct,
        "returned_summary": summary,
        "persisted_preclosure_summary": json.loads(
            (directory / "synthetic-observation-summary.json").read_bytes()
        )
        if (directory / "synthetic-observation-summary.json").exists()
        else None,
        "final_fence": fence,
        "sql_before_restart": after,
        "sql_after_restart": after_restart,
        "ledger_snapshot": snapshot,
        "restart": restart,
        "restart_pid_distinct": restart is not None and restart["pid"] != os.getpid(),
        "restart_changed_state": after != after_restart,
        "restart_changed_captures": captures_before_restart != captures_after_restart,
        "actual_backends_synthetic": True,
        "real_provider_calls": 0,
        "new_dispatch_or_refund_during_restart": after != after_restart,
    }
    save(tmp_path / "observed-result.json", record)
    assert error is None and len(injections) == 1 and len(admissions) == 1
    assert (
        restarted.returncode == 0 and record["restart_pid_distinct"] and restart["state_unchanged"]
    )
    assert not record["restart_changed_state"] and not record["restart_changed_captures"]
    assert summary["mcp_logical_calls"] == 1
    assert snapshot["counts"] == {"planner": 1, "judge": 0 if case == "pre_deny" else 1}
    assert (
        summary["binding_issuances"]
        == summary["binding_consumptions"]
        == (0 if case in ("pre_deny", "pre_review") else 1)
    )
    if admissions[0]["decision"] == "REJECTED":
        assert summary["adapter_entries"] is None and summary["mock_backend_attempts"] is None
        assert (
            summary["reported_adapter_entry_records"] == 1
            and summary["reported_mock_backend_records"] == 1
        )
    else:
        assert (
            summary["adapter_entries"]
            == summary["mock_backend_attempts"]
            == (0 if case in ("pre_deny", "pre_review") else 1)
        )
    before_admission = json.loads((tmp_path / "original-pre-admission-sql.json").read_bytes())
    for table in (
        "attempts",
        "mcp_calls",
        "liability_reservations",
        "send_leases",
        "response_facts",
    ):
        assert before_admission[table] == after[table]
    assert snapshot["reserved_liability_units"] == len(snapshot["attempts"])
    if case == "valid_permit":
        assert (
            summary["primary_projection_verified"] is True
            and fence == "CLOSED"
            and summary["result_released"] is True
        )
    if case in ("backend_timeout", "backend_malformed", *STREAM_CONTROLS):
        assert (
            summary["primary_projection_verified"] is True
            and fence == "OPEN"
            and summary["result_released"] is False
        )
    if case in ("pre_deny", "pre_review"):
        assert summary["primary_projection_verified"] is True and fence == "CLOSED"
    if case in FAULTS:
        reason = FAULTS[case]["reason"]
        assert classification == "REJECTED_END_TO_END"
        assert admissions[0]["decision"] == direct["decision"] == "REJECTED"
        assert admissions[0]["reason"] == direct["reason"] == reason
        assert summary["backend_capture_admission"] == {"decision": "REJECTED", "reason": reason}
        assert summary["primary_projection_verified"] is False
        assert fence == "OPEN" and summary["fence_close"] != "ACKNOWLEDGED"
        assert (
            restart["ensure_recoverable_allowed"] is False
            and restart["error"]["type"] == "RecoveryBlocked"
        )
        original_completed = [
            x
            for x in json_rows(tmp_path / "original-capture/audit.jsonl")
            if x.get("stage") == "completed"
        ][0]
        assert (
            summary["observed_envelope"] == original_completed["response"] == observed_envelopes[0]
        )
        assert (
            summary["result_released"] is True
            and summary["verification_state"] == "RESULT_VERIFIED"
        )
        assert summary["binding_consumptions"] == 1 and snapshot["reserved_liability_units"] == 2
    elif case in ("backend_timeout", "backend_malformed", *STREAM_CONTROLS):
        assert admissions[0]["decision"] == direct["decision"] == "ADMITTED"
        assert summary["backend_capture_admission"]["reason"] == "BOUND_BACKEND_CAPTURED"
        assert (
            restart["ensure_recoverable_allowed"] is False
            and restart["error"]["type"] == "RecoveryBlocked"
        )
        assert summary["fence_close"] != "ACKNOWLEDGED" and fence == "OPEN"
    else:
        assert (
            restart["ensure_recoverable_allowed"] is True
            and summary["fence_close"] == "ACKNOWLEDGED"
        )
    if case in STREAM_CONTROLS:
        stream = json.loads((directory / "mini04-stream-evidence.json").read_bytes())
        expected_exception = "ReadTimeout" if STREAM_CONTROLS[case] == "timeout" else "ReadError"
        assert stream["body_stream_entered"] is True and stream["chunks_yielded"] == 1
        assert stream["raised_error_class"] == expected_exception
        assert (
            stream["original_mock_type_exact"]
            and stream["retained_mock_type_exact"]
            and stream["retained_identity_matches"]
        )
        assert stream["composition_module"] == composition.__name__
        assert stream["composition_sha256"] == sha(Path(composition.__file__).read_bytes())
        terminal = completed[0]["attempts"][0]
        assert terminal["status_code"] == 200 and terminal["response_received"] is True
        assert (
            terminal["dispatch_state"] == "REQUEST_CONFIRMED"
            and terminal["response_state"] == "TRANSPORT_ERROR"
        )
        assert (
            terminal["exception_type"] == expected_exception
            and terminal["retry_decision"] == "RETRY_BLOCKED"
        )
        parts = json_rows(directory / "components.jsonl")
        assert parts[0]["status_code"] == 200 and parts[0]["error_class"] is None
        assert parts[1]["error_class"] == "AdapterError"
        assert (
            summary["verification_state"] == "RESULT_UNKNOWN"
            and summary["observed_envelope"]["status"] == "ERROR"
        )
    fence_row = after["observation_fences"][0]
    saved_bytes = (directory / "synthetic-observation-summary.json").read_bytes()
    if fence == "CLOSED":
        assert (
            fence_row["summary_sha256"] == sha(saved_bytes)
            and fence_row["closed_at_utc"] is not None
        )
    else:
        assert fence_row["summary_sha256"] is None and fence_row["closed_at_utc"] is None
