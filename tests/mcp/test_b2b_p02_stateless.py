"""Real loopback HTTP/SDK characterization. No external backend, secrets or models."""

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from time import time
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from civicgate.audit.local_journal import LocalDispatchJournal, provision_local_store
from civicgate.demo import fixture_transport
from civicgate.mcp.http_app import StreamableHTTPGatewayApp
from civicgate.mcp.http_identity import (
    LocalCredentialVerifier,
    LocalHold,
    TrustDomain,
    invocation_context,
)
from civicgate.models.requests import TOOLS
from experiments.b2b_p02_stateless_v1 import Enrollment, StatelessExperiment

REV = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
QUERY = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}
ARGS: dict[str, Any] = {"user_request": "Show public federal awards in Puerto Rico", "query": QUERY}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "synthetic-p02", "version": "1"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
CALL: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "find_federal_awards", "arguments": ARGS},
}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


def events(path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(path) as connection:
        return [
            json.loads(row[0])
            for row in connection.execute("SELECT payload FROM events ORDER BY seq")
        ]


def record(row: dict[str, Any]) -> None:
    """Only sanitized protocol responses and synthetic counters; never headers/tokens."""
    folder = os.environ.get("P02_EVIDENCE")
    if folder:
        with (Path(folder) / "observations.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


class Lab:
    def __init__(self, root: Path, mode: str = "stateless", *, provision: bool = True) -> None:
        self.root, self.mode = root, mode
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        self.key = Ed25519PrivateKey.generate()
        self.domains = [
            TrustDomain(
                "https://synthetic.p02.invalid",
                self.url,
                f"synthetic-{name}",
                "synthetic-service",
                "synthetic-instance",
            )
            for name in (["alice"] if mode == "stateful" else ["alice", "bob"])
        ]
        self.paths = [root / f"caller-{i}.sqlite" for i in range(len(self.domains))]
        self.verifiers = [LocalCredentialVerifier(d, self.key.public_key()) for d in self.domains]
        self.effects: list[dict[str, Any]] = []
        self.backend_entries: list[str] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False
        self.fail = False
        self.handlers = 0
        fixture = fixture_transport()

        async def backend(request: httpx.Request) -> httpx.Response:
            context = invocation_context.get()
            assert context is not None
            self.backend_entries.append(context.principal)
            journal = events(
                self.paths[[d.principal for d in self.domains].index(context.principal)]
            )
            assert journal[-1]["kind"] == "intent"
            assert journal[-1]["context"]["principal"] == context.principal
            self.entered.set()
            if self.block:
                await self.release.wait()
            assert invocation_context.get() == context
            if self.fail:
                raise httpx.ReadError("Synthetic response loss")
            self.effects.append({"principal": context.principal, "request": context.request})
            return await fixture.handle_async_request(request)

        self.transport = httpx.MockTransport(backend)
        if provision:
            for path, domain in zip(self.paths, self.domains, strict=True):
                provision_local_store(path, domain)
        self.make_app()

    def make_app(self) -> None:
        self.app: Any
        if self.mode == "stateful":
            self.app = StreamableHTTPGatewayApp(
                verifier=self.verifiers[0],
                store=self.paths[0],
                code_revision=REV,
                transport=self.transport,
                port=self.port,
            )
            original = self.app.server.call_tool

            async def observed(name: str, arguments: dict[str, Any]) -> Any:
                self.handlers += 1
                return await original(name, arguments)

            self.app.server.call_tool = observed
            # FastMCP captures the bound method during construction. Re-register
            # the identical wrapper/validation setting to count actual entries.
            self.app.server._mcp_server.call_tool(validate_input=False)(observed)
        else:
            self.app = StatelessExperiment(
                enrollments=tuple(
                    Enrollment(v, p, self.transport)
                    for v, p in zip(self.verifiers, self.paths, strict=True)
                ),
                port=self.port,
                code_revision=REV,
            )

    def gateway(self, caller: int = 0) -> Any:
        return self.app.gateway if self.mode == "stateful" else self.app.callers[caller].gateway

    def journal(self, caller: int = 0) -> Any:
        return self.app.journal if self.mode == "stateful" else self.app.callers[caller].journal

    def count(self) -> int:
        return (
            self.handlers
            if self.mode == "stateful"
            else sum(c.server.handler_entries for c in self.app.callers)
        )

    def token(self, caller: int = 0, **changes: Any) -> str:
        now = int(time())
        domain = self.domains[caller]
        claims = dict(
            iss=domain.issuer,
            aud=domain.audience,
            sub=domain.principal,
            iat=now,
            nbf=now,
            exp=now + 240,
            jti=str(uuid4()),
            scope="civicgate:invoke",
        )
        claims.update(changes)
        return str(jwt.encode(claims, self.key, algorithm="EdDSA"))

    def headers(self, caller: int = 0, credential: str | None = None) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + (credential or self.token(caller)),
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    @asynccontextmanager
    async def running(self) -> AsyncIterator["Lab"]:
        server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                log_level="critical",
                access_log=False,
                lifespan="on",
                timeout_graceful_shutdown=1,
            )
        )
        task = asyncio.create_task(server.serve(sockets=[self.sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise AssertionError("Loopback startup failed")
                    await asyncio.sleep(0.01)
            yield self
        finally:
            self.release.set()
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            self.sock.close()

    @asynccontextmanager
    async def sdk(self, caller: int = 0) -> AsyncIterator[Any]:
        async with httpx.AsyncClient(
            headers=self.headers(caller), trust_env=False, timeout=5
        ) as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write, sid):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session, sid


async def ready(
    h: Lab, http: httpx.AsyncClient, headers: dict[str, str], notify: bool = True
) -> dict[str, str]:
    response = await http.post(h.url, headers=headers, json=INIT)
    assert response.status_code == 200
    if "mcp-session-id" in response.headers:
        headers = headers | {"mcp-session-id": response.headers["mcp-session-id"]}
    if notify:
        assert (await http.post(h.url, headers=headers, json=INITIALIZED)).status_code == 202
    return headers


async def capture(
    h: Lab,
    http: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    message: Any = None,
    method: str = "POST",
    content: bytes | None = None,
) -> dict[str, Any]:
    before = (h.count(), len(h.backend_entries), len(h.effects))
    try:
        response = await http.request(method, h.url, headers=headers, json=message, content=content)
        try:
            body = response.json()
        except ValueError:
            body = response.text
        row = {
            "http_status": response.status_code,
            "protocol_response": body,
            "session_id_present": "mcp-session-id" in response.headers,
        }
    except httpx.HTTPError as exc:
        row = {
            "http_status": None,
            "protocol_response": type(exc).__name__,
            "session_id_present": False,
        }
    row.update(
        handler_entries=h.count() - before[0],
        dispatches=len(h.backend_entries) - before[1],
        protected_effects=len(h.effects) - before[2],
    )
    return row


@pytest.mark.parametrize("mode", ["stateful", "stateless"])
@pytest.mark.parametrize("case", [f"S{i}" for i in range(12)])
async def test_protocol_matrix(tmp_path: Path, mode: str, case: str) -> None:
    h = Lab(tmp_path, mode)
    rows: list[dict[str, Any]] = []
    async with h.running(), httpx.AsyncClient(trust_env=False, timeout=1) as http:
        headers = h.headers()
        if case == "S0":
            rows.append(await capture(h, http, headers, message=INIT))
            if mode == "stateful":
                # Initialize again on a separate session for an explicit notification.
                headers = await ready(h, http, headers)
            else:
                rows.append(await capture(h, http, headers, message=INITIALIZED))
            rows.append(await capture(h, http, headers, message=LIST))
            assert (
                rows[-1]["http_status"] == 200
                and len(rows[-1]["protocol_response"]["result"]["tools"]) == 4
            )
        elif case == "S1":
            rows.append(await capture(h, http, headers, message=CALL))
            assert rows[-1]["http_status"] == (400 if mode == "stateful" else 200)
            assert len(h.effects) == (0 if mode == "stateful" else 1)
        elif case == "S2":
            headers = await ready(h, http, headers, notify=False)
            rows.append(await capture(h, http, headers, message=CALL))
            assert rows[-1]["http_status"] == (400 if mode == "stateful" else 200)
            assert len(h.effects) == (0 if mode == "stateful" else 1)
        elif case in {"S3", "S4", "S5"}:
            headers = await ready(h, http, headers)
            for _ in range(2):
                rows.append(await capture(h, http, headers, message=CALL))
            assert len(h.effects) == 2
            contexts = [e["context"] for e in events(h.paths[0]) if e["kind"] == "begin"]
            assert len({c["request"] for c in contexts}) == 2
            assert all(bool(c["session"]) == (mode == "stateful") for c in contexts)
            foreign = headers | {"mcp-session-id": "foreign-correlation-not-authority"}
            rows.append(await capture(h, http, foreign, message=LIST))
            assert rows[-1]["http_status"] == (404 if mode == "stateful" else 200)
            fresh_token = headers | {"Authorization": "Bearer " + h.token()}
            rows.append(await capture(h, http, fresh_token, message=LIST))
            assert rows[-1]["http_status"] == (404 if mode == "stateful" else 200)
        elif case == "S6":
            headers = await ready(h, http, headers)
            rows.append(await capture(h, http, headers, method="PUT"))
            rows.append(
                await capture(
                    h, http, headers | {"MCP-Protocol-Version": "1900-01-01"}, message=LIST
                )
            )
            rows.append(
                await capture(
                    h,
                    http,
                    headers,
                    message={"jsonrpc": "2.0", "id": 4, "method": "fiction/unknown"},
                )
            )
            rows.append(await capture(h, http, headers, method="DELETE"))
            assert [r["http_status"] for r in rows] == [
                405,
                400,
                200,
                200 if mode == "stateful" else 405,
            ]
            # SDK 1.30 validates its ClientRequest union before method dispatch.
            # Preserve observed -32602, not the initial -32601 assumption.
            assert rows[2]["protocol_response"]["error"]["code"] == -32602
            assert not h.effects
        elif case == "S7":
            headers = await ready(h, http, headers)
            async with http.stream(
                "GET", h.url, headers=headers | {"Accept": "text/event-stream"}, timeout=0.15
            ) as response:
                timed_out = False
                try:
                    async for _ in response.aiter_bytes():
                        pass
                except httpx.ReadTimeout:
                    timed_out = True
                rows.append(
                    {
                        "http_status": response.status_code,
                        "protocol_response": response.headers.get("content-type"),
                        "bounded_read_timeout": timed_out,
                        "handler_entries": 0,
                        "dispatches": 0,
                        "protected_effects": 0,
                    }
                )
                assert response.status_code == (405 if mode == "stateful" else 200)
                assert timed_out == (mode == "stateless")
        elif case == "S8":
            headers = await ready(h, http, headers)
            for data in [b'{"jsonrpc":"2.0","id":2,"id":3,"method":"tools/list"}', b"{broken"]:
                rows.append(await capture(h, http, headers, content=data))
                assert rows[-1]["http_status"] == 400
            bad = CALL | {"params": CALL["params"] | {"arguments": ARGS | {"approved": True}}}
            rows.append(await capture(h, http, headers, message=bad))
            assert rows[-1]["protocol_response"]["result"]["isError"]
            assert not h.effects
        elif case == "S9":
            a = await ready(h, http, headers)
            b = await ready(h, http, h.headers(0 if mode == "stateful" else 1))
            rows.extend(
                await asyncio.gather(
                    capture(h, http, a, message=CALL), capture(h, http, b, message=CALL)
                )
            )
            assert len(h.effects) == 2
            assert len({e["principal"] for e in h.effects}) == (1 if mode == "stateful" else 2)
            for row in rows:
                # Global delta windows overlap; only case totals are independent
                # counters for this concurrent scenario, not their summed deltas.
                row.update(
                    handler_entries=None,
                    dispatches=None,
                    protected_effects=None,
                    counter_scope="concurrent case totals below",
                )
        elif case == "S10":
            headers = await ready(h, http, headers)
            h.block = True
            invocation = asyncio.create_task(capture(h, http, headers, message=CALL))
            await asyncio.wait_for(h.entered.wait(), 3)
            cancel = {
                "jsonrpc": "2.0",
                "method": "notifications/cancelled",
                "params": {"requestId": 3, "reason": "synthetic cancellation"},
            }
            rows.append(await capture(h, http, headers, message=cancel))
            await asyncio.sleep(0.1)
            h.release.set()
            rows.append(await invocation)
            assert rows[0]["http_status"] == 202
            assert len(h.backend_entries) == 1
            assert len(h.effects) == (0 if mode == "stateful" else 1)
        else:
            headers = await ready(h, http, headers)
            rows.append(await capture(h, http, headers, message=CALL))
            assert invocation_context.get() is None
            assert h.app._inflight == 0
            assert not h.gateway()._execution_boundary._issued
            assert not h.journal().active
    record(
        {
            "case": case,
            "mode": mode,
            "requests": rows,
            "total_handler_entries": h.count(),
            "total_dispatches": len(h.backend_entries),
            "total_protected_effects": len(h.effects),
        }
    )


@pytest.mark.parametrize("mode", ["stateful", "stateless"])
async def test_real_sdk_client_discovery_and_governed_read(tmp_path: Path, mode: str) -> None:
    h = Lab(tmp_path, mode)
    async with h.running(), h.sdk() as (client, sid):
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == set(TOOLS)
        assert bool(sid()) == (mode == "stateful")
        assert not h.effects and not h.gateway()._execution_boundary._issued
        response = await client.call_tool("find_federal_awards", ARGS)
        assert not response.isError and response.structuredContent["tool_executed"]
        assert response.structuredContent["decision"] == "PERMIT"
    assert len(h.effects) == 1
    finishes = [e for e in events(h.paths[0]) if e["kind"] == "finish"]
    assert finishes[0]["pre_dispatch_verification"] == "PASS" and finishes[0]["binding_consumed"]


@pytest.mark.parametrize(
    "attack",
    [
        "missing",
        "malformed",
        "issuer",
        "audience",
        "signature",
        "scope",
        "expired",
        "principal",
        "service-principal",
        "unsigned",
        "expiry-type",
    ],
)
async def test_per_request_authentication(tmp_path: Path, attack: str) -> None:
    h = Lab(tmp_path)
    changes: dict[str, dict[str, Any]] = {
        "issuer": {"iss": "https://foreign.invalid"},
        "audience": {"aud": "foreign"},
        "scope": {"scope": "admin"},
        "expired": {"iat": 1, "nbf": 1, "exp": 2},
        "principal": {"sub": "synthetic-unenrolled"},
        "service-principal": {"sub": "synthetic-service"},
        "expiry-type": {"exp": str(int(time()) + 200)},
    }
    credential = h.token(**changes.get(attack, {}))
    if attack in {"signature", "unsigned"}:
        claims = jwt.decode(credential, options={"verify_signature": False})
        credential = jwt.encode(
            claims,
            Ed25519PrivateKey.generate() if attack == "signature" else "",
            algorithm="EdDSA" if attack == "signature" else "none",
        )
    headers = h.headers(credential=credential)
    if attack == "missing":
        headers.pop("Authorization")
    elif attack == "malformed":
        headers["Authorization"] = "Bearer malformed"
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        # Prior success cannot authenticate a later request.
        assert (await http.post(h.url, headers=h.headers(), json=LIST)).status_code == 200
        result = await http.post(h.url, headers=headers, json=CALL)
        assert result.status_code == 401
    assert not h.backend_entries and not h.count()
    assert not [e for e in events(h.paths[0]) if e["kind"] == "begin"]


async def test_forged_headers_and_duplicate_request_ids_do_not_transfer_identity(
    tmp_path: Path,
) -> None:
    h = Lab(tmp_path)
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        headers = h.headers(1) | {
            "X-Forwarded-User": "synthetic-alice",
            "X-Databricks-User": "synthetic-alice",
            "X-Request-ID": "alice-owned",
            "Mcp-Session-Id": "alice-owned",
        }
        for _ in range(2):
            response = await http.post(h.url, headers=headers, json=CALL)
            assert response.status_code == 200
            assert response.json()["result"]["structuredContent"]["tool_executed"]
    assert {e["principal"] for e in h.effects} == {"synthetic-bob"}
    assert len({e["request"] for e in h.effects}) == 2
    assert not [e for e in events(h.paths[0]) if e["kind"] == "begin"]
    assert invocation_context.get() is None
    record(
        {
            "case": "AUTH_REQUEST_ID_REUSE",
            "effect_count": 2,
            "fresh_policy_count": 2,
            "meaning": "JSON-RPC correlation IDs are not idempotency keys or authority",
        }
    )


@pytest.mark.parametrize(
    "user_text,decision",
    [
        ("blacklist this contractor", "DENY"),
        ("Can you help me with something unclear?", "REVIEW_REQUIRED"),
        ("Show public federal awards in Puerto Rico", "PERMIT"),
    ],
)
async def test_stateless_lifecycle_cannot_bypass_policy(
    tmp_path: Path, user_text: str, decision: str
) -> None:
    h = Lab(tmp_path)
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        body = CALL | {"params": CALL["params"] | {"arguments": ARGS | {"user_request": user_text}}}
        response = await http.post(h.url, headers=h.headers(), json=body)
        envelope = response.json()["result"]["structuredContent"]
        assert envelope["decision"] == decision
        assert envelope["tool_executed"] == (decision == "PERMIT")
    assert len(h.effects) == int(decision == "PERMIT")
    policies = [e for e in events(h.paths[0]) if e["kind"] == "policy"]
    assert policies[0]["binding_issued"] == (decision == "PERMIT")


async def test_concurrent_principals_containment_and_restart(tmp_path: Path) -> None:
    h = Lab(tmp_path)
    deny = CALL | {
        "params": CALL["params"]
        | {"arguments": ARGS | {"user_request": "blacklist this contractor"}}
    }
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        responses = await asyncio.gather(
            *[
                http.post(h.url, headers=h.headers(i), json=deny if i == 0 else CALL)
                for i in [0, 1, 0, 1]
            ]
        )
        assert [r.json()["result"]["structuredContent"]["decision"] for r in responses] == [
            "DENY",
            "PERMIT",
            "DENY",
            "PERMIT",
        ]
        assert h.journal().denials == 2 and h.journal(1).denials == 0
        result = await http.post(h.url, headers=h.headers(), json=CALL | {"id": "new-request"})
        assert (
            "SESSION_CONTAINMENT_ACTIVE"
            in result.json()["result"]["structuredContent"]["governance"]["policy_reasons"]
        )
    h.sock = socket.socket()
    h.sock.bind(("127.0.0.1", h.port))
    h.make_app()  # Simulated process generation: new server/Gateway, same trusted stores.
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(), json=CALL)
        assert response.json()["result"]["structuredContent"]["decision"] == "DENY"
        response = await http.post(h.url, headers=h.headers(1), json=CALL)
        assert response.json()["result"]["structuredContent"]["decision"] == "PERMIT"
    assert len(h.effects) == 3 and {e["principal"] for e in h.effects} == {"synthetic-bob"}
    generations = {e["generation"] for e in events(h.paths[0]) if e["kind"] == "boot"}
    assert len(generations) == 2


async def test_queued_expiration_blocks_before_new_policy(tmp_path: Path, monkeypatch: Any) -> None:
    h = Lab(tmp_path)
    import civicgate.audit.local_journal as journal_module

    async with h.running(), httpx.AsyncClient(trust_env=False, timeout=3) as http:
        await h.gateway()._lock.acquire()
        try:
            credential = h.token()
            claims = jwt.decode(credential, options={"verify_signature": False})
            task = asyncio.create_task(
                http.post(h.url, headers=h.headers(credential=credential), json=CALL)
            )
            async with asyncio.timeout(2):
                while h.count() == 0:
                    await asyncio.sleep(0.01)
            # Deterministic clock fault only at the existing journal's queued gate.
            monkeypatch.setattr(journal_module, "time", lambda: claims["exp"] + 1)
        finally:
            h.gateway()._lock.release()
        response = await task
        assert response.json()["result"]["isError"]
    assert not h.effects and not [e for e in events(h.paths[0]) if e["kind"] == "policy"]


@pytest.mark.parametrize("attack", ["replay", "foreign", "arguments", "expired", "self-claim"])
async def test_exact_binding_required(tmp_path: Path, monkeypatch: Any, attack: str) -> None:
    h = Lab(tmp_path)
    boundary = h.gateway()._execution_boundary
    original = h.journal().intent

    def fault(authority: Any) -> None:
        original(authority)
        if attack == "replay":
            boundary.consume(
                authority,
                authority.binding.request_id,
                authority.binding.tool,
                json.loads(authority.binding.arguments_json),
                h.gateway()._policy_context(),
            )
        elif attack == "foreign":
            h.gateway()._execution_boundary = h.gateway(1)._execution_boundary
        elif attack == "arguments":
            object.__setattr__(authority.binding, "arguments_json", "{}")
        elif attack == "expired":
            monkeypatch.setattr(boundary, "_clock", lambda: authority.expires_at + 1)

    monkeypatch.setattr(h.journal(), "intent", fault)
    body = (
        CALL
        if attack != "self-claim"
        else CALL | {"params": CALL["params"] | {"arguments": ARGS | {"authority": "PERMIT"}}}
    )
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(), json=body)
        result = response.json()["result"]
        if attack == "self-claim":
            assert result["isError"]
        else:
            assert not result["structuredContent"]["tool_executed"]
            assert [e for e in events(h.paths[0]) if e["kind"] == "finish"][-1][
                "pre_dispatch_verification"
            ] == "FAIL"
    assert not h.backend_entries


