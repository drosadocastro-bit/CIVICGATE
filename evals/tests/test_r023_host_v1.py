"""Host-only launch/lifecycle controls, distinct from real MCP observations."""

from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace

import pytest

from civicgate.audit.trace import Trace
from civicgate.mcp.tools import Gateway
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
    HOST_FIXED_ROUTE,
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
            provider="R023_SYNTHETIC_HOST_UNIT_JUDGE",
        )


def intake():
    return TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query()))


def prepared():
    return ScopedFaaGateway(FaaProfileFixtureAdapter(), Judge(), Trace(), intake=intake())


def host_config(tmp_path):
    original = intake()
    values = {
        "mode": "R023_SYNTHETIC_STDIO_ONLY",
        "database": str(tmp_path / "synthetic.sqlite"),
        "run_id": "SYNTHETIC_R023_RUN",
        "observation_id": "SYNTHETIC_R023_OBSERVATION",
        "fence_id": "SYNTHETIC_R023_FENCE",
        "evidence_dir": str(tmp_path),
        "intake": {
            "request": original.original_request,
            "query_json": original.expected_query_json,
        },
        "backend_mode": "normal",
    }
    file = tmp_path / "worker-config.json"
    file.write_text(json.dumps(values), encoding="utf8")
    return file, values, original


def test_host_selects_one_fixed_launch_route_before_discovery(tmp_path):
    file, _, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)
    snapshot = host.selection_snapshot()
    assert snapshot["route"] == HOST_FIXED_ROUTE
    assert snapshot["profile_id"] == PROFILE_ID
    assert snapshot["transport"] == "stdio"
    assert snapshot["legacy_routes_exposed"] == 0
    assert snapshot["launch_state"] == "READY"
    parameters = host.consume(host.capability)
    assert parameters.command == sys.executable
    assert parameters.args == ["-B", "-m", HOST_FIXED_MODULE, "--worker-config", str(file)]
    assert host.state == "CONSUMED"
    assert not any("key" in name.lower() or "token" in name.lower() for name in parameters.env)
    assert "OPENAI_API_KEY" not in parameters.env and "ANTHROPIC_API_KEY" not in parameters.env


def test_capability_and_selection_are_immutable_but_not_human_authentication(tmp_path):
    file, _, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)
    with pytest.raises(FrozenInstanceError):
        host.capability.config_sha256 = "0" * 64
    with pytest.raises(FrozenInstanceError):
        host.capability.selection.profile_id = "legacy"
    snapshot = host.selection_snapshot()
    snapshot["profile_id"] = "legacy"
    assert host.selection_snapshot()["profile_id"] == PROFILE_ID
    assert host.selection_snapshot()["capability_is_not_human_or_execution_authority"]


@pytest.mark.parametrize("forgery", ["copy", "dict", "other_host", "none"])
def test_caller_supplied_or_self_generated_record_does_not_acquire_host_route(tmp_path, forgery):
    file, _, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)
    candidate = {
        "copy": replace(host.capability),
        "dict": host.selection_snapshot(),
        "other_host": TrustedFaaLaunchOwner(file, original).capability,
        "none": None,
    }[forgery]
    with pytest.raises(HostCompositionError, match="CAPABILITY_NOT_OWNED"):
        host.consume(candidate)
    assert host.state == "READY"


@pytest.mark.parametrize(
    "transport,endpoint",
    [
        ("sse", None),
        ("streamable-http", None),
        ("http", "http://127.0.0.1:8765/mcp"),
        ("stdio", "legacy"),
        ("stdio", ""),
        ("stdio", "https://invalid.example/mcp"),
    ],
)
def test_alternate_transport_or_endpoint_is_not_reachable_through_host_route(
    tmp_path, transport, endpoint
):
    file, _, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)
    with pytest.raises(HostCompositionError, match="HOST_ROUTE_NOT_EXPOSED"):
        host.consume(host.capability, transport=transport, endpoint=endpoint)
    assert host.state == "READY"


@pytest.mark.parametrize("key", ["owner", "gateway", "profile", "transport", "endpoint"])
def test_context_cannot_add_a_client_selected_route(tmp_path, key):
    file, values, original = host_config(tmp_path)
    values[key] = "legacy"
    file.write_text(json.dumps(values), encoding="utf8")
    with pytest.raises(HostCompositionError, match="HOST_CONFIG_FIELDS_INVALID"):
        TrustedFaaLaunchOwner(file, original)


@pytest.mark.parametrize("raw", ["not JSON", "[]", "NaN", '{"mode":1,"mode":2}'])
def test_malformed_context_has_no_default_or_fallback(tmp_path, raw):
    file, _, original = host_config(tmp_path)
    file.write_text(raw, encoding="utf8")
    with pytest.raises(HostCompositionError):
        TrustedFaaLaunchOwner(file, original)


