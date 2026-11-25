"""Metadata-only successor tests; never activate a provider or public backend."""

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from civicgate.channel_b.cloud_smoke_v1 import create_cloud_smoke


@pytest.mark.parametrize("profile", ["primary-stdio", "b2a-http", "faa-c1-http", "r022-faa-stdio"])
async def test_profile_sdk_wire_semantics_and_unchanged_contracts(tmp_path, profile):
    import json

    from civicgate.audit.trace import Trace
    from civicgate.demo import fixture_adapter
    from civicgate.llm.mock import MockProvider
    from civicgate.mcp.server import create_server
    from civicgate.mcp.tools import Gateway

    async def verify(server, client, before):
        found = await client.list_tools()
        assert [t.name for t in found.tools] == [t.name for t in before]
        assert len(found.tools) == 4
        for old, new in zip(before, found.tools, strict=True):
            expected = old.model_dump(mode="json", exclude_none=True)
            expected["annotations"]["openWorldHint"] = profile == "primary-stdio"
            assert new.model_dump(mode="json", exclude_none=True) == expected
            assert new.annotations.readOnlyHint is True
            assert new.annotations.destructiveHint is False
            assert new.annotations.idempotentHint is False
        (tmp_path / "before.json").write_text(
            json.dumps([t.model_dump(mode="json", exclude_none=True) for t in before])
        )
        (tmp_path / "after.json").write_text(found.model_dump_json(exclude_none=True))
        found.tools[0].annotations.openWorldHint = not (profile == "primary-stdio")
        again = await client.list_tools()
        assert again.tools[0].annotations.openWorldHint == (profile == "primary-stdio")

    if profile in {"b2a-http", "faa-c1-http"}:
        from tests.mcp.test_b2a_http import Harness
        from tests.mcp.test_faa_c1_http import FaaHarness, fixture

        harness = (
            Harness(tmp_path)
            if profile == "b2a-http"
            else FaaHarness(tmp_path, transport=fixture())
        )
        server = harness.app.server
        before = server._discovery.list_tools(server._tool_manager.list_tools())
        install(harness.app)
        async with harness.running(), harness.client() as (client, _, _):
            await verify(server, client, before)
        assert harness.calls == []
    else:
        if profile == "r022-faa-stdio":
            from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter
            from evals.proposals.r022.faa_contract_v1 import example_query
            from evals.proposals.r022.stdio_v1 import (
                CANONICAL_REQUEST,
                ScopedFaaGateway,
                TrustedFaaIntake,
                create_scoped_server,
            )

            gateway = ScopedFaaGateway(
                FaaProfileFixtureAdapter(),
                MockProvider(),
                Trace(),
                intake=TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query())),
            )
            server = create_scoped_server(gateway)
        else:
            gateway = Gateway(fixture_adapter(), MockProvider(), Trace())
            server = create_server(gateway)
        before = await server.list_tools()
        install(server, gateway=gateway) if profile == "r022-faa-stdio" else install(server)
        async with create_connected_server_and_client_session(server) as client:
            await verify(server, client, before)
        assert gateway.trace.events == []


@pytest.mark.parametrize("mutation", ["missing", "wrong", "unset", "tool-set"])
async def test_missing_or_inconsistent_sdk_metadata_fails_closed(mutation):
    from mcp.shared.exceptions import McpError
    from mcp.types import ListToolsRequest

    app = create_cloud_smoke(("127.0.0.1:8123",))
    original = app.server._mcp_server.request_handlers[ListToolsRequest]

    async def corrupted(request):
        result = await original(request)
        if mutation == "missing":
            result.root.tools[0].annotations = None
        elif mutation == "wrong":
            result.root.tools[0].annotations.readOnlyHint = False
        elif mutation == "unset":
            result.root.tools[0].annotations.model_fields_set.remove("openWorldHint")
        else:
            result.root.tools.pop()
        return result

    app.server._mcp_server.request_handlers[ListToolsRequest] = corrupted
    install(app)
    async with create_connected_server_and_client_session(app.server) as client:
        with pytest.raises(McpError, match="Metadata v2 legacy"):
            await client.list_tools()


