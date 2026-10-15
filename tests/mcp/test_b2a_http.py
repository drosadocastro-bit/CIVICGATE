"""Real loopback HTTP + MCP SDK client; all backend data and credentials synthetic."""

import asyncio
import json
import socket
import sqlite3
import subprocess
from contextlib import asynccontextmanager
from dataclasses import replace
from time import time
from uuid import uuid4

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError

from civicgate.audit.local_journal import LocalDispatchJournal, provision_local_store
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_adapter, fixture_transport
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp.http_app import MAX_BODY, StreamableHTTPGatewayApp
from civicgate.mcp.http_identity import LocalCredentialVerifier, LocalHold, TrustDomain
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway

REVISION = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
QUERY = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}
ARGS = {"user_request": "Show public federal awards in Puerto Rico", "query": QUERY}


def events(path):
    with sqlite3.connect(path) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT payload FROM events ORDER BY seq")]


class Harness:
    def __init__(self, tmp_path, *, transport=None):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self.domain = TrustDomain(
            "https://b2a-issuer.invalid",
            self.url,
            "synthetic-danny",
            "synthetic-service",
            "synthetic-instance",
        )
        self.key = Ed25519PrivateKey.generate()
        self.verifier = LocalCredentialVerifier(self.domain, self.key.public_key())
        self.store = tmp_path / "journal.sqlite"
        provision_local_store(self.store, self.domain)
        self.calls = []
        fixture = fixture_transport()

        async def respond(request):
            self.calls.append(request.url.path)
            evidence = events(self.store)
            # Real independent connection observes durable intent BEFORE transport.
            assert evidence[-1]["kind"] == "intent"
            return await (transport or fixture).handle_async_request(request)

        self.transport = httpx.MockTransport(respond)
        self.app = self.make_app()

    def make_app(self):
        return StreamableHTTPGatewayApp(
            verifier=self.verifier,
            store=self.store,
            code_revision=REVISION,
            transport=self.transport,
            port=self.port,
        )

    def token(self, **changes):
        now = int(time())
        claims = {
            "iss": self.domain.issuer,
            "aud": self.domain.audience,
            "sub": self.domain.principal,
            "iat": now,
            "nbf": now,
            "exp": now + 240,
            "jti": str(uuid4()),
            "scope": "civicgate:invoke",
        }
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="EdDSA")

    @asynccontextmanager
    async def running(self):
        config = uvicorn.Config(
            self.app,
            log_level="critical",
            access_log=False,
            lifespan="on",
            timeout_graceful_shutdown=2,
        )
        server = uvicorn.Server(config)
        task = asyncio.create_task(server.serve(sockets=[self.sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise AssertionError("Server did not start")
                    await asyncio.sleep(0.01)
            yield self
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            self.sock.close()

    @asynccontextmanager
    async def client(self, token=None):
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + (token or self.token())},
            trust_env=False,
            timeout=10,
        ) as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write, sid):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session, sid, http


async def test_real_http_four_tools_schema_parity_and_phase_evidence(tmp_path):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (client, sid, _):
        tools = (await client.list_tools()).tools
        stdio = create_server(Gateway(fixture_adapter(), MockProvider(), Trace()))
        assert [t.model_dump() for t in tools] == [t.model_dump() for t in await stdio.list_tools()]
        assert sid()
        queries = [QUERY, {"award_id": "1"}, {"recipient_name": "Acme"}, QUERY]
        for tool, query in zip(tools, queries, strict=True):
            result = await client.call_tool(
                tool.name, {"user_request": "Show public federal data", "query": query}
            )
            assert not result.isError
            assert result.structuredContent["tool_executed"]
        assert len(h.calls) == 4
        records = events(h.store)
        finishes = [e for e in records if e["kind"] == "finish"]
        assert all(e["pre_dispatch_verification"] == "PASS" for e in finishes)
        assert finishes[2]["final_decision"] == "REVIEW_REQUIRED"
        assert finishes[2]["tool_executed"]
        assert all(e["binding_issued"] for e in records if e["kind"] == "policy")
        assert all(e["context"]["session"] == sid() for e in records if e["kind"] == "begin")