@pytest.mark.parametrize("change", ["query", "request", "mode", "backend_mode", "missing"])
def test_invalid_or_contradictory_context_fails_before_launch(tmp_path, change):
    file, values, original = host_config(tmp_path)
    if change == "query":
        values["intake"]["query_json"] = json.dumps(example_query(limit=5))
    elif change == "request":
        values["intake"]["request"] = "Show public awards."
    elif change == "mode":
        values["mode"] = "legacy"
    elif change == "backend_mode":
        values["backend_mode"] = []
    else:
        del values["intake"]
    file.write_text(json.dumps(values), encoding="utf8")
    with pytest.raises(HostCompositionError):
        TrustedFaaLaunchOwner(file, original)


def test_changed_config_after_selection_consumes_context_without_legacy_fallback(tmp_path):
    file, values, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)
    file.write_text(json.dumps(values, indent=2), encoding="utf8")
    with pytest.raises(HostCompositionError, match="HOST_CONFIG_CHANGED_AFTER_SELECTION"):
        host.consume(host.capability)
    assert host.state == "FAILED"
    with pytest.raises(HostCompositionError, match="ALREADY_CONSUMED_OR_FINISHED"):
        host.consume(host.capability)


@pytest.mark.parametrize("success", [False, True])
def test_finish_or_failure_never_rearms_a_launch(tmp_path, success):
    file, _, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)
    host.consume(host.capability)
    host.finish(success=success)
    assert host.state == ("FINISHED" if success else "FAILED")
    with pytest.raises(HostCompositionError, match="ALREADY_CONSUMED_OR_FINISHED"):
        host.consume(host.capability)


def test_concurrent_host_consumers_cannot_launch_the_same_capability_twice(tmp_path):
    file, _, original = host_config(tmp_path)
    host = TrustedFaaLaunchOwner(file, original)

    def consume(_):
        try:
            host.consume(host.capability)
            return "CONSUMED"
        except HostCompositionError:
            return "REJECTED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == ["CONSUMED", "REJECTED"]
    assert host.state == "CONSUMED"


def test_host_rejects_legacy_gateway_instead_of_wrapping_it():
    gateway = Gateway(FaaProfileFixtureAdapter(), Judge(), Trace())
    with pytest.raises(HostCompositionError, match="STRICT_FAA_GATEWAY_REQUIRED"):
        HostSelectedFaaComposition.from_gateway(gateway)


def test_selected_server_binds_exact_existing_profile_before_discovery():
    gateway = prepared()
    composition = HostSelectedFaaComposition.from_gateway(gateway)
    snapshot = composition.selection_snapshot()
    assert snapshot["composition_state"] == "INITIALIZED"
    assert snapshot["profile_id"] == PROFILE_ID and snapshot["legacy_routes_exposed"] == 0
    assert len(snapshot["tool_names"]) == 4
    assert snapshot["intake_sha256"] == gateway.intake.intake_sha256


async def test_successful_stdio_completion_is_permanent_not_a_new_session(monkeypatch):
    composition = HostSelectedFaaComposition.from_gateway(prepared())
    entered = []

    async def stdio():
        entered.append(composition.state)

    monkeypatch.setattr(composition._server, "run_stdio_async", stdio)
    await composition.run_stdio()
    assert entered == ["STDIO_ENTERED"] and composition.state == "CLOSED"
    with pytest.raises(HostCompositionError, match="REENTRY_PROHIBITED"):
        await composition.run_stdio()


@pytest.mark.parametrize("error", [ValueError, TimeoutError, asyncio.CancelledError])
async def test_failed_stdio_never_retries_or_constructs_another_owner(monkeypatch, error):
    composition = HostSelectedFaaComposition.from_gateway(prepared())
    count = 0

    async def stdio():
        nonlocal count
        count += 1
        raise error("synthetic startup/stream failure")

    monkeypatch.setattr(composition._server, "run_stdio_async", stdio)
    with pytest.raises(error):
        await composition.run_stdio()
    assert count == 1 and composition.state == "FAILED"
    with pytest.raises(HostCompositionError, match="REENTRY_PROHIBITED"):
        await composition.run_stdio()
    assert count == 1


async def test_changed_selection_is_rejected_before_stdio(monkeypatch):
    gateway = prepared()
    composition = HostSelectedFaaComposition.from_gateway(gateway)
    gateway._intake = TrustedFaaIntake(
        'Show 5 public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2026.',
        json.dumps(example_query(limit=5)),
    )
    count = 0

    async def stdio():
        nonlocal count
        count += 1

    monkeypatch.setattr(composition._server, "run_stdio_async", stdio)
    with pytest.raises(HostCompositionError, match="HOST_COMPOSITION_SELECTION_CHANGED"):
        await composition.run_stdio()
    assert count == 0 and composition.state == "FAILED"
