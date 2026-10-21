"""MVP-002: real SDK/loopback plus direct ASGI resource tests; no backend."""

import asyncio
import socket
from contextlib import asynccontextmanager
from time import time

import httpx
import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp.exceptions import ToolError

from civicgate.channel_b.cloud_smoke_v1 import CloudSmokeApp, Limits, create_cloud_smoke
from civicgate.mcp.http_identity import LocalCredentialVerifier, TrustDomain
from civicgate.models.requests import TOOLS
from experiments.b2b_mvp_002.synthetic_identity import SyntheticAdmission

HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-11-25",
}


def rpc(method="tools/list", params=None, identity=1):
    return {
        "jsonrpc": "2.0",
        "id": identity,
        "method": method,
        **({"params": params} if params is not None else {}),
    }


def tokens(host):
    keys = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
    domains = [
        TrustDomain(
            "https://synthetic.mvp.invalid",
            f"http://{host}/mcp",
            f"synthetic-caller-{i}",
            "synthetic-app",
            "synthetic-instance",
        )
        for i in range(2)
    ]
    gate = SyntheticAdmission(
        tuple(
            LocalCredentialVerifier(d, k.public_key()) for d, k in zip(domains, keys, strict=True)
        ),
        f"http://{host}/mcp",
    )
    now = int(time())
    claims = [
        {
            "iss": d.issuer,
            "aud": d.audience,
            "sub": d.principal,
            "iat": now,
            "nbf": now,
            "exp": now + 240,
            "jti": f"synthetic-credential-{i}",
            "scope": "civicgate:invoke",
        }
        for i, d in enumerate(domains)
    ]
    encoded = [jwt.encode(c, k, algorithm="EdDSA") for c, k in zip(claims, keys, strict=True)]
    return gate, encoded, claims, keys


@asynccontextmanager
async def running(local=False):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    host = f"127.0.0.1:{sock.getsockname()[1]}"
    gate, encoded, claims, keys = tokens(host)
    app = CloudSmokeApp(hosts=(host,), local_test=gate if local else None)
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=sock.getsockname()[1], log_level="error", access_log=False
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield app, f"http://{host}", encoded, claims, keys
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


async def test_real_sdk_stateless_lifecycle_discovery_and_no_tool_authority():
    async with running() as (app, base, _, _, _):
        for _ in range(2):  # new transport/process-session context; no server session created
            async with (
                streamablehttp_client(base + "/mcp") as (read, write, sid),
                ClientSession(read, write) as client,
            ):
                await client.initialize()
                assert sid() is None
                found = (await client.list_tools()).tools
                assert [t.name for t in found] == list(TOOLS)
                for t in found:
                    q = t.inputSchema["properties"]["query"]
                    assert (
                        t.inputSchema["$defs"][q["$ref"].split("/")[-1]]
                        == TOOLS[t.name].model_json_schema()
                    )
                    assert t.inputSchema["additionalProperties"] is False
                result = await client.call_tool(
                    "get_federal_award",
                    {"user_request": "Show public award", "query": {"award_id": "synthetic-1"}},
                )
                assert result.isError and "EXECUTION_DISABLED" in str(result.content)
        assert app._inflight == 0 and all(v == 0 for v in app._counts.values())
        assert (
            app.server.settings.stateless_http
            and app.server.settings.streamable_http_path == "/mcp"
        )


