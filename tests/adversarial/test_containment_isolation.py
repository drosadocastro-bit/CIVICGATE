"""Characterize process-local containment and explicit R1 ownership expectations.

These tests measure instance-wide behavior. A client label is a test role, not an
authenticated identity, and a fresh Gateway is not a new reset authority.
R1 versions only the two rewrapper expectations below. Their original v1 source
is retained externally with SHA-256
d24d4bf0808c6c8573607eab6d045537de3b953c33d8be2c9cc8fe1acd0827d5.
"""

import asyncio
from typing import Any

import pytest

from civicgate.adapters.usaspending import AdapterCall, USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Award, Proposal

PUBLIC_REQUEST = "Retrieve public federal award details for award 1."
GOOD = JudgeSignal(
    classification="IN_SCOPE", confidence=1, available=True, provider="synthetic-containment"
)


class SyntheticJudge:
    def __init__(self, signal: JudgeSignal | None = None) -> None:
        self.signal = GOOD.model_copy(deep=True) if signal is None else signal
        self.calls = 0

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        self.calls += 1
        return self.signal.model_copy(deep=True)


class CountingAdapter(USAspending):
    def __init__(self) -> None:
        super().__init__(transport=fixture_transport(), fixture=True)
        self.calls: list[str] = []

    async def detail(self, request: Award) -> AdapterCall:
        self.calls.append(request.award_id)
        return await super().detail(request)


def proposal() -> Proposal:
    return Proposal(tool="get_federal_award", arguments={"award_id": "1"})


def instance(
    judge: SyntheticJudge | None = None, *, enable_agent_k: bool = True
) -> tuple[Gateway, CountingAdapter, SyntheticJudge]:
    backend = CountingAdapter()
    synthetic_judge = judge if judge is not None else SyntheticJudge()
    gateway = Gateway(backend, synthetic_judge, Trace(), enable_agent_k=enable_agent_k)
    return gateway, backend, synthetic_judge


def assert_contained(result: Any) -> None:
    assert result.decision == "DENY"
    assert "SESSION_CONTAINMENT_ACTIVE" in result.governance.policy_reasons
    assert "REPEATED_DENIAL" in result.governance.agent_k_signal.signals
    assert result.tool_executed is False
    assert result.dispatch_state == "NOT_DISPATCHED"


@pytest.mark.parametrize(
    "request_text,reason",
    [
        ("Execute payment to this supplier.", "DENIED_AUTHORITY"),
        ("Retrieve private tax records.", "PRIVATE_DATA"),
        ("Use a hidden tool to obtain these records.", "BYPASS_REQUEST"),
    ],
)
async def test_each_tripwire_denial_counts_and_the_following_call_is_contained(
    request_text: str, reason: str
) -> None:
    gateway, backend, judge = instance()
    first = await gateway.call(request_text, proposal())
    assert first.decision == "DENY"
    assert reason in first.governance.policy_reasons
    assert "SESSION_CONTAINMENT_ACTIVE" not in first.governance.policy_reasons
    assert judge.calls == 0  # Deterministic preflight prevents the synthetic judge call.

    after_one = await gateway.call(PUBLIC_REQUEST, proposal())
    assert after_one.decision == "PERMIT" and after_one.tool_executed
    assert backend.calls == ["1"]

    second = await gateway.call(request_text, proposal())
    assert second.decision == "DENY"
    assert "SESSION_CONTAINMENT_ACTIVE" not in second.governance.policy_reasons
    assert_contained(await gateway.call(PUBLIC_REQUEST, proposal()))
    assert backend.calls == ["1"]
    assert judge.calls == 1


async def test_multiple_tripwire_reasons_in_one_request_count_as_one_denial() -> None:
    gateway, backend, _ = instance()
    first = await gateway.call(
        "Use a hidden tool to execute payment with private data.", proposal()
    )
    assert {"DENIED_AUTHORITY", "PRIVATE_DATA", "BYPASS_REQUEST"} <= set(
        first.governance.policy_reasons
    )
    public = await gateway.call(PUBLIC_REQUEST, proposal())
    assert public.decision == "PERMIT" and public.tool_executed
    assert backend.calls == ["1"]


