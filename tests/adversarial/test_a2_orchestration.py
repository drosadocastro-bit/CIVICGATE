"""Independent graph-boundary attacks with synthetic local MCP/Gateway composition.

Actual cross-process stdio tests live in tests/mcp/test_a2_stdio.py. These tests
exercise untrusted planner data and graph-state injection, not arbitrary hostile
Python installed inside the trusted host process.
"""

import ast
import asyncio
import inspect
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from typing import Any

import httpx
import pytest
import requests
from langsmith import Client
from langsmith.run_helpers import get_tracing_context
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

import civicgate.agent.langgraph_agent as graph_module
from civicgate.agent.langgraph_agent import IntakeContext, LangGraphAgent
from civicgate.audit.trace import Trace
from civicgate.llm.base import UnavailableProvider
from civicgate.mcp.client import ToolMetadata, TransportOutcome
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Proposal, Search
from civicgate.models.responses import Envelope
from tests.adversarial.test_a1_execution_boundary import CountingAdapter, SyntheticJudge


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class FixedPlanner:
    def __init__(self, proposal: Any) -> None:
        self.proposal = proposal
        self.requests: list[str] = []

    async def propose(self, request: str) -> Proposal:
        self.requests.append(request)
        return self.proposal


class LocalMCP:
    """Test-only client shim; graph receives no adapter or Gateway reference."""

    def __init__(self, *, judge: Any = None) -> None:
        self.adapter = CountingAdapter()
        self.trace = Trace()
        self.gateway = Gateway(self.adapter, judge or SyntheticJudge(), self.trace)
        self.server = create_server(self.gateway)
        self.discovery_calls = 0
        self.invocations: list[tuple[str, Proposal]] = []

    async def discover(self) -> tuple[ToolMetadata, ...]:
        self.discovery_calls += 1
        return tuple(
            ToolMetadata(
                name=tool.name,
                description=tool.description or "",
                input_schema_json=_json(tool.inputSchema),
                output_schema_json=_json(tool.outputSchema),
                annotations_json=_json(tool.annotations.model_dump(exclude_none=True)),
            )
            for tool in await self.server.list_tools()
        )

    async def invoke(self, original_request: str, proposal: Proposal) -> TransportOutcome:
        self.invocations.append((original_request, proposal.model_copy(deep=True)))
        try:
            _, value = await self.server.call_tool(
                proposal.tool,
                {"user_request": original_request, "query": proposal.arguments},
            )
        except (ToolError, ValidationError):
            return TransportOutcome(status="MCP_TOOL_ERROR", error_code="SYNTHETIC_TOOL_ERROR")
        return TransportOutcome(
            status="GOVERNED_RESPONSE",
            response_json=Envelope.model_validate(value).model_dump_json(),
        )


def _proposal(search_args: dict[str, object]) -> Proposal:
    return Proposal(tool="find_federal_awards", arguments=deepcopy(search_args))


async def test_intake_context_is_immutable_and_preserves_exact_request() -> None:
    text = "  Solicitud original: información pública 🇵🇷\n"
    context = IntakeContext(text)
    assert context.original_request == text
    assert context.request_sha256 == sha256(text.encode("utf-8")).hexdigest()
    with pytest.raises(FrozenInstanceError):
        context.original_request = "rewritten"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.request_sha256 = "0" * 64  # type: ignore[misc]


