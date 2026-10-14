import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import pytest

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_adapter
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal
from civicgate.models.responses import Envelope
from scripts import evaluate as evaluation
from scripts.evaluate import semantic_outcome
from tests.fixture_transports import build_transport

REPO_ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_SHA256 = "28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc"
PROJECTION_SHA256 = "8079b5610c2c9bf89a9b5441924cb295ee691d400596194000e7b2197d43d160"
PROJECTION_ID = "channel-a-legacy-evaluation-r1"
PROJECTED_REPORT = "artifacts/evaluation.channel-a-legacy-r1.json"


@pytest.fixture
def copied_evaluation_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    destination = tmp_path / "tests/fixtures"
    destination.mkdir(parents=True)
    fixture = destination / "adversarial.json"
    projection = destination / "channel_a_legacy_evaluation_r1.json"
    for target in (fixture, projection):
        shutil.copy2(REPO_ROOT / "tests/fixtures" / target.name, target)
    monkeypatch.chdir(tmp_path)
    return fixture, projection


def assert_original_input_bytes(fixture: Path, projection: Path) -> None:
    for target in (fixture, projection):
        assert target.read_bytes() == (REPO_ROOT / "tests/fixtures" / target.name).read_bytes()
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == ORIGINAL_SHA256
    assert hashlib.sha256(projection.read_bytes()).hexdigest() == PROJECTION_SHA256


def prevent_gateway_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_gateway(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid projection inputs reached Gateway construction")

    monkeypatch.setattr(evaluation, "Gateway", unexpected_gateway)


def write_synthetic_projection(
    projection: Path, content: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Synthetic copies only: bypass the pinned-byte check to exercise schema checks.
    projection.write_bytes(json.dumps(content).encode("utf-8"))
    monkeypatch.setattr(
        evaluation, "R1_PROJECTION_SHA256", hashlib.sha256(projection.read_bytes()).hexdigest()
    )


class CountingJudge(MockProvider):
    def __init__(self, unavailable: bool = False) -> None:
        self.calls = 0
        self.unavailable = unavailable

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        self.calls += 1
        if self.unavailable:
            return await UnavailableProvider().assess(request, proposal)
        return await super().assess(request, proposal)


@pytest.mark.parametrize(
    ("scenario", "expected", "calls"),
    [
        ("tripwire", "JUDGE_SKIPPED_PREFLIGHT_DENY", 0),
        ("invalid", "JUDGE_SKIPPED_PREFLIGHT_DENY", 0),
        ("unavailable", "SEMANTIC_FAILURE / GOVERNANCE_HELD", 1),
        ("normal", "MOCK_SIGNAL_ONLY", 1),
        ("disabled", "JUDGE_DISABLED", 0),
        ("disabled_deny", "JUDGE_DISABLED", 0),
    ],
)
async def test_reporter_judge_participation(
    search_args: dict[str, object], scenario: str, expected: str, calls: int
) -> None:
    judge = CountingJudge(unavailable=scenario == "unavailable")
    trace = Trace()
    gateway = Gateway(
        fixture_adapter(), judge, trace, require_judge=not scenario.startswith("disabled")
    )
    request = (
        "blacklist contractor" if scenario in {"tripwire", "disabled_deny"} else "public awards"
    )
    args = search_args | {"limit": 101} if scenario == "invalid" else search_args
    result = await gateway.call(request, Proposal(tool="find_federal_awards", arguments=args))
    before = result.model_dump_json()
    assert semantic_outcome(result, trace) == expected
    assert judge.calls == calls
    assert result.model_dump_json() == before
    if scenario == "invalid":
        assert result.decision == "DENY" and "INVALID_INPUT" in result.governance.policy_reasons
    if scenario == "unavailable":
        assert result.decision == "REVIEW_REQUIRED"
        assert "SEMANTIC_FAILURE" in result.governance.policy_reasons


async def test_reporter_uses_final_request_not_warmups_or_later_request(
    search_args: dict[str, object],
) -> None:
    trace = Trace()
    judge = CountingJudge()
    gateway = Gateway(fixture_adapter(), judge, trace)
    proposal = Proposal(tool="find_federal_awards", arguments=search_args)
    first = await gateway.call("public awards", proposal)
    for _ in range(2):
        await gateway.call("blacklist contractor", proposal)
    result = await gateway.call("public awards", proposal)
    # A different gateway writes a later, successful request into the shared trace.
    last = await Gateway(fixture_adapter(), MockProvider(), trace).call("public awards", proposal)
    assert first.request_id != result.request_id != last.request_id
    assert semantic_outcome(first, trace) == semantic_outcome(last, trace) == "MOCK_SIGNAL_ONLY"
    assert result.decision == "DENY"
    assert "SESSION_CONTAINMENT_ACTIVE" in result.governance.policy_reasons
    assert semantic_outcome(result, trace) == "JUDGE_SKIPPED_PREFLIGHT_DENY"
    assert judge.calls == 1


async def test_reporter_mock_assessment_survives_post_dispatch_review() -> None:
    trace = Trace()
    result = await Gateway(fixture_adapter(), MockProvider(), trace).call(
        "resolve recipient",
        Proposal(tool="resolve_federal_recipient", arguments={"recipient_name": "Acme"}),
    )
    assert result.tool_executed and result.decision == "REVIEW_REQUIRED"
    assert semantic_outcome(result, trace) == "MOCK_SIGNAL_ONLY"


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "wrong_request_id",
        "duplicate",
        "missing_skip",
        "missing_facts",
        "missing_accounting",
        "missing_judge_fields",
    ],
)
async def test_reporter_rejects_missing_or_ambiguous_evidence(
    search_args: dict[str, object], damage: str
) -> None:
    trace = Trace()
    result = await Gateway(fixture_adapter(), UnavailableProvider(), trace).call(
        "public awards", Proposal(tool="find_federal_awards", arguments=search_args)
    )
    event = next(event for event in trace.events if event["stage"] == "policy")
    if damage == "missing":
        trace.events.remove(event)
    elif damage == "wrong_request_id":
        event["request_id"] = "other-request"
    elif damage == "duplicate":
        trace.events.append(deepcopy(event))
    elif damage == "missing_skip":
        del event["judge_preflight_skipped"]
    elif damage == "missing_facts":
        del event["facts"]["semantic_required"]
    elif damage == "missing_accounting":
        del event["failure_accounting"]
    else:
        event["judge"] = {}
    with pytest.raises(ValueError, match="Judge accounting verification failed"):
        semantic_outcome(result, trace)