async def test_registration_drift_still_blocks_discovery_and_calls():
    from mcp.shared.exceptions import McpError
    from mcp.types import ToolAnnotations

    app = create_cloud_smoke(("127.0.0.1:8123",))
    install(app)
    app.server._tool_manager.get_tool("get_federal_award").annotations = ToolAnnotations(
        readOnlyHint=False
    )
    async with create_connected_server_and_client_session(app.server) as client:
        with pytest.raises(McpError):
            await client.list_tools()
        result = await client.call_tool("get_federal_award", {})
        assert result.isError


@pytest.mark.parametrize("decision", ["DENY", "REVIEW_REQUIRED", "PERMIT"])
async def test_new_metadata_never_issues_execution_authority(decision):
    from civicgate.audit.trace import Trace
    from civicgate.demo import fixture_adapter
    from civicgate.llm.base import UnavailableProvider
    from civicgate.llm.mock import MockProvider
    from civicgate.mcp.server import create_server
    from civicgate.mcp.tools import Gateway

    judge = UnavailableProvider() if decision == "REVIEW_REQUIRED" else MockProvider()
    gateway = Gateway(fixture_adapter(), judge, Trace())
    server = create_server(gateway)
    install(server)
    async with create_connected_server_and_client_session(server) as client:
        await client.list_tools()
        assert gateway.trace.events == []
        text = "Execute payment for this award" if decision == "DENY" else "Public award details"
        result = await client.call_tool(
            "get_federal_award", {"user_request": text, "query": {"award_id": "1"}}
        )
        assert result.structuredContent["decision"] == decision
        assert result.structuredContent["tool_executed"] == (decision == "PERMIT")
        attack = await client.call_tool(
            "get_federal_award",
            {
                "user_request": "Public award details",
                "query": {"award_id": "1"},
                "authority": "PERMIT",
            },
        )
        assert attack.isError


def test_installer_rejects_unknown_owner_duplicate_install_and_late_start():
    with pytest.raises(ValueError, match="Unsupported"):
        install(object())
    app = create_cloud_smoke(("127.0.0.1:8123",))
    install(app)
    with pytest.raises(ValueError, match="already installed"):
        install(app)
    late = create_cloud_smoke(("127.0.0.1:8123",))
    late._started = True
    with pytest.raises(ValueError, match="before transport"):
        install(late)


def test_metadata_version_is_pinned_to_sdk(monkeypatch):
    import civicgate.mcp.metadata_v2 as metadata

    monkeypatch.setattr(metadata, "version", lambda _: "unreviewed-sdk")
    with pytest.raises(ValueError, match="mcp==1.30.0"):
        install(create_cloud_smoke(("127.0.0.1:8123",)))


def test_closed_http_metadata_rejects_nonfixture_judge_and_unexpected_binding(tmp_path):
    from civicgate.llm.base import UnavailableProvider
    from tests.mcp.test_b2a_http import Harness

    harness = Harness(tmp_path)
    try:
        with pytest.raises(ValueError, match="Unexpected"):
            install(harness.app, gateway=harness.app.gateway)
        harness.app.gateway._judge = UnavailableProvider()
        with pytest.raises(ValueError, match="MockProvider"):
            install(harness.app)
    finally:
        harness.sock.close()
        harness.app.journal.close()


async def test_closed_dependencies_cannot_change_between_listings(tmp_path):
    from mcp.shared.exceptions import McpError

    from civicgate.llm.base import UnavailableProvider
    from tests.mcp.test_b2a_http import Harness

    harness = Harness(tmp_path)
    install(harness.app)
    async with harness.running(), harness.client() as (client, _, _):
        await client.list_tools()
        harness.app.gateway._judge = UnavailableProvider()
        with pytest.raises(McpError, match="closed composition changed"):
            await client.list_tools()
    assert harness.calls == []