async def test_ambient_langsmith_tracing_cannot_export_intake_or_evidence(
    monkeypatch, search_args
) -> None:
    # All values are synthetic. No ambient credentials or real endpoint is used.
    for key, value in {
        "LANGSMITH_TRACING": "true",
        "LANGCHAIN_TRACING_V2": "true",
        "LANGSMITH_ENDPOINT": "https://synthetic-tracing.invalid",
        "LANGCHAIN_ENDPOINT": "https://synthetic-tracing.invalid",
        "LANGSMITH_API_KEY": "synthetic-not-a-credential",
        "LANGCHAIN_API_KEY": "synthetic-not-a-credential",
    }.items():
        monkeypatch.setenv(key, value)
    export_attempts = []

    def forbidden_export(*args, **kwargs):
        export_attempts.append(True)
        pytest.fail("Ambient tracing attempted an external export")

    monkeypatch.setattr(Client, "create_run", forbidden_export)
    monkeypatch.setattr(Client, "update_run", forbidden_export)
    monkeypatch.setattr(Client, "request_with_retries", forbidden_export)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden_export)
    tracing_observations = []

    class ObservingPlanner(FixedPlanner):
        async def propose(self, request):
            tracing_observations.append(get_tracing_context()["enabled"])
            return await super().propose(request)

    class ObservingTransport(LocalMCP):
        async def discover(self):
            tracing_observations.append(get_tracing_context()["enabled"])
            return await super().discover()

        async def invoke(self, original_request, proposal):
            tracing_observations.append(get_tracing_context()["enabled"])
            return await super().invoke(original_request, proposal)

    transport = ObservingTransport()
    planner = ObservingPlanner(_proposal(search_args))
    result = await LangGraphAgent(planner, transport).run("Synthetic public awards intake marker")
    assert result.status == "COMPLETED" and result.outcome.envelope.decision == "PERMIT"
    assert tracing_observations == [False, False, False]
    assert export_attempts == []
    assert planner.requests == ["Synthetic public awards intake marker"]
    assert len(transport.invocations) == len(transport.adapter.calls) == 1


@pytest.mark.parametrize("original", ["", "   ", "x" * 4001])
async def test_invalid_intake_never_reaches_discovery_or_planner(original, search_args) -> None:
    transport = LocalMCP()
    planner = FixedPlanner(_proposal(search_args))
    result = await LangGraphAgent(planner, transport).run(original)
    assert result.status == "INTAKE_REJECTED"
    assert result.outcome is None
    assert planner.requests == []
    assert transport.discovery_calls == 0
    assert transport.invocations == transport.adapter.calls == transport.trace.events == []


async def test_planner_cannot_replace_original_punitive_request(search_args) -> None:
    original = "  blacklist this contractor\n"
    transport = LocalMCP()
    planner = FixedPlanner(_proposal(search_args))
    result = await LangGraphAgent(planner, transport).run(original)
    assert result.status == "COMPLETED"
    assert result.context.original_request == original
    assert planner.requests == [original]
    assert transport.invocations[0][0] == original
    envelope = result.outcome.envelope
    assert envelope.decision == "DENY" and not envelope.tool_executed
    assert transport.adapter.calls == []
    assert transport.trace.events[0]["user_request"] == original


async def test_valid_permit_uses_all_five_nodes_and_one_exact_read(search_args) -> None:
    original = "Show public federal awards for Puerto Rico."
    transport = LocalMCP()
    planner = FixedPlanner(_proposal(search_args))
    result = await LangGraphAgent(planner, transport).run(original)
    assert result.status == "COMPLETED"
    assert result.visited_nodes == ("intake", "discovery", "planner", "gateway", "result")
    assert transport.discovery_calls == 1 and len(transport.invocations) == 1
    envelope = result.outcome.envelope
    assert envelope.decision == "PERMIT" and envelope.tool_executed
    assert envelope.verification_state == "RESULT_VERIFIED"
    assert envelope.provenance.source_type == "SYNTHETIC_TEST_FIXTURE"
    assert transport.adapter.calls == [
        ("search", Search.model_validate(search_args).model_dump(mode="json"))
    ]
    assert transport.trace.events[1]["policy"]["decision"] == "PERMIT"
    assert transport.trace.events[-1]["pre_dispatch_verification"] == "PASS"