@pytest.mark.parametrize(
    "damage",
    [
        "skip_flag",
        "skip_and_failure",
        "disabled_but_required",
        "judge_mismatch",
        "false_hold",
        "unrecorded_failure",
        "false_failure",
    ],
)
async def test_reporter_rejects_contradictory_evidence(
    search_args: dict[str, object], damage: str
) -> None:
    trace = Trace()
    unavailable = damage == "unrecorded_failure"
    judge = CountingJudge(unavailable=unavailable)
    result = await Gateway(fixture_adapter(), judge, trace).call(
        "public awards", Proposal(tool="find_federal_awards", arguments=search_args)
    )
    event = next(event for event in trace.events if event["stage"] == "policy")
    if damage == "skip_flag":
        event["judge_preflight_skipped"] = True
    elif damage == "skip_and_failure":
        event["judge_preflight_skipped"] = True
        event["failure_accounting"] = ["JUDGE_SKIPPED_PREFLIGHT_DENY", "JUDGE_SEMANTIC_FAILURE"]
    elif damage == "disabled_but_required":
        event["facts"]["semantic_required"] = False
    elif damage == "judge_mismatch":
        event["judge"]["available"] = False
    elif damage == "false_hold":
        event["failure_accounting"].append("GOVERNANCE_HELD")
    elif damage == "unrecorded_failure":
        event["failure_accounting"].remove("JUDGE_SEMANTIC_FAILURE")
    else:
        event["failure_accounting"].append("JUDGE_SEMANTIC_FAILURE")
    with pytest.raises(ValueError, match="Judge accounting verification failed"):
        semantic_outcome(result, trace)