@pytest.mark.parametrize("profile", ["primary-stdio", "r022-faa-stdio", "write01-stdio"])
async def test_real_stdio_successor_serialization(tmp_path, profile):
    import json
    import os
    import sys
    from pathlib import Path

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from evals.write01.demo_v1 import REQUEST, prepare, query

    root = Path(__file__).resolve().parents[2]
    config = tmp_path / "unused-config.json"
    if profile == "write01-stdio":
        directory = tmp_path / "write"
        prepare(directory, REQUEST, query(), approved=True)
        config = directory / "host-config.json"
    env = {
        k: os.environ[k]
        for k in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP")
        if k in os.environ
    }
    env.update(
        PYTHONPATH=str(root / "src") + os.pathsep + str(root),
        PYTHONDONTWRITEBYTECODE="1",
        LANGSMITH_TRACING="false",
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-B",
            "-m",
            "tests.mcp.metadata_v2_stdio_fixture",
            "--profile",
            profile,
            "--config",
            str(config),
        ],
        env=env,
    )
    stderr_log = tmp_path / "stderr.log"
    try:
        with stderr_log.open("x", encoding="utf-8") as errors:
            async with stdio_client(params, errlog=errors) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    found = await client.list_tools()
                    raw = found.model_dump_json(exclude_none=True, by_alias=True)
                    parsed = json.loads(raw)
                    assert parsed["_meta"]["civicgateMetadataContract"] == "MCP_TOOL_METADATA_V2"
                    assert parsed["_meta"]["profile"] == profile
                    expected_names = (
                        {"update_synthetic_award_review", "get_synthetic_award_review_v1"}
                        if profile == "write01-stdio"
                        else {
                            "find_federal_awards",
                            "get_federal_award",
                            "resolve_federal_recipient",
                            "summarize_federal_spending",
                        }
                    )
                    assert {t["name"] for t in parsed["tools"]} == expected_names
                    for tool in parsed["tools"]:
                        hints = tool["annotations"]
                        expected = (
                            {
                                "readOnlyHint": False,
                                "destructiveHint": True,
                                "idempotentHint": False,
                                "openWorldHint": False,
                            }
                            if tool["name"] == "update_synthetic_award_review"
                            else {
                                "readOnlyHint": True,
                                "destructiveHint": False,
                                "idempotentHint": True,
                                "openWorldHint": False,
                            }
                            if tool["name"] == "get_synthetic_award_review_v1"
                            else {
                                "readOnlyHint": True,
                                "destructiveHint": False,
                                "idempotentHint": False,
                                "openWorldHint": profile == "primary-stdio",
                            }
                        )
                        assert hints == expected
                    (tmp_path / "after.json").write_text(raw, encoding="utf-8")
    except ExceptionGroup:
        # Preserve the original failure while exposing subprocess diagnostics on CI.
        # The child receives only synthetic data and a stripped environment.
        if stderr_log.is_file():
            diagnostic = stderr_log.read_text(encoding="utf-8", errors="replace")
            print(f"STDIO child stderr [{profile}]:\n{diagnostic[-12000:]}")
        raise


def test_all_thirteen_frozen_write_hashes_match(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "evals/manifests/write01_candidate_v1.json").read_text())
    assert len(manifest["files"]) == 13
    checked = []
    for entry in manifest["files"]:
        actual = hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest()
        assert actual == entry["sha256"], entry["path"]
        checked.append({"path": entry["path"], "expected": entry["sha256"], "actual": actual})
    (tmp_path / "hashes.json").write_text(json.dumps(checked, indent=2))


