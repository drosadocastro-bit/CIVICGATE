import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from civicgate.audit.trace import Trace
from civicgate.demo import fixture_adapter
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal
from scripts.evaluate import main, semantic_outcome


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    destination = tmp_path / "tests" / "fixtures"
    destination.mkdir(parents=True)
    shutil.copy2(root / "tests/fixtures/adversarial.json", destination / "adversarial.json")
    monkeypatch.chdir(tmp_path)
    await main()
    report = json.loads((tmp_path / "artifacts/evaluation.json").read_text())
    rows = {row["id"]: row for row in report["cases"]}
    assert report["fixture_matches"] == report["fixture_count"] == 35
    for case_id in ("blacklist", "malformed-dates", "repeated-denial"):
        assert rows[case_id]["semantic_outcome"] == "JUDGE_SKIPPED_PREFLIGHT_DENY"
    assert "INVALID_INPUT" in rows["malformed-dates"]["response"]["governance"]["policy_reasons"]
    assert rows["judge-failure"]["semantic_outcome"] == "SEMANTIC_FAILURE / GOVERNANCE_HELD"
    assert rows["valid-recipient"]["semantic_outcome"] == "MOCK_SIGNAL_ONLY"
