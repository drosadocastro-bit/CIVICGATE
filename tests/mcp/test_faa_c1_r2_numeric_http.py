"""Actual loopback MCP publication, synthetic identity and raw MockTransport only."""

import httpx
import pytest

from tests.mcp.test_b2a_http import events
from tests.mcp.test_faa_c1 import REQUEST, query
from tests.mcp.test_faa_c1_http import FaaHarness
from tests.mcp.test_faa_c1_r2_numeric import independent_fingerprint, raw_amount


@pytest.mark.parametrize(
    "token,expected",
    [
        ("9007199254740993.01", "9007199254740993.01"),
        ("9007199254740994.00", "9007199254740994"),
        ("1.00", "1"),
        ("NaN", None),
    ],
)
async def test_exact_numeric_mcp_wire_and_durable_record(tmp_path, token, expected):
    raw = raw_amount(token)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=raw, headers={"content-type": "application/json"})
    )
    h = FaaHarness(tmp_path, transport=transport)
    async with h.running(), h.client() as (client, _, _):
        result = await client.call_tool(
            "find_federal_awards", {"user_request": REQUEST, "query": query()}
        )
        assert not result.isError
        wire = result.structuredContent
        assert len(h.calls) == wire["attempt_count"] == 1
        if expected is None:
            assert wire["result"] is None and wire["verification_state"] == "FAILED_VALIDATION"
        else:
            assert wire["verification_state"] == "RESULT_VERIFIED"
            assert wire["result"]["records"][0]["award_amount"] == expected
            assert wire["provenance"]["response_fingerprint"] == independent_fingerprint(
                raw, expected
            )
        records = events(h.store)
        policy = next(e for e in records if e["kind"] == "policy")
        assert policy["initial_decision"] == "PERMIT" and policy["binding_issued"]
        finish = next(e for e in records if e["kind"] == "finish")
        assert finish["tool_executed"] and finish["pre_dispatch_verification"] == "PASS"
