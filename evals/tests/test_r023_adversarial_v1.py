"""Independent host-boundary controls; not primary SDK/stdio observations.

Private-field faults below characterize integrity checks inside a trusted local
host. They do not claim containment of arbitrary Python in a compromised host.
Actual raw MCP metadata, aliases and protocol reinitialization are separate
full-path controls in the R02.3 observation selection.
"""

from __future__ import annotations

import json
import sys

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from civicgate.audit.trace import Trace
from civicgate.models.governance import JudgeSignal
from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter
from evals.proposals.r022.faa_contract_v1 import PROFILE_ID, example_query
from evals.proposals.r022.stdio_v1 import (
    CANONICAL_REQUEST,
    ScopedFaaGateway,
    TrustedFaaIntake,
)
from evals.proposals.r023.host_v1 import (
    HOST_FIXED_MODULE,
    HostCompositionError,
    HostSelectedFaaComposition,
    TrustedFaaLaunchOwner,
)


class Judge:
    async def assess(self, request, proposal):
        return JudgeSignal(
            available=True,
            classification="IN_SCOPE",
            confidence=0.99,
            flags=[],
            provider="R023_INDEPENDENT_SYNTHETIC_UNIT_JUDGE",
        )


def host(tmp_path):
    intake = TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query()))
    config = tmp_path / "host-config.json"
    config.write_text(
        json.dumps(
            {
                "mode": "R023_SYNTHETIC_STDIO_ONLY",
                "database": str(tmp_path / "unit-only.sqlite"),
                "run_id": "R023_INDEPENDENT_UNIT_RUN",
                "observation_id": "R023_INDEPENDENT_UNIT_OBSERVATION",
                "fence_id": "R023_INDEPENDENT_UNIT_FENCE",
                "evidence_dir": str(tmp_path),
                "intake": {
                    "request": intake.original_request,
                    "query_json": intake.expected_query_json,
                },
                "backend_mode": "normal",
            }
        ),
        encoding="utf8",
    )
    return TrustedFaaLaunchOwner(config, intake), config


def composition():
    intake = TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query()))
    adapter, trace = FaaProfileFixtureAdapter(), Trace()
    gateway = ScopedFaaGateway(adapter, Judge(), trace, intake=intake)
    return HostSelectedFaaComposition.from_gateway(gateway), adapter, trace


@pytest.mark.parametrize(
    "transport,endpoint",
    [
        (None, None),
        (17, None),
        ({"transport": "stdio"}, None),
        ([], None),
        ("stdio", "file:///legacy/mcp"),
        ("stdio", "../legacy"),
        ("stdio", "stdio://civicgate.mcp.server"),
    ],
)
def test_non_string_transport_and_non_http_routes_cannot_acquire_a_launch(
    tmp_path, transport, endpoint
):
    owner, _ = host(tmp_path)
    with pytest.raises(HostCompositionError, match="HOST_ROUTE_NOT_EXPOSED"):
        owner.consume(owner.capability, transport=transport, endpoint=endpoint)
    assert owner.state == "READY"
    assert owner.selection_snapshot()["worker_module"] == HOST_FIXED_MODULE


@pytest.mark.parametrize("change", ["module", "config", "command"])
def test_changed_internal_launch_target_is_not_silently_used(tmp_path, change):
    owner, config = host(tmp_path)
    if change == "command":
        owner._command = "not-an-authorized-interpreter"
    elif change == "module":
        owner._args = ("-B", "-m", "civicgate.mcp.server")
    else:
        owner._args = (
            "-B",
            "-m",
            HOST_FIXED_MODULE,
            "--worker-config",
            str(config.with_name("legacy-context.json")),
        )
    with pytest.raises(HostCompositionError, match="HOST_LAUNCH_TARGET_INTEGRITY_FAILURE"):
        owner.consume(owner.capability)
    assert owner.state == "FAILED"
    with pytest.raises(HostCompositionError, match="ALREADY_CONSUMED_OR_FINISHED"):
        owner.consume(owner.capability)


