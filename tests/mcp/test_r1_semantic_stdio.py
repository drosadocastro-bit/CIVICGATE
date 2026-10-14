"""The installed MCP1.30.0 stdio path must apply the independent R1 hold."""

from pathlib import Path

import pytest

from tests.mcp.test_a2_stdio import _records, synthetic_stdio


@pytest.mark.parametrize(
    "request_text,expected",
    [
        ("Authorize a transfer of public funds to the vendor.", "REVIEW_REQUIRED"),
        ("Determina de forma vinculante los requisitos del proveedor.", "REVIEW_REQUIRED"),
        ("Get public award records and take care of their status.", "REVIEW_REQUIRED"),
        ("Describe the meaning of public award authorization.", "REVIEW_REQUIRED"),
        ("Get public federal award details.", "PERMIT"),
    ],
)
async def test_stdio_model_permission_cannot_override_independent_request_review(
    tmp_path: Path, request_text: str, expected: str
) -> None:
    async with synthetic_stdio(tmp_path) as (session, audit, backend):
        result = await session.call_tool(
            "get_federal_award", {"user_request": request_text, "query": {"award_id": "1"}}
        )
        assert result.isError is False
        response = result.structuredContent
        assert response["decision"] == expected
        assert len(_records(backend)) == int(expected == "PERMIT")
        events = _records(audit)
        assert (
            next(event for event in events if event["stage"] == "policy")["policy"]["decision"]
            == expected
        )
        assert sum(event["stage"] == "execution_started" for event in events) == int(
            expected == "PERMIT"
        )
