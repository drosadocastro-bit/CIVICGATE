"""Passive A2 observations and evidence projection; no policy or execution interface."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

from langgraph.graph.state import CompiledStateGraph

from civicgate.agent import langgraph_agent as a2
from civicgate.models.requests import TOOLS
from evals.harness.evidence import write_new
from evals.harness.live_composition_v3 import ReservedMCPTransport

EXPECTED_NODES = ["intake", "discovery", "planner", "gateway", "result"]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def install_a2_capture(monkeypatch, directory):
    log = directory / "a2-events.jsonl"
    with log.open("xb"):
        pass

    def event(kind, **fields):
        row = {
            "event": kind,
            "parent_monotonic_ns": perf_counter_ns(),
            "observed_at_utc": datetime.now(UTC).isoformat(),
            **fields,
        }
        with log.open("ab") as stream:
            stream.write(
                (
                    json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
                ).encode()
            )
            stream.flush()
            os.fsync(stream.fileno())

    original_enter = a2._Run.enter
    original_run = a2.LangGraphAgent.run
    original_graph_invoke = CompiledStateGraph.ainvoke
    original_mcp = ReservedMCPTransport.invoke

    def enter(self, node):
        previous = self.next_node
        value = original_enter(self, node)
        event(
            "A2_NODE_ENTERED",
            node=node,
            ordinal=len(self.visited),
            previous_expected_node=previous,
            original_request=self.context.original_request,
            request_sha256=self.context.request_sha256,
            proposal_json=self.proposal_json,
        )
        return value

    async def graph_invoke(self, *args, **kwargs):
        event(
            "COMPILED_LANGGRAPH_INVOKE_STARTED",
            graph_module=type(self).__module__,
            graph_class=type(self).__qualname__,
            delegate_module=original_graph_invoke.__module__,
        )
        try:
            value = await original_graph_invoke(self, *args, **kwargs)
        except BaseException as exc:
            event("COMPILED_LANGGRAPH_INVOKE_FAILED", error_class=type(exc).__name__)
            raise
        event("COMPILED_LANGGRAPH_INVOKE_RETURNED", returned_state=value)
        return value

    async def agent_run(self, request):
        event(
            "A2_RUN_STARTED",
            original_request=request,
            planner_class=type(self._model).__qualname__,
            planner_module=type(self._model).__module__,
            a2_source_sha256=sha(Path(a2.__file__).read_bytes()),
        )
        value = await original_run(self, request)
        write_new(
            directory / "a2-orchestration-result.json",
            {
                "context": asdict(value.context),
                "visited_nodes": list(value.visited_nodes),
                "status": value.status,
                "error_code": value.error_code,
                "outcome": asdict(value.outcome) if value.outcome is not None else None,
                "source": "ACTUAL_UNCHANGED_LANGGRAPH_AGENT_RETURN",
                "human_identity_authentication": "NOT_ESTABLISHED",
            },
        )
        event("A2_RUN_RETURNED", status=value.status, visited_nodes=list(value.visited_nodes))
        return value

    async def mcp_invoke(self, request, proposal):
        write_new(
            directory / "a2-mcp-client-input.json",
            {
                "request": request,
                "proposal": proposal.model_dump(mode="json"),
                "source": "ACTUAL_RESERVED_MCP_TRANSPORT_INPUT",
            },
        )
        event("A2_MCP_INVOKE_STARTED", original_request=request, tool=proposal.tool)
        value = await original_mcp(self, request, proposal)
        write_new(
            directory / "a2-mcp-client-receipt.json",
            {"outcome": asdict(value), "source": "ACTUAL_RESERVED_MCP_TRANSPORT_RETURN"},
        )
        event("A2_MCP_INVOKE_RETURNED", status=value.status)
        return value

    monkeypatch.setattr(a2._Run, "enter", enter)
    monkeypatch.setattr(CompiledStateGraph, "ainvoke", graph_invoke)
    monkeypatch.setattr(a2.LangGraphAgent, "run", agent_run)
    monkeypatch.setattr(ReservedMCPTransport, "invoke", mcp_invoke)


def verify_a2_capture(directory, scenario, audit, returned):
    events = [
        json.loads(line) for line in (directory / "a2-events.jsonl").read_bytes().splitlines()
    ]
    nodes = [row for row in events if row["event"] == "A2_NODE_ENTERED"]
    actual = read(directory / "a2-orchestration-result.json")
    client = read(directory / "a2-mcp-client-input.json")
    receipt = read(directory / "a2-mcp-client-receipt.json")
    assert [row["node"] for row in nodes] == actual["visited_nodes"] == EXPECTED_NODES
    assert [row["ordinal"] for row in nodes] == [1, 2, 3, 4, 5]
    assert all(row["previous_expected_node"] == row["node"] for row in nodes)
    assert all(row["original_request"] == scenario.request for row in nodes)
    request_hash = sha(scenario.request.encode("utf-8"))
    assert all(row["request_sha256"] == request_hash for row in nodes)
    assert actual["context"] == {
        "original_request": scenario.request,
        "request_sha256": request_hash,
    }
    assert actual["status"] == "COMPLETED" and actual["error_code"] is None
    kinds = [row["event"] for row in events]
    for name in [
        "A2_RUN_STARTED",
        "A2_RUN_RETURNED",
        "COMPILED_LANGGRAPH_INVOKE_STARTED",
        "COMPILED_LANGGRAPH_INVOKE_RETURNED",
        "A2_MCP_INVOKE_STARTED",
        "A2_MCP_INVOKE_RETURNED",
    ]:
        assert kinds.count(name) == 1
    assert "COMPILED_LANGGRAPH_INVOKE_FAILED" not in kinds
    monotonic = [row["parent_monotonic_ns"] for row in events]
    assert monotonic == sorted(monotonic)
    final_graph = next(
        row for row in events if row["event"] == "COMPILED_LANGGRAPH_INVOKE_RETURNED"
    )
    assert final_graph["returned_state"]["node"] == "result"
    proposal = json.loads(next(row for row in nodes if row["node"] == "gateway")["proposal_json"])
    assert client["proposal"] == proposal and client["request"] == scenario.request
    original = next(row for row in audit if row["stage"] == "proposal")
    effective = (
        TOOLS[proposal["tool"]].model_validate(proposal["arguments"]).model_dump(mode="json")
    )
    assert original["proposal"] == {"tool": proposal["tool"], "arguments": effective}
    assert original["user_request"] == scenario.request
    assert receipt["outcome"] == actual["outcome"]
    assert receipt["outcome"]["status"] == "GOVERNED_RESPONSE"
    assert json.loads(receipt["outcome"]["response_json"]) == returned["observed_envelope"]
    started = next(row for row in events if row["event"] == "A2_RUN_STARTED")
    result = {
        "source": "ACTUAL_A2_NODE_ENTRIES_AND_RETURN_VERIFIED_AGAINST_MCP_AND_GATEWAY",
        "nodes": list(actual["visited_nodes"]),
        "compiled_graph_invocations": 1,
        "mcp_invocations": 1,
        "context": actual["context"],
        "planner_proposal": proposal,
        "effective_proposal": {"tool": proposal["tool"], "arguments": effective},
        "planner_implementation": {
            "module": started["planner_module"],
            "class": started["planner_class"],
        },
        "a2_source_sha256": started["a2_source_sha256"],
        "node_entries": nodes,
        "status": actual["status"],
        "error_code": actual["error_code"],
        "observed_outcome": actual["outcome"],
    }
    write_new(directory / "verified-a2-path.json", result)
    return result


def write_console_projection(
    directory,
    case,
    run_id,
    observation_id,
    graph,
    returned,
    envelope,
    policy,
    events,
    state,
    discovery,
):
    tables = state["tables"]
    fence = tables["observation_fences"][0]
    issued = [row for row in events if row.get("status") == "ISSUED"]
    consumed = [row for row in events if row.get("status") == "VERIFIED_CONSUMED"]
    evidence = directory / "evidence"
    artifacts = []
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            artifacts.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "bytes": len(raw),
                    "sha256": sha(raw),
                }
            )
    projection = {
        "record_type": "PROPOSED_CONSOLE_READ_MODEL_FROM_OBSERVED_LOCAL_EVIDENCE",
        "contract_status": "DOCUMENTARY_PROPOSAL_NOT_A_FASTAPI_SERVICE",
        "capture_id": directory.parents[2].name,
        "budget_run_id": run_id,
        "observation_id": observation_id,
        "gateway_request_id": envelope.request_id,
        "request": {
            "state": "VERIFIED",
            "original_request": graph["context"]["original_request"],
            "sha256": graph["context"]["request_sha256"],
            "human_identity_authentication": "NOT_ESTABLISHED",
        },
        "proposal": {
            "state": "VERIFIED",
            "planner": graph["planner_proposal"],
            "effective": graph["effective_proposal"],
        },
        "graph": {
            "state": "VERIFIED",
            "visited_nodes": graph["nodes"],
            "node_entries": graph["node_entries"],
            "status": graph["status"],
            "compiled_graph_invocations": graph["compiled_graph_invocations"],
        },
        "discovery": {"state": "VERIFIED", "tools": discovery, "grants_authority": False},
        "policy": {
            "state": "VERIFIED",
            "preflight": [row for row in events if row.get("phase") == "policy_preflight"],
            "initial_decision": policy["policy"]["decision"],
            "final_disposition": envelope.decision,
            "reasons": policy["policy"]["reasons"],
            "authority_source": "DETERMINISTIC_POLICY_GATE",
        },
        "judge": {
            "state": "OBSERVED",
            "signal": policy["judge"],
            "fixture_identity": "SYNTHETIC_PROTOCOL_ONLY_NOT_REAL_LUNA",
            "effective_real_model_identity": "UNKNOWN",
        },
        "binding": {
            "state": "VERIFIED",
            "issued_count": len(issued),
            "consumed_count": len(consumed),
            "issuance": issued,
            "consumption": consumed,
        },
        "backend": {
            "state": "VERIFIED",
            "adapter_entries": returned["adapter_entries"],
            "mock_transport_attempts": returned["mock_backend_attempts"],
            "dispatch_state": envelope.dispatch_state,
            "response_state": envelope.response_state,
            "verified_absence": returned["adapter_entries"]
            == returned["mock_backend_attempts"]
            == 0,
            "absence_basis": "COMPLETE_ADMITTED_OBSERVER_DISPATCH_HTTP_CHANNELS",
        },
        "result": {
            "state": "OBSERVED",
            "metadata_validation": "VERIFIED",
            "verification_state": envelope.verification_state,
            "validation_lane": envelope.validation_lane,
            "validation_reason": envelope.validation_reason,
            "value": envelope.result,
            "provenance": envelope.provenance.model_dump(mode="json")
            if envelope.provenance
            else None,
        },
        "custody": {
            "state": "VERIFIED",
            "database_state": fence["state"],
            "opened_at_utc": fence["opened_at_utc"],
            "closed_at_utc": fence["closed_at_utc"],
            "persisted_summary_sha256": fence["summary_sha256"],
            "persisted_summary_close_field": read(evidence / "synthetic-observation-summary.json")[
                "fence_close"
            ],
            "returned_close_ack": returned["fence_close"],
            "restart_preserved": True,
            "meaning": "DOCUMENTARY_CUSTODY_NOT_HUMAN_ACCEPTANCE",
        },
        "source_identities": {
            "a2_module_sha256": graph["a2_source_sha256"],
            "planner_implementation": graph["planner_implementation"],
            "planner_identity": "SYNTHETIC_PROVIDER_FIXTURE_NOT_REAL_GRANITE",
            "observer_kind": "PASSIVE_TEST_WRAPPERS_DELEGATING_UNCHANGED_METHODS",
        },
        "artifacts": artifacts,
        "limitations": {
            "os_isolation": "NOT_ESTABLISHED",
            "durable_stop": "PARTIAL",
            "live_execution": "HOLD",
            "faa_definitions": "54_BLOCKED_SKIP",
            "fastapi_service": "NOT_IMPLEMENTED",
        },
    }
    write_new(directory / "console-evidence-projection.json", projection)
