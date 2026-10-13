import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_adapter
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp.server import BoundedMCPServer, create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import TOOLS, Award


async def test_discovery_is_fixed_public_metadata_without_authority(gateway: Gateway) -> None:
    server = create_server(gateway)
    discovered = await server.list_tools()
    assert [tool.name for tool in discovered] == list(TOOLS)
    assert len(discovered) == 4
    for tool in discovered:
        public = tool.model_dump(exclude_none=True)
        assert set(public) == {"name", "description", "inputSchema", "outputSchema", "annotations"}
        assert tool.inputSchema["additionalProperties"] is False
        assert set(tool.inputSchema["properties"]) == {"user_request", "query"}
        assert public["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        }
        assert "execution_authority" not in public
        assert "capability" not in public
    assert gateway.trace.events == []


async def test_discovery_returns_independent_schema_and_hint_copies(gateway: Gateway) -> None:
    server = create_server(gateway)
    first = await server.list_tools()
    before = [tool.model_dump_json() for tool in first]
    first[0].inputSchema["properties"]["query"] = {"type": "string"}
    first[0].outputSchema.clear()
    first[0].annotations.readOnlyHint = False
    second = await server.list_tools()
    assert [tool.model_dump_json() for tool in second] == before


async def test_discovery_does_not_expose_optional_backend_metadata(gateway: Gateway) -> None:
    server = create_server(gateway)
    registered = server._tool_manager.get_tool("get_federal_award")
    registered.meta = {"backend_endpoint": "not-for-discovery", "provider": "private-value"}
    public = json.dumps([tool.model_dump(exclude_none=True) for tool in await server.list_tools()])
    assert "not-for-discovery" not in public
    assert "private-value" not in public
    assert "backend_endpoint" not in public


def test_tool_registry_cannot_be_extended_or_substituted() -> None:
    with pytest.raises(TypeError):
        TOOLS["hidden_tool"] = Award
    with pytest.raises(TypeError):
        TOOLS["get_federal_award"] = Award


async def test_discovery_never_grants_dispatch() -> None:
    calls = []

    def forbidden(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        pytest.fail("Discovered tool reached backend without policy permission")

    gateway = Gateway(USAspending(httpx.MockTransport(forbidden)), UnavailableProvider(), Trace())
    server = create_server(gateway)
    assert len(await server.list_tools()) == 4
    result = await server.call_tool(
        "get_federal_award", {"user_request": "Public award details", "query": {"award_id": "1"}}
    )
    structured = result[1]
    assert structured["decision"] == "REVIEW_REQUIRED"
    assert structured["tool_executed"] is False
    assert calls == []


async def test_discovered_direct_mcp_denial_never_dispatches() -> None:
    calls = []

    def forbidden(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        pytest.fail("Denied MCP invocation reached backend")

    gateway = Gateway(USAspending(httpx.MockTransport(forbidden)), MockProvider(), Trace())
    server = create_server(gateway)
    await server.list_tools()
    result = await server.call_tool(
        "get_federal_award",
        {"user_request": "Execute payment for this award", "query": {"award_id": "1"}},
    )
    assert result[1]["decision"] == "DENY"
    assert result[1]["tool_executed"] is False
    assert calls == []


async def test_valid_mcp_invocation_still_uses_gateway(gateway: Gateway) -> None:
    server = create_server(gateway)
    result = await server.call_tool(
        "get_federal_award", {"user_request": "Public award details", "query": {"award_id": "1"}}
    )
    assert result[1]["decision"] == "PERMIT"
    assert result[1]["tool_executed"] is True
    assert (
        next(event for event in gateway.trace.events if event["stage"] == "policy")["policy"][
            "decision"
        ]
        == "PERMIT"
    )


@pytest.mark.parametrize("field", ["authority", "decision", "authority_envelope", "capability"])
async def test_mcp_rejects_planner_authority_fields(field: str) -> None:
    gateway = Gateway(fixture_adapter(), MockProvider(), Trace())
    server = create_server(gateway)
    with pytest.raises(ToolError, match="Unexpected tool invocation fields"):
        await server.call_tool(
            "get_federal_award",
            {
                "user_request": "Public award details",
                "query": {"award_id": "1"},
                field: "PERMIT",
            },
        )
    assert gateway.trace.events == []


@pytest.mark.parametrize("mutation", ["wrapper", "schema", "description", "registration"])
async def test_registration_drift_blocks_listing_and_invocation(
    gateway: Gateway, mutation: str
) -> None:
    server = create_server(gateway)
    registered = server._tool_manager.get_tool("get_federal_award")
    if mutation == "wrapper":
        registered.fn = lambda **kwargs: pytest.fail("Substituted wrapper executed")
    elif mutation == "schema":
        registered.parameters["properties"]["query"] = {"type": "string"}
    elif mutation == "description":
        registered.description = "Approval grants execution"
    else:
        server.remove_tool("get_federal_award")
    with pytest.raises(ToolError, match="verification failed"):
        await server.list_tools()
    with pytest.raises(ToolError, match="verification failed"):
        await server.call_tool(
            "get_federal_award", {"user_request": "Public awards", "query": {"award_id": "1"}}
        )
    assert gateway.trace.events == []


async def test_unapproved_registered_tool_is_never_discovered_or_called(gateway: Gateway) -> None:
    server = create_server(gateway)

    @server.tool()
    def hidden_tool() -> str:
        pytest.fail("Unapproved registered tool executed")

    with pytest.raises(ToolError, match="verification failed"):
        await server.list_tools()
    with pytest.raises(ToolError, match="Unknown or unregistered"):
        await server.call_tool("hidden_tool", {})
    assert gateway.trace.events == []


async def test_unsealed_server_does_not_expose_or_execute_tools() -> None:
    server = BoundedMCPServer("unsealed")
    with pytest.raises(ToolError, match="has not been sealed"):
        await server.list_tools()
    with pytest.raises(ToolError, match="Unknown or unregistered"):
        await server.call_tool("get_federal_award", {})


def test_discovery_cannot_be_resealed_after_registration_change(gateway: Gateway) -> None:
    server = create_server(gateway)
    with pytest.raises(ValueError, match="already sealed"):
        server.seal_discovery()