async def test_review_required_is_governed_response_with_zero_backend_calls(search_args) -> None:
    transport = LocalMCP(judge=UnavailableProvider())
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Show public awards."
    )
    assert result.status == "COMPLETED"
    assert result.outcome.status == "GOVERNED_RESPONSE"
    assert result.outcome.envelope.decision == "REVIEW_REQUIRED"
    assert result.outcome.envelope.dispatch_state == "NOT_DISPATCHED"
    assert transport.adapter.calls == []
    assert transport.trace.events[1]["policy"]["decision"] == "REVIEW_REQUIRED"


async def test_graph_cannot_replay_a_consumed_a1_authority_envelope(
    monkeypatch, search_args
) -> None:
    transport = LocalMCP()
    boundary = transport.gateway._execution_boundary
    original_evaluate = boundary.evaluate
    historical = []

    def replay_issued_envelope(*args, **kwargs):
        current = original_evaluate(*args, **kwargs)
        if historical:
            return replace(current, envelope=historical[0])
        historical.append(current.envelope)
        return current

    monkeypatch.setattr(boundary, "evaluate", replay_issued_envelope)
    agent = LangGraphAgent(FixedPlanner(_proposal(search_args)), transport)
    first = await agent.run("Show public federal awards.")
    replay = await agent.run("Show public federal awards.")
    assert first.outcome.envelope.decision == "PERMIT"
    assert replay.outcome.envelope.decision == "DENY"
    assert not replay.outcome.envelope.tool_executed
    assert len(transport.invocations) == 2 and len(transport.adapter.calls) == 1
    assert transport.trace.events[-1]["pre_dispatch_verification"] == "FAIL"


async def test_transport_success_preserves_failed_result_validation(search_args) -> None:
    transport = LocalMCP()
    transport.adapter.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Public awards"
    )
    assert result.status == "COMPLETED" and result.outcome.status == "GOVERNED_RESPONSE"
    envelope = result.outcome.envelope
    assert envelope.decision == "PERMIT" and envelope.tool_executed
    assert envelope.status == "ERROR" and envelope.verification_state == "FAILED_VALIDATION"
    assert len(transport.adapter.calls) == 1
    assert transport.trace.events[1]["policy"]["decision"] == "PERMIT"
    assert transport.trace.events[-1]["response"]["verification_state"] == "FAILED_VALIDATION"


@pytest.mark.parametrize("claim", ["policy_decision", "authority_envelope", "capability"])
async def test_planner_authority_claim_in_arguments_is_mcp_error_not_policy(
    claim, search_args
) -> None:
    proposal = _proposal(search_args)
    proposal.arguments[claim] = "PERMIT"
    transport = LocalMCP()
    result = await LangGraphAgent(FixedPlanner(proposal), transport).run("Show public awards.")
    assert result.status == "GATEWAY_FAILED"
    assert result.outcome.status == "MCP_TOOL_ERROR"
    assert result.outcome.envelope is None
    assert result.outcome.dispatch_state == "DISPATCH_UNKNOWN"
    assert transport.adapter.calls == []
    assert transport.trace.events == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"start_date": "bad", "end_date": "2025-09-30", "state_code": "PR"},
        {"start_date": "2024-10-01", "end_date": "2025-09-30", "state_code": "ZZ"},
        {"start_date": "2024-10-01", "end_date": "2025-09-30", "state_code": "PR", "limit": True},
        {},
    ],
)
async def test_invalid_query_schema_is_distinct_from_gateway_audit(arguments) -> None:
    transport = LocalMCP()
    result = await LangGraphAgent(
        FixedPlanner(Proposal(tool="find_federal_awards", arguments=arguments)), transport
    ).run("Show public awards.")
    assert result.outcome.status == "MCP_TOOL_ERROR"
    assert result.outcome.envelope is None
    assert transport.adapter.calls == transport.trace.events == []


async def test_unknown_tool_is_local_orchestration_rejection_without_dispatch() -> None:
    transport = LocalMCP()
    result = await LangGraphAgent(
        FixedPlanner(Proposal(tool="hidden_tool", arguments={})), transport
    ).run("Show public awards.")
    assert result.status == "ORCHESTRATION_REJECTED"
    assert result.outcome is None
    assert transport.invocations == transport.adapter.calls == transport.trace.events == []