def test_deleted_context_after_selection_does_not_produce_launch_parameters(tmp_path):
    owner, config = host(tmp_path)
    config.unlink()
    with pytest.raises(OSError):
        owner.consume(owner.capability)
    assert owner.state == "FAILED"


def test_synthetic_credential_environment_does_not_enter_the_launch(tmp_path, monkeypatch):
    # Only synthetic sentinels are set/read; no credential store is accessed.
    names = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DATABRICKS_TOKEN", "HTTP_PROXY")
    for name in names:
        monkeypatch.setenv(name, "SYNTHETIC_SENTINEL_NOT_A_CREDENTIAL")
    owner, _ = host(tmp_path)
    params = owner.consume(owner.capability)
    assert params.command == sys.executable
    assert all(name not in params.env for name in names)


async def test_mutating_a_returned_selection_record_cannot_change_the_actual_gateway():
    selected, adapter, trace = composition()
    record = selected.selection_snapshot()
    record.update(profile_id="LEGACY", worker_module="civicgate.mcp.server", tool_names=())
    assert trace.events == [] and adapter.entries == adapter.http_attempts == 0
    await selected._server.call_tool(
        "find_federal_awards",
        {"user_request": CANONICAL_REQUEST, "query": example_query()},
    )
    snapshot = selected.selection_snapshot()
    assert snapshot["profile_id"] == PROFILE_ID
    assert snapshot["worker_module"] == HOST_FIXED_MODULE
    policy = next(event for event in trace.events if event["stage"] == "policy")
    complete = next(event for event in trace.events if event["stage"] == "completed")
    assert policy["policy"]["decision"] == "PERMIT" and policy["binding_issued"] is True
    assert complete["pre_dispatch_verification"] == "PASS"
    assert len(complete["response"]["result"]["records"]) == 16
    assert adapter.entries == adapter.http_attempts == 1


async def test_runtime_alias_registration_invalidates_discovery_instead_of_adding_a_route():
    selected, adapter, trace = composition()
    entered = []

    async def legacy_alias():
        entered.append(True)
        return {"not": "a real legacy gateway"}

    selected._server.add_tool(legacy_alias, name="legacy.find_federal_awards")
    with pytest.raises(ToolError, match="registration verification failed"):
        await selected._server.list_tools()
    with pytest.raises(ToolError, match="registration verification failed"):
        await selected._server.call_tool(
            "find_federal_awards",
            {"user_request": CANONICAL_REQUEST, "query": example_query()},
        )
    assert entered == [] and trace.events == []
    assert adapter.entries == adapter.http_attempts == 0


@pytest.mark.parametrize("method", ["sse_app", "streamable_http_app"])
def test_selected_server_cannot_be_reexposed_as_an_http_application(method):
    selected, adapter, trace = composition()
    with pytest.raises(ValueError, match="one trusted stdio owner only"):
        getattr(selected._server, method)()
    assert adapter.entries == adapter.http_attempts == 0 and trace.events == []


@pytest.mark.parametrize("method", ["run_sse_async", "run_streamable_http_async"])
async def test_selected_server_rejects_alternate_transport_execution(method):
    selected, adapter, trace = composition()
    with pytest.raises(ValueError, match="one trusted stdio owner only"):
        await getattr(selected._server, method)()
    assert adapter.entries == adapter.http_attempts == 0 and trace.events == []


async def test_lost_contract_reference_is_rejected_before_stdio_entry(monkeypatch):
    selected, adapter, trace = composition()
    selected._gateway._contract = None
    entries = []

    async def stdio():
        entries.append(True)

    monkeypatch.setattr(selected._server, "run_stdio_async", stdio)
    with pytest.raises(HostCompositionError, match="HOST_COMPOSITION_SELECTION_CHANGED"):
        await selected.run_stdio()
    assert entries == [] and selected.state == "FAILED"
    assert adapter.entries == adapter.http_attempts == 0 and trace.events == []