async def test_unknown_dispatch_stays_hold_across_requests_and_generation(tmp_path: Path) -> None:
    h = Lab(tmp_path)
    h.fail = True
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(), json=CALL)
        envelope = response.json()["result"]["structuredContent"]
        assert envelope["dispatch_state"] == "DISPATCH_UNKNOWN" and envelope["result"] is None
        assert envelope["next_action"] == "HUMAN_REVIEW_REQUIRED" and envelope["attempt_count"] == 1
        assert h.journal().held
        response = await http.post(h.url, headers=h.headers(), json=CALL | {"id": "fresh"})
        assert response.json()["result"]["isError"]
        assert len(h.backend_entries) == 1
    before = h.paths[0].read_bytes()
    with pytest.raises(LocalHold, match="RECOVERY_HOLD"):
        LocalDispatchJournal(h.paths[0], h.domains[0], REV)
    assert h.paths[0].read_bytes() == before
    assert not h.effects


@pytest.mark.parametrize(
    "bad",
    [b"[]", b'{"jsonrpc":"2.0","id":1,"method":"tools/list","x":NaN}', b'{"a":{"b":1,"b":2}}'],
)
async def test_ambiguous_json_rejected(tmp_path: Path, bad: bytes) -> None:
    h = Lab(tmp_path)
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(), content=bad)
        assert response.status_code == 400
    assert not h.count() and not h.effects


