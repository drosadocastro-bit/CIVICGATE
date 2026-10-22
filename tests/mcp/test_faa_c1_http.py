"""Real local SDK Streamable HTTP; all identities/data/backends are synthetic."""

import httpx
import pytest

from civicgate.channel_b.faa_adapter_v1 import FAA_C1
from civicgate.channel_b.faa_http_v1 import FaaC1HTTPApp, _FaaHTTPServer, register_faa_tools
from civicgate.channel_b.faa_profile_v1 import FAA, FaaScopeV1
from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.models.requests import TOOLS, Search
from tests.mcp.test_b2a_http import REVISION, Harness, events
from tests.mcp.test_b2a_recovery import assert_restart_hold
from tests.mcp.test_faa_c1 import REQUEST, Capture, body, query


class FaaHarness(Harness):
    def make_app(self):
        return FaaC1HTTPApp(
            verifier=self.verifier,
            store=self.store,
            code_revision=REVISION,
            transport=self.transport,
            port=self.port,
        )


def fixture(obj=None):
    return httpx.MockTransport(lambda _: httpx.Response(200, json=body() if obj is None else obj))


async def test_real_mcp_discovery_and_exact_faa_call_with_durable_intent(tmp_path):
    h = FaaHarness(tmp_path, transport=fixture())
    async with h.running(), h.client() as (client, sid, _):
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == list(TOOLS)
        for tool in tools:
            schema = tool.inputSchema
            q = schema["properties"]["query"]
            q = schema["$defs"][q["$ref"].split("/")[-1]] if "$ref" in q else q
            expected = FaaScopeV1 if tool.name == "find_federal_awards" else TOOLS[tool.name]
            assert q == expected.model_json_schema()
            assert not tool.inputSchema["additionalProperties"]
        assert len(h.calls) == 0
        result = await client.call_tool(
            "find_federal_awards", {"user_request": REQUEST, "query": query()}
        )
        assert not result.isError
        evidence = result.structuredContent
        assert evidence["decision"] == "PERMIT" and evidence["tool_executed"]
        assert evidence["result"]["records"][0]["awarding_sub_agency"] == FAA
        assert len(h.calls) == 1
        records = events(h.store)
        policy = next(e for e in records if e["kind"] == "policy")
        assert policy["initial_decision"] == "PERMIT" and policy["binding_issued"]
        finish = next(e for e in records if e["kind"] == "finish")
        assert finish["pre_dispatch_verification"] == "PASS" and finish["tool_executed"]
        assert finish["final_decision"] == "PERMIT"
        assert all(e["context"]["session"] == sid() for e in records if e["kind"] == "begin")


@pytest.mark.parametrize(
    "attack", ["contract", "authority", "legacy-schema", "unknown", "extra-filter", "other-tool"]
)
async def test_direct_mcp_cannot_select_contract_or_bypass_gateway(tmp_path, attack):
    h = FaaHarness(tmp_path, transport=fixture())
    args = {"user_request": REQUEST, "query": query()}
    name = "find_federal_awards"
    if attack in {"contract", "authority"}:
        args[attack] = "legacy" if attack == "contract" else "PERMIT"
    elif attack == "legacy-schema":
        args["query"] = {
            "start_date": "2024-10-01",
            "end_date": "2025-09-30",
            "awarding_agency": FAA,
        }
    elif attack == "unknown":
        name = "hidden_tool"
    elif attack == "other-tool":
        name = "summarize_federal_spending"
    else:
        args["query"]["funding_agency"] = FAA
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool(name, args)
        assert result.isError
        assert h.calls == []
        assert not any(e["kind"] == "intent" for e in events(h.store))
        assert h.app.gateway.trace.events == []  # MCP-layer rejection, not a policy event.


@pytest.mark.parametrize(
    "prompt,decision",
    [
        ("Deny this award.", "DENY"),
        ('Get public awards for agency "Other Agency".', "REVIEW_REQUIRED"),
    ],
)
async def test_mcp_policy_denial_and_review_have_no_backend_dispatch(tmp_path, prompt, decision):
    h = FaaHarness(tmp_path, transport=fixture())
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool(
            "find_federal_awards", {"user_request": prompt, "query": query()}
        )
        assert not result.isError
        assert (
            result.structuredContent["decision"] == decision
            and not result.structuredContent["tool_executed"]
        )
        assert h.calls == []
        policy = next(e for e in events(h.store) if e["kind"] == "policy")
        assert policy["initial_decision"] == decision and not policy["binding_issued"]


