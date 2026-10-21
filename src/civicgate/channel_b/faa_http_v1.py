"""FAA-C1 Channel B composition using the unchanged B2a HTTP custody boundary.

Experimental local synthetic transport only; not a Databricks/PostgreSQL rollout.
No stdio server import, public contract selector, new authentication or policy.
"""

from importlib.metadata import version
from pathlib import Path

import httpx
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from civicgate.audit.local_journal import LocalDispatchJournal
from civicgate.audit.trace import Trace
from civicgate.channel_b.faa_adapter_v1 import FAA_C1, FaaFixtureAdapter
from civicgate.channel_b.faa_profile_v1 import FaaScopeV1
from civicgate.llm.mock import MockProvider
from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.mcp.http_app import (
    MAX_BODY,
    MAX_SESSIONS,
    StreamableHTTPGatewayApp,
    UserRequest,
    _HTTPServer,
)
from civicgate.mcp.http_identity import LocalCredentialVerifier
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope


class _FaaHTTPServer(_HTTPServer):
    def seal_discovery(self) -> None:
        self._discovery = BoundedToolDiscovery(self._tool_manager.list_tools(), contract=FAA_C1)


class FaaC1HTTPApp(StreamableHTTPGatewayApp):
    """Reuse B2a HTTP ingress/session/custody verbatim; replace only composition."""

    def __init__(
        self,
        *,
        verifier: LocalCredentialVerifier,
        store: Path,
        code_revision: str,
        transport: httpx.MockTransport,
        port: int,
    ) -> None:
        if version("mcp") != "1.30.0":
            raise ValueError("FAA-C1 reference composition requires mcp==1.30.0")
        if (
            type(transport) is not httpx.MockTransport
            or type(port) is not int
            or not 1 <= port <= 65535
        ):
            raise ValueError("Synthetic MockTransport and explicit local port required")
        self.verifier = verifier
        self.host = f"127.0.0.1:{port}"
        self.origin = f"http://{self.host}"
        if verifier.domain.audience != self.origin + "/mcp":
            raise ValueError("Credential audience must be this instance's MCP endpoint")
        self.journal = LocalDispatchJournal(store, verifier.domain, code_revision)
        self.gateway = Gateway(
            FaaFixtureAdapter(transport),
            MockProvider(),
            Trace(),
            dispatch_journal=self.journal,
            contract=FAA_C1,
        )
        self.server = _FaaHTTPServer(
            "CivicGate Channel B FAA-C1 LOCAL SYNTHETIC",
            host="127.0.0.1",
            port=port,
            json_response=True,
            stateless_http=False,
            max_request_body_size=MAX_BODY,
            session_idle_timeout=60,
            max_sessions=MAX_SESSIONS,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[self.host],
                allowed_origins=[self.origin],
            ),
        )
        self.gateway._claim_mcp_owner(self.server)
        register_faa_tools(self.server, self.gateway)
        self.server.seal_discovery()
        self._app = self.server.streamable_http_app()
        self._sessions: dict[str, tuple[str, int]] = {}
        self._initialized: set[str] = set()
        self._inflight = 0
        self._started = False


def register_faa_tools(server: _FaaHTTPServer, gateway: Gateway) -> None:
    if gateway.contract is not FAA_C1:
        raise ValueError("FAA server requires its startup contract")
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True
    )

    @server.tool(annotations=annotations)
    async def find_federal_awards(user_request: UserRequest, query: FaaScopeV1) -> Envelope:
        """FAA-awarded prime records, explicit subtier/DOT/FY scope; one bounded page, not total spending."""
        return await gateway.call(
            user_request,
            Proposal(tool="find_federal_awards", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def get_federal_award(user_request: UserRequest, query: Award) -> Envelope:
        """Existing generic public award detail; no automatic FAA attribution."""
        return await gateway.call(
            user_request,
            Proposal(tool="get_federal_award", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def resolve_federal_recipient(user_request: UserRequest, query: Recipient) -> Envelope:
        """Existing generic candidate resolution; human clarification may be required."""
        return await gateway.call(
            user_request,
            Proposal(tool="resolve_federal_recipient", arguments=query.model_dump(mode="json")),
        )

    @server.tool(annotations=annotations)
    async def summarize_federal_spending(user_request: UserRequest, query: Search) -> Envelope:
        """Existing generic returned-page summary. Not FAA-profile or fiscal-year spending."""
        return await gateway.call(
            user_request,
            Proposal(tool="summarize_federal_spending", arguments=query.model_dump(mode="json")),
        )