async def test_context_is_reset_on_wrapper_success_and_failure(tmp_path: Path) -> None:
    h = Lab(tmp_path)
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        for i in [1, 0, 1, 0]:
            response = await http.post(h.url, headers=h.headers(i), json=CALL)
            assert not response.json()["result"]["isError"]
        assert invocation_context.get() is None
        assert not h.app._inflight
    for i in range(2):
        contexts = [e["context"] for e in events(h.paths[i]) if e["kind"] in {"begin", "intent"}]
        assert {c["principal"] for c in contexts} == {h.domains[i].principal}
        assert all(c["session"] == "" for c in contexts)
    assert all(c.server.cleanup_checks == 2 for c in h.app.callers)
    assert all(c.server.cleanup_failures == 0 for c in h.app.callers)
    assert (
        not h.gateway()._execution_boundary._issued and not h.gateway(1)._execution_boundary._issued
    )


async def test_interruption_is_not_rollback_or_retry_authority(tmp_path: Path) -> None:
    h = Lab(tmp_path)
    h.block = True
    async with h.running(), httpx.AsyncClient(trust_env=False, timeout=0.15) as http:
        task = asyncio.create_task(http.post(h.url, headers=h.headers(), json=CALL))
        await asyncio.wait_for(h.entered.wait(), 2)
        with pytest.raises(httpx.ReadTimeout):
            await task
        h.release.set()
        async with asyncio.timeout(3):
            while h.journal().active:
                await asyncio.sleep(0.01)
        # Response was lost at the MCP client, but the synthetic read completed.
        # No automatic resend; this is distinct from backend DISPATCH_UNKNOWN.
        assert len(h.backend_entries) == len(h.effects) == 1
        assert not h.journal().held
    record(
        {
            "case": "MCP_RESPONSE_LOST",
            "client_outcome": "UNKNOWN",
            "backend_effects": 1,
            "journal_finish": "REQUEST_CONFIRMED",
            "automatic_retry": False,
        }
    )


