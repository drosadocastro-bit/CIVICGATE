"""A bounded client of the existing MCP tools, with no backend or policy authority."""

import asyncio
import json
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Protocol

from mcp import ClientSession
from mcp.shared.exceptions import McpError
from mcp.types import Tool
from pydantic import ValidationError

from civicgate.models.requests import TOOLS, Proposal
from civicgate.models.responses import DispatchState, Envelope

TransportStatus = Literal[
    "GOVERNED_RESPONSE",
    "MCP_TOOL_ERROR",
    "TRANSPORT_TIMEOUT",
    "PROTOCOL_ERROR",
    "INVALID_GATEWAY_RESPONSE",
]
MAX_DISCOVERY_BYTES = 262144


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    input_schema_json: str
    output_schema_json: str
    annotations_json: str

    @property
    def input_schema(self) -> dict[str, Any]:
        return dict(json.loads(self.input_schema_json))

    @property
    def output_schema(self) -> dict[str, Any]:
        return dict(json.loads(self.output_schema_json))

    @classmethod
    def from_tool(cls, tool: Tool) -> "ToolMetadata":
        """Only exposed descriptive metadata is retained, never opaque SDK extras."""
        if tool.name not in TOOLS or not tool.outputSchema:
            raise ValueError("Unsupported discovered tool")
        if set(tool.inputSchema.get("properties", {})) != {"user_request", "query"}:
            raise ValueError("Unsupported discovered invocation schema")
        if tool.inputSchema.get("additionalProperties") is not False:
            raise ValueError("Unbounded discovered invocation schema")
        metadata = cls(
            name=tool.name,
            description=tool.description or "",
            input_schema_json=_canonical(tool.inputSchema),
            output_schema_json=_canonical(tool.outputSchema),
            annotations_json=_canonical(
                {
                    key: value
                    for key, value in (
                        tool.annotations.model_dump(exclude_none=True) if tool.annotations else {}
                    ).items()
                    if key in {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
                }
            ),
        )
        if len(_canonical(metadata.__dict__).encode("utf-8")) > MAX_DISCOVERY_BYTES:
            raise ValueError("Discovery exceeds metadata bound")
        return metadata


@dataclass(frozen=True)
class TransportOutcome:
    status: TransportStatus
    response_json: str | None = None
    error_code: str | None = None

    @property
    def envelope(self) -> Envelope | None:
        # Callers receive an independent model, not a retained mutable receipt.
        if self.status != "GOVERNED_RESPONSE" or self.response_json is None:
            return None
        return Envelope.model_validate_json(self.response_json)

    @property
    def dispatch_state(self) -> DispatchState:
        envelope = self.envelope
        return envelope.dispatch_state if envelope is not None else "DISPATCH_UNKNOWN"


class GovernedMCPTransport(Protocol):
    async def discover(self) -> tuple[ToolMetadata, ...]: ...

    async def invoke(self, original_request: str, proposal: Proposal) -> TransportOutcome: ...


class DiscoveryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MCPTransport:
    """One initialized local SDK session; no automatic retries or direct adapter.

    The host supplies and trusts the local server process. MCP's user_request is
    caller-supplied context, not authenticated human intent. isError can occur
    after dispatch, so it never supplies a synthetic Gateway decision or receipt.
    """

    def __init__(self, session: ClientSession, *, timeout_seconds: float = 5) -> None:
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Transport timeout must be finite and positive")
        self._session = session
        self._timeout_seconds = timeout_seconds

    async def discover(self) -> tuple[ToolMetadata, ...]:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._session.list_tools()
            if result.nextCursor is not None:
                raise DiscoveryError("DISCOVERY_PAGINATION_UNSUPPORTED")
            tools = result.tools
            if len(tools) != len(TOOLS) or {tool.name for tool in tools} != set(TOOLS):
                raise DiscoveryError("DISCOVERY_REGISTRY_MISMATCH")
            metadata = tuple(ToolMetadata.from_tool(tool) for tool in tools)
            size = sum(len(_canonical(tool.__dict__).encode("utf-8")) for tool in metadata)
            if size > MAX_DISCOVERY_BYTES:
                raise DiscoveryError("DISCOVERY_LIMIT_EXCEEDED")
            return metadata
        except DiscoveryError:
            raise
        except TimeoutError as exc:
            raise DiscoveryError("DISCOVERY_TIMEOUT") from exc
        except Exception as exc:
            # Do not release provider bodies or invent a Gateway rejection.
            raise DiscoveryError("DISCOVERY_PROTOCOL_ERROR") from exc

    async def invoke(self, original_request: str, proposal: Proposal) -> TransportOutcome:
        try:
            proposal = Proposal.model_validate(proposal.model_dump()).model_copy(deep=True)
            arguments = {"user_request": original_request, "query": proposal.arguments}
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._session.call_tool(
                    proposal.tool,
                    arguments,
                    read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                )
        except TimeoutError:
            return TransportOutcome("TRANSPORT_TIMEOUT", error_code="MCP_TIMEOUT")
        except McpError as exc:
            status: TransportStatus = (
                "TRANSPORT_TIMEOUT" if exc.error.code == 408 else "PROTOCOL_ERROR"
            )
            return TransportOutcome(status, error_code=f"MCP_{exc.error.code}")
        except Exception:
            return TransportOutcome("PROTOCOL_ERROR", error_code="MCP_TRANSPORT_FAILURE")
        if result.isError:
            return TransportOutcome("MCP_TOOL_ERROR", error_code="MCP_TOOL_ERROR")
        try:
            envelope = Envelope.model_validate(result.structuredContent)
            if envelope.tool != proposal.tool:
                raise ValueError("Returned tool identity does not match invocation")
            return TransportOutcome("GOVERNED_RESPONSE", response_json=envelope.model_dump_json())
        except (ValidationError, ValueError, TypeError, AttributeError):
            return TransportOutcome(
                "INVALID_GATEWAY_RESPONSE", error_code="GATEWAY_RESPONSE_INVALID"
            )
