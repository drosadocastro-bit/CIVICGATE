"""Client observations never create Gateway policy or infer non-dispatch on error."""

import asyncio
import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from mcp import types
from mcp.shared.exceptions import McpError

from civicgate.mcp.client import DiscoveryError, MCPTransport, ToolMetadata
from civicgate.mcp.server import create_server
from civicgate.models.requests import Proposal


class SyntheticSession:
    def __init__(self, tools=(), response=None, error=None, delay=0):
        self.tools = list(tools)
        self.response = response
        self.error = error
        self.delay = delay
        self.calls = []
        self.cursor = None

    async def list_tools(self):
        return types.ListToolsResult(tools=self.tools, nextCursor=self.cursor)

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.response


def proposal():
    return Proposal(tool="get_federal_award", arguments={"award_id": "1"})


async def test_only_bounded_metadata_is_retained_and_copies_are_independent(gateway):
    tools = await create_server(gateway).list_tools()
    tools[0].meta = {"authority": "PERMIT", "backend_secret": "synthetic-hidden"}
    tools[0].annotations.model_extra["authority"] = "PERMIT"
    session = SyntheticSession(tools)
    metadata = await MCPTransport(session).discover()
    assert len(metadata) == 4 and all(type(tool) is ToolMetadata for tool in metadata)
    before = metadata[0].input_schema_json
    copy = metadata[0].input_schema
    copy.clear()
    assert metadata[0].input_schema_json == before and metadata[0].input_schema
    assert "synthetic-hidden" not in repr(metadata)
    assert "authority" not in metadata[0].annotations_json
    assert session.calls == []
    with pytest.raises(FrozenInstanceError):
        metadata[0].name = "hidden_tool"


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown", "pagination", "schema"])
async def test_discovery_rejects_unsupported_contracts(gateway, fault):
    tools = await create_server(gateway).list_tools()
    session = SyntheticSession(tools)
    if fault == "missing":
        session.tools.pop()
    elif fault == "duplicate":
        session.tools[-1] = session.tools[0]
    elif fault == "unknown":
        session.tools[0].name = "hidden_tool"
    elif fault == "pagination":
        session.cursor = "unsupported-second-page"
    else:
        session.tools[0].inputSchema["additionalProperties"] = True
    with pytest.raises(DiscoveryError):
        await MCPTransport(session).discover()
    assert session.calls == []


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), True, "5"])
def test_invalid_transport_timeouts_rejected(seconds):
    with pytest.raises(ValueError):
        MCPTransport(SyntheticSession(), timeout_seconds=seconds)


async def test_governed_response_preserves_original_decision_and_independent_receipt(gateway):
    result = await gateway.call("Execute payment", proposal())
    session = SyntheticSession(
        response=types.CallToolResult(content=[], structuredContent=result.model_dump(mode="json"))
    )
    observation = await MCPTransport(session).invoke("Execute payment", proposal())
    assert observation.status == "GOVERNED_RESPONSE"
    assert observation.envelope.decision == "DENY"
    assert observation.dispatch_state == "NOT_DISPATCHED"
    observation.envelope.decision = "PERMIT"
    assert observation.envelope.decision == "DENY"
    assert session.calls == [
        ("get_federal_award", {"user_request": "Execute payment", "query": {"award_id": "1"}})
    ]


async def test_mcp_tool_error_is_unknown_dispatch_and_no_policy_even_with_payload(gateway):
    envelope = await gateway.call("Public award details", proposal())
    session = SyntheticSession(
        response=types.CallToolResult(
            content=[], isError=True, structuredContent=envelope.model_dump(mode="json")
        )
    )
    result = await MCPTransport(session).invoke("Public award details", proposal())
    assert result.status == "MCP_TOOL_ERROR"
    assert result.envelope is None and result.dispatch_state == "DISPATCH_UNKNOWN"
    assert len(session.calls) == 1


@pytest.mark.parametrize("payload", [None, {}, {"decision": "PERMIT"}])
async def test_missing_or_malformed_structured_receipt_never_becomes_verified(payload):
    session = SyntheticSession(response=types.CallToolResult(content=[], structuredContent=payload))
    result = await MCPTransport(session).invoke("Public award details", proposal())
    assert result.status == "INVALID_GATEWAY_RESPONSE"
    assert result.envelope is None and result.dispatch_state == "DISPATCH_UNKNOWN"


async def test_returned_tool_substitution_is_rejected(gateway):
    envelope = await gateway.call("Public award details", proposal())
    envelope.tool = "summarize_federal_spending"
    session = SyntheticSession(
        response=types.CallToolResult(
            content=[], structuredContent=envelope.model_dump(mode="json")
        )
    )
    result = await MCPTransport(session).invoke("Public award details", proposal())
    assert result.status == "INVALID_GATEWAY_RESPONSE"
    assert result.envelope is None


@pytest.mark.parametrize("code,expected", [(408, "TRANSPORT_TIMEOUT"), (-32601, "PROTOCOL_ERROR")])
async def test_jsonrpc_failure_never_infers_a_gateway_decision_or_retries(code, expected):
    session = SyntheticSession(error=McpError(types.ErrorData(code=code, message="synthetic")))
    result = await MCPTransport(session).invoke("Public award details", proposal())
    assert result.status == expected
    assert result.envelope is None and result.dispatch_state == "DISPATCH_UNKNOWN"
    assert len(session.calls) == 1


async def test_outer_transport_timeout_is_unknown_and_not_retried():
    session = SyntheticSession(delay=1)
    result = await MCPTransport(session, timeout_seconds=0.001).invoke(
        "Public award details", proposal()
    )
    assert result.status == "TRANSPORT_TIMEOUT"
    assert result.envelope is None and result.dispatch_state == "DISPATCH_UNKNOWN"
    assert len(session.calls) == 1


async def test_transport_exception_body_is_not_released():
    session = SyntheticSession(error=RuntimeError("synthetic-sensitive-provider-body"))
    result = await MCPTransport(session).invoke("Public award details", proposal())
    assert result.status == "PROTOCOL_ERROR" and result.envelope is None
    assert "synthetic-sensitive-provider-body" not in repr(result)


async def test_successful_transport_preserves_unverified_result_state(gateway):
    envelope = await gateway.call("Public award details", proposal())
    envelope.verification_state = "RESULT_UNKNOWN"
    envelope.result = None
    session = SyntheticSession(
        response=SimpleNamespace(
            isError=False, structuredContent=json.loads(envelope.model_dump_json())
        )
    )
    result = await MCPTransport(session).invoke("Public award details", proposal())
    assert result.status == "GOVERNED_RESPONSE"
    assert result.envelope.verification_state == "RESULT_UNKNOWN"
    assert result.envelope.result is None
