import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_contract(tmp_path) -> None:
    env = dict(
        os.environ,
        CIVICGATE_PROVIDER="unavailable",
        CIVICGATE_AUDIT_PATH=str(tmp_path / "audit.jsonl"),
    )
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "civicgate.mcp.server"], env=env
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        assert len(tools) == 4
        assert all(tool.outputSchema and tool.annotations.readOnlyHint for tool in tools)
        result = await session.call_tool(
            "get_federal_award",
            {"user_request": "Get public award details", "query": {"award_id": "1"}},
        )
        assert result.structuredContent["decision"] == "REVIEW_REQUIRED"
        assert not result.structuredContent["tool_executed"]
        bad = await session.call_tool(
            "get_federal_award", {"user_request": "Details", "query": {"award_id": "../private"}}
        )
        assert bad.isError
        unknown = await session.call_tool("hidden_tool", {})
        assert unknown.isError