def test_no_production_import_or_changes_to_protected_entrypoints() -> None:
    import ast

    root = Path(__file__).resolve().parents[2]
    module = root / "experiments/b2b_p02_stateless_v1.py"
    imports = [
        n.module
        for n in ast.walk(ast.parse(module.read_text(encoding="utf-8")))
        if isinstance(n, ast.ImportFrom)
    ]
    assert "civicgate.mcp.server" not in imports
    assert not any("postgres" in str(i) or "admission" in str(i) for i in imports)
    assert not any("b2b_p02" in p.read_text(encoding="utf-8") for p in (root / "src").rglob("*.py"))


@pytest.mark.parametrize(
    "fault", ["unknown_tool", "bad_query", "missing_request", "wrong_tool", "authority_claim"]
)
async def test_schema_or_authority_claim_rejected(tmp_path: Path, fault: str) -> None:
    h = Lab(tmp_path)
    args: dict[str, Any] = dict(ARGS)
    name = "find_federal_awards"
    if fault == "unknown_tool":
        name = "execute_payment"
    elif fault == "bad_query":
        args["query"] = QUERY | {"unexpected": True}
    elif fault == "missing_request":
        args.pop("user_request")
    elif fault == "wrong_tool":
        name = "get_federal_award"
    else:
        args["authority_envelope"] = {"decision": "PERMIT", "verified": True}
    body = CALL | {"params": {"name": name, "arguments": args}}
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(), json=body)
        assert response.json()["result"]["isError"]
    assert not h.backend_entries
    assert not [e for e in events(h.paths[0]) if e["kind"] == "policy"]
    assert h.app.callers[0].server.cleanup_failures == 0


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"Origin": "https://foreign.invalid"}, 403),
        ({"Host": "foreign.invalid"}, 403),
        ({"Last-Event-Id": "foreign"}, 400),
        ({"Content-Encoding": "gzip"}, 400),
    ],
)
async def test_ingress_failures(tmp_path: Path, headers: dict[str, str], status: int) -> None:
    h = Lab(tmp_path)
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers() | headers, json=CALL)
        assert response.status_code == status
    assert not h.count() and not h.backend_entries