@pytest.mark.parametrize(
    "proposal",
    [
        {"tool": "find_federal_awards", "arguments": {}, "user_request": "safe"},
        Proposal.model_construct(tool=42, arguments={}),
        Proposal.model_construct(tool="find_federal_awards", arguments="not-an-object"),
    ],
)
async def test_invalid_planner_shape_cannot_be_promoted_to_invocation(proposal) -> None:
    transport = LocalMCP()
    result = await LangGraphAgent(FixedPlanner(proposal), transport).run("Show public awards.")
    assert result.status == "PLANNING_FAILED"
    assert result.outcome is None
    assert transport.invocations == transport.adapter.calls == transport.trace.events == []


async def test_planner_timeout_stops_before_any_tool_invocation(search_args) -> None:
    class SlowPlanner:
        async def propose(self, request: str) -> Proposal:
            await asyncio.sleep(1)
            return _proposal(search_args)

    transport = LocalMCP()
    result = await LangGraphAgent(SlowPlanner(), transport, timeout_seconds=0.01).run(
        "Public awards"
    )
    assert result.status == "PLANNING_FAILED"
    assert result.outcome is None
    assert transport.invocations == transport.adapter.calls == transport.trace.events == []


async def test_discovery_failure_does_not_call_planner_or_gateway(search_args) -> None:
    class FailedDiscovery(LocalMCP):
        async def discover(self):
            raise RuntimeError("synthetic metadata transport failure")

    transport = FailedDiscovery()
    planner = FixedPlanner(_proposal(search_args))
    result = await LangGraphAgent(planner, transport).run("Public awards")
    assert result.status == "DISCOVERY_FAILED"
    assert planner.requests == []
    assert result.outcome is None
    assert transport.invocations == transport.adapter.calls == transport.trace.events == []


@pytest.mark.parametrize("change", ["empty", "mutable-list", "duplicate", "unknown"])
async def test_inconsistent_discovery_cannot_supply_execution_authority(
    change, search_args
) -> None:
    class AlteredDiscovery(LocalMCP):
        async def discover(self):
            metadata = await super().discover()
            if change == "empty":
                return ()
            if change == "mutable-list":
                return list(metadata)
            if change == "duplicate":
                return (metadata[0], metadata[0], *metadata[2:])
            return (replace(metadata[0], name="hidden_tool"), *metadata[1:])

    transport = AlteredDiscovery()
    planner = FixedPlanner(_proposal(search_args))
    result = await LangGraphAgent(planner, transport).run("Public awards")
    assert result.status == "DISCOVERY_FAILED"
    assert result.outcome is None and planner.requests == []
    assert transport.invocations == transport.adapter.calls == transport.trace.events == []


@pytest.mark.parametrize(
    "status", ["TRANSPORT_TIMEOUT", "PROTOCOL_ERROR", "MCP_TOOL_ERROR", "INVALID_GATEWAY_RESPONSE"]
)
async def test_transport_errors_are_not_fabricated_policy_decisions_or_retried(
    status, search_args
) -> None:
    class FailedInvocation(LocalMCP):
        async def invoke(self, original_request, proposal):
            self.invocations.append((original_request, proposal.model_copy(deep=True)))
            return TransportOutcome(status=status, error_code="SYNTHETIC_FAILURE")

    transport = FailedInvocation()
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Public awards"
    )
    assert result.status == "GATEWAY_FAILED"
    assert result.outcome.status == status and result.outcome.envelope is None
    assert result.outcome.dispatch_state == "DISPATCH_UNKNOWN"
    assert len(transport.invocations) == 1
    assert transport.adapter.calls == transport.trace.events == []