@pytest.mark.parametrize("decision", ["PERMIT", "DENY", "REVIEW_REQUIRED"])
async def test_call_before_discovery_keeps_original_gate(decision):
    from civicgate.audit.trace import Trace
    from civicgate.demo import fixture_adapter
    from civicgate.llm.base import UnavailableProvider
    from civicgate.llm.mock import MockProvider
    from civicgate.mcp.server import create_server
    from civicgate.mcp.tools import Gateway

    judge = UnavailableProvider() if decision == "REVIEW_REQUIRED" else MockProvider()
    gateway = Gateway(fixture_adapter(), judge, Trace())
    server = create_server(gateway)
    install(server)
    assert not server._mcp_server._tool_cache
    async with create_connected_server_and_client_session(server) as client:
        prompt = "Execute payment for this award" if decision == "DENY" else "Public award details"
        result = await client.call_tool(
            "get_federal_award", {"user_request": prompt, "query": {"award_id": "1"}}
        )
        assert result.structuredContent["decision"] == decision
        assert result.structuredContent["tool_executed"] == (decision == "PERMIT")
    assert (
        server._mcp_server._tool_cache["get_federal_award"].inputSchema
        == (await server.list_tools())[1].inputSchema
    )


async def test_successor_retains_legacy_cache_and_second_session_rejection():
    from mcp.shared.exceptions import McpError

    from civicgate.audit.trace import Trace
    from civicgate.demo import fixture_adapter
    from civicgate.llm.mock import MockProvider
    from civicgate.mcp.server import create_server
    from civicgate.mcp.tools import Gateway

    gateway = Gateway(fixture_adapter(), MockProvider(), Trace())
    server = create_server(gateway)
    install(server)
    async with create_connected_server_and_client_session(server) as client:
        found = await client.list_tools()
        for tool in found.tools:
            cached = server._mcp_server._tool_cache[tool.name]
            assert cached.inputSchema == tool.inputSchema
            assert cached.outputSchema == tool.outputSchema
            assert cached.annotations == tool.annotations
    async with create_connected_server_and_client_session(server) as client:
        with pytest.raises(McpError, match="session sharing"):
            await client.list_tools()
    assert gateway.trace.events == []


async def test_cloud_successor_over_actual_stateless_http(tmp_path, monkeypatch):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from civicgate.channel_b.cloud_smoke_v1 import CloudSmokeApp
    from experiments.b2b_mvp_002 import test_smoke

    def configured(*args, **kwargs):
        app = CloudSmokeApp(*args, **kwargs)
        install(app)
        return app

    monkeypatch.setattr(test_smoke, "CloudSmokeApp", configured)
    async with test_smoke.running() as (app, base, _, _, _):
        async with streamable_http_client(base + "/mcp") as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                found = await client.list_tools()
                assert all(t.annotations.openWorldHint is False for t in found.tools)
                for tool in found.tools:
                    cached = app.server._mcp_server._tool_cache[tool.name]
                    assert cached.inputSchema == tool.inputSchema
                    assert cached.annotations.openWorldHint is True
                    assert cached is not tool
                (tmp_path / "after.json").write_text(
                    found.model_dump_json(exclude_none=True, by_alias=True), encoding="utf-8"
                )
        assert all(t.annotations.openWorldHint is True for t in await app.server.list_tools())


async def test_metadata_view_does_not_bypass_http_request_context(tmp_path):
    from mcp.shared.exceptions import McpError

    from tests.mcp.test_b2a_http import Harness

    harness = Harness(tmp_path)
    install(harness.app)
    try:
        async with create_connected_server_and_client_session(harness.app.server) as client:
            with pytest.raises(McpError, match="Authenticated HTTP request required"):
                await client.list_tools()
        assert harness.calls == []
    finally:
        harness.sock.close()
        harness.app.journal.close()


def install(owner, **kwargs):
    try:
        from civicgate.mcp.metadata_v2 import install_metadata_v2
    except ModuleNotFoundError:
        pytest.fail("Host opt-in metadata_v2 implementation is missing")
    return install_metadata_v2(owner, **kwargs)