@pytest.mark.parametrize(
    "change",
    [
        None,
        "garbage",
        {"exp": 1},
        {"aud": "wrong"},
        {"iss": "wrong"},
        {"sub": "foreign"},
        {"scope": "admin"},
        {"nbf": 9999999999},
        {"exp": "9999999999"},
        {"jti": "short"},
    ],
)
async def test_credentials_rejected_before_gateway(tmp_path, change):
    h = Harness(tmp_path)
    headers = (
        {}
        if change is None
        else {
            "Authorization": "Bearer " + (change if isinstance(change, str) else h.token(**change))
        }
    )
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=headers, json={})
        assert response.status_code == 401
    assert not h.calls
    assert not [e for e in events(h.store) if e["kind"] == "begin"]


async def test_wrong_signature_and_unsigned_token(tmp_path):
    h = Harness(tmp_path)
    claims = jwt.decode(h.token(), options={"verify_signature": False})
    tokens = [
        jwt.encode(claims, Ed25519PrivateKey.generate(), algorithm="EdDSA"),
        jwt.encode(claims, "", algorithm="none"),
    ]
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        for token in tokens:
            assert (
                await http.post(h.url, headers={"Authorization": "Bearer " + token}, json={})
            ).status_code == 401
    assert not h.calls


async def test_schema_extra_tools_mutation_and_inputs_denied(tmp_path):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (client, _, _):
        for tool, args in [
            ("hidden_tool", ARGS),
            ("find_federal_awards", ARGS | {"authority": "PERMIT"}),
            ("find_federal_awards", ARGS | {"query": QUERY | {"unknown": 1}}),
            ("find_federal_awards", ARGS | {"query": {"state_code": "PR"}}),
        ]:
            assert (await client.call_tool(tool, args)).isError
        registered = h.app.server._tool_manager.list_tools()[0]
        registered.parameters["properties"]["query"] = {"type": "string"}
        assert (await client.call_tool("find_federal_awards", ARGS)).isError
        with pytest.raises(McpError):
            await client.list_tools()
    assert not h.calls


async def test_extra_registration_denies_all_calls(tmp_path):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (client, _, _):

        @h.app.server.tool()
        def hidden_tool() -> str:
            return "never"

        assert (await client.call_tool("find_federal_awards", ARGS)).isError
        with pytest.raises(McpError):
            await client.list_tools()
    assert not h.calls


async def test_deny_pre_review_post_review(tmp_path):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (client, _, _):
        deny = await client.call_tool(
            "find_federal_awards", ARGS | {"user_request": "blacklist this contractor"}
        )
        assert deny.structuredContent["decision"] == "DENY"
        assert not deny.structuredContent["tool_executed"]
        h.app.gateway._judge = UnavailableProvider()
        review = await client.call_tool("find_federal_awards", ARGS)
        assert review.structuredContent["decision"] == "REVIEW_REQUIRED"
        assert not review.structuredContent["tool_executed"]
        h.app.gateway._judge = MockProvider()
        post = await client.call_tool(
            "find_federal_awards",
            ARGS
            | {
                "query": QUERY | {"recipient_name": "Acme"},
                "user_request": 'Show federal awards to recipient "Acme" in Puerto Rico during FY2025.',
            },
        )
        assert post.structuredContent["decision"] == "REVIEW_REQUIRED"
        assert post.structuredContent["tool_executed"]
        assert (
            "RECIPIENT_IDENTITY_UNCONFIRMED"
            in post.structuredContent["governance"]["policy_reasons"]
        )
    phases = [e for e in events(h.store) if e["kind"] == "policy"]
    assert [e["initial_decision"] for e in phases] == ["DENY", "REVIEW_REQUIRED", "PERMIT"]
    assert [e["binding_issued"] for e in phases] == [False, False, True]
    assert len(h.calls) == 1


