"""R3 synthetic composition with fail-closed capture admission.

Only evaluation fixtures are admitted. No real-provider CLI or credentials are
accepted. Parent and child each own their ephemeral response server. Their
separate receipts, resource reservations, MCP calls, policy decisions, binding
consumptions and MockTransport backend attempts remain separate evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from types import FrameType
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from civicgate.agent.langgraph_agent import LangGraphAgent
from civicgate.mcp.server import create_server
from evals.harness import synthetic_http_server_v1 as fixtures
from evals.harness.backend_capture_admission_v1 import validate_backend_capture
from evals.harness.bounded_provider_v3 import DeadlinePlan
from evals.harness.evidence import canonical, child_environment, sha256, write_new
from evals.harness.governance_observer_v2 import ReadOnlyGovernanceObserver
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_composition_v3 import (
    EvaluationGateway,
    GuardedSyntheticAdapter,
    OfflineScenario,
    ReservedMCPTransport,
    _validate_observer_capture,
    install_dataset_guard,
)
from evals.harness.live_provider_candidate_v2 import build_synthetic_http_providers
from evals.harness.provider_capture_admission_v1 import (
    read_provider_capture,
    validate_provider_capture,
)
from evals.harness.provider_response_admission_v2 import strict_json_loads
from evals.harness.runner import ObservedTransport
from evals.harness.synthetic_server import EvidenceLedger, SyntheticTrace
from evals.harness.synthetic_server_v2 import ResponseLossTrace

_NETWORK_GUARD_INSTALLED = False


def _json_lines(path: Path) -> list[dict[str, Any]]:
    """Bounded strict reader; empty is syntax-valid, never proof of no dispatch."""
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
        raise ValueError("R3_CAPTURE_FILE_UNAVAILABLE")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("R3_CAPTURE_INCOMPLETE_LINE")
    lines = raw.splitlines()
    if len(lines) > 128:
        raise ValueError("R3_CAPTURE_LINE_BOUND")
    rows = []
    for line in lines:
        row = strict_json_loads(line)
        if type(row) is not dict:
            raise ValueError("R3_CAPTURE_OBJECT_REQUIRED")
        rows.append(row)
    return rows


def install_fixture_network_guard() -> None:
    """Process-local audit guard, not an OS sandbox or hostile-Python guarantee."""
    global _NETWORK_GUARD_INSTALLED
    if _NETWORK_GUARD_INSTALLED:
        return

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event == "socket.getaddrinfo" or event == "socket.sendto":
            raise PermissionError("EVAL002B_DNS_AND_DATAGRAM_DISABLED")
        if event == "socket.connect":
            address = args[1]
            # Windows Proactor creates a private TCP socketpair for its wakeup
            # pipe. The permanent audit hook must permit that stdlib operation
            # in subsequent event loops, while refusing application endpoints.
            socketpair = getattr(socket, "_fallback_socketpair", None)
            make_pipe = getattr(
                getattr(asyncio, "proactor_events", None), "BaseProactorEventLoop", None
            )
            pipe_method = getattr(make_pipe, "_make_self_pipe", None)
            required = {
                getattr(socketpair, "__code__", None),
                getattr(pipe_method, "__code__", None),
            }
            frames = set()
            frame: FrameType | None = sys._getframe()
            while frame is not None:
                frames.add(frame.f_code)
                frame = frame.f_back
            if (
                None not in required
                and required <= frames
                and isinstance(address, tuple)
                and address[0] == "127.0.0.1"
            ):
                return
            allowed = {
                ("127.0.0.1", owner.endpoint.port)
                for owner in fixtures._OWNED_ENDPOINTS.values()
                if owner.active and owner.endpoint is not None
            }
            if address not in allowed:
                raise PermissionError("EVAL002B_NON_FIXTURE_NETWORK_DISABLED")

    sys.addaudithook(audit)
    _NETWORK_GUARD_INSTALLED = True


def synthetic_reply(role: str, scenario: OfflineScenario) -> fixtures.SyntheticReply:
    mode = scenario.planner_mode if role == "planner" else scenario.judge_mode
    content = (
        scenario.proposal().model_dump(mode="json")
        if role == "planner"
        else {
            "classification": "IN_SCOPE",
            "confidence": 0.99,
            "flags": list(scenario.judge_flags),
            "rationale": "Synthetic protocol fixture only.",
        }
    )
    model = "SYNTHETIC_GRANITE_CONTRACT_STUB" if role == "planner" else "gpt-5.6-luna"
    body: dict[str, Any] = {
        "model": model if mode != "mismatch" else "SYNTHETIC_OTHER_MODEL",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
    }
    if mode == "missing_model":
        del body["model"]
    if mode == "malformed":
        body["choices"][0]["message"]["content"] = "{}"
    return fixtures.SyntheticReply.json(
        body,
        status_code=503 if mode == "unavailable" else 200,
        header_delay_seconds=3.0 if mode == "timeout" else 0.0,
    )


def provider_evidence(providers: Any, server: fixtures.SyntheticHTTPServer) -> dict[str, Any]:
    roles: dict[str, Any] = {}
    for role in ("planner", "judge"):
        transport = getattr(providers, role + "_transport")
        delegate = transport.response_delegate
        roles[role] = {
            "events": transport.events,
            "wire": {**dict(delegate.wire.facts), "wire_fixture_path": delegate.wire.endpoint.path}
            if delegate.wire is not None
            else None,
            "response_contract": delegate.facts,
            "response_facts_acknowledged": delegate.facts_acknowledged,
        }
    return {
        "roles": roles,
        "server_receipts": [dict(row) for row in server.receipts],
        "server_connections": server.connection_count,
        "server_errors": list(server.errors),
    }


def validate_http_primary(
    primary: dict[str, Any], role: str, observation_id: str, state: dict[str, Any]
) -> None:
    """Reconcile primary captures with SQLite, not authenticate a hostile host."""
    validate_provider_capture(primary)
    if type(primary) is not dict or set(primary) != {
        "roles",
        "server_receipts",
        "server_connections",
        "server_errors",
    }:
        raise ValueError("HTTP_PRIMARY_CAPTURE_SCHEMA")
    if type(primary["roles"]) is not dict or set(primary["roles"]) != {"planner", "judge"}:
        raise ValueError("HTTP_PRIMARY_ROLES_SCHEMA")
    current = [
        row
        for row in state["attempts"]
        if row["observation_id"] == observation_id and row["role"] == role
    ]
    captured = primary["roles"][role]
    if type(captured) is not dict or set(captured) != {
        "events",
        "wire",
        "response_contract",
        "response_facts_acknowledged",
    }:
        raise ValueError("HTTP_ROLE_CAPTURE_SCHEMA")
    if type(captured["events"]) is not list or any(
        type(row) is not dict or type(row.get("event")) is not str for row in captured["events"]
    ):
        raise ValueError("HTTP_ROLE_EVENTS_SCHEMA")
    receipts, wire = primary["server_receipts"], captured["wire"]
    if (
        type(receipts) is not list
        or len(receipts) > 1
        or type(primary["server_connections"]) is not int
    ):
        raise ValueError("HTTP_SERVER_CAPTURE_SCHEMA")
    if primary["server_connections"] != len(receipts) or primary["server_errors"] != []:
        raise ValueError("HTTP_SERVER_CAPTURE_INCOMPLETE_OR_INCONSISTENT")
    if not current:
        if wire is not None or receipts or primary["server_connections"] != 0 or captured["events"]:
            raise ValueError("HTTP_UNRESERVED_ACTIVITY_CAPTURED")
        return
    if len(current) != 1 or type(wire) is not dict:
        raise ValueError("HTTP_EXACT_ATTEMPT_CAPTURE_REQUIRED")
    reservation = current[0]
    leases = [row for row in state["send_leases"] if row["attempt_id"] == reservation["attempt_id"]]
    if len(leases) != 1 or wire.get("request_sha256") != reservation["request_sha256"]:
        raise ValueError("HTTP_LEASE_REQUEST_CAPTURE_MISMATCH")
    if wire.get("header_emission_attempts") != len(receipts) or len(receipts) != 1:
        raise ValueError("HTTP_DELIVERY_CAPTURE_INCOMPLETE")
    receipt = receipts[0]
    headers = {name.lower(): value for name, value in receipt["headers"]}
    if (
        type(receipt) is not dict
        or leases[0]["state"] != "CONSUMED"
        or receipt.get("body_received") is not True
        or receipt.get("request_sha256") != reservation["request_sha256"]
        or receipt.get("received_body_bytes") != wire.get("body_emission_attempted_bytes")
        or receipt.get("declared_body_bytes") != receipt.get("received_body_bytes")
        or receipt.get("path") != wire.get("wire_fixture_path")
        or headers
        != {
            "host": wire["wire_fixture_origin"].removeprefix("http://"),
            "content-type": "application/json",
            "content-length": str(receipt["received_body_bytes"]),
            "connection": "close",
        }
        or wire.get("wire_fixture_origin") != leases[0]["binding"]["wire_fixture_origin"]
        or wire.get("logical_origin") != leases[0]["binding"]["logical_origin"]
    ):
        raise ValueError("HTTP_SERVER_WIRE_LEASE_MISMATCH")
    facts = [
        row for row in state["response_facts"] if row["attempt_id"] == reservation["attempt_id"]
    ]
    if (
        len(facts) != 1
        or captured["response_facts_acknowledged"] is not True
        or facts[0]["facts"] != captured["response_contract"]
        or wire.get("raw_body_sha256") != facts[0]["facts"]["body_sha256"]
        or wire.get("response_retained_bytes") != facts[0]["facts"]["body_bytes"]
    ):
        raise ValueError("HTTP_RESPONSE_FACTS_CAPTURE_MISMATCH")


async def serve_synthetic_worker(config_file: Path) -> None:
    install_dataset_guard()
    install_fixture_network_guard()
    if config_file.name != "synthetic-http-worker-config.json" or config_file.is_symlink():
        raise ValueError("EXACT_SYNTHETIC_CONFIG_REQUIRED")
    if config_file.stat().st_size > 65_536:
        raise ValueError("BOUNDED_CONFIG_REQUIRED")
    config = json.loads(config_file.read_bytes())
    if (
        type(config) is not dict
        or set(config)
        != {
            "mode",
            "budget_path",
            "run_id",
            "observation_id",
            "fence_id",
            "scenario",
            "evidence_dir",
        }
        or config["mode"] != "SYNTHETIC_SOCKET_ONLY_NO_LIVE_AUTHORIZATION"
    ):
        raise ValueError("SYNTHETIC_CONFIG_CONTRACT_REQUIRED")
    directory = Path(config["evidence_dir"])
    if directory.resolve() != config_file.resolve().parent:
        raise ValueError("CONFIG_CUSTODY_DIRECTORY_MISMATCH")
    values = dict(config["scenario"])
    values["judge_flags"] = tuple(values["judge_flags"])
    scenario = OfflineScenario(**values)
    budget = LiveAttemptBudget(Path(config["budget_path"]), config["run_id"])
    budget.join_observation(config["observation_id"], config["fence_id"])
    async with fixtures.SyntheticHTTPServer(synthetic_reply("judge", scenario)) as server:
        assert server.endpoint is not None
        providers = build_synthetic_http_providers(
            budget, config["observation_id"], server.endpoint, server.endpoint
        )
        ledger = EvidenceLedger(directory)
        observer = ReadOnlyGovernanceObserver(directory, config["observation_id"])
        trace = (
            ResponseLossTrace(ledger, observer, config["observation_id"])
            if scenario.drop_response
            else SyntheticTrace(ledger)
        )
        gateway = EvaluationGateway(
            GuardedSyntheticAdapter(ledger, scenario.backend_mode, budget),
            providers.judge,
            trace,
            budget,
            config["observation_id"],
            observer,
        )
        try:
            with observer:
                await create_server(gateway).run_stdio_async()
        finally:
            await providers.shutdown()
            write_new(directory / "worker-http-evidence.json", provider_evidence(providers, server))


async def run_synthetic_observation(
    budget_path: Path,
    run_id: str,
    observation_id: str,
    evidence_dir: Path,
    scenario: OfflineScenario | None = None,
) -> dict[str, Any]:
    """One synthetic graph/MCP observation; no transport retry or real mode."""
    install_dataset_guard()
    install_fixture_network_guard()
    scenario = scenario or OfflineScenario()
    budget = LiveAttemptBudget(budget_path, run_id)
    budget.ensure_recoverable()
    fence = budget.begin_observation(observation_id)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    config = {
        "mode": "SYNTHETIC_SOCKET_ONLY_NO_LIVE_AUTHORIZATION",
        "budget_path": str(budget_path.resolve()),
        "run_id": run_id,
        "observation_id": observation_id,
        "fence_id": fence,
        "scenario": asdict(scenario),
        "evidence_dir": str(evidence_dir.resolve()),
    }
    config_file = evidence_dir / "synthetic-http-worker-config.json"
    write_new(config_file, config)
    result = None
    error: str | None = None
    reserved = None
    observed = None
    projection_ok = False
    worker: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    dispatch: list[dict[str, Any]] = []
    backend: list[dict[str, Any]] = []
    governance_available = dispatch_available = backend_available = False
    supervisor: dict[str, Any] | None = None
    supervisor_custody_ack = False
    root_stop_attempted = False
    root_stop_acknowledged: bool | None = None

    def request_stop(reason: str) -> None:
        nonlocal root_stop_attempted, root_stop_acknowledged
        root_stop_attempted = True
        try:
            budget.stop(reason)
        except Exception:
            root_stop_acknowledged = False
        else:
            root_stop_acknowledged = True

    async with fixtures.SyntheticHTTPServer(synthetic_reply("planner", scenario)) as server:
        assert server.endpoint is not None
        providers = build_synthetic_http_providers(
            budget, observation_id, server.endpoint, server.endpoint
        )
        try:
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-B",
                    "-m",
                    "evals.harness.eval_002b_composition_v2",
                    "--synthetic-worker-config",
                    str(config_file),
                ],
                env=child_environment(),
            )
            with (evidence_dir / "worker-stderr.txt").open("x", encoding="utf-8") as errlog:
                async with asyncio.timeout(DeadlinePlan().observation_seconds):
                    async with (
                        stdio_client(params, errlog=errlog) as (read, write),
                        ClientSession(
                            read, write, read_timeout_seconds=timedelta(seconds=15)
                        ) as session,
                    ):
                        await session.initialize()
                        observed = ObservedTransport(session)
                        reserved = ReservedMCPTransport(
                            observed, budget, observation_id, DeadlinePlan()
                        )
                        result = await LangGraphAgent(
                            providers.planner, reserved, timeout_seconds=20
                        ).run(scenario.request)
        except BaseException as exc:
            error = type(exc).__name__
            request_stop("SYNTHETIC_OBSERVATION_FAILED")
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            try:
                await providers.shutdown()
                supervisor = provider_evidence(providers, server)
                write_new(evidence_dir / "supervisor-http-evidence.json", supervisor)
                # Admit the actual acknowledged JSON bytes, not the shallow
                # in-memory server view whose headers are immutable tuples.
                supervisor = read_provider_capture(evidence_dir / "supervisor-http-evidence.json")
                supervisor_custody_ack = True
            except Exception:
                error = error or "SUPERVISOR_CAPTURE_CUSTODY_UNACKNOWLEDGED"
                request_stop("SUPERVISOR_CAPTURE_CUSTODY_UNACKNOWLEDGED")
    capture_errors = []
    try:
        events = _json_lines(evidence_dir / "governance-observations.jsonl")
        _validate_observer_capture(events, observation_id)
        governance_available = True
    except (OSError, ValueError, KeyError, TypeError):
        capture_errors.append("GOVERNANCE_CAPTURE_UNAVAILABLE")
    try:
        dispatch = _json_lines(evidence_dir / "dispatch.jsonl")
        dispatch_available = True
    except (OSError, ValueError, KeyError, TypeError):
        capture_errors.append("DISPATCH_CAPTURE_UNAVAILABLE")
    try:
        backend = _json_lines(evidence_dir / "http-attempts.jsonl")
        backend_available = True
    except (OSError, ValueError, KeyError, TypeError):
        capture_errors.append("BACKEND_CAPTURE_UNAVAILABLE")
    try:
        worker = read_provider_capture(evidence_dir / "worker-http-evidence.json")
    except (OSError, ValueError, KeyError, TypeError):
        capture_errors.append("WORKER_HTTP_CAPTURE_UNAVAILABLE")
    projection_ok = not capture_errors
    if capture_errors:
        error = error or "PRIMARY_EVIDENCE_UNAVAILABLE"
        request_stop("PRIMARY_EVIDENCE_UNAVAILABLE")
    state: dict[str, Any] | None = None
    try:
        state = budget.snapshot()
    except Exception:
        capture_errors.append("COORDINATOR_SNAPSHOT_UNKNOWN")
        error = error or "COORDINATOR_SNAPSHOT_UNKNOWN"
        request_stop("COORDINATOR_SNAPSHOT_UNKNOWN")
    worker_http_valid = False
    supervisor_http_valid = False
    try:
        if state is None or supervisor is None or not supervisor_custody_ack:
            raise ValueError("SUPERVISOR_HTTP_CAPTURE_UNCORRELATED")
        validate_http_primary(supervisor, "planner", observation_id, state)
        supervisor_http_valid = True
    except (ValueError, TypeError, KeyError):
        capture_errors.append("SUPERVISOR_HTTP_CAPTURE_UNCORRELATED")
    try:
        if state is None or worker is None:
            raise ValueError("WORKER_HTTP_CAPTURE_UNCORRELATED")
        validate_http_primary(worker, "judge", observation_id, state)
        worker_http_valid = True
    except (ValueError, TypeError, KeyError):
        capture_errors.append("WORKER_HTTP_CAPTURE_UNCORRELATED")
        # Do not retain a rejected object for later summary/acceptance access.
        worker = None
    current_attempts = (
        [row for row in state["attempts"] if row["observation_id"] == observation_id]
        if state is not None
        else []
    )
    current_ids = {row["attempt_id"] for row in current_attempts}
    outcome = result.outcome if result is not None else None
    envelope = outcome.envelope if outcome is not None else None
    backend_capture: dict[str, Any] | None = None
    try:
        backend_capture = validate_backend_capture(
            evidence_dir,
            observation_id,
            events,
            expected_request=scenario.request,
            expected_tool=scenario.proposal_tool,
            expected_arguments=scenario.proposal().arguments,
            expected_request_id=envelope.request_id if envelope is not None else None,
        )
    except (OSError, ValueError, TypeError, KeyError):
        capture_errors.append("BACKEND_CAPTURE_INCOMPLETE_OR_MISMATCHED")
    projection_ok = not capture_errors
    if not projection_ok:
        error = error or "PRIMARY_CAPTURE_INCOMPLETE"
        request_stop("PRIMARY_CAPTURE_INCOMPLETE")
    if root_stop_attempted:
        try:
            state = budget.snapshot()
        except Exception:
            state = None
            error = error or "FINAL_COORDINATOR_SNAPSHOT_UNKNOWN"
    summary = {
        "mode": config["mode"],
        "observation_id": observation_id,
        "graph_status": result.status if result is not None else "INTERRUPTED",
        "decision": envelope.decision if envelope is not None else None,
        "verification_state": envelope.verification_state if envelope is not None else None,
        "result_released": envelope.result is not None if envelope is not None else False,
        "context_preserved": result.context.original_request == scenario.request
        if result
        else False,
        "mcp_logical_calls": observed.calls if observed else 0,
        "attempt_reservations": len(current_attempts) if state is not None else None,
        "send_lease_consumptions": sum(
            row["state"] == "CONSUMED"
            for row in state["send_leases"]
            if row["attempt_id"] in current_ids
        )
        if state is not None
        else None,
        "server_request_receipts": server.request_count + len(worker["server_receipts"])
        if worker_http_valid and worker is not None and supervisor_http_valid
        else None,
        "supervisor_server_request_receipts": server.request_count,
        "worker_capture_state": "VALIDATED" if worker_http_valid else "UNKNOWN_INCOMPLETE",
        "supervisor_capture_state": "VALIDATED" if supervisor_http_valid else "UNKNOWN_INCOMPLETE",
        "response_facts_acks": sum(
            row["attempt_id"] in current_ids for row in state["response_facts"]
        )
        if state is not None
        else None,
        "binding_issuances": sum(row.get("status") == "ISSUED" for row in events)
        if governance_available
        else None,
        "binding_consumptions": sum(row.get("status") == "VERIFIED_CONSUMED" for row in events)
        if governance_available
        else None,
        "adapter_entries": len(backend_capture["dispatch"])
        if backend_capture is not None
        else None,
        "mock_backend_attempts": len(backend_capture["backend"])
        if backend_capture is not None
        else None,
        "reported_adapter_entry_records": sum(row.get("phase") == "entered" for row in dispatch)
        if dispatch_available
        else None,
        "reported_mock_backend_records": sum(row.get("phase") == "entered" for row in backend)
        if backend_available
        else None,
        "backend_capture_state": backend_capture["state"]
        if backend_capture is not None
        else "UNKNOWN_INCOMPLETE",
        "capture_errors": capture_errors,
        "primary_projection_verified": projection_ok,
        "budget_stopped": state["stopped"] if state is not None else None,
        "coordinator_snapshot_state": "OBSERVED" if state is not None else "UNKNOWN",
        "root_stop_attempted": root_stop_attempted,
        "root_stop_acknowledged": root_stop_acknowledged,
        "mcp_custody_ack": reserved.custody_write_acknowledged if reserved else False,
        "mcp_custody_incomplete": reserved.custody_incomplete if reserved else True,
        "mcp_stop_attempted": reserved.stop_attempted if reserved else False,
        "mcp_stop_acknowledged": reserved.custody_stop_acknowledged if reserved else None,
        "error": error,
        "real_provider_requests": 0,
        "real_backend_requests": 0,
        "live_authorization": "HOLD",
        "global_history": "UNKNOWN",
        "fence_close": "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE",
    }
    # Do not close OPEN after invalid backend/typed response or incomplete custody.
    judge_used = any(row["role"] == "judge" for row in current_attempts)
    judge_accepted = worker is not None and any(
        row.get("event") == "ROLE_ACCEPTED" for row in worker["roles"]["judge"]["events"]
    )
    safe = (
        error is None
        and state is not None
        and not state["stopped"]
        and projection_ok
        and result is not None
        and result.status == "COMPLETED"
        and reserved is not None
        and reserved.custody_write_acknowledged
        and not reserved.custody_incomplete
        and not reserved.stop_attempted
        and providers.planner_transport.acceptance is not None
        and (not judge_used or judge_accepted)
        and envelope is not None
        and str(envelope.verification_state) not in {"FAILED_VALIDATION", "RESULT_UNKNOWN"}
        and not any(row.get("event") == "STOP" for row in providers.planner_transport.events)
        and worker is not None
        and not any(row.get("event") == "STOP" for row in worker["roles"]["judge"]["events"])
        and worker_http_valid
        and supervisor_http_valid
        and backend_capture is not None
        and not root_stop_attempted
    )
    try:
        write_new(evidence_dir / "synthetic-observation-summary.json", summary)
    except Exception:
        request_stop("FINAL_SUMMARY_CUSTODY_UNKNOWN")
        return {
            **summary,
            "error": "FINAL_SUMMARY_CUSTODY_UNKNOWN",
            "primary_projection_verified": False,
            "summary_custody": "UNKNOWN_INCOMPLETE",
            "root_stop_attempted": root_stop_attempted,
            "root_stop_acknowledged": root_stop_acknowledged,
            "budget_stopped": True if root_stop_acknowledged else None,
            "fence_close": "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE",
        }
    if safe:
        try:
            budget.close_safe_observation(observation_id, sha256(canonical(summary) + b"\n"))
        except Exception:
            summary = {**summary, "fence_close": "UNKNOWN"}
        else:
            summary = {**summary, "fence_close": "ACKNOWLEDGED"}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-worker-config", type=Path, required=True)
    options = parser.parse_args()
    asyncio.run(serve_synthetic_worker(options.synthetic_worker_config))


if __name__ == "__main__":
    main()
