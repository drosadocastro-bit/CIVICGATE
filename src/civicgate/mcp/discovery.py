"""A bounded metadata view of the existing tool registry, never execution authority."""

import json
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp.tools.base import Tool as RegisteredTool
from mcp.types import Tool, ToolAnnotations

from civicgate.models.requests import TOOLS


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _contract(tool: RegisteredTool) -> str:
    return _canonical(
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
            "argument_schema": tool.fn_metadata.arg_model.model_json_schema(by_alias=True),
            "output_schema": tool.output_schema,
            "metadata_output_schema": tool.fn_metadata.output_schema,
            "wrap_output": tool.fn_metadata.wrap_output,
            "annotations": tool.annotations.model_dump() if tool.annotations else None,
            "context_kwarg": tool.context_kwarg,
            "is_async": tool.is_async,
        }
    )


@dataclass(frozen=True)
class _Entry:
    registration: RegisteredTool
    function: Any
    metadata: Any
    argument_model: Any
    output_model: Any
    contract_json: str
    public_json: str


class BoundedToolDiscovery:
    """Startup snapshot of only the four locally registered public metadata contracts.

    A fresh MCP Tool is reconstructed for each listing. No token, policy outcome,
    backend object, provider configuration or authorization capability is exposed.
    Wrapper identity and schemas are checked again before both listing and calling.
    This protects supported MCP entry points, not hostile Python in the server process.
    """

    def __init__(self, registrations: list[RegisteredTool]) -> None:
        by_name = {tool.name: tool for tool in registrations}
        if len(by_name) != len(registrations) or set(by_name) != set(TOOLS):
            raise ValueError("Bounded tool registry mismatch")
        entries = []
        for name in TOOLS:
            tool = by_name[name]
            parameters = json.loads(_canonical(tool.parameters))
            if set(parameters.get("properties", {})) != {"user_request", "query"}:
                raise ValueError("Bounded tool input contract mismatch")
            query = parameters["properties"]["query"]
            query_schema = (
                parameters.get("$defs", {}).get(query["$ref"].removeprefix("#/$defs/"))
                if "$ref" in query
                else query
            )
            if query_schema != TOOLS[name].model_json_schema():
                raise ValueError("Bounded tool query schema mismatch")
            # FastMCP's generated wrapper model ignores extras by default. The
            # server rejects them explicitly, and discovery describes that gate.
            parameters["additionalProperties"] = False
            public = Tool(
                name=name,
                description=tool.description,
                inputSchema=parameters,
                outputSchema=tool.output_schema,
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=False,
                    openWorldHint=True,
                ),
            )
            entries.append(
                _Entry(
                    tool,
                    tool.fn,
                    tool.fn_metadata,
                    tool.fn_metadata.arg_model,
                    tool.fn_metadata.output_model,
                    _contract(tool),
                    public.model_dump_json(exclude_none=True),
                )
            )
        self._entries = tuple(entries)

    def validate(self, registrations: list[RegisteredTool]) -> None:
        by_name = {tool.name: tool for tool in registrations}
        if len(by_name) != len(registrations) or set(by_name) != set(TOOLS):
            raise ValueError("Bounded tool registry mismatch")
        for entry in self._entries:
            tool = by_name[entry.registration.name]
            if (
                tool is not entry.registration
                or tool.fn is not entry.function
                or tool.fn_metadata is not entry.metadata
                or tool.fn_metadata.arg_model is not entry.argument_model
                or tool.fn_metadata.output_model is not entry.output_model
                or _contract(tool) != entry.contract_json
            ):
                raise ValueError("Bounded tool registration changed")

    def list_tools(self, registrations: list[RegisteredTool]) -> list[Tool]:
        self.validate(registrations)
        return [Tool.model_validate_json(entry.public_json) for entry in self._entries]