async def test_sessions_credentials_concurrency_and_delete(tmp_path):
    h = Harness(tmp_path)
    token1, token2 = h.token(), h.token()
    async with (
        h.running(),
        h.client(token1) as (a, sid_a, http_a),
        h.client(token2) as (b, sid_b, http_b),
    ):
        assert sid_a() != sid_b()
        for method in ("POST", "DELETE", "GET"):
            response = await http_b.request(method, h.url, headers={"mcp-session-id": sid_a()})
            assert response.status_code in {404, 405}
        results = await asyncio.gather(
            *[client.call_tool("find_federal_awards", ARGS) for client in (a, b, a, b)]
        )
        assert all(r.structuredContent["tool_executed"] for r in results)
        records = [e for e in events(h.store) if e["kind"] in {"begin", "finish"}]
        assert [e["kind"] for e in records] == ["begin", "finish"] * 4
        assert {e["context"]["session"] for e in records if e["kind"] == "begin"} == {
            sid_a(),
            sid_b(),
        }
        response = await http_a.delete(h.url, headers={"mcp-session-id": sid_a()})
        assert response.status_code == 200
        assert (
            await http_a.post(h.url, headers={"mcp-session-id": sid_a()}, json={})
        ).status_code == 404


async def test_host_origin_body_protocol_and_session_rejection(tmp_path):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (_, sid, http):
        for headers in (
            {"Host": "evil.example"},
            {"Origin": "https://evil.example"},
            {"Origin": "null"},
        ):
            assert (await http.post(h.url, headers=headers, json={})).status_code == 403
        assert (await http.post(h.url, content=b"x" * (MAX_BODY + 1))).status_code == 413
        assert (
            await http.post(h.url, content=b'{"method":"initialize","method":"tools/call"}')
        ).status_code == 400
        assert (await http.post(h.url, json=[])).status_code == 400
        assert (await http.post(h.url, json={"method": "tools/call"})).status_code == 400
        assert (
            await http.post(h.url, headers={"mcp-session-id": "foreign"}, json={})
        ).status_code == 404
        assert (
            await http.post(
                h.url,
                headers={
                    "mcp-session-id": sid(),
                    "mcp-protocol-version": "1900-01-01",
                    "Accept": "application/json, text/event-stream",
                },
                json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
            )
        ).status_code == 400
        assert (await http.get(h.url, headers={"mcp-session-id": sid()})).status_code == 405
    assert not h.calls


@pytest.mark.parametrize("failure", ["timeout", "network", "status500"])
async def test_no_retry_unknown_hold_and_restart(tmp_path, failure):
    attempts = []

    def respond(request):
        attempts.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic uncertainty")
        if failure == "network":
            raise httpx.ConnectError("synthetic uncertainty")
        return httpx.Response(500, json={})

    h = Harness(tmp_path, transport=httpx.MockTransport(respond))
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool("find_federal_awards", ARGS)
        assert not result.isError
        assert result.structuredContent["attempt_count"] == 1
        assert not result.structuredContent["errors"][0]["retryable"]
        if failure != "status500":
            assert result.structuredContent["next_action"] == "HUMAN_REVIEW_REQUIRED"
            assert (await client.call_tool("find_federal_awards", ARGS)).isError
    assert len(attempts) == 1
    if failure != "status500":
        with pytest.raises(LocalHold, match="RECOVERY_HOLD"):
            LocalDispatchJournal(h.store, h.domain, REVISION)


