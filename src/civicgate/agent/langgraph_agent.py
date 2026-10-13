"""Minimal local orchestration over the existing governed MCP transport.

The host captures the original request before any await. Graph state and planner
output cannot supply a replacement request, policy decision or execution token.
This is a trusted local composition boundary, not authentication of user intent
or a sandbox against arbitrary Python installed in the trusted host process.
"""

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langsmith import tracing_context
from typing_extensions import TypedDict

from civicgate.llm.base import AgentModel
from civicgate.mcp.client import GovernedMCPTransport, ToolMetadata, TransportOutcome
from civicgate.models.requests import TOOLS, Proposal

OrchestrationStatus = Literal[
    "COMPLETED",
    "INTAKE_REJECTED",
    "DISCOVERY_FAILED",
    "PLANNING_FAILED",
    "ORCHESTRATION_REJECTED",
    "GATEWAY_FAILED",
]


@dataclass(frozen=True)
class IntakeContext:
    """Host-captured text; its digest establishes integrity, not human identity."""

    original_request: str
    request_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.original_request) is not str:
            raise TypeError("The original request must be a string")
        object.__setattr__(
            self,
            "request_sha256",
            hashlib.sha256(self.original_request.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True)
class OrchestrationResult:
    context: IntakeContext
    visited_nodes: tuple[str, ...]
    status: OrchestrationStatus
    outcome: TransportOutcome | None = None
    error_code: str | None = None


class _GraphState(TypedDict, total=False):
    node: str


@dataclass
class _Run:
    """Private invocation data; graph channel updates are never authority inputs."""

    context: IntakeContext
    next_node: str = "intake"
    visited: list[str] = field(default_factory=list)
    metadata: tuple[ToolMetadata, ...] = ()
    proposal_json: str | None = None
    outcome: TransportOutcome | None = None
    status: OrchestrationStatus = "ORCHESTRATION_REJECTED"
    error_code: str | None = None
    result: OrchestrationResult | None = None

    def enter(self, node: str) -> None:
        if self.next_node != node:
            raise RuntimeError("Orchestration node sequencing violation")
        self.visited.append(node)
        self.next_node = "RUNNING"

    def reject(self, status: OrchestrationStatus, error_code: str) -> None:
        self.status = status
        self.error_code = error_code
        self.next_node = "result"


class LangGraphAgent:
    """One bounded plan and one MCP invocation; no adapters or authority issuer.

    The existing AgentModel interface also admits GranitePlanner. Tests and the
    synthetic demo inject deterministic planners and a local fixture MCP server.
    Compiled graphs are private and scoped to exactly one host-captured intake.
    No checkpoints, retries, external callbacks or recursive tool loop are used.
    """

    def __init__(
        self,
        model: AgentModel,
        transport: GovernedMCPTransport,
        *,
        timeout_seconds: float = 30,
    ) -> None:
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Timeout must be finite and positive")
        self._model = model
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    async def run(self, request: str) -> OrchestrationResult:
        # Capture before discovery, planner execution or any other awaited work.
        run = _Run(IntakeContext(request))
        graph = self._build_graph(run)
        try:
            # Ambient LangSmith configuration must not export request/evidence.
            with tracing_context(enabled=False):
                await graph.ainvoke(
                    {"node": "pending"},
                    config={"callbacks": [], "recursion_limit": 8},
                )
        except Exception:
            # An observed transport result remains available even if later graph
            # handling fails. Never dispatch or retry as an error fallback.
            return OrchestrationResult(
                run.context,
                tuple(run.visited),
                "ORCHESTRATION_REJECTED",
                run.outcome,
                "GRAPH_EXECUTION_ERROR",
            )
        if run.result is None:
            return OrchestrationResult(
                run.context,
                tuple(run.visited),
                "ORCHESTRATION_REJECTED",
                run.outcome,
                "GRAPH_RESULT_MISSING",
            )
        return run.result

    def _build_graph(
        self, run: _Run
    ) -> CompiledStateGraph[_GraphState, None, _GraphState, _GraphState]:
        async def intake(state: _GraphState) -> _GraphState:
            run.enter("intake")
            if not 0 < len(run.context.original_request.strip()) <= 4000:
                run.reject("INTAKE_REJECTED", "INVALID_ORIGINAL_REQUEST")
            else:
                run.next_node = "discovery"
            return {"node": "intake"}

        async def discovery(state: _GraphState) -> _GraphState:
            run.enter("discovery")
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    metadata = await self._transport.discover()
                if (
                    type(metadata) is not tuple
                    or len(metadata) != len(TOOLS)
                    or any(type(item) is not ToolMetadata for item in metadata)
                    or {item.name for item in metadata} != set(TOOLS)
                ):
                    raise ValueError("Unexpected bounded discovery contract")
                # Immutable metadata contains no AuthorityEnvelope or policy
                # result. The MCP server owns authoritative schema validation.
                run.metadata = metadata
                run.next_node = "planner"
            except TimeoutError:
                run.reject("DISCOVERY_FAILED", "DISCOVERY_TIMEOUT")
            except Exception:
                run.reject("DISCOVERY_FAILED", "DISCOVERY_CONTRACT_ERROR")
            return {"node": "discovery"}

        async def planner(state: _GraphState) -> _GraphState:
            run.enter("planner")
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    supplied = await self._model.propose(run.context.original_request)
                proposal = Proposal.model_validate(supplied.model_dump(mode="json"))
                if proposal.tool not in {item.name for item in run.metadata}:
                    run.reject("ORCHESTRATION_REJECTED", "UNDISCOVERED_TOOL")
                else:
                    run.proposal_json = json.dumps(
                        proposal.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    run.next_node = "gateway"
            except TimeoutError:
                run.reject("PLANNING_FAILED", "PLANNER_TIMEOUT")
            except Exception:
                run.reject("PLANNING_FAILED", "INVALID_PLANNER_PROPOSAL")
            return {"node": "planner"}

        async def gateway(state: _GraphState) -> _GraphState:
            run.enter("gateway")
            if run.proposal_json is None:
                run.reject("ORCHESTRATION_REJECTED", "PLANNER_SNAPSHOT_MISSING")
                return {"node": "gateway"}
            proposal = Proposal.model_validate_json(run.proposal_json)
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    outcome = await self._transport.invoke(run.context.original_request, proposal)
                if type(outcome) is not TransportOutcome:
                    raise ValueError("Invalid transport outcome")
                envelope = outcome.envelope
                if outcome.status == "GOVERNED_RESPONSE" and (
                    envelope is None or envelope.tool != proposal.tool
                ):
                    raise ValueError("Gateway response is not bound to the selected tool")
                run.outcome = outcome
            except TimeoutError:
                run.outcome = TransportOutcome(
                    "TRANSPORT_TIMEOUT", error_code="ORCHESTRATION_GATEWAY_TIMEOUT"
                )
            except Exception:
                run.outcome = TransportOutcome(
                    "INVALID_GATEWAY_RESPONSE", error_code="ORCHESTRATION_TRANSPORT_ERROR"
                )
            run.status = (
                "COMPLETED" if run.outcome.status == "GOVERNED_RESPONSE" else "GATEWAY_FAILED"
            )
            run.error_code = run.outcome.error_code
            run.next_node = "result"
            return {"node": "gateway"}

        async def result(state: _GraphState) -> _GraphState:
            run.enter("result")
            # Ignore caller-injected response, policy and context fields. Only
            # the actual invocation outcome may become returned evidence.
            run.result = OrchestrationResult(
                run.context,
                tuple(run.visited),
                run.status,
                run.outcome,
                run.error_code,
            )
            run.next_node = "DONE"
            return {"node": "result"}

        def route(_state: _GraphState) -> str:
            return run.next_node

        graph = StateGraph(_GraphState)
        graph.add_node("intake", intake)
        graph.add_node("discovery", discovery)
        graph.add_node("planner", planner)
        graph.add_node("gateway", gateway)
        graph.add_node("result", result)
        graph.add_edge(START, "intake")
        graph.add_conditional_edges("intake", route, ["discovery", "result"])
        graph.add_conditional_edges("discovery", route, ["planner", "result"])
        graph.add_conditional_edges("planner", route, ["gateway", "result"])
        graph.add_edge("gateway", "result")
        graph.add_edge("result", END)
        return graph.compile()