async def test_reporter_persists_corrected_labels(
    tmp_path: Path,
    copied_evaluation_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, projection = copied_evaluation_inputs
    original_cases = {case["id"]: case for case in json.loads(fixture.read_bytes())}
    contract = json.loads(projection.read_bytes())
    receipt_calls: list[dict[str, Any]] = []
    original_receipt_check = evaluation.assert_observed_receipt

    def checked_receipt(expected: dict[str, Any], result: Envelope, trace: Trace) -> None:
        # The production helper must still inspect every original receipt field.
        original_receipt_check(expected, result, trace)
        receipt_calls.append(deepcopy(expected))

    monkeypatch.setattr(evaluation, "assert_observed_receipt", checked_receipt)
    await evaluation.main(projection=PROJECTION_ID)
    report = json.loads((tmp_path / PROJECTED_REPORT).read_text())
    rows = {row["id"]: row for row in report["cases"]}
    assert report["mode"] == "SYNTHETIC_R1_PROJECTED_FIXTURE"
    assert report["fixture_matches"] == report["fixture_count"] == 35
    assert all(row["matched"] for row in rows.values())
    for case_id in ("blacklist", "malformed-dates", "repeated-denial"):
        assert rows[case_id]["semantic_outcome"] == "JUDGE_SKIPPED_PREFLIGHT_DENY"
    assert "INVALID_INPUT" in rows["malformed-dates"]["response"]["governance"]["policy_reasons"]
    assert rows["judge-failure"]["semantic_outcome"] == "SEMANTIC_FAILURE / GOVERNANCE_HELD"
    assert rows["valid-recipient"]["semantic_outcome"] == "MOCK_SIGNAL_ONLY"
    transport_ids = ("five-hundred-then-success", "timeout-then-changed-snapshot")
    assert receipt_calls == [
        original_cases[case_id]["observed_receipt"] for case_id in transport_ids
    ]
    for case_id in transport_ids:
        assert rows[case_id]["response"]["tool_executed"] is True
        assert rows[case_id]["response"]["attempt_count"] == 2

    expected_changes = {
        case_id: {
            field: {"original": original_cases[case_id][field], "effective": value}
            for field, value in overrides.items()
        }
        for case_id, overrides in contract["overrides"].items()
    }
    evidence = report["projection"]
    assert evidence["contract_id"] == PROJECTION_ID
    assert evidence["original_fixture_sha256"] == ORIGINAL_SHA256
    assert evidence["projection_sha256"] == PROJECTION_SHA256
    assert evidence["original_fixture_path"] == "tests/fixtures/adversarial.json"
    assert evidence["projection_path"] == "tests/fixtures/channel_a_legacy_evaluation_r1.json"
    assert evidence["basis"] == contract["basis"]
    assert evidence["changes"] == expected_changes
    effective_cases = [
        case | contract["overrides"].get(case["id"], {}) for case in original_cases.values()
    ]
    effective_bytes = json.dumps(
        effective_cases, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert evidence["effective_fixture_sha256"] == hashlib.sha256(effective_bytes).hexdigest()
    assert evidence["effective_fixture_sha256"] != ORIGINAL_SHA256
    for case in effective_cases:
        row = rows[case["id"]]
        assert row["original_request"] == original_cases[case["id"]]["request"]
        assert row["effective_request"] == case["request"]
        assert row["projection_changes"] == expected_changes.get(case["id"], {})

    # Matching a projected expected hold does not count as a valid request succeeding.
    metric = report["metrics"]["valid_request_success_rate"]
    assert (metric["numerator"], metric["denominator"], metric["value"]) == (4, 8, 0.5)
    for case_id in (
        "benign-risk-term",
        "contradictory-semantic",
        "timeout-provider",
        "judge-semantic-disagreement",
    ):
        assert rows[case_id]["matched"] is True
        assert rows[case_id]["status"] == "BLOCKED"
        assert rows[case_id]["response"]["tool_executed"] is False
    assert not (tmp_path / "artifacts/evaluation.json").exists()
    assert_original_input_bytes(fixture, projection)


def test_reporter_default_load_preserves_original_contract(
    copied_evaluation_inputs: tuple[Path, Path],
) -> None:
    fixture, projection = copied_evaluation_inputs
    original = json.loads(fixture.read_bytes())
    projection.unlink()  # The historical default must not depend on the R1 contract.
    fixtures, evidence = evaluation.load_fixtures()
    assert fixtures == original
    assert evidence is None
    cases = {case["id"]: case for case in fixtures}
    assert cases["benign-risk-term"]["expected_decision"] == "PERMIT"
    assert cases["ambiguous-recipient"]["expected_status"] == "CLARIFICATION_REQUIRED"
    assert cases["five-hundred-then-success"]["request"].endswith("transient upstream error")
    assert fixture.read_bytes() == (REPO_ROOT / "tests/fixtures/adversarial.json").read_bytes()


async def test_reporter_default_main_keeps_original_receipt_failure(
    tmp_path: Path, copied_evaluation_inputs: tuple[Path, Path]
) -> None:
    with pytest.raises(AssertionError, match="observed_receipt field 'attempt_count'"):
        await evaluation.main()
    assert not (tmp_path / PROJECTED_REPORT).exists()
    assert not (tmp_path / "artifacts/evaluation.json").exists()
    assert_original_input_bytes(*copied_evaluation_inputs)


@pytest.mark.parametrize("case_id", ["five-hundred-then-success", "timeout-then-changed-snapshot"])
async def test_original_transport_wording_stays_held_without_backend_dispatch(case_id: str) -> None:
    cases = json.loads((REPO_ROOT / "tests/fixtures/adversarial.json").read_bytes())
    case = next(case for case in cases if case["id"] == case_id)
    backend = build_transport(case["transport_factory"])
    dispatches = 0

    async def count_dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal dispatches
        dispatches += 1
        return await backend.handle_async_request(request)

    trace = Trace()
    result = await Gateway(
        USAspending(httpx.MockTransport(count_dispatch), fixture=True), MockProvider(), trace
    ).call(case["request"], Proposal(tool=case["tool"], arguments=case["arguments"]))
    assert (result.decision, result.status) == ("REVIEW_REQUIRED", "BLOCKED")
    assert result.tool_executed is False
    assert result.dispatch_state == "NOT_DISPATCHED"
    assert result.attempt_count == dispatches == 0
    assert not any(event["stage"] == "execution_started" for event in trace.events)
    assert semantic_outcome(result, trace) == "MOCK_SIGNAL_ONLY"


@pytest.mark.parametrize("target", ["fixture", "projection"])
async def test_reporter_rejects_changed_source_hash_before_gateway(
    tmp_path: Path,
    copied_evaluation_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    path = copied_evaluation_inputs[1 if target == "projection" else 0]
    path.write_bytes(path.read_bytes() + b"\n")
    prevent_gateway_construction(monkeypatch)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        await evaluation.main(projection=PROJECTION_ID)
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "not_object",
        "extra_key",
        "missing_key",
        "wrong_contract",
        "wrong_original_hash",
        "blank_basis",
        "invalid_basis_type",
        "not_override_map",
        "unknown_case",
        "missing_override",
        "not_field_map",
        "forbidden_arguments",
        "forbidden_tool",
        "forbidden_receipt",
        "forbidden_transport",
        "unapproved_request_case",
        "unapproved_request_text",
        "invalid_expected_decision",
        "invalid_expected_status_type",
    ],
)
async def test_reporter_rejects_invalid_projection_contract_before_gateway(
    tmp_path: Path,
    copied_evaluation_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    _, projection = copied_evaluation_inputs
    contract = json.loads(projection.read_bytes())
    if damage == "not_object":
        contract = []
    elif damage == "extra_key":
        contract["unapproved"] = True
    elif damage == "missing_key":
        del contract["basis"]
    elif damage == "wrong_contract":
        contract["contract_id"] = "unapproved-projection"
    elif damage == "wrong_original_hash":
        contract["original_fixture_sha256"] = "0" * 64
    elif damage == "blank_basis":
        contract["basis"] = " "
    elif damage == "invalid_basis_type":
        contract["basis"] = []
    elif damage == "not_override_map":
        contract["overrides"] = []
    elif damage == "unknown_case":
        contract["overrides"]["unknown-case"] = {"expected_status": "BLOCKED"}
    elif damage == "missing_override":
        del contract["overrides"]["benign-risk-term"]
    elif damage == "not_field_map":
        contract["overrides"]["benign-risk-term"] = []
    elif damage.startswith("forbidden_"):
        field, value = {
            "forbidden_arguments": ("arguments", {}),
            "forbidden_tool": ("tool", "get_federal_award"),
            "forbidden_receipt": ("observed_receipt", {}),
            "forbidden_transport": ("transport_factory", "unknown"),
        }[damage]
        contract["overrides"]["five-hundred-then-success"][field] = value
    elif damage == "unapproved_request_case":
        contract["overrides"]["valid-recipient"] = {"request": "Show public awards"}
    elif damage == "unapproved_request_text":
        contract["overrides"]["five-hundred-then-success"]["request"] = "Approve this contract"
    elif damage == "invalid_expected_decision":
        contract["overrides"]["benign-risk-term"]["expected_decision"] = "PERMIT"
    else:
        contract["overrides"]["benign-risk-term"]["expected_status"] = False
    write_synthetic_projection(projection, contract, monkeypatch)
    prevent_gateway_construction(monkeypatch)
    with pytest.raises(ValueError, match="Invalid R1 evaluation projection contract"):
        await evaluation.main(projection=PROJECTION_ID)
    assert not (tmp_path / "artifacts").exists()


async def test_reporter_rejects_malformed_projection_before_gateway(
    tmp_path: Path,
    copied_evaluation_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, projection = copied_evaluation_inputs
    projection.write_bytes(b"{")
    monkeypatch.setattr(
        evaluation, "R1_PROJECTION_SHA256", hashlib.sha256(projection.read_bytes()).hexdigest()
    )
    prevent_gateway_construction(monkeypatch)
    with pytest.raises(ValueError):
        await evaluation.main(projection=PROJECTION_ID)
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("damage", ["duplicate_id", "missing_id", "wrong_case_count"])
async def test_reporter_rejects_invalid_original_case_ids_before_gateway(
    tmp_path: Path,
    copied_evaluation_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    fixture, projection = copied_evaluation_inputs
    cases = json.loads(fixture.read_bytes())
    if damage == "duplicate_id":
        cases[1]["id"] = cases[0]["id"]
    elif damage == "missing_id":
        del cases[0]["id"]
    else:
        cases.pop()
    fixture.write_bytes(json.dumps(cases).encode("utf-8"))
    synthetic_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
    monkeypatch.setattr(evaluation, "ORIGINAL_FIXTURE_SHA256", synthetic_sha256)
    contract = json.loads(projection.read_bytes())
    contract["original_fixture_sha256"] = synthetic_sha256
    write_synthetic_projection(projection, contract, monkeypatch)
    prevent_gateway_construction(monkeypatch)
    with pytest.raises(ValueError):
        await evaluation.main(projection=PROJECTION_ID)
    assert not (tmp_path / "artifacts").exists()


async def test_reporter_rejects_unknown_projection_before_gateway(
    tmp_path: Path,
    copied_evaluation_inputs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prevent_gateway_construction(monkeypatch)
    with pytest.raises(ValueError, match="Unsupported evaluation projection"):
        await evaluation.main(projection="unapproved-projection")
    assert not (tmp_path / "artifacts").exists()
    assert_original_input_bytes(*copied_evaluation_inputs)


def test_reporter_exact_ci_projection_command(
    tmp_path: Path, copied_evaluation_inputs: tuple[Path, Path]
) -> None:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/evaluate.py"), "--projection", PROJECTION_ID],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((tmp_path / PROJECTED_REPORT).read_text())
    assert report["fixture_matches"] == report["fixture_count"] == 35
    assert report["projection"]["contract_id"] == PROJECTION_ID
    assert not (tmp_path / "artifacts/evaluation.json").exists()
    assert_original_input_bytes(*copied_evaluation_inputs)


@pytest.mark.parametrize(
    "arguments", [["--projection", "unapproved-projection"], ["--projection-file", "other.json"]]
)
def test_reporter_cli_rejects_unsupported_contracts_and_flags(
    tmp_path: Path, copied_evaluation_inputs: tuple[Path, Path], arguments: list[str]
) -> None:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/evaluate.py"), *arguments],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2
    assert "usage:" in completed.stderr
    assert not (tmp_path / "artifacts").exists()
    assert_original_input_bytes(*copied_evaluation_inputs)