async def test_mcp_post_result_review_keeps_initial_permit_and_intent(tmp_path):
    obj = body()
    obj["results"][0]["Awarding Sub Agency"] = "Federal Highway Administration"
    obj["results"][0]["Funding Sub Agency"] = FAA
    h = FaaHarness(tmp_path, transport=fixture(obj))
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool(
            "find_federal_awards", {"user_request": REQUEST, "query": query()}
        )
        assert not result.isError
        assert result.structuredContent["decision"] == "REVIEW_REQUIRED"
        assert (
            result.structuredContent["result"] is None and result.structuredContent["tool_executed"]
        )
        records = events(h.store)
        assert next(e for e in records if e["kind"] == "policy")["initial_decision"] == "PERMIT"
        finish = next(e for e in records if e["kind"] == "finish")
        assert (
            finish["pre_dispatch_verification"] == "PASS"
            and finish["final_decision"] == "REVIEW_REQUIRED"
        )
        assert len(h.calls) == 1


async def test_mcp_transport_unknown_has_durable_hold_and_no_retry(tmp_path):
    def fail(_):
        raise httpx.ReadTimeout("synthetic unknown dispatch")

    h = FaaHarness(tmp_path, transport=httpx.MockTransport(fail))
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool(
            "find_federal_awards", {"user_request": REQUEST, "query": query()}
        )
        assert result.structuredContent["dispatch_state"] == "DISPATCH_UNKNOWN"
        assert result.structuredContent["next_action"] == "HUMAN_REVIEW_REQUIRED"
        assert result.structuredContent["retry_class"] == "UNSAFE"
        again = await client.call_tool(
            "find_federal_awards", {"user_request": REQUEST, "query": query()}
        )
        assert again.isError and len(h.calls) == 1
    assert_restart_hold(h.store, h.domain)


def test_cross_channel_discovery_and_registration_drift_rejected():
    c = Capture()
    server = _FaaHTTPServer("synthetic")
    register_faa_tools(server, c.gateway)
    registrations = server._tool_manager.list_tools()
    with pytest.raises(ValueError, match="schema mismatch"):
        BoundedToolDiscovery(registrations)
    bounded = BoundedToolDiscovery(registrations, contract=FAA_C1)
    public = bounded.list_tools(registrations)
    public[0].inputSchema["properties"]["query"] = {}
    assert bounded.list_tools(registrations)[0].inputSchema["properties"]["query"]
    registrations[0].parameters["properties"]["query"] = {"type": "string"}
    with pytest.raises(ValueError):
        bounded.validate(registrations)
    assert c.requests == [] and TOOLS["find_federal_awards"] is Search


async def test_channel_b_legacy_client_schema_cannot_cross_into_faa(tmp_path):
    h = FaaHarness(tmp_path, transport=fixture())
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool(
            "find_federal_awards",
            {
                "user_request": REQUEST,
                "query": {
                    "awarding_agency": FAA,
                    "start_date": "2024-10-01",
                    "end_date": "2025-09-30",
                },
            },
        )
        assert result.isError and not h.calls


async def test_other_three_tools_retain_legacy_schema_and_routes(tmp_path):
    # Generic tools use the original fixture responses, not FAA labels.
    h = FaaHarness(tmp_path)
    async with h.running(), h.client() as (client, _, _):
        cases = [
            ("get_federal_award", {"award_id": "1"}),
            ("resolve_federal_recipient", {"recipient_name": "Acme"}),
            (
                "summarize_federal_spending",
                {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"},
            ),
        ]
        for name, args in cases:
            result = await client.call_tool(
                name, {"user_request": "Show public federal data", "query": args}
            )
            assert not result.isError and result.structuredContent["tool_executed"]
        assert len(h.calls) == 3