async def test_credential_expires_during_judge_before_intent(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import civicgate.audit.local_journal as journal_module

    h = Lab(tmp_path)
    original = h.gateway()._judge.assess

    async def expire(user_text: str, proposal: Any) -> Any:
        result = await original(user_text, proposal)
        context = invocation_context.get()
        assert context is not None
        monkeypatch.setattr(journal_module, "time", lambda: context.expires_at + 1)
        return result

    monkeypatch.setattr(h.gateway()._judge, "assess", expire)
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(), json=CALL)
        assert response.json()["result"]["isError"]
        assert h.journal().held
    assert not h.backend_entries
    assert h.app.callers[0].server.cleanup_checks == 1
    assert h.app.callers[0].server.cleanup_failures == 0


async def test_foreign_cancellation_cannot_cancel_other_caller(tmp_path: Path) -> None:
    h = Lab(tmp_path)
    h.block = True
    async with h.running(), httpx.AsyncClient(trust_env=False, timeout=3) as http:
        pending = asyncio.create_task(http.post(h.url, headers=h.headers(), json=CALL))
        await asyncio.wait_for(h.entered.wait(), 2)
        cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 3}}
        response = await http.post(h.url, headers=h.headers(1), json=cancel)
        assert response.status_code == 202
        await asyncio.sleep(0.05)
        assert not pending.done()
        h.release.set()
        response = await pending
        assert response.json()["result"]["structuredContent"]["tool_executed"]
    assert len(h.effects) == 1 and h.effects[0]["principal"] == "synthetic-alice"