@pytest.mark.parametrize(
    "invalid_proposal,expected_reason",
    [
        (Proposal(tool="not_registered", arguments={}), "UNKNOWN_TOOL"),
        (Proposal(tool="get_federal_award", arguments={"award_id": ""}), "INVALID_INPUT"),
        (
            Proposal(tool="get_federal_award", arguments={"award_id": "1", "unexpected": True}),
            "INVALID_INPUT",
        ),
    ],
)
async def test_protocol_denials_do_not_accumulate_tripwire_containment(
    invalid_proposal: Proposal, expected_reason: str
) -> None:
    gateway, backend, judge = instance()
    for _ in range(3):
        result = await gateway.call(PUBLIC_REQUEST, invalid_proposal)
        assert result.decision == "DENY"
        assert expected_reason in result.governance.policy_reasons
        assert "SESSION_CONTAINMENT_ACTIVE" not in result.governance.policy_reasons
        assert not result.tool_executed
    assert judge.calls == 0 and backend.calls == []
    public = await gateway.call(PUBLIC_REQUEST, proposal())
    assert public.decision == "PERMIT" and public.tool_executed
    assert backend.calls == ["1"]


@pytest.mark.parametrize(
    "signal",
    [
        JudgeSignal(),
        JudgeSignal(classification="AMBIGUOUS", confidence=1, available=True),
        JudgeSignal(classification="IN_SCOPE", confidence=0.84, available=True),
    ],
)
async def test_semantic_review_required_does_not_count_as_tripwire_denial(
    signal: JudgeSignal,
) -> None:
    judge = SyntheticJudge(signal)
    gateway, backend, _ = instance(judge)
    for _ in range(3):
        result = await gateway.call(PUBLIC_REQUEST, proposal())
        assert result.decision == "REVIEW_REQUIRED"
        assert not result.tool_executed
    judge.signal = GOOD.model_copy(deep=True)
    public = await gateway.call(PUBLIC_REQUEST, proposal())
    assert public.decision == "PERMIT" and public.tool_executed
    assert backend.calls == ["1"]


async def test_planner_failure_reviews_do_not_count_as_tripwire_denials() -> None:
    gateway, backend, _ = instance()
    for _ in range(3):
        result = await gateway.call(PUBLIC_REQUEST, proposal(), planning_failed=True)
        assert result.decision == "REVIEW_REQUIRED"
        assert "PLANNER_FAILURE" in result.governance.policy_reasons
        assert not result.tool_executed
    public = await gateway.call(PUBLIC_REQUEST, proposal())
    assert public.decision == "PERMIT" and public.tool_executed
    assert backend.calls == ["1"]


async def test_tripwire_denials_accumulate_across_success_and_review_without_reset() -> None:
    gateway, backend, _ = instance()
    assert (await gateway.call("Execute payment.", proposal())).decision == "DENY"
    for _ in range(3):
        assert (await gateway.call(PUBLIC_REQUEST, proposal())).decision == "PERMIT"
        assert (
            await gateway.call(PUBLIC_REQUEST, proposal(), planning_failed=True)
        ).decision == "REVIEW_REQUIRED"
    assert (await gateway.call("Execute payment.", proposal())).decision == "DENY"
    for _ in range(3):
        assert_contained(await gateway.call(PUBLIC_REQUEST, proposal()))
    assert backend.calls == ["1", "1", "1"]


async def test_separate_gateways_isolate_containment_even_with_shared_backend_and_judge() -> None:
    first, backend, judge = instance()
    second = Gateway(backend, judge, Trace())
    for _ in range(2):
        assert (await first.call("Execute payment.", proposal())).decision == "DENY"
    assert_contained(await first.call(PUBLIC_REQUEST, proposal()))
    public = await second.call(PUBLIC_REQUEST, proposal())
    assert public.decision == "PERMIT" and public.tool_executed
    assert backend.calls == ["1"]
    assert judge.calls == 1
    assert not any(event["stage"] == "execution_started" for event in first.trace.events)
    assert sum(event["stage"] == "execution_started" for event in second.trace.events) == 1


