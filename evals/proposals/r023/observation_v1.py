"""Fixed host route and original FAA governance under synthetic stdio only.
No production edits, legacy launch selector or live backend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from civicgate.agent.langgraph_agent import LangGraphAgent
from civicgate.models.requests import Proposal
from evals.demos.observability_v1 import install_a2_capture
from evals.harness import live_composition_v3 as old_composition
from evals.harness.eval_002b_composition_v4 import install_fixture_network_guard
from evals.harness.evidence import sha256, write_new
from evals.harness.governance_observer_v3 import ReadOnlyGovernanceObserver
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy
from evals.harness.synthetic_server import EvidenceLedger, SyntheticTrace
from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter, dataset_transport
from evals.proposals.r022.faa_contract_v1 import FAA_FY2026_PR_CONTRACT, PROFILE_ID
from evals.proposals.r022.observation_v1 import (
    FixtureJudge,
    ProfileObservedTransport,
    ProfileReservedTransport,
    append,
    invocation_digest,
    rows,
)
from evals.proposals.r022.stdio_v1 import ProfileAdmissionError, ScopedFaaGateway, TrustedFaaIntake
from evals.proposals.r023.host_v1 import (
    HOST_FIXED_MODULE,
    HostSelectedFaaComposition,
    TrustedFaaLaunchOwner,
)


async def serve_worker(config_file):
    install_fixture_network_guard()
    old_composition.install_dataset_guard()
    config = json.loads(config_file.read_bytes())
    directory = config_file.parent
    expected = {
        "mode",
        "database",
        "run_id",
        "observation_id",
        "fence_id",
        "evidence_dir",
        "intake",
        "backend_mode",
    }
    if (
        set(config) != expected
        or config["evidence_dir"] != str(directory.resolve())
        or config["mode"] != "R023_SYNTHETIC_STDIO_ONLY"
    ):
        raise ValueError("R023_WORKER_CONFIG_INVALID")
    registry = FAA_FY2026_PR_CONTRACT.registry
    budget = LiveAttemptBudget(Path(config["database"]), config["run_id"])
    budget.join_observation(config["observation_id"], config["fence_id"])
    ledger, observer = (
        EvidenceLedger(directory),
        ReadOnlyGovernanceObserver(directory, config["observation_id"]),
    )
    (directory / "ingress.jsonl").write_bytes(b"")
    (directory / "judge.jsonl").write_bytes(b"")
    judge, trace = FixtureJudge(directory), SyntheticTrace(ledger)
    append(
        directory / "host-audit.jsonl",
        {
            "event": "FIXED_WORKER_STARTED",
            "worker_module": HOST_FIXED_MODULE,
            "worker_sha256": sha256(Path(__file__).read_bytes()),
            "pid": os.getpid(),
            "observation_id": config["observation_id"],
        },
    )
    try:
        await serve_selected(config, directory, budget, ledger, observer, judge, trace, registry)
    except BaseException as exc:
        append(
            directory / "host-audit.jsonl",
            {
                "event": "HOST_WORKER_TERMINATED",
                "exception_type": type(exc).__name__,
                "legacy_fallback_attempted": False,
            },
        )
        raise


async def serve_selected(config, directory, budget, ledger, observer, judge, trace, registry):
    base_transport = dataset_transport(config["backend_mode"])

    async def respond(request):
        ledger.append(
            "http-attempts.jsonl",
            phase="entered",
            method=request.method,
            request_path=request.url.path,
            request_body_sha256=sha256(request.content),
        )
        write_new(directory / "backend-request.json", json.loads(request.content))
        try:
            value = await base_transport.handle_async_request(request)
        except BaseException as exc:
            ledger.append(
                "components.jsonl",
                component="synthetic_http",
                phase="finish",
                error_class=type(exc).__name__,
            )
            raise
        ledger.append(
            "components.jsonl",
            component="synthetic_http",
            phase="finish",
            error_class=None,
            status_code=value.status_code,
        )
        with (directory / "backend-response.bin").open("xb") as stream:
            stream.write(value.content)
            stream.flush()
            os.fsync(stream.fileno())
        write_new(
            directory / "backend-response-meta.json",
            {
                "status_code": value.status_code,
                "content_type": value.headers.get("content-type", ""),
            },
        )
        return value

    class AuditedAdapter(FaaProfileFixtureAdapter):
        async def find_profile(self, query):
            budget.assert_active_observation(config["observation_id"])
            ledger.append(
                "dispatch.jsonl",
                phase="entered",
                method="find_profile",
                query=query.model_dump(mode="json"),
            )
            error = None
            try:
                return await super().find_profile(query)
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                ledger.append(
                    "components.jsonl", component="adapter", phase="finish", error_class=error
                )

    class AuditedGateway(ScopedFaaGateway):
        async def call(self, request, proposal, planning_failed=False):
            if getattr(self, "_host_invocation_started", False):
                append(
                    directory / "host-audit.jsonl",
                    {
                        "event": "REUSED_OBSERVATION_REFUSED",
                        "observation_id": config["observation_id"],
                    },
                )
                raise ProfileAdmissionError("HOST_OBSERVATION_ALREADY_USED")
            self._host_invocation_started = True
            append(
                directory / "host-audit.jsonl",
                {
                    "event": "FIRST_GATEWAY_INVOCATION",
                    "observation_id": config["observation_id"],
                    "profile_id": PROFILE_ID,
                },
            )
            budget.assert_active_observation(config["observation_id"])
            budget.admit_mcp(
                config["observation_id"], invocation_digest(request, proposal, registry)
            )
            try:
                return await super().call(request, proposal, planning_failed)
            except ProfileAdmissionError as exc:
                append(
                    directory / "ingress.jsonl",
                    {"layer": "HOST_PROFILE_ADMISSION_NOT_POLICY", "reason": exc.code},
                )
                raise
            finally:
                observer.close()

    intake = TrustedFaaIntake(config["intake"]["request"], config["intake"]["query_json"])
    gateway = AuditedGateway(
        AuditedAdapter(httpx.MockTransport(respond)), judge, trace, intake=intake
    )
    composition = HostSelectedFaaComposition.from_gateway(gateway)
    append(
        directory / "host-audit.jsonl",
        {
            "event": "HOST_SELECTED_BEFORE_DISCOVERY",
            "selection": composition.selection_snapshot(),
            "pid": os.getpid(),
            "worker_module": HOST_FIXED_MODULE,
            "worker_sha256": sha256(Path(__file__).read_bytes()),
            "observation_id": config["observation_id"],
        },
    )
    write_new(
        directory / "selected-intake.json",
        {
            "profile_id": PROFILE_ID,
            "original_request": intake.original_request,
            "expected_query_json": intake.expected_query_json,
            "intake_sha256": intake.intake_sha256,
            "identity_authentication": "NOT_ESTABLISHED_TRUSTED_LOCAL_HOST_BOUNDARY",
        },
    )
    with observer:
        await composition.run_stdio()


async def observe_case(case, directory, monkeypatch):
    directory.mkdir(parents=True, exist_ok=False)
    registry = FAA_FY2026_PR_CONTRACT.registry
    intake = TrustedFaaIntake(case["host_request"], json.dumps(case["host_query"]))
    intake_data = {"request": intake.original_request, "query_json": intake.expected_query_json}
    evidence = directory / "evidence"
    evidence.mkdir()
    database = directory / "coordinator.sqlite"
    run_id, observation_id = "R023_" + uuid4().hex, "R023_OBS_" + uuid4().hex
    budget = LiveAttemptBudget.create(
        database, run_id, liability_policy=SyntheticLiabilityPolicy(24)
    )
    fence = budget.begin_observation(observation_id)
    config = {
        "mode": "R023_SYNTHETIC_STDIO_ONLY",
        "database": str(database.resolve()),
        "run_id": run_id,
        "observation_id": observation_id,
        "fence_id": fence,
        "evidence_dir": str(evidence.resolve()),
        "intake": intake_data,
        "backend_mode": case.get("backend_mode", "normal"),
    }
    config_file = evidence / "worker-config.json"
    write_new(config_file, config)
    write_new(directory / "case.json", case)
    install_a2_capture(monkeypatch, directory)
    proposal = Proposal.model_validate(case["proposal"])
    request = case.get("wire_request", case["host_request"])
    launch = TrustedFaaLaunchOwner(config_file, intake)
    write_new(directory / "host-launch-selection.json", launch.selection_snapshot())
    params = launch.consume(launch.capability)
    write_new(
        directory / "stdio-command.json",
        {
            "command": params.command,
            "args": params.args,
            "environment": params.env,
            "target_is_host_selected": True,
        },
    )
    if case.get("startup_mutation") == "missing_config_after_reservation":
        with (evidence / "worker-config-preserved.bin").open("xb") as stream:
            stream.write(config_file.read_bytes())
        config_file.unlink()
        write_new(
            directory / "startup-test-mutation.json",
            {
                "mutation": "removed new synthetic config after host launch consumption",
                "not_historical_file": True,
            },
        )
    observed, reserved, graph = None, None, None
    raw_call = ClientSession.call_tool
    sdk_calls = []

    async def capture_call(self, *args, **kwargs):
        if case.get("mcp_meta") is not None:
            kwargs["meta"] = case["mcp_meta"]
        wire_args = dict(args[1] if len(args) > 1 else kwargs.get("arguments", {}))
        wire_args.update(case.get("extra_fields", {}))
        if "wire_query" in case:
            wire_args["query"] = case["wire_query"]
        for key in case.get("remove_wire_fields", []):
            wire_args.pop(key, None)
        if len(args) > 1:
            args = (args[0], wire_args, *args[2:])
        else:
            kwargs["arguments"] = wire_args
        call = {
            "name": args[0] if args else kwargs["name"],
            "arguments": wire_args,
            "meta": kwargs.get("meta"),
            "target_module": HOST_FIXED_MODULE,
        }
        sdk_calls.append(call)
        append(
            directory / "raw-mcp-calls.jsonl", {"phase": "sent", "index": len(sdk_calls), **call}
        )
        value = await raw_call(self, *args, **kwargs)
        append(
            directory / "raw-mcp-calls.jsonl",
            {
                "phase": "response",
                "index": len(sdk_calls),
                "is_error": value.isError,
                "response": value.model_dump(mode="json"),
            },
        )
        if len(sdk_calls) == 1:
            write_new(directory / "raw-mcp-result.json", value.model_dump(mode="json"))
        return value

    monkeypatch.setattr(ClientSession, "call_tool", capture_call)
    error = None
    outcome = None
    protocol_reinitializations = 0
    with (directory / "worker-stderr.log").open("x", encoding="utf-8") as stderr:
        try:
            async with asyncio.timeout(60):
                async with (
                    stdio_client(params, errlog=stderr) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    initialized = await session.initialize()
                    write_new(
                        directory / "mcp-initialize.json", initialized.model_dump(mode="json")
                    )
                    write_new(
                        directory / "host-selection-at-initialize.json",
                        rows(evidence / "host-audit.jsonl"),
                    )
                    observed = ProfileObservedTransport(session, registry, directory)
                    reserved = ProfileReservedTransport(
                        observed, budget, observation_id, directory, registry
                    )
                    if case.get("execution", "a2") == "direct":
                        await reserved.discover()
                        outcome = await reserved.invoke(request, proposal)
                    else:

                        class Planner:
                            async def propose(self, original_request):
                                assert original_request == request
                                return proposal.model_copy(deep=True)

                        graph = await LangGraphAgent(Planner(), reserved, timeout_seconds=20).run(
                            request
                        )
                        outcome = graph.outcome
                    if case.get("after_call") == "reinitialize_then_repeat":
                        again = await session.initialize()
                        protocol_reinitializations += 1
                        write_new(directory / "reinitialized.json", again.model_dump(mode="json"))
                        listed = await session.list_tools()
                        write_new(
                            directory / "reinitialized-tools.json", listed.model_dump(mode="json")
                        )
                    if case.get("after_call") in {"repeat", "reinitialize_then_repeat"}:
                        replay = await capture_call(
                            session,
                            proposal.tool,
                            {"user_request": request, "query": proposal.arguments},
                        )
                        write_new(directory / "replay-result.json", replay.model_dump(mode="json"))
        except BaseException as exc:
            error = type(exc).__name__
            budget.stop("R023_OBSERVATION_INCOMPLETE")
    launch.finish(success=error is None)
    write_new(directory / "host-launch-final.json", launch.selection_snapshot())
    envelope = outcome.envelope if outcome is not None else None

    def read_rows(path):
        # An intentionally failed pre-server startup has no ledger or observer.
        # Never treat missing normal captures, symlinks or corrupt files as empty.
        if (
            case.get("startup_mutation") == "missing_config_after_reservation"
            and error is not None
            and not path.exists()
            and not path.is_symlink()
        ):
            return []
        return rows(path)

    audit = read_rows(evidence / "audit.jsonl")
    events = read_rows(evidence / "governance-observations.jsonl")
    dispatch = [r for r in read_rows(evidence / "dispatch.jsonl") if r.get("phase") == "entered"]
    http = [r for r in read_rows(evidence / "http-attempts.jsonl") if r.get("phase") == "entered"]
    policies = [r for r in audit if r["stage"] == "policy"]
    issued = [r for r in events if r.get("status") == "ISSUED"]
    consumed = [r for r in events if r.get("status") == "VERIFIED_CONSUMED"]
    integrity = [r for r in events if r.get("event") == "observer_integrity"]
    verified = (
        len(integrity) == 1
        and integrity[0]["status"] == "PASS"
        and len(issued) == len(consumed) == len(dispatch) == len(http)
    )
    if issued:
        verified = verified and issued[0]["binding"] == consumed[0]["binding"]
    if envelope is not None:
        completed = [r for r in audit if r["stage"] == "completed"]
        verified = (
            verified
            and len(policies) == len(completed) == 1
            and completed[0]["response"] == envelope.model_dump(mode="json")
        )
    else:
        verified = verified and not policies and not issued and not dispatch
    capture_admission = {
        "status": "NOT_VERIFIED",
        "reason": "PROFILE_CAPTURE_RECONCILIATION_PENDING",
    }
    try:
        from evals.proposals.r022.profile_capture_v1 import validate_capture

        capture_admission = validate_capture(
            evidence, request, proposal, registry, "strict", envelope
        )
    except (ImportError, ValueError, TypeError, KeyError, OSError) as exc:
        verified = False
        capture_admission = {
            "status": "REJECTED_OR_UNAVAILABLE",
            "reason": type(exc).__name__,
            "detail": str(exc)[:160],
        }
        budget.stop("R023_PRIMARY_CAPTURE_NOT_ADMITTED")
    host_events = read_rows(evidence / "host-audit.jsonl")
    selections = [r for r in host_events if r.get("event") == "HOST_SELECTED_BEFORE_DISCOVERY"]
    launch_snapshot = launch.selection_snapshot()
    selection_verified = False
    if selections:
        selected = selections[0]
        snapshot = selected["selection"]
        selection_verified = (
            len(selections) == 1
            and selected["worker_module"] == HOST_FIXED_MODULE
            and selected["worker_sha256"] == sha256(Path(__file__).read_bytes())
            and selected["observation_id"] == observation_id
            and snapshot["intake_sha256"] == intake.intake_sha256
            and snapshot["profile_id"] == PROFILE_ID
            and snapshot["transport"] == "stdio"
            and snapshot["legacy_routes_exposed"] is False
            and all(
                snapshot[key] == launch_snapshot[key]
                for key in (
                    "route",
                    "worker_module",
                    "profile_id",
                    "intake_sha256",
                    "find_schema_sha256",
                    "request_sha256",
                )
            )
        )
        at_initialize = json.loads((directory / "host-selection-at-initialize.json").read_bytes())
        selection_verified = (
            selection_verified
            and selected in at_initialize
            and not any(r.get("event") == "FIRST_GATEWAY_INVOCATION" for r in at_initialize)
        )
    startup_refusal_verified = (
        case.get("startup_mutation") == "missing_config_after_reservation"
        and error is not None
        and not host_events
        and not sdk_calls
        and not (directory / "mcp-initialize.json").exists()
        and not audit
        and not dispatch
        and not http
        and not events
        and launch_snapshot["launch_state"] == "FAILED"
        and sha256((evidence / "worker-config-preserved.bin").read_bytes())
        == launch_snapshot["config_sha256"]
        and "FileNotFoundError" in (directory / "worker-stderr.log").read_text(encoding="utf8")
    )
    if not selection_verified and not startup_refusal_verified:
        verified = False
        budget.stop("R023_HOST_SELECTION_NOT_VERIFIED")
    manual_replays = read_rows(directory / "raw-mcp-calls.jsonl")
    if case.get("after_call"):
        refused = [r for r in host_events if r.get("event") == "REUSED_OBSERVATION_REFUSED"]
        replay_responses = [
            r for r in manual_replays if r.get("phase") == "response" and r["index"] == 2
        ]
        if (
            len(refused) != 1
            or len(replay_responses) != 1
            or replay_responses[0]["is_error"] is not True
        ):
            verified = False
            budget.stop("R023_REPLAY_REFUSAL_NOT_VERIFIED")
    if graph is not None:
        entries = [
            r for r in rows(directory / "a2-events.jsonl") if r["event"] == "A2_NODE_ENTERED"
        ]
        verified = verified and [r["node"] for r in entries] == list(graph.visited_nodes) == [
            "intake",
            "discovery",
            "planner",
            "gateway",
            "result",
        ]
        verified = (
            verified
            and graph.context.original_request == request
            and all(r["original_request"] == request for r in entries)
        )
    summary = {
        "case_id": case["case_id"],
        "run_id": run_id,
        "observation_id": observation_id,
        "execution": case.get("execution", "a2"),
        "transport_status": outcome.status if outcome else None,
        "initial_policy": policies[0]["policy"]["decision"] if policies else None,
        "final_policy": envelope.decision if envelope else None,
        "policy_reasons": envelope.governance.policy_reasons if envelope else [],
        "binding_issuances": len(issued),
        "binding_consumptions": len(consumed),
        "adapter_entries": len(dispatch),
        "mock_backend_attempts": len(http),
        "observed_envelope": envelope.model_dump(mode="json") if envelope else None,
        "primary_projection_verified": verified,
        "host_selection_verified": selection_verified,
        "startup_refusal_verified_no_gateway_projection": startup_refusal_verified,
        "host_path_verified": selection_verified or startup_refusal_verified,
        "host_worker_selection": selections[0] if selections else None,
        "profile_specific_capture_admission": capture_admission,
        "mcp_custody_ack": reserved.custody_write_acknowledged if reserved else False,
        "host_requested_profile": PROFILE_ID,
        "server_selected_profile": PROFILE_ID if selection_verified else None,
        "scope_profile_supported": bool(policies),
        "profile_admission_passed_to_policy": bool(policies),
        "mcp_logical_calls": observed.calls if observed else 0,
        "actual_sdk_tool_calls": len(sdk_calls),
        "manual_adversarial_replay_calls": max(0, len(sdk_calls) - 1),
        "protocol_reinitializations": protocol_reinitializations,
        "fixed_target_module": HOST_FIXED_MODULE,
        "legacy_routes_offered_to_agent": [],
        "graph_nodes": list(graph.visited_nodes) if graph else [],
        "error": error,
        "custody_close_ack": "NOT_ATTEMPTED",
        "real_provider_requests": 0,
        "live_backend_requests": 0,
        "policy_evaluation_absent_on_mcp_rejection": not policies,
    }
    write_new(directory / "summary-before-close.json", summary)
    state = budget.snapshot()
    if (
        verified
        and error is None
        and envelope is not None
        and reserved.custody_write_acknowledged
        and not state["stopped"]
        and envelope.verification_state not in {"FAILED_VALIDATION", "RESULT_UNKNOWN"}
    ):
        budget.close_safe_observation(
            observation_id, sha256((directory / "summary-before-close.json").read_bytes())
        )
        summary["custody_close_ack"] = "ACKNOWLEDGED"
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            table: [dict(r) for r in connection.execute("SELECT * FROM " + table)]
            for table in ("meta", "observation_fences", "attempts", "mcp_calls", "send_leases")
        }
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    write_new(directory / "sqlite-readonly.json", tables)
    summary["custody_state"] = tables["observation_fences"][0]["state"]
    summary["budget_stopped"] = budget.snapshot()["stopped"]
    write_new(directory / "measurement.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-config", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve_worker(args.worker_config))


if __name__ == "__main__":
    main()
