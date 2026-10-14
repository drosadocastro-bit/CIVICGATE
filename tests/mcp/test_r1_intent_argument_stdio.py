"""The actual SDK transport cannot bypass explicit name/filter consistency."""

import json

import pytest

from tests.mcp.test_a2_stdio import _records, synthetic_stdio

BASE = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}
CASES = [
    (
        'Get public records for recİpient "Example Foundation".',
        "find_federal_awards",
        BASE | {"recipient_name": "Other Recipient", "awarding_agency": "Example Foundation"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for destİnatario "Example Foundation".',
        "summarize_federal_spending",
        BASE | {"recipient_name": "Other Recipient", "awarding_agency": "Example Foundation"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for agency "Example Office".',
        "find_federal_awards",
        BASE | {"awarding_agency": "Example Office"},
        "PERMIT",
    ),
    (
        'Get public records for agency "Example Office".',
        "summarize_federal_spending",
        BASE | {"awarding_agency": "Example Office"},
        "PERMIT",
    ),
    (
        r'Get public records for agencia "Oficina \u00c1lamo".',
        "find_federal_awards",
        BASE | {"awarding_agency": "Oficina Álamo"},
        "PERMIT",
    ),
    (
        'Get public records for agency "Example Office".',
        "find_federal_awards",
        BASE | {"awarding_agency": "Other Agency"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for agency "Example Office".',
        "find_federal_awards",
        BASE,
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for recipient "Cooperativa El Niño".',
        "find_federal_awards",
        BASE | {"recipient_name": "Other Recipient"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for agency "Example Office".',
        "get_federal_award",
        {"award_id": "1"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for agency "Example Office".',
        "resolve_federal_recipient",
        {"recipient_name": "Example Office"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for agency "Élan".',
        "find_federal_awards",
        BASE | {"awarding_agency": "E\u0301lan"},
        "REVIEW_REQUIRED",
    ),
    (
        r'Get public records for agency "\u0045xample Office".',
        "find_federal_awards",
        BASE | {"awarding_agency": "Other Agency"},
        "REVIEW_REQUIRED",
    ),
    (
        'Get public records for agency "Example Office".',
        "find_federal_awards",
        BASE | {"awarding_agency": "Execute payment"},
        "DENY",
    ),
]


@pytest.mark.parametrize("encoded_query", [False, True])
@pytest.mark.parametrize("request_text,tool,query,expected", CASES)
async def test_direct_mcp_name_scope_is_checked_before_dispatch(
    tmp_path, request_text, tool, query, expected, encoded_query
):
    async with synthetic_stdio(tmp_path) as (session, audit, backend):
        response = await session.call_tool(
            tool,
            {
                "user_request": request_text,
                "query": json.dumps(query, ensure_ascii=False) if encoded_query else query,
            },
        )
        assert not response.isError
        envelope = response.structuredContent
        assert envelope["decision"] == expected
        dispatched = expected == "PERMIT"
        assert envelope["tool_executed"] is dispatched
        assert len(_records(backend)) == int(dispatched)
        events = _records(audit)
        policy = next(event for event in events if event["stage"] == "policy")
        assert policy["policy"]["decision"] == expected
        assert policy["binding_issued"] is dispatched
        assert sum(event["stage"] == "execution_started" for event in events) == int(dispatched)
        assert json.loads(policy["facts"]["arguments_json"]).items() >= query.items()