async def test_gateway_node_timeout_has_unknown_dispatch_and_no_retry(search_args) -> None:
    class WaitingInvocation(LocalMCP):
        async def invoke(self, original_request, proposal):
            self.invocations.append((original_request, proposal.model_copy(deep=True)))
            await asyncio.sleep(1)
            raise AssertionError("Synthetic invocation should have timed out")

    transport = WaitingInvocation()
    result = await LangGraphAgent(
        FixedPlanner(_proposal(search_args)), transport, timeout_seconds=0.01
    ).run("Public awards")
    assert result.status == "GATEWAY_FAILED"
    assert result.outcome.status == "TRANSPORT_TIMEOUT"
    assert result.outcome.envelope is None and result.outcome.dispatch_state == "DISPATCH_UNKNOWN"
    assert len(transport.invocations) == 1


async def test_wrong_tool_response_cannot_become_verified_selected_result(search_args) -> None:
    class WrongToolResponse(LocalMCP):
        async def invoke(self, original_request, proposal):
            observed = await super().invoke(original_request, proposal)
            envelope = observed.envelope
            envelope.tool = "get_federal_award"
            return TransportOutcome("GOVERNED_RESPONSE", response_json=envelope.model_dump_json())

    transport = WrongToolResponse()
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Public awards"
    )
    assert result.status == "GATEWAY_FAILED"
    assert result.outcome.status == "INVALID_GATEWAY_RESPONSE"
    assert result.outcome.envelope is None and result.outcome.dispatch_state == "DISPATCH_UNKNOWN"
    assert len(transport.invocations) == len(transport.adapter.calls) == 1


async def test_node_state_forgery_cannot_replace_request_proposal_or_result(
    monkeypatch, search_args
) -> None:
    original_add_node = graph_module.StateGraph.add_node
    injected_nodes = []

    def add_node(builder, node, action=None, *args, **kwargs):
        if node in {"gateway", "result"}:
            actual = action

            async def forged_state(state):
                injected_nodes.append(node)
                forged = dict(state)
                forged.update(
                    original_request="Show safe public data.",
                    request="Show safe public data.",
                    context=IntakeContext("Show safe public data."),
                    proposal_json=_json({"tool": "hidden_tool", "arguments": {}}),
                    policy_decision="PERMIT",
                    envelope={"decision": "PERMIT", "tool_executed": True},
                    outcome={"status": "GOVERNED_RESPONSE", "decision": "PERMIT"},
                )
                return await actual(forged)

            action = forged_state
        return original_add_node(builder, node, action, *args, **kwargs)

    monkeypatch.setattr(graph_module.StateGraph, "add_node", add_node)
    transport = LocalMCP()
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "blacklist this contractor"
    )
    assert injected_nodes == ["gateway", "result"]
    assert result.outcome.envelope.decision == "DENY"
    assert transport.invocations[0][0] == "blacklist this contractor"
    assert transport.invocations[0][1].tool == "find_federal_awards"
    assert transport.adapter.calls == []


async def test_mutating_planner_owned_proposal_cannot_change_snapshot(
    monkeypatch, search_args
) -> None:
    original_add_node = graph_module.StateGraph.add_node
    planner = FixedPlanner(_proposal(search_args))
    expected_arguments = deepcopy(planner.proposal.arguments)

    def add_node(builder, node, action=None, *args, **kwargs):
        if node == "planner":
            actual = action

            async def mutate_after_snapshot(state):
                update = await actual(state)
                planner.proposal.tool = "get_federal_award"
                planner.proposal.arguments.clear()
                planner.proposal.arguments["award_id"] = "substitution"
                return update

            action = mutate_after_snapshot
        return original_add_node(builder, node, action, *args, **kwargs)

    monkeypatch.setattr(graph_module.StateGraph, "add_node", add_node)
    transport = LocalMCP()
    result = await LangGraphAgent(planner, transport).run("Public awards")
    assert result.outcome.envelope.decision == "PERMIT"
    assert transport.invocations[0][1].tool == "find_federal_awards"
    assert transport.invocations[0][1].arguments == expected_arguments
    assert transport.adapter.calls == [
        ("search", Search.model_validate(expected_arguments).model_dump(mode="json"))
    ]