async def test_cloud_sdk_closed_hints_without_new_execution_handler():
    app = create_cloud_smoke(("127.0.0.1:8123",))
    server = app.server
    handlers = dict(server._mcp_server.request_handlers)
    registration_ids = [id(t) for t in server._tool_manager.list_tools()]
    handle = install(app)
    async with create_connected_server_and_client_session(server) as client:
        listing = await client.list_tools()
        assert len(listing.tools) == 4
        assert all(t.annotations.openWorldHint is False for t in listing.tools)
        assert listing.meta["civicgateMetadataContract"] == "MCP_TOOL_METADATA_V2"
        assert handle.profile == "cloud-discovery"
        for tool in listing.tools:
            result = await client.call_tool(
                tool.name, {"user_request": "Read public award", "query": {"award_id": "1"}}
            )
            assert result.isError
            assert "EXECUTION_DISABLED" in str(result.content)
    from mcp.types import ListToolsRequest

    assert [id(t) for t in server._tool_manager.list_tools()] == registration_ids
    assert all(
        server._mcp_server.request_handlers[k] is v
        for k, v in handlers.items()
        if k is not ListToolsRequest
    )


@pytest.mark.parametrize("scenario", ["PERMIT", "DENY", "REVIEW_REQUIRED"])
async def test_write_successor_metadata_preserves_exact_frozen_execution(tmp_path, scenario):
    import json

    from evals.write01.contract_v1 import READ_TOOL, WRITE_TOOL
    from evals.write01.demo_v1 import READ_REQUEST, REQUEST, prepare, query
    from evals.write01.stdio_v1 import configured_server

    proposed = query()
    if scenario == "DENY":
        proposed["proposed_status"] = "AWARD_CONTRACT"
    directory = tmp_path / "write"
    prepare(directory, REQUEST, proposed, approved=scenario != "REVIEW_REQUIRED")
    server = configured_server(directory / "host-config.json")
    legacy = {t.name: t for t in await server.list_tools()}
    assert legacy[WRITE_TOOL].annotations.destructiveHint is False
    handlers = dict(server._mcp_server.request_handlers)
    install(server)
    async with create_connected_server_and_client_session(server) as client:
        listing = await client.list_tools()
        public = {t.name: t for t in listing.tools}
        assert public[WRITE_TOOL].annotations.model_dump(exclude_none=True) == {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False,
        }
        for name in legacy:
            assert public[name].inputSchema == legacy[name].inputSchema
            assert public[name].outputSchema == legacy[name].outputSchema
        result = await client.call_tool(WRITE_TOOL, {"user_request": REQUEST, "query": proposed})
        value = result.structuredContent
        assert value["decision"] == scenario
        assert value["adapter_entries"] == int(scenario == "PERMIT")
        assert value["binding_consumed"] == (scenario == "PERMIT")
        if scenario == "PERMIT":
            receipt = value["result"]["receipt"]
            assert receipt["before"]["status"] == "UNREVIEWED"
            assert receipt["after"]["status"] == "PENDING_REVIEW"
            assert receipt["after"]["version"] == 1
            repeated = await client.call_tool(
                WRITE_TOOL, {"user_request": REQUEST, "query": proposed}
            )
            assert repeated.structuredContent["adapter_entries"] == 0
            read = await client.call_tool(
                READ_TOOL,
                {"user_request": READ_REQUEST, "query": {"award_id": proposed["award_id"]}},
            )
            assert read.structuredContent["result"] == receipt["after"]
    import sqlite3

    with sqlite3.connect((directory / "review.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT count(*) FROM notes").fetchone()[0] == int(scenario == "PERMIT")
        assert db.execute("SELECT count(*) FROM intents").fetchone()[0] == int(scenario == "PERMIT")
    events = [json.loads(x) for x in (directory / "audit.jsonl").read_text().splitlines()]
    assert sum(e["stage"] == "adapter_entry" and e["tool"] == WRITE_TOOL for e in events) == int(
        scenario == "PERMIT"
    )
    from mcp.types import ListToolsRequest

    assert all(
        server._mcp_server.request_handlers[k] is v
        for k, v in handlers.items()
        if k is not ListToolsRequest
    )