async def test_two_stateful_instances_have_independent_owners(tmp_path: Path) -> None:
    a, b = Lab(tmp_path / "a", "stateful"), Lab(tmp_path / "b", "stateful")
    # Different independently pinned keys, endpoint audiences and stores;
    # descriptive sub names alone do not establish an authentication domain.
    async with a.running(), b.running(), a.sdk() as (ca, _), b.sdk() as (cb, _):
        for _ in range(2):
            result = await ca.call_tool(
                "find_federal_awards", ARGS | {"user_request": "blacklist this contractor"}
            )
            assert result.structuredContent["decision"] == "DENY"
        result = await cb.call_tool("find_federal_awards", ARGS)
        assert result.structuredContent["decision"] == "PERMIT"
    assert not a.effects and len(b.effects) == 1


async def test_post_dispatch_review_is_not_initial_denial(tmp_path: Path) -> None:
    h = Lab(tmp_path)
    async with h.running(), h.sdk() as (client, _):
        response = await client.call_tool(
            "resolve_federal_recipient",
            {"user_request": "Show public federal data", "query": {"recipient_name": "Acme"}},
        )
        assert response.structuredContent["decision"] == "REVIEW_REQUIRED"
        assert response.structuredContent["tool_executed"]
    policies = [e for e in events(h.paths[0]) if e["kind"] == "policy"]
    finish = [e for e in events(h.paths[0]) if e["kind"] == "finish"][-1]
    assert policies[0]["initial_decision"] == "PERMIT" and policies[0]["binding_issued"]
    assert finish["pre_dispatch_verification"] == "PASS"
    assert finish["final_decision"] == "REVIEW_REQUIRED" and len(h.effects) == 1