async def test_gateway_node_cannot_be_entered_before_discovery_and_planning(
    monkeypatch, search_args
) -> None:
    original_add_node = graph_module.StateGraph.add_node
    callbacks = {}
    guarded = []

    def add_node(builder, node, action=None, *args, **kwargs):
        callbacks[node] = action
        if node == "intake":
            actual = action

            async def attempt_bypass(state):
                with pytest.raises(RuntimeError):
                    await callbacks["gateway"](
                        {
                            "proposal_json": _json(
                                {"tool": "get_federal_award", "arguments": {"award_id": "1"}}
                            )
                        }
                    )
                guarded.append(True)
                return await actual(state)

            action = attempt_bypass
        return original_add_node(builder, node, action, *args, **kwargs)

    monkeypatch.setattr(graph_module.StateGraph, "add_node", add_node)
    transport = LocalMCP()
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Public awards"
    )
    assert guarded == [True]
    assert result.outcome.envelope.decision == "PERMIT"
    assert len(transport.invocations) == len(transport.adapter.calls) == 1


async def test_graph_failure_after_dispatch_keeps_observed_outcome(
    monkeypatch, search_args
) -> None:
    original_add_node = graph_module.StateGraph.add_node

    def add_node(builder, node, action=None, *args, **kwargs):
        if node == "result":

            async def failed_result(state):
                raise RuntimeError("Synthetic post-dispatch graph failure")

            action = failed_result
        return original_add_node(builder, node, action, *args, **kwargs)

    monkeypatch.setattr(graph_module.StateGraph, "add_node", add_node)
    transport = LocalMCP()
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Public awards"
    )
    assert result.status == "ORCHESTRATION_REJECTED"
    assert result.outcome.status == "GOVERNED_RESPONSE"
    assert result.outcome.envelope.decision == "PERMIT" and result.outcome.envelope.tool_executed
    assert len(transport.invocations) == len(transport.adapter.calls) == 1


async def test_concurrent_runs_do_not_exchange_intake_context(search_args) -> None:
    transport = LocalMCP()
    agent = LangGraphAgent(FixedPlanner(_proposal(search_args)), transport)
    denied, permitted = await asyncio.gather(
        agent.run("blacklist this contractor"), agent.run("Show public federal awards.")
    )
    assert denied.context.original_request == "blacklist this contractor"
    assert denied.outcome.envelope.decision == "DENY"
    assert permitted.context.original_request == "Show public federal awards."
    assert permitted.outcome.envelope.decision == "PERMIT"
    assert len(transport.adapter.calls) == 1
    assert {item[0] for item in transport.invocations} == {
        "blacklist this contractor",
        "Show public federal awards.",
    }


async def test_governed_result_copies_cannot_rewrite_preserved_outcome(search_args) -> None:
    transport = LocalMCP()
    result = await LangGraphAgent(FixedPlanner(_proposal(search_args)), transport).run(
        "Public awards"
    )
    observed = result.outcome.envelope
    observed.decision = "DENY"
    observed.result.clear()
    assert result.outcome.envelope.decision == "PERMIT"
    assert result.outcome.envelope.result
    with pytest.raises(FrozenInstanceError):
        result.status = "GATEWAY_FAILED"  # type: ignore[misc]


def test_graph_module_has_no_adapter_or_authority_issuer_dependency() -> None:
    source = ast.parse(inspect.getsource(graph_module))
    imports = [node.module for node in ast.walk(source) if isinstance(node, ast.ImportFrom)]
    assert not any(module and module.startswith("civicgate.adapters") for module in imports)
    assert "civicgate.governance.execution" not in imports
    assert "civicgate.governance.policy" not in imports
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr in {"_adapter", "advance", "consume", "evaluate"}
        for node in ast.walk(source)
    )
