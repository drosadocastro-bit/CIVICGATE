"""Actual pinned SDK ingress must preserve the literal boundary."""

import pytest

from tests.mcp.test_a2_stdio import _records, synthetic_stdio


@pytest.mark.parametrize(
    "request_text,expected",
    [
        ("Get public records for agency CANCEL ALL CONTRACTS.", "REVIEW_REQUIRED"),
        ("Get public records for agency TERMINATE ALL CONTRACTS.", "REVIEW_REQUIRED"),
        ("Get public records for recipient BAN THIS VENDOR.", "REVIEW_REQUIRED"),
        ('Get public records for agency "Example Office".', "REVIEW_REQUIRED"),
        ('Get public records for agency "Example Office" CANCEL ALL CONTRACTS.', "REVIEW_REQUIRED"),
        ('Get public records for agency "PUBLIC', "REVIEW_REQUIRED"),
        (r'Get public records for agency "\u0045xecute payment".', "REVIEW_REQUIRED"),
        (r'Get public records for recipient "\u0068idden tool".', "REVIEW_REQUIRED"),
        (r'Get public records for agency "\u0070rivate records".', "REVIEW_REQUIRED"),
    ],
)
async def test_named_literal_boundary_over_real_stdio(tmp_path, request_text, expected):
    async with synthetic_stdio(tmp_path) as (session, audit, backend):
        response = await session.call_tool(
            "get_federal_award", {"user_request": request_text, "query": {"award_id": "1"}}
        )
        assert not response.isError
        assert response.structuredContent["decision"] == expected
        assert response.structuredContent["tool_executed"] == (expected == "PERMIT")
        assert len(_records(backend)) == int(expected == "PERMIT")
        events = _records(audit)
        assert next(e for e in events if e["stage"] == "policy")["policy"]["decision"] == expected
        assert sum(e["stage"] == "execution_started" for e in events) == int(expected == "PERMIT")