@pytest.mark.parametrize("tool", list(TOOLS) + ["hidden-admin"])
async def test_direct_and_replayed_rpc_never_dispatch(tool):
    async with running() as (app, base, *_):
        async with httpx.AsyncClient(headers=HEADERS) as client:
            req = rpc(
                "tools/call",
                {
                    "name": tool,
                    "arguments": {
                        "authority": "PERMIT",
                        "query": {},
                        "user_request": "Get public records",
                    },
                },
            )
            for _ in range(2):
                response = await client.post(base + "/mcp", json=req)
                assert response.status_code == 200
                result = response.json()
                assert result.get("result", {}).get("isError") or "error" in result
            for forbidden in ("gateway", "journal", "adapter", "_dispatch_journal"):
                assert not hasattr(app, forbidden)
            assert app._inflight == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"x-forwarded-access-token": "unverified"},
        {"authorization": "Bearer malformed"},
        {"x-forwarded-user": "administrator", "x-forwarded-client-id": "app-service-principal"},
        {"x-civicgate-authority": "PERMIT", "x-durable-intent": "ACK", "x-session-id": "new-owner"},
    ],
)
async def test_cloud_forwarded_claims_never_authenticate_or_enable_tools(headers):
    async with running() as (_, base, *_):
        async with httpx.AsyncClient(headers=HEADERS | headers) as client:
            health = (await client.get(base + "/health")).json()
            assert (
                not health["caller_identity_verified"]
                and not health["execution_enabled"]
                and not health["durable_execution_ready"]
            )
            r = await client.post(
                base + "/mcp",
                json=rpc(
                    "tools/call",
                    {
                        "name": "get_federal_award",
                        "arguments": {
                            "user_request": "Show public award",
                            "query": {"award_id": "1"},
                        },
                    },
                ),
            )
            assert r.json()["result"]["isError"]


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "malformed",
        "wrong-signature",
        "other-subject",
        "audience",
        "expired",
        "none-algorithm",
        "forwarded",
    ],
)
async def test_local_synthetic_crypto_rejects_invalid_identity(case):
    async with running(True) as (_, base, encoded, claims, keys):
        headers = HEADERS.copy()
        c = dict(claims[0])
        if case == "absent":
            token = None
        elif case == "malformed":
            token = "not-a-token"
        elif case == "wrong-signature":
            token = jwt.encode(c, Ed25519PrivateKey.generate(), algorithm="EdDSA")
        elif case == "none-algorithm":
            token = jwt.encode(c, key="", algorithm="none")
        else:
            if case == "other-subject":
                c["sub"] = claims[1]["sub"]
            if case == "audience":
                c["aud"] = "https://foreign.invalid/mcp"
            if case == "expired":
                c["iat"] -= 300
                c["nbf"] -= 300
                c["exp"] -= 300
            token = jwt.encode(c, keys[0], algorithm="EdDSA")
        if token:
            headers["authorization"] = "Bearer " + token
        if case == "forwarded":
            headers["x-forwarded-access-token"] = encoded[0]
        async with httpx.AsyncClient(headers=headers) as client:
            assert (await client.post(base + "/mcp", json=rpc())).status_code == 401


async def test_local_cross_caller_discovery_contains_no_identity_or_authority():
    async with running(True) as (app, base, encoded, _, _):
        async with httpx.AsyncClient() as client:

            async def call(token):
                r = await client.post(
                    base + "/mcp",
                    headers=HEADERS | {"authorization": "Bearer " + token},
                    json=rpc(),
                )
                assert r.status_code == 200
                assert "synthetic-caller" not in r.text and token not in r.text
                return r.json()

            a, b = await asyncio.gather(*(call(t) for t in encoded))
            assert a == b and len(app._counts) == 2
            assert all(v == 0 for v in app._counts.values())


@pytest.mark.parametrize(
    "path,method,headers,status",
    [
        ("/mcp/", "POST", {}, 404),
        ("/sse", "GET", {}, 404),
        ("/messages/", "POST", {}, 404),
        ("/mcp", "GET", {}, 405),
        ("/mcp", "DELETE", {}, 405),
        ("/mcp", "POST", {"mcp-session-id": "forged"}, 400),
        ("/mcp", "POST", {"last-event-id": "resume"}, 400),
        ("/mcp", "POST", {"content-encoding": "gzip"}, 400),
        ("/mcp", "POST", {"origin": "https://foreign.invalid"}, 403),
        ("/mcp", "POST", {"host": "foreign.invalid"}, 403),
        ("/mcp?profile=execute", "POST", {}, 404),
    ],
)
async def test_no_alternate_route_session_recovery_or_host_bypass(path, method, headers, status):
    async with running() as (_, base, *_):
        async with httpx.AsyncClient() as client:
            r = await client.request(method, base + path, headers=HEADERS | headers, json=rpc())
            assert r.status_code == status