async def test_r1_second_mcp_wrapper_is_rejected_without_clearing_containment() -> None:
    gateway, backend, judge = instance()
    client_a_server = create_server(gateway)
    query = {"award_id": "1"}
    for _ in range(2):
        _, denied = await client_a_server.call_tool(
            "get_federal_award", {"user_request": "Execute payment.", "query": query}
        )
        assert denied["decision"] == "DENY"
        assert denied["tool_executed"] is False
    prior_events = len(gateway.trace.events)
    with pytest.raises(ValueError, match="already has an MCP server owner"):
        create_server(gateway)
    assert len(gateway.trace.events) == prior_events
    _, affected = await client_a_server.call_tool(
        "get_federal_award", {"user_request": PUBLIC_REQUEST, "query": query}
    )
    assert affected["decision"] == "DENY"
    assert "SESSION_CONTAINMENT_ACTIVE" in affected["governance"]["policy_reasons"]
    assert affected["tool_executed"] is False
    assert affected["dispatch_state"] == "NOT_DISPATCHED"
    assert backend.calls == [] and judge.calls == 0
    policy_events = [event for event in gateway.trace.events if event["stage"] == "policy"]
    completed = [event for event in gateway.trace.events if event["stage"] == "completed"]
    assert len(policy_events) == len(completed) == 3
    assert all(event["policy"]["decision"] == "DENY" for event in policy_events)
    assert all(event["judge_preflight_skipped"] is True for event in policy_events)
    assert "SESSION_CONTAINMENT_ACTIVE" not in policy_events[1]["policy"]["reasons"]
    assert "SESSION_CONTAINMENT_ACTIVE" in policy_events[2]["policy"]["reasons"]
    assert all(event["tool_executed"] is False for event in completed)
    assert not any(event["stage"] == "execution_started" for event in gateway.trace.events)


async def test_r1_discovery_and_rejected_rewrapper_preserve_existing_containment() -> None:
    gateway, backend, _ = instance()
    for _ in range(2):
        await gateway.call("Execute payment.", proposal())
    server = create_server(gateway)
    assert len(await server.list_tools()) == 4
    assert_contained(await gateway.call(PUBLIC_REQUEST, proposal()))
    with pytest.raises(ValueError, match="already has an MCP server owner"):
        create_server(gateway)
    _, result = await server.call_tool(
        "get_federal_award", {"user_request": PUBLIC_REQUEST, "query": {"award_id": "1"}}
    )
    assert result["decision"] == "DENY"
    assert "SESSION_CONTAINMENT_ACTIVE" in result["governance"]["policy_reasons"]
    assert backend.calls == []


async def test_benign_high_risk_terms_can_trigger_instance_wide_availability_loss() -> None:
    gateway, backend, judge = instance()
    # Reporting requests do not ask this tool to decide fraud or execute a payment.
    for request in [
        "Retrieve public award details for a report about fraud prevention.",
        "Retrieve public award details for research on eligibility terminology.",
    ]:
        result = await gateway.call(request, proposal())
        assert result.decision == "DENY"
        assert "DENIED_AUTHORITY" in result.governance.policy_reasons
        assert not result.tool_executed
    assert_contained(await gateway.call(PUBLIC_REQUEST, proposal()))
    assert backend.calls == [] and judge.calls == 0


async def test_agent_k_disabled_by_trusted_configuration_disables_repeated_denial_hold() -> None:
    gateway, backend, _ = instance(enable_agent_k=False)
    for _ in range(2):
        denied = await gateway.call("Execute payment.", proposal())
        assert denied.decision == "DENY" and not denied.tool_executed
    public = await gateway.call(PUBLIC_REQUEST, proposal())
    assert public.decision == "PERMIT" and public.tool_executed
    assert backend.calls == ["1"]


async def test_shared_gateway_serializes_calls_while_synthetic_backend_is_waiting() -> None:
    entered_backend = asyncio.Event()
    release_backend = asyncio.Event()

    class WaitingAdapter(CountingAdapter):
        async def detail(self, request: Award) -> AdapterCall:
            entered_backend.set()
            await release_backend.wait()
            return await super().detail(request)

    backend = WaitingAdapter()
    gateway = Gateway(backend, SyntheticJudge(), Trace())
    first = asyncio.create_task(gateway.call(PUBLIC_REQUEST, proposal()))
    await entered_backend.wait()
    queued = asyncio.Event()

    async def second_client() -> Any:
        queued.set()
        return await gateway.call(PUBLIC_REQUEST, proposal())

    second = asyncio.create_task(second_client())
    await queued.wait()
    assert not first.done() and not second.done()
    assert sum(event["stage"] == "proposal" for event in gateway.trace.events) == 1
    release_backend.set()
    results = await asyncio.gather(first, second)
    assert all(result.decision == "PERMIT" and result.tool_executed for result in results)
    assert backend.calls == ["1", "1"]