async def test_containment_survives_reconnect_and_restart(tmp_path):
    h = Harness(tmp_path)
    async with h.running():
        async with h.client() as (client, _, _):
            for _ in range(2):
                assert (
                    await client.call_tool(
                        "find_federal_awards", ARGS | {"user_request": "blacklist this contractor"}
                    )
                ).structuredContent["decision"] == "DENY"
        async with h.client() as (client, _, _):
            result = await client.call_tool("find_federal_awards", ARGS)
            assert (
                "SESSION_CONTAINMENT_ACTIVE"
                in result.structuredContent["governance"]["policy_reasons"]
            )
    assert not h.calls
    h.sock = socket.socket()
    h.sock.bind(("127.0.0.1", h.port))
    h.app = h.make_app()
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool("find_federal_awards", ARGS)
        assert (
            "SESSION_CONTAINMENT_ACTIVE" in result.structuredContent["governance"]["policy_reasons"]
        )
        assert "Restart and reconnect do not clear" in result.structuredContent["clarification"]
    assert not h.calls


@pytest.mark.parametrize("point", ["begin", "policy", "intent", "finish"])
async def test_durable_write_failure_fails_closed(tmp_path, monkeypatch, point):
    h = Harness(tmp_path)
    original = h.app.journal._append

    def failing(kind, **evidence):
        if kind == point:
            raise sqlite3.OperationalError("synthetic disk full")
        return original(kind, **evidence)

    monkeypatch.setattr(h.app.journal, "_append", failing)
    async with h.running(), h.client() as (client, _, _):
        assert (await client.call_tool("find_federal_awards", ARGS)).isError
        assert (await client.call_tool("find_federal_awards", ARGS)).isError
    assert len(h.calls) == (1 if point == "finish" else 0)
    with pytest.raises(LocalHold, match="RECOVERY_HOLD"):
        LocalDispatchJournal(h.store, h.domain, REVISION)


@pytest.mark.parametrize("attack", ["expiry", "tamper", "foreign", "replay", "credential_expiry"])
async def test_binding_verification_after_durable_intent(tmp_path, monkeypatch, attack):
    h = Harness(tmp_path)
    original = h.app.journal.intent
    boundary = h.app.gateway._execution_boundary

    def altered(authority):
        original(authority)
        if attack == "expiry":
            monkeypatch.setattr(boundary, "_clock", lambda: authority.expires_at + 1)
        elif attack == "tamper":
            object.__setattr__(authority.binding, "arguments_sha256", "0" * 64)
        elif attack == "foreign":
            h.app.gateway._execution_boundary = Gateway(
                fixture_adapter(), MockProvider(), Trace()
            )._execution_boundary
        elif attack == "replay":
            boundary.consume(
                authority,
                authority.binding.request_id,
                authority.binding.tool,
                json.loads(authority.binding.arguments_json),
                h.app.gateway._policy_context(),
            )
        else:
            from civicgate.mcp.http_identity import invocation_context

            context = invocation_context.get()
            invocation_context.set(replace(context, expires_at=0))
            h.app.journal._context()

    monkeypatch.setattr(h.app.journal, "intent", altered)
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool("find_federal_awards", ARGS)
        if attack == "credential_expiry":
            assert result.isError
        else:
            assert result.structuredContent["decision"] == "DENY"
            assert not result.structuredContent["tool_executed"]
            assert result.structuredContent["errors"]
    assert not h.calls


def test_missing_store_wrong_domain_and_exclusive_ownership(tmp_path):
    h = Harness(tmp_path)
    try:
        with pytest.raises(OSError):
            LocalDispatchJournal(h.store, h.domain, REVISION)
        with pytest.raises((OSError, sqlite3.Error, LocalHold)):
            LocalDispatchJournal(tmp_path / "missing.sqlite", h.domain, REVISION)
        h.app.journal.close()
        for domain in (replace(h.domain, principal="other"), replace(h.domain, instance="other")):
            with pytest.raises(LocalHold, match="TRUST_DOMAIN_MISMATCH"):
                LocalDispatchJournal(h.store, domain, REVISION)
    finally:
        h.app.journal.close()
        h.sock.close()


