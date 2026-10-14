"""R1 composition guards, using synthetic reads and actual pinned SDK sessions.

These tests do not claim caller authentication. Private SDK transport access is
used only to challenge the session ingress guard; supported deployment is stdio.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Barrier

import anyio
import pytest
from mcp import ClientSession, types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_client_server_memory_streams

from civicgate.mcp.server import BoundedMCPServer, create_server
from tests.adversarial.test_containment_isolation import (
    PUBLIC_REQUEST,
    assert_contained,
    instance,
    proposal,
)

ARGUMENTS = {"user_request": PUBLIC_REQUEST, "query": {"award_id": "1"}}
DENIED_ARGUMENTS = {"user_request": "Execute payment.", "query": {"award_id": "1"}}


@asynccontextmanager
async def sdk_session(server):
    """Real SDK JSON-RPC sessions over memory streams, with no external I/O."""
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as group:
            group.start_soon(
                server._mcp_server.run,
                *server_streams,
                server._mcp_server.create_initialization_options(),
            )
            async with ClientSession(*client_streams) as session:
                await session.initialize()
                yield session
            group.cancel_scope.cancel()


def test_attachment_claim_is_atomic_across_trusted_host_threads() -> None:
    gateway, backend, judge = instance()
    barrier = Barrier(2)

    def attach():
        barrier.wait(timeout=5)
        try:
            return create_server(gateway)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attach(), range(2)))
    assert sum(isinstance(result, BoundedMCPServer) for result in results) == 1
    errors = [result for result in results if isinstance(result, ValueError)]
    assert len(errors) == 1 and "already has an MCP server owner" in str(errors[0])
    assert gateway.trace.events == [] and backend.calls == [] and judge.calls == 0


async def test_single_wrapper_keeps_trusted_direct_gateway_calls_compatible() -> None:
    gateway, backend, judge = instance()
    server = create_server(gateway)
    assert len(await server.list_tools()) == 4
    direct = await gateway.call(PUBLIC_REQUEST, proposal())
    _, wrapped = await server.call_tool("get_federal_award", ARGUMENTS)
    assert direct.decision == wrapped["decision"] == "PERMIT"
    assert direct.tool_executed and wrapped["tool_executed"]
    assert backend.calls == ["1", "1"] and judge.calls == 2
    with pytest.raises(ValueError, match="already has an MCP server owner"):
        create_server(gateway)


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
async def test_stdio_runner_claim_survives_every_exit_without_reset(monkeypatch, outcome) -> None:
    gateway, backend, judge = instance()
    for _ in range(2):
        await gateway.call("Execute payment.", proposal())
    server = create_server(gateway)
    started = []

    async def synthetic_stdio(self):
        started.append(self)
        if outcome == "failed":
            raise OSError("synthetic stdio failure")
        if outcome == "cancelled":
            raise asyncio.CancelledError

    monkeypatch.setattr(FastMCP, "run_stdio_async", synthetic_stdio)
    if outcome == "completed":
        await server.run_stdio_async()
    elif outcome == "failed":
        with pytest.raises(OSError, match="synthetic stdio failure"):
            await server.run_stdio_async()
    else:
        with pytest.raises(asyncio.CancelledError):
            await server.run_stdio_async()
    with pytest.raises(ValueError, match="re-entry is prohibited"):
        await server.run_stdio_async()
    with pytest.raises(ValueError, match="already has an MCP server owner"):
        create_server(gateway)
    assert started == [server]
    assert len(await server.list_tools()) == 4
    assert_contained(await gateway.call(PUBLIC_REQUEST, proposal()))
    assert backend.calls == [] and judge.calls == 0


async def test_concurrent_stdio_runner_is_rejected_before_second_transport(monkeypatch) -> None:
    gateway, _, _ = instance()
    server = create_server(gateway)
    entered, release = asyncio.Event(), asyncio.Event()
    starts = []

    async def synthetic_stdio(self):
        starts.append(self)
        entered.set()
        await release.wait()

    monkeypatch.setattr(FastMCP, "run_stdio_async", synthetic_stdio)
    running = asyncio.create_task(server.run_stdio_async())
    await entered.wait()
    with pytest.raises(ValueError, match="re-entry is prohibited"):
        await server.run_stdio_async()
    assert starts == [server] and not running.done()
    release.set()
    await running
    with pytest.raises(ValueError, match="re-entry is prohibited"):
        await server.run_stdio_async()


def test_default_sync_stdio_runner_uses_one_lifetime_claim(monkeypatch) -> None:
    gateway, _, _ = instance()
    server = create_server(gateway)
    starts = []

    async def synthetic_stdio(self):
        starts.append(self)

    monkeypatch.setattr(FastMCP, "run_stdio_async", synthetic_stdio)
    server.run()
    assert starts == [server]
    with pytest.raises(ValueError, match="re-entry is prohibited"):
        server.run(transport="stdio")
    assert starts == [server]


@pytest.mark.parametrize("transport", ["sse", "streamable-http", "unknown"])
def test_sync_network_transport_rejected_before_sdk_start(monkeypatch, transport) -> None:
    gateway, _, _ = instance()
    server = create_server(gateway)
    starts = []
    monkeypatch.setattr(FastMCP, "run", lambda *args, **kwargs: starts.append(args))
    with pytest.raises(ValueError, match="stdio owner only"):
        server.run(transport=transport)
    assert starts == [] and not server._stdio_started


@pytest.mark.parametrize("factory", ["sse_app", "streamable_http_app"])
def test_network_app_factory_rejected_before_sdk_construction(monkeypatch, factory) -> None:
    gateway, _, _ = instance()
    server = create_server(gateway)
    starts = []
    monkeypatch.setattr(FastMCP, factory, lambda *args, **kwargs: starts.append(args))
    with pytest.raises(ValueError, match="stdio owner only"):
        getattr(server, factory)()
    assert starts == [] and not server._stdio_started


@pytest.mark.parametrize("runner", ["run_sse_async", "run_streamable_http_async"])
async def test_async_network_runner_rejected_before_sdk_start(monkeypatch, runner) -> None:
    gateway, _, _ = instance()
    server = create_server(gateway)
    starts = []

    async def forbidden(*args, **kwargs):
        starts.append(args)

    monkeypatch.setattr(FastMCP, runner, forbidden)
    with pytest.raises(ValueError, match="stdio owner only"):
        await getattr(server, runner)()
    assert starts == [] and not server._stdio_started


async def test_actual_sdk_second_session_rejected_even_with_matching_caller_metadata() -> None:
    gateway, backend, judge = instance()
    server = create_server(gateway)
    async with sdk_session(server) as first, sdk_session(server) as second:
        metadata = types.PaginatedRequestParams(
            _meta={"client_id": "shared-id", "session_id": "same"}
        )
        assert len((await first.list_tools(params=metadata)).tools) == 4
        owner = server._session_owner
        before = len(gateway.trace.events)
        rejected = await second.call_tool(
            "get_federal_award", ARGUMENTS, meta={"client_id": "shared-id", "session_id": "same"}
        )
        assert rejected.isError
        assert server._session_owner is owner
        assert len(gateway.trace.events) == before and backend.calls == [] and judge.calls == 0
        with pytest.raises(McpError, match="session sharing is prohibited"):
            await second.list_tools()
        for _ in range(2):
            denied = await first.call_tool(
                "get_federal_award",
                DENIED_ARGUMENTS,
                meta={"client_id": "shared-id", "session_id": "same"},
            )
            assert not denied.isError and denied.structuredContent["decision"] == "DENY"
        contained = await first.call_tool(
            "get_federal_award", ARGUMENTS, meta={"client_id": "changed", "session_id": "new"}
        )
        assert not contained.isError
        assert (
            "SESSION_CONTAINMENT_ACTIVE"
            in contained.structuredContent["governance"]["policy_reasons"]
        )
        assert not contained.structuredContent["tool_executed"]
        assert server._session_owner is owner
    assert backend.calls == [] and judge.calls == 0


async def test_actual_sdk_closed_session_does_not_release_owner_or_containment() -> None:
    gateway, backend, judge = instance()
    server = create_server(gateway)
    async with sdk_session(server) as first:
        for _ in range(2):
            denied = await first.call_tool("get_federal_award", DENIED_ARGUMENTS)
            assert denied.structuredContent["decision"] == "DENY"
        owner = server._session_owner
    async with sdk_session(server) as second:
        rejected = await second.call_tool("get_federal_award", ARGUMENTS)
        assert rejected.isError and server._session_owner is owner
    assert_contained(await gateway.call(PUBLIC_REQUEST, proposal()))
    assert backend.calls == [] and judge.calls == 0


async def test_actual_sdk_concurrent_sessions_bind_exactly_one_owner() -> None:
    gateway, backend, judge = instance()
    server = create_server(gateway)
    async with sdk_session(server) as first, sdk_session(server) as second:
        results = await asyncio.gather(
            first.list_tools(), second.list_tools(), return_exceptions=True
        )
        assert sum(isinstance(result, McpError) for result in results) == 1
        assert sum(not isinstance(result, BaseException) for result in results) == 1
        winner, loser = (
            (first, second) if not isinstance(results[0], BaseException) else (second, first)
        )
        accepted = await winner.call_tool("get_federal_award", ARGUMENTS)
        rejected = await loser.call_tool("get_federal_award", ARGUMENTS)
        assert not accepted.isError and accepted.structuredContent["decision"] == "PERMIT"
        assert accepted.structuredContent["tool_executed"]
        assert rejected.isError
    assert backend.calls == ["1"] and judge.calls == 1


async def test_actual_sdk_separate_gateways_isolate_concurrent_containment() -> None:
    first_gateway, first_backend, first_judge = instance()
    second_gateway, second_backend, second_judge = instance()
    first_server, second_server = create_server(first_gateway), create_server(second_gateway)
    async with sdk_session(first_server) as first, sdk_session(second_server) as second:
        for _ in range(2):
            denied, accepted = await asyncio.gather(
                first.call_tool("get_federal_award", DENIED_ARGUMENTS),
                second.call_tool("get_federal_award", ARGUMENTS),
            )
            assert denied.structuredContent["decision"] == "DENY"
            assert accepted.structuredContent["decision"] == "PERMIT"
        contained, accepted = await asyncio.gather(
            first.call_tool("get_federal_award", ARGUMENTS),
            second.call_tool("get_federal_award", ARGUMENTS),
        )
        assert (
            "SESSION_CONTAINMENT_ACTIVE"
            in contained.structuredContent["governance"]["policy_reasons"]
        )
        assert not contained.structuredContent["tool_executed"]
        assert accepted.structuredContent["decision"] == "PERMIT"
        assert accepted.structuredContent["tool_executed"]
    assert first_backend.calls == [] and first_judge.calls == 0
    assert second_backend.calls == ["1", "1", "1"] and second_judge.calls == 3


@pytest.mark.parametrize("field", ["session_id", "owner", "client_id", "reset"])
async def test_payload_cannot_select_or_reset_owner(field) -> None:
    gateway, backend, judge = instance()
    server = create_server(gateway)
    with pytest.raises(ToolError, match="Unexpected tool invocation fields"):
        await server.call_tool("get_federal_award", {**ARGUMENTS, field: "caller-selected"})
    assert gateway.trace.events == [] and backend.calls == [] and judge.calls == 0


async def test_same_owner_concurrent_denials_contain_the_following_call() -> None:
    gateway, backend, judge = instance()
    server = create_server(gateway)
    async with sdk_session(server) as session:
        denied = await asyncio.gather(
            session.call_tool("get_federal_award", DENIED_ARGUMENTS),
            session.call_tool("get_federal_award", DENIED_ARGUMENTS),
        )
        assert all(
            not result.isError and result.structuredContent["decision"] == "DENY"
            for result in denied
        )
        assert all(
            "SESSION_CONTAINMENT_ACTIVE"
            not in result.structuredContent["governance"]["policy_reasons"]
            for result in denied
        )
        for _ in range(3):
            assert len((await session.list_tools()).tools) == 4
            contained = await session.call_tool("get_federal_award", ARGUMENTS)
            assert not contained.isError
            assert (
                "SESSION_CONTAINMENT_ACTIVE"
                in contained.structuredContent["governance"]["policy_reasons"]
            )
            assert not contained.structuredContent["tool_executed"]
    assert backend.calls == [] and judge.calls == 0