@pytest.mark.parametrize(
    "raw,status",
    [
        (b"{", 400),
        (b"[]", 400),
        (b'{"jsonrpc":"2.0","method":[]}', 400),
        (b'{"jsonrpc":"2.0","method":"tools/list","method":"tools/call"}', 400),
        (b'{"jsonrpc":"2.0","method":"tools/list","id":NaN}', 400),
        (b'{"jsonrpc":"2.0","method":"resources/list","id":1}', 400),
        (b"x" * 65537, 413),
    ],
    ids=["broken", "batch", "method-type", "duplicate", "nonfinite", "unsupported", "oversize"],
)
async def test_invalid_and_unbounded_input(raw, status):
    async with running() as (_, base, *_):
        async with httpx.AsyncClient() as client:
            r = await client.post(base + "/mcp", headers=HEADERS, content=raw)
            assert r.status_code == status


def scope(host="127.0.0.1:8000", token=None):
    headers = [
        (b"host", host.encode()),
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
    ]
    if token:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8000),
    }


async def test_verified_caller_cannot_exhaust_other_caller_slots_and_cancel_cleans_up():
    gate, tok, _, _ = tokens("127.0.0.1:8000")
    app = CloudSmokeApp(hosts=("127.0.0.1:8000",), local_test=gate)
    waiting = asyncio.Event()

    async def slow():
        await waiting.wait()
        return {"type": "http.disconnect"}

    async def send(_):
        pass

    tasks = [asyncio.create_task(app(scope(token=tok[0]), slow, send)) for _ in range(2)]
    await asyncio.sleep(0.02)
    assert app._inflight == 2 and app._counts[gate.principals[0]] == 2
    result = []

    async def record(message):
        result.append(message)

    await app(scope(token=tok[0]), slow, record)
    assert result[0]["status"] == 429
    # Second verified caller is admitted to its own body slot; cancellation is cleanup, not authority reset.
    other = asyncio.create_task(app(scope(token=tok[1]), slow, send))
    await asyncio.sleep(0.02)
    assert app._inflight == 3 and app._counts[gate.principals[1]] == 1
    for task in tasks + [other]:
        task.cancel()
    await asyncio.gather(*tasks, other, return_exceptions=True)
    assert app._inflight == 0 and all(v == 0 for v in app._counts.values())


async def test_slow_body_deadline_releases_resource_without_authority():
    app = CloudSmokeApp(hosts=("127.0.0.1:8000",), limits=Limits(body_seconds=0.01))
    messages = []

    async def receive():
        await asyncio.sleep(1)
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    await app(scope(), receive, send)
    assert messages[0]["status"] == 408 and app._inflight == 0


async def test_discovery_mutation_and_direct_registered_wrapper_fail_closed():
    app = create_cloud_smoke(("127.0.0.1:8000",))
    found = await app.server.list_tools()
    found[0].inputSchema.clear()
    assert (await app.server.list_tools())[0].inputSchema
    with pytest.raises(ToolError):
        await app.server.call_tool("get_federal_award", {})
    registration = app.server._tool_manager.list_tools()[0]
    with pytest.raises(ToolError):
        await registration.fn("Get public awards", None)
    registration.parameters["properties"]["query"] = {}
    with pytest.raises(ValueError):
        await app.server.list_tools()


@pytest.mark.parametrize(
    "option", ["journal", "gateway", "execution_enabled", "authority", "local_test"]
)
def test_public_cloud_factory_has_no_execution_or_trust_switch(option):
    with pytest.raises(TypeError):
        create_cloud_smoke(("127.0.0.1:8000",), **{option: True})


@pytest.mark.parametrize(
    "hosts",
    [(), ("*",), ("evil.invalid/path",), ("UPPER.invalid",), ("good.invalid", "a", "b", "c")],
)
def test_wildcard_or_unbounded_hosts_rejected(hosts):
    with pytest.raises(ValueError):
        create_cloud_smoke(hosts)