async def test_mid_response_failure_has_one_attempt_and_holds(tmp_path):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"results":'
            raise httpx.ReadTimeout("synthetic partial response")

    h = Harness(
        tmp_path,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "application/json"}, stream=BrokenStream()
            )
        ),
    )
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool("find_federal_awards", ARGS)
        assert result.structuredContent["attempt_count"] == 1
        assert result.structuredContent["response_state"] == "TRANSPORT_ERROR"
        assert result.structuredContent["next_action"] == "HUMAN_REVIEW_REQUIRED"
        assert (await client.call_tool("find_federal_awards", ARGS)).isError
    assert len(h.calls) == 1
    with pytest.raises(LocalHold, match="RECOVERY_HOLD"):
        LocalDispatchJournal(h.store, h.domain, REVISION)


async def test_cross_instance_sessions_and_credentials_are_not_transferable(tmp_path):
    a, b = Harness(tmp_path / "a"), Harness(tmp_path / "b")
    async with (
        a.running(),
        b.running(),
        a.client() as (_, a_sid, a_http),
        b.client() as (_, _, b_http),
    ):
        # A's verified credential is not valid at B, which has its own key/audience.
        assert (await a_http.post(b.url, json={})).status_code == 401
        # A's session is not identity even with a valid B credential.
        assert (
            await b_http.post(b.url, headers={"mcp-session-id": a_sid()}, json={})
        ).status_code == 404
    assert not a.calls and not b.calls


async def test_request_identity_headers_cannot_replace_verified_principal(tmp_path):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (client, _, http):
        http.headers["x-principal"] = "administrator"
        http.headers["x-service-identity"] = "caller"
        result = await client.call_tool("find_federal_awards", ARGS)
        assert result.structuredContent["tool_executed"]
    begin = next(e for e in events(h.store) if e["kind"] == "begin")
    assert begin["context"]["principal"] == h.domain.principal
    assert begin["service_identity"] == h.domain.service_identity


async def test_initialization_lifecycle_rejects_early_tool_call(tmp_path):
    h = Harness(tmp_path)
    async with (
        h.running(),
        httpx.AsyncClient(
            trust_env=False,
            headers={
                "Authorization": "Bearer " + h.token(),
                "Accept": "application/json, text/event-stream",
            },
        ) as http,
    ):
        response = await http.post(
            h.url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        sid = response.headers["mcp-session-id"]
        response = await http.post(
            h.url,
            headers={"mcp-session-id": sid, "mcp-protocol-version": "2025-11-25"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "find_federal_awards", "arguments": ARGS},
            },
        )
        assert "error" in response.json()
        await http.delete(h.url, headers={"mcp-session-id": sid})
    assert not h.calls


async def test_request_limit_rejects_without_gateway(tmp_path, monkeypatch):
    h = Harness(tmp_path)
    async with h.running(), h.client() as (_, sid, http):
        monkeypatch.setattr(h.app, "_inflight", 16)
        response = await http.post(h.url, headers={"mcp-session-id": sid()}, json={})
        assert response.status_code == 429
        monkeypatch.setattr(h.app, "_inflight", 0)
    assert not h.calls


async def test_stdio_gateway_cannot_be_attached_to_http_owner(tmp_path):
    h = Harness(tmp_path)
    try:
        with pytest.raises(ValueError, match="already has an MCP server owner"):
            create_server(h.app.gateway)
        stdio_gateway = Gateway(fixture_adapter(), MockProvider(), Trace())
        create_server(stdio_gateway)
        with pytest.raises(ValueError, match="already has an MCP server owner"):
            stdio_gateway._claim_mcp_owner(h.app.server)
        with pytest.raises(ToolError, match="Authenticated HTTP"):
            await h.app.server.call_tool("find_federal_awards", ARGS)
    finally:
        h.app.journal.close()
        h.sock.close()
