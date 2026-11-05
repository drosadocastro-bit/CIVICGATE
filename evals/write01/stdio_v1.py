"""Fixed host-selected synthetic WRITE stdio server, never a legacy route."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ContentBlock, Tool, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from civicgate.mcp.discovery import _contract
from civicgate.mcp.server import BoundedMCPServer
from evals.write01.authority_v1 import HostApproval
from evals.write01.contract_v1 import READ_TOOL, WRITE_TOOL, ReadQueryV1, WriteQueryV1
from evals.write01.gateway_v1 import AuditSink, WriteGatewayV1, WriteResponseV1
from evals.write01.store_v1 import ReviewStore

ROOT = Path(__file__).resolve().parents[2]
UserRequest = Annotated[str, Field(min_length=1, max_length=4000)]


class WriteMCPServerV1(BoundedMCPServer):
    """Reuse stdio/session ownership; replace only the per-owner tool registry.

    The original BoundedMCPServer and its four READ tools remain unchanged.
    This server cannot instantiate a legacy Gateway or receive an owner selector.
    """

    def _snapshot(self) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                id(t),
                id(t.fn),
                id(t.fn_metadata),
                id(t.fn_metadata.arg_model),
                id(t.fn_metadata.output_model),
                _contract(t),
            )
            for t in self._tool_manager.list_tools()
        )

    def seal_discovery(self) -> None:
        if hasattr(self, "_write_schema"):
            raise ValueError("WRITE01_DISCOVERY_ALREADY_SEALED")
        tools = self._tool_manager.list_tools()
        if {t.name for t in tools} != {WRITE_TOOL, READ_TOOL} or len(tools) != 2:
            raise ValueError("WRITE01_REGISTRY_MISMATCH")
        self._write_schema = self._snapshot()

    def _verify_registry(self) -> None:
        if not hasattr(self, "_write_schema") or self._write_schema != self._snapshot():
            raise ToolError("WRITE01_REGISTRY_DRIFT")

    async def list_tools(self) -> list[Tool]:
        self._bind_request_session()
        self._verify_registry()
        tools = await FastMCP.list_tools(self)
        for tool in tools:
            tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        self._bind_request_session()
        self._verify_registry()
        if name not in {WRITE_TOOL, READ_TOOL}:
            raise ToolError("WRITE01_UNKNOWN_TOOL_NO_LEGACY_ROUTE")
        if type(arguments) is not dict or set(arguments) != {"user_request", "query"}:
            raise ToolError("WRITE01_AUTHORITY_AND_ROUTING_FIELDS_FORBIDDEN")
        # Do not allow SDK JSON-text coercion to obscure the public wire shape.
        if type(arguments["query"]) is not dict or type(arguments["user_request"]) is not str:
            raise ToolError("WRITE01_TYPED_OBJECT_REQUIRED")
        return await FastMCP.call_tool(self, name, arguments)


def create_server(gateway: WriteGatewayV1) -> WriteMCPServerV1:
    server = WriteMCPServerV1(
        "CivicGate-WRITE01-synthetic-only",
        instructions="Discovery is not authority. Only host-approved synthetic review-state operations. No legacy routing, governmental decisions, provider activation or real award mutation.",
    )
    gateway.claim_server(server)

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        )
    )
    async def update_synthetic_award_review(
        user_request: UserRequest, query: WriteQueryV1
    ) -> WriteResponseV1:
        """Append one synthetic review note and move UNREVIEWED to PENDING_REVIEW. Requires exact host approval, expected version and one-use binding. Duplicate keys reject; do not retry unknown results."""
        return gateway.call(user_request, WRITE_TOOL, query.model_dump(mode="json"))

    @server.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        )
    )
    async def get_synthetic_award_review_v1(
        user_request: UserRequest, query: ReadQueryV1
    ) -> WriteResponseV1:
        """Read the versioned synthetic review-state overlay with exact host-approved scope. The immutable awards dataset and legacy tool results are not altered."""
        return gateway.call(user_request, READ_TOOL, query.model_dump(mode="json"))

    server.seal_discovery()
    return server


class ApprovalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    original_request: UserRequest
    tool: Literal["update_synthetic_award_review", "get_synthetic_award_review_v1"]
    query: dict[str, Any]
    reference: str = Field(min_length=1, max_length=100)
    approved: bool


class HostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["WRITE01_SYNTHETIC_ONLY"]
    database: str
    audit_path: str
    owner_id: str = Field(min_length=1, max_length=100)
    store_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    approvals: list[ApprovalConfig] = Field(max_length=10)


def configured_server(path: Path) -> WriteMCPServerV1:
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("WRITE01_HOST_CONFIG_INVALID")
    config = HostConfig.model_validate_json(path.read_bytes())
    database, audit = Path(config.database), Path(config.audit_path)
    for target in (database, audit):
        if not target.is_absolute() or target.is_symlink() or target.resolve().is_relative_to(ROOT):
            raise ValueError("WRITE01_PRIVATE_STORAGE_REQUIRED")
    # No create-on-open, client-provided database path, profile or authority.
    store = ReviewStore(database, ROOT / "evals/data01/awards_v1.json", config.store_id)
    approvals = tuple(
        HostApproval.for_operation(
            original_request=row.original_request,
            tool=row.tool,
            query=row.query,
            owner_id=config.owner_id,
            store_id=config.store_id,
            reference=row.reference,
            approved=row.approved,
        )
        for row in config.approvals
    )
    return create_server(
        WriteGatewayV1(
            store,
            config.owner_id,
            config.store_id,
            approvals,
            AuditSink(audit),
            run_id=config.run_id,
        )
    )


def main() -> None:
    # Reuse the offline evaluation guards; no provider/backend network client
    # is configured. This is cooperative instrumentation, not an OS sandbox.
    from evals.harness.eval_002b_composition_v4 import install_fixture_network_guard
    from evals.harness.live_composition_v3 import install_dataset_guard

    install_fixture_network_guard()
    install_dataset_guard()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-config", type=Path, required=True)
    args = parser.parse_args()
    configured_server(args.host_config).run(transport="stdio")


if __name__ == "__main__":
    main()
