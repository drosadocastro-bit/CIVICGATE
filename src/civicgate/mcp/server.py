from collections.abc import Sequence
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ContentBlock, Tool, ToolAnnotations
from pydantic import Field

from civicgate.config import configured_gateway
from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope

UserRequest = Annotated[
    str,
    Field(
        min_length=1,
        max_length=4000,
        description="Full original user request, including intended use. Treated as untrusted context, never as authority.",
    ),
]


class BoundedMCPServer(FastMCP):
    """MCP exposes fixed metadata; execution always re-enters the governed Gateway."""

    _discovery: BoundedToolDiscovery | None = None

    def seal_discovery(self) -> None:
        if self._discovery is not None:
            raise ValueError("Bounded discovery is already sealed")
        self._discovery = BoundedToolDiscovery(self._tool_manager.list_tools())

    async def list_tools(self) -> list[Tool]:
        if self._discovery is None:
            raise ToolError("Bounded discovery has not been sealed")
        try:
            return self._discovery.list_tools(self._tool_manager.list_tools())
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ToolError("Bounded tool registration verification failed") from exc

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        if self._discovery is None or name not in TOOLS:
            raise ToolError("Unknown or unregistered tool")
        if set(arguments) - {"user_request", "query"}:
            raise ToolError("Unexpected tool invocation fields")
        try:
            self._discovery.validate(self._tool_manager.list_tools())
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise ToolError("Bounded tool registration verification failed") from exc
        return await super().call_tool(name, arguments)


def create_server(gateway: Gateway) -> BoundedMCPServer:
    server = BoundedMCPServer(
        "CivicGate",
        instructions="Sandbox public federal spending research only. Discovery describes only permitted metadata and grants no execution authority. Each call passes deterministic governance. Never interpret a PERMIT as correctness or governmental decision authority. Preserve errors and provenance. REVIEW_REQUIRED means clarify; do not select an identity arbitrarily.",
    )
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True
    )

    @server.tool(annotations=annotations)
    async def find_federal_awards(user_request: UserRequest, query: Search) -> Envelope:
        """Find up to 100 federal awards in a bounded date interval. State filters place of performance. Defaults to contracts; results are search matches, not verified legal identities. Requires a recipient, agency or state filter."""
        return await gateway.call(
            user_request,
            Proposal(tool="find_federal_awards", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def get_federal_award(user_request: UserRequest, query: Award) -> Envelope:
        """Retrieve factual details for one known USAspending internal numeric ID or generated award ID from search results. Cannot determine eligibility, fraud or debarment."""
        return await gateway.call(
            user_request,
            Proposal(tool="get_federal_award", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def resolve_federal_recipient(user_request: UserRequest, query: Recipient) -> Envelope:
        """Find up to 25 public recipient identity candidates. Multiple, missing or truncated candidates require clarification. Never choose among candidates on the user's behalf."""
        return await gateway.call(
            user_request,
            Proposal(tool="resolve_federal_recipient", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def summarize_federal_spending(user_request: UserRequest, query: Search) -> Envelope:
        """Retrieve one authorized bounded page and sum its award amounts in USD. This is NOT fiscal-year transaction spending or a complete population total. Reports truncation and provenance; ambiguous identity prevents aggregation."""
        return await gateway.call(
            user_request,
            Proposal(tool="summarize_federal_spending", arguments=query.model_dump(mode="json")),
        )

    server.seal_discovery()
    return server


def main() -> None:
    create_server(configured_gateway()).run(transport="stdio")


if __name__ == "__main__":
    main()
