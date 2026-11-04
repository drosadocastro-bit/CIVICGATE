"""Synthetic stdio observations of a host-selected profile and legacy control.

Reuses original A2, MCP transport, deterministic Gateway, ExecutionBoundary,
SQLite coordinator and observer. No historical validator is weakened to accept
the new schema. New profile-specific reconciliation is explicitly separate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from civicgate.agent.langgraph_agent import LangGraphAgent
from civicgate.mcp.client import TransportOutcome
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from evals.data01.backend_v1 import fixture_transport as legacy_dataset_transport
from evals.demos.observability_v1 import install_a2_capture
from evals.harness import live_composition_v3 as old_composition
from evals.harness.bounded_provider_v3 import DeadlinePlan
from evals.harness.eval_002b_composition_v4 import _json_lines as bounded_rows
from evals.harness.eval_002b_composition_v4 import install_fixture_network_guard
from evals.harness.evidence import canonical, child_environment, sha256, write_new
from evals.harness.governance_observer_v3 import ReadOnlyGovernanceObserver
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy
from evals.harness.runner import ObservedTransport
from evals.harness.synthetic_server import EvidenceLedger, SyntheticAdapter, SyntheticTrace
from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter, dataset_transport
from evals.proposals.r022.faa_contract_v1 import FAA_FY2026_PR_CONTRACT, PROFILE_ID
from evals.proposals.r022.stdio_v1 import (
    ProfileAdmissionError,
    ScopedFaaGateway,
    TrustedFaaIntake,
    create_scoped_server,
)


def rows(path):
    return bounded_rows(path)


def append(path, data):
    with path.open("ab") as stream:
        stream.write(canonical(data) + b"\n")
        stream.flush()


def registry_for(owner):
    if owner == "strict":
        return FAA_FY2026_PR_CONTRACT.registry
    if owner == "legacy-control":
        return TOOLS
    raise ValueError("R022_HOST_OWNER_SELECTION_INVALID")


def invocation_digest(request, proposal, registry):
    # Accounting identity only, never authority. Invalid ingress remains raw
    # because no Gateway may consume its reservation before SDK rejection.
    arguments = proposal.arguments
    if proposal.tool in registry:
        try:
            arguments = registry[proposal.tool].model_validate(arguments).model_dump(mode="json")
        except ValueError:
            pass
    return sha256(
        canonical(
            {"user_request": request, "proposal": {"tool": proposal.tool, "arguments": arguments}}
        )
    )


class FixtureJudge:
    def __init__(self, directory):
        self.directory = directory

    async def assess(self, request, proposal):
        append(
            self.directory / "judge.jsonl",
            {"source": "DETERMINISTIC_SYNTHETIC_JUDGE_NOT_LUNA", "request": request},
        )
        return JudgeSignal(
            available=True,
            classification="IN_SCOPE",
            confidence=0.99,
            flags=[],
            provider="r022-synthetic",
            rationale="Synthetic advisory fixture only",
        )


class ProfileObservedTransport(ObservedTransport):
    def __init__(self, session, registry, directory):
        super().__init__(session)
        self.registry = registry
        self.directory = directory

    async def discover(self):
        metadata = await self.transport.discover()
        for item in metadata:
            schema = item.input_schema
            query = schema["properties"]["query"]
            if "$ref" in query:
                query = schema["$defs"][query["$ref"].removeprefix("#/$defs/")]
            if query != self.registry[item.name].model_json_schema():
                raise ValueError("R022_SELECTED_SCHEMA_DISCOVERY_MISMATCH")
        self.discovered = [asdict(item) for item in metadata]
        write_new(self.directory / "mcp-tools-list.json", self.discovered)
        return metadata


class ProfileReservedTransport(old_composition.ReservedMCPTransport):
    def __init__(self, observed, budget, observation_id, directory, registry):
        super().__init__(observed, budget, observation_id, DeadlinePlan())
        self.directory = directory
        self.registry = registry

    async def invoke(self, request, proposal):
        write_new(
            self.directory / "mcp-client-input.json",
            {"request": request, "proposal": proposal.model_dump(mode="json")},
        )
        if self.custody_incomplete:
            return TransportOutcome("PROTOCOL_ERROR", error_code="CUSTODY_INCOMPLETE")
        try:
            self.budget.ensure_recoverable()
            self.budget.assert_active_observation(self.observation_id)
            self.budget.reserve_mcp(
                self.observation_id, invocation_digest(request, proposal, self.registry)
            )
        except Exception:
            self._stop_incomplete_custody()
            raise
        try:
            value = await self.observed.invoke(request, proposal)
        except BaseException:
            self.custody_incomplete = True
            try:
                self.budget.finish_mcp(
                    self.observation_id,
                    "CLIENT_RECEIPT_UNKNOWN",
                    {"error_code": "MCP_CALL_INTERRUPTED"},
                )
            except old_composition.BudgetError:
                self._stop_incomplete_custody()
            raise
        self.received_outcome = value
        receipt = (
            "CLIENT_RESPONSE_OBSERVED" if value.envelope is not None else "CLIENT_RECEIPT_UNKNOWN"
        )
        metadata = {"client_receipt_state": receipt, "backend_dispatch_state": value.dispatch_state}
        if value.envelope is not None:
            metadata["final_policy_disposition"] = value.envelope.decision
        try:
            self.budget.finish_mcp(self.observation_id, receipt, metadata)
        except old_composition.BudgetError:
            self._stop_incomplete_custody()
        else:
            self.custody_write_acknowledged = True
        if value.envelope is not None and value.envelope.verification_state in {
            "RESULT_UNKNOWN",
            "FAILED_VALIDATION",
        }:
            if not self._request_stop("POST_RESULT_VALIDATION_OR_COMPLETION_FAILED"):
                self.custody_incomplete = True
        write_new(self.directory / "mcp-client-receipt.json", asdict(value))
        return value


async def serve_worker(config_file):
    install_fixture_network_guard()
    old_composition.install_dataset_guard()
    config = json.loads(config_file.read_bytes())
    directory = config_file.parent
    if (
        config["evidence_dir"] != str(directory.resolve())
        or config["mode"] != "R022_SYNTHETIC_STDIO_ONLY"
    ):
        raise ValueError("R022_WORKER_CONFIG_INVALID")
    owner = config["owner"]
    registry = registry_for(owner)
    budget = LiveAttemptBudget(Path(config["database"]), config["run_id"])
    budget.join_observation(config["observation_id"], config["fence_id"])
    ledger, observer = (
        EvidenceLedger(directory),
        ReadOnlyGovernanceObserver(directory, config["observation_id"]),
    )
    (directory / "ingress.jsonl").write_bytes(b"")
    (directory / "judge.jsonl").write_bytes(b"")
    judge, trace = FixtureJudge(directory), SyntheticTrace(ledger)

    if owner == "strict":
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
        server = create_scoped_server(gateway)
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
    else:
        from unittest.mock import patch

        from evals.harness import synthetic_server

        class AuditedLegacyGateway(Gateway):
            async def call(self, request, proposal, planning_failed=False):
                budget.assert_active_observation(config["observation_id"])
                budget.admit_mcp(
                    config["observation_id"], invocation_digest(request, proposal, registry)
                )
                try:
                    return await super().call(request, proposal, planning_failed)
                finally:
                    observer.close()

        with patch.object(synthetic_server, "fixture_transport", legacy_dataset_transport):
            adapter = SyntheticAdapter(ledger, "normal")
        gateway = AuditedLegacyGateway(adapter, judge, trace)
        server = create_server(gateway)
    with observer:
        await server.run_stdio_async()


async def observe_case(case, directory, monkeypatch):
    directory.mkdir(parents=True, exist_ok=False)
    owner = case["owner"]
    registry = registry_for(owner)
    if owner == "strict":
        intake = TrustedFaaIntake(case["host_request"], json.dumps(case["host_query"]))
        intake_data = {"request": intake.original_request, "query_json": intake.expected_query_json}
    else:
        intake_data = None
    evidence = directory / "evidence"
    evidence.mkdir()
    database = directory / "coordinator.sqlite"
    run_id, observation_id = "R022_" + uuid4().hex, "R022_OBS_" + uuid4().hex
    budget = LiveAttemptBudget.create(
        database, run_id, liability_policy=SyntheticLiabilityPolicy(24)
    )
    fence = budget.begin_observation(observation_id)
    config = {
        "mode": "R022_SYNTHETIC_STDIO_ONLY",
        "owner": owner,
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
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-B",
            "-m",
            "evals.proposals.r022.observation_v1",
            "--worker-config",
            str(config_file),
        ],
        env=child_environment(),
    )
    write_new(
        directory / "stdio-command.json",
        {"command": params.command, "args": params.args, "environment": params.env},
    )
    observed, reserved, graph = None, None, None
    raw_call = ClientSession.call_tool

    async def capture_call(self, *args, **kwargs):
        value = await raw_call(self, *args, **kwargs)
        write_new(directory / "raw-mcp-result.json", value.model_dump(mode="json"))
        return value

    monkeypatch.setattr(ClientSession, "call_tool", capture_call)
    error = None
    outcome = None
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
        except BaseException as exc:
            error = type(exc).__name__
            budget.stop("R022_OBSERVATION_INCOMPLETE")
    envelope = outcome.envelope if outcome is not None else None
    audit = rows(evidence / "audit.jsonl")
    events = rows(evidence / "governance-observations.jsonl")
    dispatch = [r for r in rows(evidence / "dispatch.jsonl") if r.get("phase") == "entered"]
    http = [r for r in rows(evidence / "http-attempts.jsonl") if r.get("phase") == "entered"]
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

        capture_admission = validate_capture(evidence, request, proposal, registry, owner, envelope)
    except (ImportError, ValueError, TypeError, KeyError, OSError) as exc:
        verified = False
        capture_admission = {
            "status": "REJECTED_OR_UNAVAILABLE",
            "reason": type(exc).__name__,
            "detail": str(exc)[:160],
        }
        budget.stop("R022_PRIMARY_CAPTURE_NOT_ADMITTED")
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
        "owner": owner,
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
        "profile_specific_capture_admission": capture_admission,
        "mcp_custody_ack": reserved.custody_write_acknowledged if reserved else False,
        "server_selected_profile": PROFILE_ID if owner == "strict" else "LEGACY_UNSCOPED_CONTROL",
        "scope_profile_supported": owner == "strict" and bool(policies),
        "profile_admission_passed_to_policy": owner == "strict" and bool(policies),
        "mcp_logical_calls": observed.calls if observed else 0,
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
