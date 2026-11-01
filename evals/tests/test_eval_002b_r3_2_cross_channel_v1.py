# Additive R3.2 A/B regression; original SHA-256 8afd47e84db8cbe61f93933e3b22916884daa3cb2bc788b9d53069ef6d4d5949
"""Two exact cross-channel faults plus five legitimate full-composition controls.

Safety assertions require explicit rejection and durable OPEN for contradictions.
All cases use actual composition, stdio exit and independent restart custody checks.
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
FAULTS = (
    "probe_a",
    "probe_b",
    "probe_a_other",
    "probe_b_response_only",
    "probe_b_attempt_only",
    "probe_b_unknown",
)
CASES = ("valid_permit", *FAULTS, "backend_timeout", "backend_malformed", "pre_deny", "pre_review")


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
    if type(left) is dict and type(right) is dict and set(left) == set(right):
        return [x for key in left for x in leaves(left[key], right[key], path + (str(key),))]
    if type(left) is list and type(right) is list and len(left) == len(right):
        return [
            x
            for i, (a, b) in enumerate(zip(left, right, strict=True))
            for x in leaves(a, b, path + (str(i),))
        ]
    return (
        []
        if left == right and type(left) is type(right)
        else [{"path": "/" + "/".join(path), "before": left, "after": right}]
    )


@pytest.mark.parametrize("case", CASES)
def test_full_composition_safety(tmp_path, monkeypatch, case):
    suffix = sha(str(tmp_path.resolve()).encode())[:16]
    run_id = "MINI04_AB_" + case.upper() + "_" + suffix
    observation = "MINI04_AB_OBSERVATION_" + case.upper() + "_" + suffix
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

    @asynccontextmanager
    async def stdio(*args, **kwargs):
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
                target = directory / (
                    "components.jsonl" if case.startswith("probe_a") else "audit.jsonl"
                )
                before = target.read_bytes()
                lines = before.splitlines(keepends=True)
                parsed_before = [json.loads(line) for line in lines]
                indices = (
                    [i for i, row in enumerate(parsed_before) if row.get("component") == "adapter"]
                    if case.startswith("probe_a")
                    else [
                        i for i, row in enumerate(parsed_before) if row.get("stage") == "completed"
                    ]
                )
                assert len(indices) == 1
                index = indices[0]
                row = parsed_before[index]
                if case.startswith("probe_a"):
                    assert row["error_class"] is None
                    value = "TimeoutError" if case == "probe_a" else "RuntimeError"
                    lines[index], count = re.subn(
                        rb'("error_class"\s*:\s*)null',
                        lambda match: match[1] + ('"' + value + '"').encode(),
                        lines[index],
                    )
                    expected = [{"path": f"/{index}/error_class", "before": None, "after": value}]
                    assert count == 1
                else:
                    assert row["response"]["dispatch_state"] == "REQUEST_CONFIRMED"
                    assert (
                        len(row["attempts"]) == 1
                        and row["attempts"][0]["dispatch_state"] == "REQUEST_CONFIRMED"
                    )
                    assert row["attempts"][0]["response_received"] is True
                    value = "DISPATCH_UNKNOWN" if case == "probe_b_unknown" else "NOT_DISPATCHED"
                    matches = list(
                        re.finditer(rb'("dispatch_state"\s*:\s*)"REQUEST_CONFIRMED"', lines[index])
                    )
                    assert len(matches) == 2
                    indices = (
                        [0]
                        if case == "probe_b_response_only"
                        else [1]
                        if case == "probe_b_attempt_only"
                        else [0, 1]
                    )
                    expected = []
                    for selected in reversed(indices):
                        match = matches[selected]
                        lines[index] = (
                            lines[index][: match.start()]
                            + match[1]
                            + ('"' + value + '"').encode()
                            + lines[index][match.end() :]
                        )
                    for selected in indices:
                        leaf = (
                            "response/dispatch_state"
                            if selected == 0
                            else "attempts/0/dispatch_state"
                        )
                        expected.append(
                            {
                                "path": f"/{index}/" + leaf,
                                "before": "REQUEST_CONFIRMED",
                                "after": value,
                            }
                        )
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
    classification = "CONTROL"
    if case in FAULTS:
        classification = "INCONCLUSIVE"
        if error is None and injections and admissions:
            if (
                admissions[-1]["decision"] == "ADMITTED"
                and summary["primary_projection_verified"] is True
                and fence == "CLOSED"
            ):
                classification = "CONFIRMED_END_TO_END"
            elif admissions[-1]["decision"] == "ADMITTED" and fence != "CLOSED":
                classification = "VALIDATOR_ONLY"
            elif admissions[-1]["decision"] == "REJECTED" and fence != "CLOSED":
                classification = "REMEDIATED_END_TO_END"
    record = {
        "case": case,
        "classification": classification,
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
    if case in FAULTS:
        # Rejected capture cannot supply verified aggregate counts. Preserve
        # the separately labeled reports and underlying known consumed facts.
        assert summary["adapter_entries"] is None
        assert summary["mock_backend_attempts"] is None
        assert summary["reported_adapter_entry_records"] == 1
        assert summary["reported_mock_backend_records"] == 1
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
    if case in ("backend_timeout", "backend_malformed"):
        assert (
            summary["primary_projection_verified"] is True
            and fence == "OPEN"
            and summary["result_released"] is False
        )
    if case in ("pre_deny", "pre_review"):
        assert summary["primary_projection_verified"] is True and fence == "CLOSED"
    if case in FAULTS:
        reason = (
            "BACKEND_CAPTURE_ADAPTER_TERMINATION_CONTRADICTION"
            if case.startswith("probe_a")
            else "BACKEND_CAPTURE_TERMINAL_DISPATCH_STATE_INVALID"
            if case == "probe_b_attempt_only"
            else "BACKEND_CAPTURE_DISPATCH_STATE_CONTRADICTION"
        )
        assert classification == "REMEDIATED_END_TO_END"
        assert admissions[0]["decision"] == "REJECTED" and admissions[0]["reason"] == reason
        assert direct["decision"] == "REJECTED" and direct["reason"] == reason
        assert summary["backend_capture_admission"] == {"decision": "REJECTED", "reason": reason}
        assert summary["primary_projection_verified"] is False
        assert summary["fence_close"] != "ACKNOWLEDGED" and fence == "OPEN"
        assert (
            restart["ensure_recoverable_allowed"] is False
            and restart["error"]["type"] == "RecoveryBlocked"
        )
        # Capture rejection is after the original synthetic response was observed.
        original_completed = [
            x
            for x in json_rows(tmp_path / "original-capture/audit.jsonl")
            if x.get("stage") == "completed"
        ][0]
        assert summary["observed_envelope"] == original_completed["response"]
        assert (
            summary["result_released"] is True
            and summary["verification_state"] == "RESULT_VERIFIED"
        )
        assert summary["binding_consumptions"] == 1 and snapshot["reserved_liability_units"] == 2
    elif case in ("backend_timeout", "backend_malformed"):
        assert (
            restart["ensure_recoverable_allowed"] is False
            and restart["error"]["type"] == "RecoveryBlocked"
        )
        assert summary["fence_close"] != "ACKNOWLEDGED"
    else:
        assert restart["ensure_recoverable_allowed"] is True
        assert summary["fence_close"] == "ACKNOWLEDGED"
    fence_row = after["observation_fences"][0]
    saved_bytes = (directory / "synthetic-observation-summary.json").read_bytes()
    if fence == "CLOSED":
        assert (
            fence_row["summary_sha256"] == sha(saved_bytes)
            and fence_row["closed_at_utc"] is not None
        )
    else:
        assert fence_row["summary_sha256"] is None and fence_row["closed_at_utc"] is None
