# Additive R3.2 derivative of evals/tests/test_eval_002b_r3_1_backend_v1.py; SHA-256 cea06080d47d2dd35ddcb165a2c6c948285a9c5e9190a2db534eb9ea4b4e0cc1
# Additive R3.1 regression derivative; original SHA-256: a27f919fc3dd4dc2f9a0d5c38248398a729e3745e418f551dcda9619c06b1c75
"""Generated local captures: exact invocation reconciliation, never live data."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from evals.harness.backend_capture_admission_v3 import validate_backend_capture
from evals.harness.evidence import canonical
from evals.harness.governance_observer_v2 import ReadOnlyGovernanceObserver
from evals.harness.provider_response_admission_v2 import strict_json_loads
from evals.harness.synthetic_server import EvidenceLedger, SyntheticAdapter, SyntheticTrace

OBSERVATION = "SYNTHETIC_R3_BACKEND_OBSERVATION"
REQUEST = "Show public federal awards."
SEARCH = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}


class _Judge:
    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        return JudgeSignal(
            classification="IN_SCOPE",
            confidence=0.99,
            available=True,
            provider="SYNTHETIC_R3_UNIT_FIXTURE",
        )


def _rows(directory: Path, name: str) -> list[dict[str, Any]]:
    return [strict_json_loads(line) for line in (directory / name).read_bytes().splitlines()]


def _write(directory: Path, name: str, rows: list[dict[str, Any]]) -> None:
    (directory / name).write_bytes(b"".join(canonical(row) + b"\n" for row in rows))


def _capture(
    directory: Path,
    *,
    tool: str = "find_federal_awards",
    arguments: dict[str, Any] | None = None,
    request: str = REQUEST,
    backend_mode: str = "normal",
) -> dict[str, Any]:
    arguments = SEARCH if arguments is None else arguments
    # MCP query parsing supplies these exact defaults before the original Gateway.
    effective = TOOLS[tool].model_validate(arguments).model_dump(mode="json")
    directory.mkdir()
    ledger = EvidenceLedger(directory)
    gateway = Gateway(SyntheticAdapter(ledger, backend_mode), _Judge(), SyntheticTrace(ledger))
    with ReadOnlyGovernanceObserver(directory, OBSERVATION):
        envelope = asyncio.run(gateway.call(request, Proposal(tool=tool, arguments=effective)))
    return {
        "expected_request": request,
        "expected_tool": tool,
        "expected_arguments": arguments,
        "expected_request_id": envelope.request_id,
        "expected_envelope": envelope,
    }


def _admit(directory: Path, expected: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return validate_backend_capture(
        directory,
        OBSERVATION,
        _rows(directory, "governance-observations.jsonl"),
        **(expected | overrides),
    )


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("find_federal_awards", SEARCH),
        (
            "find_federal_awards",
            SEARCH
            | {
                "recipient_name": "CAFÉ",
                "awarding_agency": "Fixture Agency",
                "award_types": ["A", "02"],
                "limit": 1,
            },
        ),
        ("summarize_federal_spending", SEARCH),
        ("get_federal_award", {"award_id": "1"}),
        ("resolve_federal_recipient", {"recipient_name": "EXAMPLE RECIPIENT"}),
    ],
)
def test_all_four_original_tools_reconcile_exact_protocol(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, Any],
) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory, tool=tool, arguments=arguments)
    admitted = _admit(directory, expected)
    assert admitted["state"] == "BOUND_BACKEND_CAPTURED"
    assert admitted["request_id"] == expected["expected_request_id"]
    assert len(admitted["dispatch"]) == len(admitted["backend"]) == 1


@pytest.mark.parametrize(
    "backend_mode", ["malformed", "timeout", "missing_provenance", "output_injection"]
)
def test_complete_backend_failure_capture_is_preserved(tmp_path: Path, backend_mode: str) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory, backend_mode=backend_mode)
    admitted = _admit(directory, expected)
    assert admitted["state"] == "BOUND_BACKEND_CAPTURED"
    assert admitted["backend"][0]["mode"] == backend_mode


@pytest.mark.parametrize(
    "user_request,arguments,decision",
    [
        ("Blacklist this contractor from future federal work.", SEARCH, "DENY"),
        (REQUEST, {"start_date": "2025-01-01", "end_date": "2025-02-01"}, "REVIEW_REQUIRED"),
    ],
)
def test_predispatch_held_capture_legitimately_has_no_backend(
    tmp_path: Path,
    user_request: str,
    arguments: dict[str, Any],
    decision: str,
) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory, request=user_request, arguments=arguments)
    admitted = _admit(directory, expected)
    assert admitted["state"] == "PRE_DISPATCH_HELD"
    assert admitted["audit"][-1]["response"]["decision"] == decision
    assert admitted["dispatch"] == admitted["backend"] == admitted["components"] == []


def test_no_mcp_activity_requires_all_reserved_streams_empty(tmp_path: Path) -> None:
    directory = tmp_path / "capture"
    directory.mkdir()
    EvidenceLedger(directory)
    with ReadOnlyGovernanceObserver(directory, OBSERVATION):
        pass
    admitted = _admit(directory, {"expected_request": REQUEST, "expected_envelope": None})
    assert admitted["state"] == "NO_GOVERNANCE_ACTIVITY"


@pytest.mark.parametrize(
    "name",
    [
        "governance-observations.jsonl",
        "audit.jsonl",
        "dispatch.jsonl",
        "http-attempts.jsonl",
        "components.jsonl",
    ],
)
@pytest.mark.parametrize(
    "corruption", ["missing", "empty", "malformed", "truncated", "duplicate", "nonfinite"]
)
def test_incomplete_or_malformed_bound_primary_streams_fail_closed(
    tmp_path: Path,
    name: str,
    corruption: str,
) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory)
    events = _rows(directory, "governance-observations.jsonl")
    path = directory / name
    original = path.read_bytes()
    if corruption == "missing":
        path.unlink()
    elif corruption == "empty":
        path.write_bytes(b"")
    elif corruption == "malformed":
        path.write_bytes(b"{\n")
    elif corruption == "truncated":
        path.write_bytes(original[:-1])
    elif corruption == "duplicate":
        path.write_bytes(original + original.splitlines()[0] + b"\n")
    else:
        path.write_bytes(b'{"value":1e999}\n')
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_"):
        validate_backend_capture(directory, OBSERVATION, events, **expected)


@pytest.mark.parametrize(
    "name,key,value",
    [
        ("dispatch.jsonl", "entry_index", 2),
        ("dispatch.jsonl", "entry_index", True),
        ("dispatch.jsonl", "method", "detail"),
        ("dispatch.jsonl", "synthetic", False),
        ("http-attempts.jsonl", "attempt_index", 2),
        ("http-attempts.jsonl", "method", "GET"),
        ("http-attempts.jsonl", "request_path", "/api/v2/recipient/"),
        ("http-attempts.jsonl", "request_body_sha256", "0" * 64),
        ("http-attempts.jsonl", "timestamp_utc", "2020-01-01T00:00:00+00:00"),
        ("components.jsonl", "attempt_index", 2),
        ("components.jsonl", "mode", "malformed"),
        ("components.jsonl", "status_code", 503),
    ],
)
def test_backend_identity_and_finish_mismatches_are_rejected(
    tmp_path: Path,
    name: str,
    key: str,
    value: Any,
) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory)
    rows = _rows(directory, name)
    rows[0][key] = value
    _write(directory, name, rows)
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_"):
        _admit(directory, expected)


def test_count_preserving_dispatch_query_substitution_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory)
    rows = _rows(directory, "dispatch.jsonl")
    rows[0]["query"]["state_code"] = "CA"
    _write(directory, "dispatch.jsonl", rows)
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_DISPATCH_IDENTITY_MISMATCH"):
        _admit(directory, expected)


@pytest.mark.parametrize(
    "key,value",
    [
        ("expected_request", "A different public research request."),
        ("expected_request_id", "OTHER_ACTUAL_REQUEST_ID"),
        ("expected_tool", "summarize_federal_spending"),
        ("expected_arguments", SEARCH | {"state_code": "CA"}),
    ],
)
def test_independent_invocation_constraints_reject_coherent_cross_capture(
    tmp_path: Path,
    key: str,
    value: Any,
) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory)
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_"):
        _admit(directory, expected, **{key: value})


@pytest.mark.parametrize(
    "mutation", ["observation", "request", "call_index", "arguments_hash", "binding_hash"]
)
def test_governance_identity_mismatches_are_rejected(tmp_path: Path, mutation: str) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory)
    rows = _rows(directory, "governance-observations.jsonl")
    if mutation == "observation":
        rows[0]["correlation_id"] = "OTHER_OBSERVATION"
    elif mutation == "request":
        rows[0]["request_id"] = "OTHER_REQUEST"
    elif mutation == "call_index":
        rows[0]["call_index"] = 2
    else:
        field = "arguments_sha256" if mutation == "arguments_hash" else "binding_sha256"
        for row in rows:
            if type(row.get("binding")) is dict:
                row["binding"][field] = "0" * 64
        audit = _rows(directory, "audit.jsonl")
        audit[2]["execution_binding"][field] = "0" * 64
        _write(directory, "audit.jsonl", audit)
    _write(directory, "governance-observations.jsonl", rows)
    with pytest.raises(ValueError):
        _admit(directory, expected)


def test_duplicate_json_key_is_not_a_valid_capture(tmp_path: Path) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory)
    path = directory / "dispatch.jsonl"
    original_row = canonical(_rows(directory, "dispatch.jsonl")[0])
    corrupted = original_row.replace(b'"entry_index":1', b'"entry_index":99,"entry_index":1')
    assert corrupted != original_row  # Prove the fixture mutation actually happened.
    path.write_bytes(corrupted + b"\n")
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_"):
        _admit(directory, expected)


def test_held_capture_cannot_hide_nonempty_backend_stream(tmp_path: Path) -> None:
    directory = tmp_path / "capture"
    expected = _capture(directory, request="Blacklist this contractor from future federal work.")
    _write(directory, "dispatch.jsonl", [{"entry_index": 1}])
    with pytest.raises(ValueError, match="BACKEND_CAPTURE_HELD_BACKEND_ACTIVITY"):
        _admit(directory, expected)
