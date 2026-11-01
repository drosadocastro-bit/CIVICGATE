"""EVAL-002A-R4 offline composition with write-ahead observation custody.

The sole CLI is a synthetic stdio child. No credential/configuration factory or
real-provider entrypoint is exposed. Resource reservations never authorize tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from civicgate.adapters.usaspending import AdapterCall
from civicgate.agent.langgraph_agent import LangGraphAgent
from civicgate.mcp.client import ToolMetadata, TransportOutcome
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope
from evals.harness.attempt_budget_v2 import AttemptBudget, BudgetError
from evals.harness.bounded_provider_v3 import (
    DeadlinePlan,
    build_bound_providers,
    digest,
)
from evals.harness.evidence import canonical, child_environment, sha256, write_new
from evals.harness.governance_observer_v2 import OBSERVER_VERSION, ReadOnlyGovernanceObserver
from evals.harness.runner import ObservedTransport
from evals.harness.synthetic_server import (
    EvidenceLedger,
    SyntheticAdapter,
    SyntheticTrace,
    install_network_guard,
)
from evals.harness.synthetic_server_v2 import ResponseLossTrace

SYNTHETIC_GRANITE_MODEL = "SYNTHETIC_GRANITE_CONTRACT_STUB"
MODES = frozenset({"normal", "timeout", "mismatch", "missing_model", "malformed", "unavailable"})
_DATASET_GUARD_INSTALLED = False


def install_dataset_guard() -> None:
    """Evaluation worker lifetime only: no dataset is an input to these fixtures."""
    global _DATASET_GUARD_INSTALLED
    if _DATASET_GUARD_INSTALLED:
        return
    dataset_root = Path(__file__).resolve().parents[1] / "datasets"

    def audit(event: str, arguments: tuple[Any, ...]) -> None:
        if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(arguments[0])).resolve()
            if path.is_relative_to(dataset_root):
                raise PermissionError("EVAL002A_DATASET_ACCESS_DISABLED")

    sys.addaudithook(audit)
    _DATASET_GUARD_INSTALLED = True


@dataclass(frozen=True)
class OfflineScenario:
    request: str = "Show public federal awards."
    proposal_tool: str = "find_federal_awards"
    proposal_arguments_json: str = (
        '{"start_date":"2025-01-01","end_date":"2025-02-01","state_code":"PR"}'
    )
    planner_mode: str = "normal"
    judge_mode: str = "normal"
    judge_flags: tuple[str, ...] = ()
    backend_mode: str = "normal"
    drop_response: bool = False

    def __post_init__(self) -> None:
        if self.planner_mode not in MODES or self.judge_mode not in MODES:
            raise ValueError("OFFLINE_SCENARIO_MODE_UNSUPPORTED")
        if type(self.request) is not str or type(self.drop_response) is not bool:
            raise ValueError("OFFLINE_SCENARIO_TYPE_INVALID")
        if type(self.judge_flags) is not tuple:
            raise ValueError("OFFLINE_FLAGS_MUST_BE_IMMUTABLE")
        if type(json.loads(self.proposal_arguments_json)) is not dict:
            raise ValueError("OFFLINE_ARGUMENT_OBJECT_REQUIRED")

    def proposal(self) -> Proposal:
        return Proposal(tool=self.proposal_tool, arguments=json.loads(self.proposal_arguments_json))


def effective_invocation_digest(request: str, proposal: Proposal) -> str:
    """Same typed normalization as MCP query parsing, before authorization."""
    if proposal.tool not in TOOLS:
        raise ValueError("OFFLINE_UNREGISTERED_TOOL")
    query = TOOLS[proposal.tool].model_validate(proposal.arguments)
    return digest(
        {
            "user_request": request,
            "proposal": {
                "tool": proposal.tool,
                "arguments": query.model_dump(mode="json"),
            },
        }
    )


def provider_stub(role: str, scenario: OfflineScenario) -> httpx.MockTransport:
    """Deterministic protocol fixtures, never new semantic reference labels."""
    if role not in {"planner", "judge"}:
        raise ValueError("OFFLINE_PROVIDER_ROLE")
    mode = scenario.planner_mode if role == "planner" else scenario.judge_mode

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.path != "/v1/chat/completions":
            raise ValueError("OFFLINE_PROVIDER_ENDPOINT")
        payload = json.loads(request.content)
        model = SYNTHETIC_GRANITE_MODEL if role == "planner" else "gpt-5.6-luna"
        if payload.get("model") != model:
            raise ValueError("OFFLINE_REQUESTED_MODEL")
        if mode == "timeout":
            await asyncio.sleep(60)
        if mode == "unavailable":
            return httpx.Response(503, json={"error": {"type": "synthetic_unavailable"}})
        content: dict[str, Any]
        if role == "planner":
            content = scenario.proposal().model_dump(mode="json")
        else:
            content = {
                "classification": "IN_SCOPE",
                "confidence": 0.99,
                "flags": list(scenario.judge_flags),
                "rationale": "Explicit synthetic protocol fixture; not real-model evidence.",
            }
        if mode == "malformed":
            content = {}
        body: dict[str, Any] = {
            "model": model if mode != "mismatch" else "SYNTHETIC_WRONG_MODEL",
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
        }
        if mode == "missing_model":
            del body["model"]
        return httpx.Response(200, json=body)

    return httpx.MockTransport(respond)


@contextmanager
def parent_network_guard() -> Iterator[None]:
    """Scoped Python network denial, entered after loop creation; not an OS jail."""

    def deny(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("EVAL002A_OFFLINE_NETWORK_DISABLED")

    with (
        patch.object(socket.socket, "connect", deny),
        patch.object(socket.socket, "connect_ex", deny),
        patch.object(socket.socket, "sendto", deny),
        patch.object(socket, "getaddrinfo", deny),
        patch.object(socket, "create_connection", deny),
    ):
        yield


class GuardedSyntheticAdapter(SyntheticAdapter):
    def __init__(self, ledger: EvidenceLedger, mode: str, budget: AttemptBudget) -> None:
        super().__init__(ledger, mode)
        self._retained_transport = self.transport
        self._budget = budget

    async def _observe(
        self,
        method: str,
        query: Search | Award | Recipient,
        operation: Callable[[], Awaitable[AdapterCall]],
    ) -> AdapterCall:
        if (
            type(self.transport) is not httpx.MockTransport
            or self.transport is not self._retained_transport
            or self.fixture is not True
            or self.max_attempts != 1
        ):
            raise ValueError("EVAL002A_SYNTHETIC_BACKEND_INTEGRITY")
        self._budget.assert_active_observation()
        return await super()._observe(method, query, operation)


class EvaluationGateway(Gateway):
    """Additional resource admission only; policy and binding code stay original."""

    def __init__(
        self,
        adapter: GuardedSyntheticAdapter,
        judge: Any,
        trace: SyntheticTrace,
        budget: AttemptBudget,
        observation_id: str,
        observer: ReadOnlyGovernanceObserver,
    ) -> None:
        super().__init__(adapter, judge, trace)
        self._evaluation_budget = budget
        self._observation_id = observation_id
        self._observer = observer

    async def call(
        self, request: str, proposal: Proposal, planning_failed: bool = False
    ) -> Envelope:
        snapshot = proposal.model_copy(deep=True)
        self._evaluation_budget.assert_active_observation(self._observation_id)
        self._evaluation_budget.admit_mcp(
            self._observation_id, effective_invocation_digest(request, snapshot)
        )
        try:
            return await super().call(request, snapshot, planning_failed)
        finally:
            # Preserve real issuance/consumption evidence before the MCP reply.
            self._observer.close()


class ReservedMCPTransport:
    def __init__(
        self,
        observed: ObservedTransport,
        budget: AttemptBudget,
        observation_id: str,
        deadlines: DeadlinePlan,
    ) -> None:
        self.observed = observed
        self.budget = budget
        self.observation_id = observation_id
        self.deadlines = deadlines
        # The capability is accounting custody, never governance authority.
        self.budget.begin_observation(observation_id)
        self.received_outcome: TransportOutcome | None = None
        self.custody_incomplete = False
        self.custody_write_acknowledged = False
        self.custody_stop_acknowledged: bool | None = None
        self.stop_attempted = False
        self.stop_reason: str | None = None

    def _request_stop(self, reason: str) -> bool:
        self.stop_attempted = True
        self.stop_reason = self.stop_reason or reason
        try:
            self.budget.stop(reason)
        except BudgetError:
            self.custody_stop_acknowledged = False
            return False
        self.custody_stop_acknowledged = True
        return True

    def _stop_incomplete_custody(self) -> None:
        # A local refusal is immediate even when SQLite cannot acknowledge STOP.
        # Pending durable reservations remain intact for the recovery gate.
        self.custody_incomplete = True
        self._request_stop("MCP_RESULT_CUSTODY_INCOMPLETE")

    async def discover(self) -> tuple[ToolMetadata, ...]:
        if self.custody_incomplete:
            raise BudgetError("EVAL002A_CUSTODY_INCOMPLETE")
        async with asyncio.timeout(self.deadlines.mcp_seconds):
            result = await self.observed.discover()
        return tuple(result)

    async def invoke(self, request: str, proposal: Proposal) -> TransportOutcome:
        if self.custody_incomplete:
            return TransportOutcome("PROTOCOL_ERROR", error_code="EVAL002A_CUSTODY_INCOMPLETE")
        try:
            self.budget.ensure_recoverable()
            self.budget.assert_active_observation(self.observation_id)
            self.budget.reserve_mcp(
                self.observation_id, effective_invocation_digest(request, proposal)
            )
        except BudgetError:
            self._stop_incomplete_custody()
            return TransportOutcome("PROTOCOL_ERROR", error_code="EVAL002A_MCP_RESERVATION_FAILED")
        except ValueError:
            return TransportOutcome("PROTOCOL_ERROR", error_code="EVAL002A_MCP_RESERVATION_FAILED")
        try:
            async with asyncio.timeout(self.deadlines.mcp_seconds):
                result = await self.observed.invoke(request, proposal)
        except BaseException:
            # Set before cleanup: LangGraph may absorb the original interruption,
            # but an unacknowledged write must never become "RECORDED" afterward.
            self.custody_incomplete = True
            try:
                self.budget.finish_mcp(
                    self.observation_id,
                    "CLIENT_RECEIPT_UNKNOWN",
                    {"client_receipt_state": "UNKNOWN", "error_code": "MCP_CALL_INTERRUPTED"},
                )
            except BudgetError:
                self._stop_incomplete_custody()
            else:
                self.custody_write_acknowledged = True
                self.custody_incomplete = False
            raise
        envelope = result.envelope
        self.received_outcome = result
        receipt = "CLIENT_RESPONSE_OBSERVED" if envelope is not None else "CLIENT_RECEIPT_UNKNOWN"
        metadata: dict[str, Any] = {
            "client_receipt_state": receipt,
            "backend_dispatch_state": result.dispatch_state,
        }
        if envelope is not None:
            metadata["final_policy_disposition"] = envelope.decision
        if result.error_code:
            metadata["error_code"] = result.error_code
        try:
            self.budget.finish_mcp(self.observation_id, receipt, metadata)
        except BudgetError:
            # Preserve the actual received result, without claiming durable custody.
            self._stop_incomplete_custody()
        else:
            self.custody_write_acknowledged = True
        if envelope is not None and envelope.verification_state in {
            "RESULT_UNKNOWN",
            "FAILED_VALIDATION",
        }:
            if not self._request_stop("POST_RESULT_VALIDATION_OR_COMPLETION_FAILED"):
                self.custody_incomplete = True
        return result


def _json_lines(path: Path) -> list[dict[str, Any]]:
    # The child explicitly reserves even unused ledger streams. Missing is not
    # equivalent to an observed empty stream, and a partial final line is not a
    # completed projection. The observer separately seals its buffered capture.
    if not path.is_file() or path.is_symlink():
        raise ValueError("REQUIRED_EVIDENCE_STREAM_UNAVAILABLE")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("INCOMPLETE_EVIDENCE_STREAM")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    if any(type(row) is not dict for row in rows):
        raise ValueError("EVIDENCE_STREAM_OBJECT_REQUIRED")
    return rows


def _validate_observer_capture(events: list[dict[str, Any]], observation_id: str) -> None:
    integrities = [row for row in events if row.get("event") == "observer_integrity"]
    returns = [row for row in events if row.get("event") == "governance_return"]
    if len(integrities) != 1 or not events or events[-1] is not integrities[0]:
        raise ValueError("COMPLETE_OBSERVER_CAPTURE_REQUIRED")
    final = integrities[0]
    if (
        final.get("status") != "PASS"
        or final.get("profiler_intact") is not True
        or final.get("active_frames_at_close") != 0
        or final.get("failures") != []
        or type(final.get("matched_calls")) is not int
        or type(final.get("matched_returns")) is not int
        or type(final.get("active_frames_at_close")) is not int
        or final["matched_calls"] != len(returns)
        or final["matched_returns"] != len(returns)
        or len(events) != len(returns) + 1
        or any(
            row.get("correlation_id") != observation_id
            or row.get("observer_version") != OBSERVER_VERSION
            for row in events
        )
        or any(type(row.get("call_index")) is not int for row in returns)
        or sorted(row.get("call_index", -1) for row in returns) != list(range(1, len(returns) + 1))
    ):
        raise ValueError("OBSERVER_CAPTURE_INTEGRITY_UNVERIFIED")


def _child_provider_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("CHILD_PROVIDER_CAPTURE_UNAVAILABLE")
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError("INCOMPLETE_CHILD_PROVIDER_CAPTURE")
    captured = json.loads(raw)
    if type(captured) is not dict or set(captured) != {"planner", "judge"}:
        raise ValueError("CHILD_PROVIDER_CAPTURE_CONTRACT")
    if any(
        type(captured[role]) is not list
        or any(
            type(event) is not dict or type(event.get("event")) is not str
            for event in captured[role]
        )
        for role in ("planner", "judge")
    ):
        raise ValueError("CHILD_PROVIDER_CAPTURE_CONTRACT")
    return cast(list[dict[str, Any]], captured["planner"] + captured["judge"])


async def serve_offline(config_file: Path) -> None:
    install_dataset_guard()
    if (
        config_file.name != "offline-config.json"
        or any("holdout" in part.casefold() for part in config_file.parts)
        or config_file.is_symlink()
        or config_file.stat().st_size > 65_536
    ):
        raise ValueError("EVAL002A_CONFIG_OUTSIDE_OFFLINE_SCOPE")
    config = json.loads(config_file.read_bytes())
    if set(config) != {
        "mode",
        "budget_path",
        "run_id",
        "observation_id",
        "evidence_dir",
        "scenario",
        "observation_fence_id",
    }:
        raise ValueError("EVAL002A_CHILD_CONFIG_FIELDS")
    if config["mode"] != "SYNTHETIC_OFFLINE_ONLY":
        raise ValueError("EVAL002A_LIVE_EXECUTION_DISABLED")
    values = dict(config["scenario"])
    values["judge_flags"] = tuple(values["judge_flags"])
    scenario = OfflineScenario(**values)
    directory = Path(config["evidence_dir"])
    if directory.resolve() != config_file.resolve().parent:
        raise ValueError("EVAL002A_CONFIG_EVIDENCE_DIRECTORY_MISMATCH")
    budget = AttemptBudget(Path(config["budget_path"]), config["run_id"])
    budget.join_observation(config["observation_id"], config["observation_fence_id"])
    ledger = EvidenceLedger(directory)
    install_network_guard(ledger)
    providers = build_bound_providers(
        budget,
        config["observation_id"],
        SYNTHETIC_GRANITE_MODEL,
        provider_stub("planner", scenario),
        provider_stub("judge", scenario),
    )
    observer = ReadOnlyGovernanceObserver(directory, config["observation_id"])
    trace = (
        ResponseLossTrace(ledger, observer, config["observation_id"])
        if scenario.drop_response
        else SyntheticTrace(ledger)
    )
    adapter = GuardedSyntheticAdapter(ledger, scenario.backend_mode, budget)
    gateway = EvaluationGateway(
        adapter, providers.judge, trace, budget, config["observation_id"], observer
    )
    server = create_server(gateway)
    try:
        with observer:
            await server.run_stdio_async()
    finally:
        await providers.shutdown()
        write_new(
            directory / "child-provider-events.json",
            {
                "planner": providers.planner_transport.events,
                "judge": providers.judge_transport.events,
            },
        )


async def run_offline_observation(
    budget_path: Path,
    run_id: str,
    observation_id: str,
    evidence_dir: Path,
    scenario: OfflineScenario,
) -> dict[str, Any]:
    """Exactly one synthetic graph invocation; no retry, live mode or dataset loader."""
    budget = AttemptBudget(budget_path, run_id)
    budget.ensure_recoverable()
    fence_id = budget.begin_observation(observation_id)
    install_dataset_guard()
    evidence_dir.mkdir(parents=True, exist_ok=False)
    # Snapshot the immutable configuration before the first awaited operation.
    snapshot = OfflineScenario(**asdict(scenario))
    config = {
        "mode": "SYNTHETIC_OFFLINE_ONLY",
        "budget_path": str(budget_path.resolve()),
        "run_id": run_id,
        "observation_id": observation_id,
        "evidence_dir": str(evidence_dir.resolve()),
        "scenario": asdict(snapshot),
        "observation_fence_id": fence_id,
    }
    write_new(evidence_dir / "offline-config.json", config)
    deadlines = DeadlinePlan()
    providers = build_bound_providers(
        budget,
        observation_id,
        SYNTHETIC_GRANITE_MODEL,
        provider_stub("planner", snapshot),
        provider_stub("judge", snapshot),
        deadlines=deadlines,
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-B",
            "-m",
            "evals.harness.live_composition_v3",
            "--offline-server-config",
            str(evidence_dir / "offline-config.json"),
        ],
        env=child_environment(),
    )
    result: Any = None
    transport: ObservedTransport | None = None
    reserved: ReservedMCPTransport | None = None
    error_class: str | None = None
    interrupted_custody_incomplete = False
    interrupted_stop_acknowledged: bool | None = None
    runner_stop_attempted = False

    def request_runner_stop(reason: str) -> bool:
        nonlocal runner_stop_attempted, interrupted_stop_acknowledged
        runner_stop_attempted = True
        try:
            budget.stop(reason)
        except BudgetError:
            interrupted_stop_acknowledged = False
            return False
        interrupted_stop_acknowledged = True
        return True

    try:
        with (
            parent_network_guard(),
            (evidence_dir / "server-stderr.txt").open("x", encoding="utf-8") as errors,
        ):
            async with asyncio.timeout(deadlines.observation_seconds):
                async with (
                    stdio_client(params, errlog=errors) as (read, write),
                    ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=15)
                    ) as session,
                ):
                    await session.initialize()
                    transport = ObservedTransport(session)
                    reserved = ReservedMCPTransport(transport, budget, observation_id, deadlines)
                    result = await LangGraphAgent(
                        providers.planner, reserved, timeout_seconds=20
                    ).run(snapshot.request)
    except BaseException as exc:
        error_class = type(exc).__name__
        if reserved is not None and reserved.custody_incomplete:
            # The wrapper already attempted STOP; do not retry an uncertain
            # receipt write or relabel its incomplete custody after cancellation.
            interrupted_custody_incomplete = True
        else:
            try:
                interrupted_state = budget.snapshot()
                pending = next(
                    (
                        row
                        for row in interrupted_state["mcp_calls"]
                        if row["observation_id"] == observation_id
                    ),
                    None,
                )
                if pending is not None and pending["outcome"] is None:
                    runner_stop_attempted = True
                    budget.finish_mcp(
                        observation_id,
                        "CLIENT_RECEIPT_UNKNOWN",
                        {
                            "client_receipt_state": "UNKNOWN",
                            "error_code": "OBSERVATION_INTERRUPTED",
                        },
                    )
                    interrupted_stop_acknowledged = True
                else:
                    if not request_runner_stop("OBSERVATION_INTERRUPTED"):
                        interrupted_custody_incomplete = True
            except BudgetError:
                interrupted_custody_incomplete = True
                request_runner_stop("OBSERVATION_CUSTODY_INCOMPLETE")
    finally:
        await providers.shutdown()
    projection_available = True
    events, dispatch, attempts, components = [], [], [], []
    observer_capture_verified = False
    dispatch_available = attempts_available = components_available = False
    provider_events = list(providers.planner_transport.events) + list(
        providers.judge_transport.events
    )
    try:
        events = _json_lines(evidence_dir / "governance-observations.jsonl")
        _validate_observer_capture(events, observation_id)
        observer_capture_verified = True
        dispatch = _json_lines(evidence_dir / "dispatch.jsonl")
        dispatch_available = True
        attempts = _json_lines(evidence_dir / "http-attempts.jsonl")
        attempts_available = True
        components = _json_lines(evidence_dir / "components.jsonl")
        components_available = True
        provider_events.extend(_child_provider_events(evidence_dir / "child-provider-events.json"))
    except (OSError, ValueError, KeyError, TypeError):
        projection_available = False
        interrupted_custody_incomplete = True
        error_class = error_class or "EvidenceProjectionUnavailable"
        request_runner_stop("FINAL_EVIDENCE_PROJECTION_UNAVAILABLE")
    state: dict[str, Any] | None = None
    budget_stop_acknowledged = False
    try:
        state = budget.snapshot()
    except BudgetError:
        error_class = error_class or "BudgetUnavailable"
        budget_stop_acknowledged = request_runner_stop("FINAL_BUDGET_SNAPSHOT_UNAVAILABLE")
    rows = (
        [row for row in state["attempts"] if row["observation_id"] == observation_id]
        if state is not None
        else []
    )
    outcome = result.outcome if result is not None else None
    if reserved is not None and reserved.received_outcome is not None:
        outcome = reserved.received_outcome
    envelope = outcome.envelope if outcome is not None else None
    integrities = [row for row in events if row.get("event") == "observer_integrity"]
    provider_stops = [event for event in provider_events if event.get("event") == "STOP"]
    provider_stop_unknown = any(
        event.get("stop_persistence") != "PERSISTED" for event in provider_stops
    )

    def role_count(role: str, *, reservations: bool = False) -> int | None:
        if state is None:
            return None
        selected = [row for row in rows if row["role"] == role]
        if reservations:
            return len(selected)
        if any(type(row["metadata"].get("delegate_entered")) is not bool for row in selected):
            return None
        return sum(row["metadata"]["delegate_entered"] is True for row in selected)

    summary = {
        "mode": "SYNTHETIC_OFFLINE_ONLY",
        "observation_id": observation_id,
        "graph_status": result.status if result is not None else "OBSERVATION_INTERRUPTED",
        "transport_status": outcome.status if outcome is not None else None,
        "final_decision": envelope.decision if envelope is not None else None,
        "gateway_status": envelope.status if envelope is not None else None,
        "verification_state": envelope.verification_state if envelope is not None else None,
        "next_action": envelope.next_action if envelope is not None else None,
        "result_released": envelope.result is not None if envelope is not None else None,
        "client_result_observed": envelope is not None and envelope.result is not None,
        "planner_http_attempts": role_count("planner"),
        "judge_http_attempts": role_count("judge"),
        "planner_attempt_reservations": role_count("planner", reservations=True),
        "judge_attempt_reservations": role_count("judge", reservations=True),
        "provider_attempt_counter_basis": "OBSERVED_DELEGATION_NOT_REMOTE_EXECUTION",
        "mcp_invocations": transport.calls if transport is not None else 0,
        "mcp_invocation_state": (
            "ATTEMPTED" if transport is not None and transport.calls else "NOT_ATTEMPTED"
        ),
        "binding_issuance_count": sum(row.get("status") == "ISSUED" for row in events),
        "binding_consumption_count": sum(
            row.get("status") == "VERIFIED_CONSUMED" for row in events
        ),
        "adapter_entries": sum(row.get("phase") == "entered" for row in dispatch),
        "synthetic_http_attempts": sum(row.get("phase") == "entered" for row in attempts),
        "backend_responses": sum(
            row.get("component") == "synthetic_http"
            and row.get("phase") == "finish"
            and row.get("status_code") is not None
            for row in components
        ),
        "client_receipt_state": (
            "CLIENT_RESPONSE_OBSERVED" if envelope is not None else "CLIENT_RECEIPT_UNKNOWN"
        ),
        "observer_integrity": (
            "PASS"
            if observer_capture_verified
            else "FAIL"
            if integrities and integrities[-1].get("status") == "FAIL"
            else "UNKNOWN"
        ),
        "observer_reported_integrity": integrities[-1].get("status", "UNKNOWN")
        if integrities
        else "NOT_OBSERVED",
        "context_preserved": (
            result.context.original_request == snapshot.request if result is not None else False
        ),
        "visited_nodes": list(result.visited_nodes) if result is not None else [],
        "budget_stopped": state["stopped"] if state is not None else None,
        "budget_status": "OBSERVED" if state is not None else "UNAVAILABLE_FAIL_CLOSED",
        "budget_stop_acknowledged_after_snapshot_failure": budget_stop_acknowledged,
        "stop_attempted": bool(provider_stops)
        or runner_stop_attempted
        or (reserved.stop_attempted if reserved else False)
        or (state is not None and state["stopped"]),
        "provider_stop_attempted": bool(provider_stops),
        "provider_stop_persistence": (
            "UNKNOWN"
            if provider_stop_unknown
            else "ACKNOWLEDGED"
            if provider_stops
            else "NOT_REQUESTED"
        ),
        "stop_persistence": (
            "ACKNOWLEDGED"
            if (state is not None and state["stopped"])
            or (reserved is not None and reserved.custody_stop_acknowledged is True)
            or interrupted_stop_acknowledged is True
            else "UNKNOWN"
            if bool(provider_stops)
            or runner_stop_attempted
            or (reserved is not None and reserved.stop_attempted)
            else "NOT_REQUESTED"
        ),
        "client_result_custody": (
            "INCOMPLETE_STOP"
            if state is None
            or interrupted_custody_incomplete
            or provider_stop_unknown
            or (reserved is not None and reserved.custody_incomplete)
            else "RECORDED"
        ),
        "mcp_custody_write_acknowledged": (
            reserved.custody_write_acknowledged if reserved is not None else None
        ),
        "mcp_custody_stop_persistence": (
            "ACKNOWLEDGED"
            if (reserved is not None and reserved.custody_stop_acknowledged is True)
            or interrupted_stop_acknowledged is True
            or budget_stop_acknowledged
            else "UNKNOWN"
            if (reserved is not None and reserved.custody_stop_acknowledged is False)
            or interrupted_stop_acknowledged is False
            else "NOT_REQUESTED_FOR_CUSTODY_FAILURE"
        ),
        "counter_semantics": "RECORDED_EVENTS_NOT_PROOF_OF_NO_EXECUTION",
        "evidence_projection_available": projection_available,
        "evidence_projection_status": "VERIFIED_COMPLETE"
        if projection_available
        else "UNKNOWN_INCOMPLETE",
        "observation_fence_acknowledged": True,
        "observation_fence_state_at_summary": "OPEN",
        "observation_fence_close_persistence": "NOT_ATTEMPTED_AT_SUMMARY_WRITE",
        "backend_dispatch_state": (envelope.dispatch_state if envelope is not None else "UNKNOWN"),
        "error_class": error_class,
        "real_model_inference_calls": 0,
        "real_backend_requests": 0,
    }
    for key, available in (
        ("binding_issuance_count", observer_capture_verified),
        ("binding_consumption_count", observer_capture_verified),
        ("adapter_entries", dispatch_available),
        ("synthetic_http_attempts", attempts_available),
        ("backend_responses", components_available),
    ):
        if not available:
            summary[key] = None
    try:
        # Completion evidence is flushed before the sole fence-closing commit.
        # After that commit no fallible evidence write can create a lost STOP.
        write_new(evidence_dir / "offline-summary.json", summary)
    except (OSError, ValueError):
        summary["client_result_custody"] = "INCOMPLETE_STOP"
        summary["error_class"] = "FinalSummaryWriteUnavailable"
        summary["stop_attempted"] = True
        summary["mcp_custody_stop_persistence"] = (
            "ACKNOWLEDGED" if request_runner_stop("FINAL_SUMMARY_WRITE_UNAVAILABLE") else "UNKNOWN"
        )
        summary["stop_persistence"] = summary["mcp_custody_stop_persistence"]
        summary["observation_fence_close_persistence"] = "NOT_ATTEMPTED_INCOMPLETE_SUMMARY"
        return summary
    safe_completion = (
        state is not None
        and not state["stopped"]
        and error_class is None
        and summary["client_result_custody"] == "RECORDED"
        and projection_available
        and result is not None
        and result.status == "COMPLETED"
        and envelope is not None
        and reserved is not None
        and reserved.custody_write_acknowledged
        and not provider_stops
        and summary["observer_integrity"] == "PASS"
        and any(
            event.get("event") == "ROLE_ACCEPTED" and event.get("role") == "planner"
            for event in provider_events
        )
        and (
            not any(row["role"] == "judge" for row in rows)
            or (
                envelope.governance.judge_signal.available
                and any(
                    event.get("event") == "ROLE_ACCEPTED" and event.get("role") == "judge"
                    for event in provider_events
                )
            )
        )
    )
    if safe_completion:
        try:
            budget.close_safe_observation(observation_id, sha256(canonical(summary) + b"\n"))
        except BudgetError:
            # The complete, safe summary predates this possible lost commit
            # ACK. UNKNOWN is not a new STOP obligation or a claimed ACK.
            summary = {**summary, "observation_fence_close_persistence": "UNKNOWN"}
        else:
            summary = {**summary, "observation_fence_close_persistence": "ACKNOWLEDGED"}
    else:
        summary = {
            **summary,
            "observation_fence_close_persistence": "NOT_ATTEMPTED_UNSAFE_COMPLETION",
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-server-config", type=Path, required=True)
    options = parser.parse_args()
    asyncio.run(serve_offline(options.offline_server_config))


if __name__ == "__main__":
    main()
