"""Dedicated synthetic FAA stdio owner; no legacy fallback or new authority.

The trusted host captures intent and selects this composition before planning.
MCP/user_request is still caller-supplied context, not authenticated human intent.
This closes downgrades inside this owner, not access to a separate legacy owner.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.llm.base import JudgeModel
from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.mcp.server import BoundedMCPServer, UserRequest
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope
from evals.proposals.r022.faa_contract_v1 import (
    FAA,
    FAA_FY2026_PR_CONTRACT,
    PROFILE_ID,
    FaaFy2026PrReadV1,
)

CANONICAL_REQUEST = (
    'Find public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2026.'
)
NATURAL_REQUEST = "Find FY2026 FAA awards with a place of performance in Puerto Rico."


class ProfileAdmissionError(ValueError):
    """Ingress/context rejection, not an invented deterministic policy result."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_query(query: FaaFy2026PrReadV1) -> str:
    return json.dumps(
        query.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _strict_query(raw: str) -> FaaFy2026PrReadV1:
    if type(raw) is not str or not 0 < len(raw.encode("utf-8")) <= 16_000:
        raise ProfileAdmissionError("PROFILE_QUERY_CONTEXT_INVALID")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate query field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Nonfinite query value")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
        return FaaFy2026PrReadV1.model_validate(value)
    except (ValueError, TypeError) as exc:
        raise ProfileAdmissionError("PROFILE_QUERY_CONTEXT_INVALID") from exc


def accepted_request_templates(scope: FaaFy2026PrReadV1) -> tuple[str, ...]:
    """Explicit templates, not a general semantic parser or intent rewrite."""
    if tuple(scope.award_types) != ("A", "B", "C", "D"):
        return ()
    prefix = f'public awards for agency "{FAA}"'
    if scope.recipient_name is not None:
        prefix += " for recipient " + json.dumps(scope.recipient_name, ensure_ascii=False)
    suffix = " in Puerto Rico during FY2026."
    choices = ("Find " + prefix + suffix, f"Show {scope.limit} " + prefix + suffix)
    if scope.recipient_name is None:
        # The original natural request is preserved verbatim. The unchanged
        # policy may still hold it; admission never rewrites it to obtain PERMIT.
        choices += (NATURAL_REQUEST,)
    return choices


@dataclass(frozen=True, slots=True)
class TrustedFaaIntake:
    original_request: str
    expected_query_json: str
    profile_id: str = field(init=False, default=PROFILE_ID)

    def __post_init__(self) -> None:
        if type(self.original_request) is not str or not 0 < len(self.original_request) <= 4000:
            raise ProfileAdmissionError("ORIGINAL_INTENT_CONTEXT_INVALID")
        scope = _strict_query(self.expected_query_json)
        if self.original_request not in accepted_request_templates(scope):
            raise ProfileAdmissionError("ORIGINAL_INTENT_UNSUPPORTED_BY_PROFILE")
        object.__setattr__(self, "expected_query_json", canonical_query(scope))

    @property
    def request_sha256(self) -> str:
        return hashlib.sha256(self.original_request.encode()).hexdigest()

    @property
    def intake_sha256(self) -> str:
        # Documentary integrity, never independent human authentication.
        raw = json.dumps(
            {
                "profile": self.profile_id,
                "request": self.original_request,
                "query": json.loads(self.expected_query_json),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(raw).hexdigest()


class ScopedFaaGateway(Gateway):
    """Host-selected context admission followed by the unchanged authority core."""

    def __init__(
        self,
        adapter: USAspending,
        judge: JudgeModel,
        trace: Trace,
        *,
        intake: TrustedFaaIntake,
    ) -> None:
        from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter

        if type(intake) is not TrustedFaaIntake:
            raise ProfileAdmissionError("TRUSTED_INTAKE_REQUIRED")
        if not isinstance(adapter, FaaProfileFixtureAdapter):
            raise ProfileAdmissionError("PROFILE_ADAPTER_REQUIRED")
        # Revalidate copied primitive context; do not retain a model-generated
        # mutable query object or take a contract selector from an MCP request.
        self._intake = TrustedFaaIntake(intake.original_request, intake.expected_query_json)
        super().__init__(adapter, judge, trace, contract=FAA_FY2026_PR_CONTRACT)

    @property
    def intake(self) -> TrustedFaaIntake:
        return self._intake

    async def call(
        self, request: str, proposal: Proposal, planning_failed: bool = False
    ) -> Envelope:
        if self.contract is not FAA_FY2026_PR_CONTRACT:
            raise ProfileAdmissionError("SERVER_PROFILE_INTEGRITY_FAILURE")
        self.contract.validate()
        if type(request) is not str or request != self._intake.original_request:
            raise ProfileAdmissionError("ORIGINAL_REQUEST_MISMATCH")
        if not isinstance(proposal, Proposal) or proposal.tool != "find_federal_awards":
            raise ProfileAdmissionError("TOOL_OUTSIDE_SELECTED_PROFILE")
        try:
            snapshot = Proposal.model_validate(proposal.model_dump(mode="json"))
            scope = FaaFy2026PrReadV1.model_validate(snapshot.arguments)
        except (ValueError, TypeError) as exc:
            raise ProfileAdmissionError("PROFILE_QUERY_INVALID_OR_DOWNGRADED") from exc
        if canonical_query(scope) != self._intake.expected_query_json:
            raise ProfileAdmissionError("EXPECTED_QUERY_MISMATCH")
        snapshot = Proposal(tool="find_federal_awards", arguments=scope.model_dump(mode="json"))
        return await super().call(request, snapshot, planning_failed)


class ScopedFaaMCPServer(BoundedMCPServer):
    def seal_discovery(self) -> None:
        if self._discovery is not None:
            raise ValueError("Bounded discovery is already sealed")
        self._discovery = BoundedToolDiscovery(
            self._tool_manager.list_tools(),
            contract=FAA_FY2026_PR_CONTRACT,
        )


async def _forward(
    gateway: ScopedFaaGateway,
    request: str,
    tool: str,
    query: BaseModel,
) -> Envelope:
    try:
        return await gateway.call(
            request, Proposal(tool=tool, arguments=query.model_dump(mode="json"))
        )
    except ProfileAdmissionError as exc:
        raise ToolError("FAA_PROFILE_ADMISSION_REJECTED:" + exc.code) from None


def create_scoped_server(gateway: ScopedFaaGateway) -> ScopedFaaMCPServer:
    if not isinstance(gateway, ScopedFaaGateway) or gateway.contract is not FAA_FY2026_PR_CONTRACT:
        raise ProfileAdmissionError("SCOPED_GATEWAY_REQUIRED")
    server = ScopedFaaMCPServer(
        "CivicGate FAA FY2026 PR SYNTHETIC PROFILE",
        instructions="Trusted host-selected FAA synthetic READ profile. Four tools are discoverable; only the exact admitted FIND query can execute in this owner. No legacy fallback, profile selection, WRITE or authority arises from discovery.",
    )
    gateway._claim_mcp_owner(server)
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True
    )

    @server.tool(annotations=annotations)
    async def find_federal_awards(user_request: UserRequest, query: FaaFy2026PrReadV1) -> Envelope:
        """Find a bound page of SYNTHETIC FAA-awarded FY2026 PR contracts under the server-selected profile."""
        return await _forward(gateway, user_request, "find_federal_awards", query)

    @server.tool(annotations=annotations)
    async def get_federal_award(user_request: UserRequest, query: Award) -> Envelope:
        """Legacy detail schema is discoverable; invocation is unavailable in this query-only FAA owner."""
        return await _forward(gateway, user_request, "get_federal_award", query)

    @server.tool(annotations=annotations)
    async def resolve_federal_recipient(user_request: UserRequest, query: Recipient) -> Envelope:
        """Legacy recipient schema is discoverable; invocation is unavailable in this query-only FAA owner."""
        return await _forward(gateway, user_request, "resolve_federal_recipient", query)

    @server.tool(annotations=annotations)
    async def summarize_federal_spending(user_request: UserRequest, query: Search) -> Envelope:
        """Legacy summary schema is discoverable; it cannot downgrade this owner to a toptier search."""
        return await _forward(gateway, user_request, "summarize_federal_spending", query)

    server.seal_discovery()
    return server
