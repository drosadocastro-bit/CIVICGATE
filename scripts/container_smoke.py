"""Real MCP initialization and fail-closed call through a hardened Linux container."""

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "--rm",
            "-i",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp",
            "civicgate:test",
        ],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        assert len((await session.list_tools()).tools) == 4
        result = await session.call_tool(
            "get_federal_award",
            {"user_request": "Get public award details", "query": {"award_id": "1"}},
        )
        assert result.structuredContent["decision"] == "REVIEW_REQUIRED"
        assert not result.structuredContent["tool_executed"]
        print("Container MCP smoke passed")


asyncio.run(main())