async def test_no_credentials_in_protocol_or_logs(tmp_path: Path, caplog: Any) -> None:
    h = Lab(tmp_path)
    credential = h.token()
    async with h.running(), httpx.AsyncClient(trust_env=False) as http:
        response = await http.post(h.url, headers=h.headers(credential=credential), json=CALL)
        assert response.status_code == 200
    assert credential not in response.text and credential not in caplog.text
    assert credential not in json.dumps(events(h.paths[0]))
    assert credential not in json.dumps(h.gateway().trace.events)


async def test_counterexample_shared_ingress_capacity_is_not_availability_isolation(
    tmp_path: Path,
) -> None:
    h = Lab(tmp_path)
    async with h.running(), httpx.AsyncClient(trust_env=False, timeout=2) as http:
        async with AsyncExitStack() as streams:
            for _ in range(16):
                response = await streams.enter_async_context(
                    http.stream("GET", h.url, headers=h.headers() | {"Accept": "text/event-stream"})
                )
                assert response.status_code == 200
            response = await http.post(h.url, headers=h.headers(1), json=LIST)
            assert response.status_code == 429
            assert not h.backend_entries
        async with asyncio.timeout(3):
            while h.app._inflight:
                await asyncio.sleep(0.01)
        assert (await http.post(h.url, headers=h.headers(1), json=LIST)).status_code == 200
    record(
        {
            "case": "COUNTEREXAMPLE_SHARED_INGRESS_CAPACITY",
            "alice_open_sse": 16,
            "bob_http_status": 429,
            "after_cleanup": 200,
            "protected_effects": 0,
            "property": "availability isolation not established; identity/authority not transferred",
        }
    )
