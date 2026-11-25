"""Opt-in MCP_TOOL_METADATA_V2 discovery view for trusted host composition.

Only the SDK tools/list response handler is decorated. Frozen registrations,
session/auth checks, schemas, tool-call handlers, policy and dispatch are retained.
Install before transport startup. Direct server.list_tools remains the legacy view.
"""

from dataclasses import dataclass
from importlib.metadata import version
from typing import Any

import httpx
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ListToolsRequest, ListToolsResult, ServerResult

from civicgate.channel_b.cloud_smoke_v1 import CloudSmokeApp
from civicgate.channel_b.faa_http_v1 import FaaC1HTTPApp
from civicgate.llm.mock import MockProvider
from civicgate.mcp.http_app import StreamableHTTPGatewayApp
from civicgate.mcp.server import BoundedMCPServer

CONTRACT_ID = "MCP_TOOL_METADATA_V2"
_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


@dataclass(frozen=True)
class MetadataViewV2:
    contract_id: str
    profile: str


def _composition(owner: Any, gateway: Any) -> tuple[Any, str, Any]:
    if type(owner) is CloudSmokeApp:
        return owner.server, "cloud-discovery", None
    if type(owner) is FaaC1HTTPApp:
        return owner.server, "faa-c1-http", owner.gateway
    if type(owner) is StreamableHTTPGatewayApp:
        return owner.server, "b2a-http", owner.gateway
    if type(owner) is BoundedMCPServer:
        return owner, "primary-stdio", None
    # Evaluation packages are source-checkout-only; no runtime factory or
    # credential reader is invoked to classify a trusted host owner.
    if type(owner).__module__ == "evals.write01.stdio_v1":
        from evals.write01.stdio_v1 import WriteMCPServerV1

        if type(owner) is WriteMCPServerV1:
            return owner, "write01-stdio", None
    if type(owner).__module__ == "evals.proposals.r022.stdio_v1":
        from evals.proposals.r022.stdio_v1 import ScopedFaaGateway, ScopedFaaMCPServer

        if (
            type(owner) is ScopedFaaMCPServer
            and type(gateway) is ScopedFaaGateway
            and gateway._mcp_owner is owner
        ):
            return owner, "r022-faa-stdio", gateway
    raise ValueError("Unsupported or unbound metadata owner")


def _closed_dependencies(gateway: Any) -> None:
    if gateway is not None and (
        gateway._adapter.fixture is not True
        or type(gateway._adapter.transport) is not httpx.MockTransport
        or type(gateway._judge) is not MockProvider
    ):
        raise ValueError("Closed metadata requires explicit fixture and MockProvider")


def install_metadata_v2(owner: Any, *, gateway: Any = None) -> MetadataViewV2:
    """Host opt-in before startup; clients cannot choose a classification.

    R022 requires its original bound Gateway, so an arbitrary external advisory
    provider cannot be described as closed-world. No caller-provided hint values
    or profile identifiers are accepted. Other owners use exact built-in types.
    """
    if version("mcp") != "1.30.0":
        raise ValueError("Metadata v2 requires mcp==1.30.0")
    server, profile, closed_gateway = _composition(owner, gateway)
    if gateway is not None and profile != "r022-faa-stdio":
        raise ValueError("Unexpected metadata Gateway argument")
    if (
        getattr(owner, "_started", False)
        or getattr(server, "_stdio_started", False)
        or getattr(server, "_session_owner", None) is not None
    ):
        raise ValueError("Install metadata before transport startup")
    _closed_dependencies(closed_gateway)
    if getattr(server, "_metadata_v2_installed", False):
        raise ValueError("Metadata v2 is already installed")
    original = server._mcp_server.request_handlers[ListToolsRequest]

    async def listing(request: ListToolsRequest) -> ServerResult:
        # The original handler runs with the ORIGINAL SDK request context.
        # Its bounded registry verification is never bypassed or resealed.
        response = await original(request)
        result = response.root
        try:
            _closed_dependencies(closed_gateway)
        except ValueError as exc:
            raise ToolError("Metadata v2 closed composition changed") from exc
        names = (
            {"update_synthetic_award_review", "get_synthetic_award_review_v1"}
            if profile == "write01-stdio"
            else {
                "find_federal_awards",
                "get_federal_award",
                "resolve_federal_recipient",
                "summarize_federal_spending",
            }
        )
        if (
            not isinstance(result, ListToolsResult)
            or {t.name for t in result.tools} != names
            or len(result.tools) != len(names)
        ):
            raise ToolError("Metadata v2 legacy listing mismatch")
        public = result.model_copy(deep=True)
        for tool in public.tools:
            annotations = tool.annotations
            expected = (
                (False, False, False, False)
                if tool.name == "update_synthetic_award_review"
                else (True, False, True, False)
                if tool.name == "get_synthetic_award_review_v1"
                else (True, False, False, True)
            )
            if (
                annotations is None
                or not set(_HINTS).issubset(annotations.model_fields_set)
                or tuple(getattr(annotations, k) for k in _HINTS) != expected
            ):
                raise ToolError("Metadata v2 legacy annotations mismatch")
            if tool.name == "update_synthetic_award_review":
                annotations.destructiveHint = True
            elif profile not in {"write01-stdio", "primary-stdio"}:
                annotations.openWorldHint = False
        public.meta = {
            **(public.meta or {}),
            "civicgateMetadataContract": CONTRACT_ID,
            "profile": profile,
        }
        return ServerResult(public)

    server._mcp_server.request_handlers[ListToolsRequest] = listing
    server._metadata_v2_installed = True
    return MetadataViewV2(CONTRACT_ID, profile)
