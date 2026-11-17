"""Dormant host release: existing runner/worker seams, gated before runtime access."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from demo_models_v1.contract import PLANNERS
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from civicgate.models.requests import Proposal

from .a2_v3 import LangGraphAgent
from .capture_binding71 import HostCapture71 as Exchange
from .catalog import select_owner
from .common import HERE, MODE, canonical, load, save, sha, verify_sources
from .fixtures import planner_response
from .mcp_v3 import MCPTransport
from .providers_v3 import Planner


async def run_turn(
    root: Path,
    question: str,
    provider: str,
    worker: Path,
    *,
    fault: str = "none",
    judge_fault: str = "none",
) -> dict[str, Any]:
    from .host_gate71 import require_release

    require_release()
    started = time.monotonic()
    record = load(root / "session.json")
    # Dedicated host release entry is gated and fixed to the approved READ question.
    from .catalog import PUBLIC_READ

    if (
        record.get("mode") != "LIVE"
        or record.get("fresh_host71") is not True
        or question != PUBLIC_READ
        or provider != "nemotron"
    ):
        raise ValueError("HOST71_FIXED_SCOPE_REQUIRED")
    if (
        record["mode"] not in {MODE, "LIVE"}
        or record["root"] != str(root.resolve())
        or record["source_sha256"] != verify_sources()
    ):
        raise ValueError("HOST_SESSION_IDENTITY_REJECTED")
    if (
        provider not in record["approved_planners"]
        or type(question) is not str
        or not 0 < len(question.strip()) <= 4000
    ):
        raise ValueError("HOST_INPUT_REJECTED")
    if record["mode"] == "LIVE":
        from .host_runtime71 import HostAdmission71
        from .transport_profile_v1 import ChatProfile

        HostAdmission71(
            ChatProfile.model_validate(record["profile"]),
            Path(record["anchor"]),
            Path(record["chain_anchor"]),
        ).check()
        if fault != "none" or judge_fault != "none":
            raise ValueError("LIVE_FAULT_INJECTION_FORBIDDEN")
    from .intake_v17 import fixture_owner, route

    owner, free_text_unknown = route(
        question, record, fixture_owner(question, record, select_owner(question))
    )
    turn = "TURN_" + uuid4().hex
    output = root / "turns" / turn
    output.mkdir(exist_ok=False)
    # Immutable original request exists before planner construction / any await.
    intake_sha = save(
        output / "intake.json",
        {
            "question": question,
            "request_sha256": sha(question.encode()),
            "owner": owner,
            "planner_selected": provider,
            "mode": record["mode"],
            "turn": turn,
        },
    )
    state: dict[str, Any] = {
        "turn": turn,
        "run_id": record["run_id"],
        "observation": record["run_id"] + "_" + turn,
        "request": question,
        "owner": owner,
        "intake_kind": "FREE_TEXT_UNKNOWN_NO_EXECUTION"
        if free_text_unknown
        else "HOST_REJECTED"
        if owner == "HOST_HOLD"
        else "GUIDED",
        "planner_selected": provider,
        "mode": record["mode"],
        "source": "NEW_OFFLINE_CAPTURE_NOT_LIVE_INFERENCE"
        if record["mode"] == MODE
        else "NEW_LIVE_INFERENCE_SYNTHETIC_BACKEND",
        "live_authorized": record["mode"] == "LIVE",
        "intake_sha256": intake_sha,
        "decision": None,
        "host_disposition": None,
        "binding_issued": 0,
        "binding_consumed": 0,
        "adapter_entries": 0,
        "backend_attempts": 0,
        "judge_called": False,
        "judge_signal": None,
        "error": None,
        "custody": "NOT_OPENED",
        "graph_nodes": [],
        "proposal": None,
        "planner_invoked": False,
        "planner_model": None,
        "judge_model": None,
    }
    if owner == "HOST_HOLD":
        state.update(
            host_disposition="REVIEW_REQUIRED",
            error="QUESTION_OUTSIDE_HOST_DEMO_CONTRACT",
            planner_provenance="NOT_INVOKED",
            evidence_reference=f"/api/governed-chat/turns/{turn}",
        )
        save(output / "returned.json", state)
        return state
    from .host_runtime71 import open_runtime

    budget, admission, secrets = open_runtime(record)
    from .public_backend_v12 import require_scope

    public_backend = require_scope(budget, question, owner)
    state["backend_kind"] = "USASPENDING_FIXED_READ_V11" if public_backend else "SYNTHETIC_ONLY"
    state["data_semantics"] = (
        "API time_period filter; Award Amount is not FY spending or newly awarded amount. Partial first page may apply."
        if public_backend
        else "Synthetic demonstration only."
    )
    if public_backend and admission is not None:
        state["source"] = "LIVE_MODELS_PUBLIC_API"
    if (
        free_text_unknown
        or getattr(getattr(budget, "profile", None), "backend", None) == "NO_EXECUTION"
    ):
        state["backend_kind"] = "NO_EXECUTION"
        state["data_semantics"] = "Negative policy test; no backend authority or result data."
        if admission is not None:
            state["source"] = "LIVE_MODELS_NO_BACKEND_AUTHORITY"
    budget.ensure_recoverable()
    fence = budget.begin_observation(state["observation"])
    state["custody"] = "OPEN"
    config = {
        "mode": record["mode"],
        "root": str(root),
        "run_id": record["run_id"],
        "ledger": str(root / "custody.sqlite"),
        "observation": state["observation"],
        "fence": fence,
        "question": question,
        "owner": owner,
        "judge_fault": "public_review" if free_text_unknown else judge_fault,
        "free_text_unknown": free_text_unknown,
    }
    if owner != "PUBLIC_API_READ":
        raise ValueError("PUBLIC_READ_ONLY")
    from .public_read_v11.contract import expected_proposal
    from .registry_v1 import owner_registry

    proposal = expected_proposal(question)
    registry = owner_registry(owner)
    save(output / "worker.json", config)
    exchange: Exchange | None = None
    planner: Any
    exchange = Exchange(
        budget,
        state["observation"],
        provider,
        planner_response(provider, question, proposal.model_dump(mode="json"), fault)
        if admission is None
        else None,
        mode=record["mode"],
        admission=admission,
    )
    planner = Planner(provider, exchange, secrets, registry=registry)
    state.update(
        planner_provenance="VERSIONED_EXISTING_ADAPTER_EXPLICIT_MOCK_TRANSPORT"
        if admission is None
        else "LIVE_PROVIDER_RESPONSE",
        planner_model=PLANNERS[provider],
    )
    pending = False
    transport: MCPTransport | None = None

    def reconcile(response: dict[str, Any], identity: str) -> None:
        nonlocal pending
        receipt = load(output / "server-receipt.json")
        if (
            receipt["response"] != response
            or receipt["proposal_sha256"] != identity
            or receipt["request_sha256"] != sha(question.encode())
            or receipt["observation"] != state["observation"]
        ):
            raise ValueError("CROSS_CHANNEL_RECEIPT_MISMATCH")
        for key in (
            "binding_issued",
            "binding_consumed",
            "adapter_entries",
            "backend_attempts",
            "judge_called",
            "judge_signal",
            "judge_raw_signal",
            "judge_flag_normalization",
        ):
            state[key] = receipt[key]
        state["public_http_attempts"] = receipt.get("public_http_attempts", [])
        state["data_provenance"] = response.get("provenance") if public_backend else None
        if state["backend_attempts"] and (
            state["binding_issued"] != 1 or state["binding_consumed"] != 1
        ):
            raise ValueError("UNAUTHORIZED_DISPATCH")
        if response["decision"] != "PERMIT" and state["backend_attempts"]:
            # A post-result failure may have dispatched; retain it as STOP, not DENY zero.
            budget.stop("DISPATCH_WITH_NONPERMIT_FINAL_RESPONSE")
        state.update(
            decision=response["decision"],
            response=response,
            policy_reasons=response.get(
                "reasons", response.get("governance", {}).get("policy_reasons", [])
            ),
            verification=response.get("result_verification", response.get("verification_state")),
            result=response.get("result"),
            judge_model="gpt-5.6-luna" if receipt["judge_called"] else None,
        )
        budget.finish_mcp(
            state["observation"],
            "CLIENT_RESPONSE_OBSERVED",
            {
                "final_policy_disposition": response["decision"],
                "binding_issued": bool(state["binding_issued"]),
                "binding_consumed": bool(state["binding_consumed"]),
                "adapter_entries": state["adapter_entries"],
                "synthetic_http_attempts": 0,
                "client_receipt_state": "OBSERVED",
            },
        )
        pending = False
        if (
            response.get("status") == "ERROR"
            or response.get("result_verification") == "UNKNOWN"
            or response.get("custody") in {"UNKNOWN", "OPEN"}
        ):
            budget.stop("RESULT_CUSTODY_UNVERIFIED")

    class ReservedTransport:
        async def discover(self) -> Any:
            assert transport is not None
            metadata = await transport.discover()
            state["discovered_tools"] = [item.name for item in metadata]
            return metadata

        async def invoke(self, request: str, proposed: Proposal) -> Any:
            nonlocal pending
            assert transport is not None
            effective = Proposal(
                tool=proposed.tool,
                arguments=registry[proposed.tool]
                .model_validate_json(json.dumps(proposed.arguments), strict=True)
                .model_dump(mode="json"),
            )
            identity = sha(canonical(effective.model_dump(mode="json")))
            budget.reserve_mcp(state["observation"], identity)
            pending = True
            response = await transport.invoke(request, proposed)
            if response.envelope is None:
                raise ValueError("MCP_RESPONSE_UNVERIFIED")
            reconcile(response.envelope.model_dump(mode="json"), identity)
            return response

    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATH", "PATHEXT"}
    }
    from bootstrap_v3 import SOURCE

    env.update(
        PYTHONPATH=str(SOURCE / "src"),
        PYTHONDONTWRITEBYTECODE="1",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    params = StdioServerParameters(
        command=str(worker),
        args=[
            "-B",
            str(HERE / "entry_host71.py"),
            "server-worker-live" if admission else "server-worker",
            "--root",
            str(root),
            "--input",
            str(output / "worker.json"),
        ],
        env=env,
    )
    try:
        with (output / "worker.stderr.txt").open("x", encoding="utf-8") as stderr:
            async with stdio_client(params, errlog=stderr) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    transport = MCPTransport(
                        client,
                        timeout_seconds=40,
                        tool_names=frozenset(registry),
                        contract="READ",
                    )
                    async with asyncio.timeout(180):
                        graph = await LangGraphAgent(
                            planner,
                            ReservedTransport(),
                            timeout_seconds=130,
                            tool_names=frozenset(registry),
                        ).run(question)
                    state.update(
                        graph_nodes=list(graph.visited_nodes),
                        graph_status=graph.status,
                        graph_error=graph.error_code,
                        orchestration="VERSIONED_LANGGRAPH_A2_HOST_CONTRACT",
                    )
                    if graph.status not in {"COMPLETED", "PLANNING_FAILED"}:
                        raise ValueError("GRAPH_INCOMPLETE")
        if exchange is not None:
            state.update(
                planner_invoked=exchange.used,
                planner_attempt=exchange.facts,
                planner_error=planner.error,
                proposal=planner.accepted.model_dump(mode="json") if planner.accepted else None,
            )
        else:
            state["proposal"] = proposal.model_dump(mode="json")
        if pending or budget.snapshot()["stopped"]:
            raise ValueError("CUSTODY_OR_DELIVERY_INCOMPLETE")
        state["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
        state["evidence_reference"] = f"/api/governed-chat/turns/{turn}"
        summary_sha = save(output / "summary.json", state)
        budget.close_safe_observation(state["observation"], summary_sha)
        state.update(custody="CLOSED", summary_sha256=summary_sha)
    except BaseException as error:
        state["error"] = (
            "CANCELLED_EXECUTION_UNKNOWN"
            if isinstance(error, asyncio.CancelledError)
            else "EXECUTION_OR_CUSTODY_HOLD"
        )
        if exchange is not None:
            state.update(
                planner_attempt=exchange.facts,
                planner_error=planner.error,
                planner_invoked=exchange.used,
            )
        if pending:
            try:
                budget.finish_mcp(state["observation"], "CLIENT_RECEIPT_UNKNOWN")
            except Exception:
                state["mcp_finish_ack"] = "UNKNOWN"
        try:
            budget.stop("CHAT_TURN_INCOMPLETE")
            state["stop_ack"] = True
        except Exception:
            state["stop_ack"] = False
        state["custody"] = "OPEN_OR_UNKNOWN"
    save(output / "returned.json", state)
    return state
