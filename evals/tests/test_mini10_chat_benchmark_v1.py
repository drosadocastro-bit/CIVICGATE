"""Bounded MINI10 benchmark definitions and pre-MCP planner-failure controls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from civicgate.agent.langgraph_agent import LangGraphAgent
from civicgate.models.requests import Proposal
from evals.demos.mini10_chat_fixtures_v1 import FIXTURES, fixture_for_request
from tests.adversarial.test_a2_orchestration import LocalMCP

ROOT = Path(__file__).resolve().parents[2]


def test_benchmark_has_eight_distinct_declared_categories() -> None:
    value = json.loads((ROOT / "tests/fixtures/mini10_chat_benchmark_v1.json").read_bytes())
    assert (
        value["scope"] == "SCRIPTED_PLANNER_FIXTURE_AND_ORCHESTRATION_SAFETY_NOT_GRANITE_ACCURACY"
    )
    cases = value["cases"]
    assert len(cases) == 8
    assert {row["case_id"] for row in cases} == {f"CHAT-{index:03d}" for index in range(1, 9)}
    assert len({row["category"] for row in cases}) == 8
    declared = {row["case_id"]: row["expected"] for row in cases[:6]}
    assert declared == {fixture.case_id: fixture.expected_decision for fixture in FIXTURES}
    assert {row["case_id"]: row["expected"] for row in cases[6:]} == {
        "CHAT-007": "PLANNING_FAILED",
        "CHAT-008": "PLANNING_FAILED",
    }


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.case_id)
def test_synthetic_planner_fixture_identity_is_exact_and_explicit(fixture) -> None:
    selected = fixture_for_request(fixture.request)
    assert selected is fixture
    assert selected.scenario.request == fixture.request
    assert selected.expected_decision in {"PERMIT", "DENY", "REVIEW_REQUIRED"}


@pytest.mark.asyncio
async def test_unseen_prompt_is_not_silently_narrowed_or_dispatched() -> None:
    request = "Show public awards in Puerto Rico during FY2026."
    fixture = fixture_for_request(request)
    proposal = fixture.scenario.proposal()
    assert fixture.case_id == "CHAT-UNMATCHED"
    assert fixture.expected_decision == "REVIEW_REQUIRED"
    assert proposal.arguments == {
        "start_date": "2025-10-01",
        "end_date": "2026-09-30",
        "limit": 5,
    }
    transport = LocalMCP()

    class Planner:
        async def propose(self, original: str) -> Proposal:
            assert original == request
            return proposal

    result = await LangGraphAgent(Planner(), transport).run(request)
    assert result.status == "COMPLETED"
    envelope = result.outcome.envelope
    assert envelope is not None and envelope.decision == "REVIEW_REQUIRED"
    assert envelope.tool_executed is False
    policy = [event for event in transport.trace.events if event["stage"] == "policy"]
    assert len(policy) == 1 and policy[0]["binding_issued"] is False
    assert not any(event["stage"] == "execution_started" for event in transport.trace.events)
    assert transport.adapter.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [("timeout", "PLANNER_TIMEOUT"), ("malformed", "INVALID_PLANNER_PROPOSAL")],
)
async def test_planner_failure_stops_before_mcp_policy_binding_or_backend(
    mode: str, expected_code: str
) -> None:
    transport = LocalMCP()

    class FailedPlanner:
        async def propose(self, request: str) -> Any:
            if mode == "timeout":
                await asyncio.sleep(0.1)
                return Proposal(tool="find_federal_awards", arguments={})
            return {"tool": "find_federal_awards", "arguments": "not-an-object"}

    result = await LangGraphAgent(
        FailedPlanner(),
        transport,
        timeout_seconds=0.001 if mode == "timeout" else 1,
    ).run("Show public federal awards.")
    assert result.status == "PLANNING_FAILED"
    assert result.error_code == expected_code
    assert result.outcome is None
    assert transport.invocations == []
    assert transport.adapter.calls == transport.trace.events == []


@pytest.mark.asyncio
async def test_incorrect_schema_arguments_never_reach_backend() -> None:
    transport = LocalMCP()

    class InvalidArgumentsPlanner:
        async def propose(self, request: str) -> Proposal:
            return Proposal(
                tool="find_federal_awards",
                arguments={"start_date": "bad", "end_date": "also-bad", "limit": 5},
            )

    result = await LangGraphAgent(InvalidArgumentsPlanner(), transport).run(
        "Show public federal awards."
    )
    assert result.outcome is not None
    assert result.outcome.status == "MCP_TOOL_ERROR"
    assert result.outcome.envelope is None
    assert transport.adapter.calls == transport.trace.events == []
