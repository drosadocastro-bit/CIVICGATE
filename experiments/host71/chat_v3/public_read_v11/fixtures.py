"""Explicit synthetic public API shapes, never a LIVE fallback."""

from __future__ import annotations

import json

import httpx

from .contract import SEARCH_PATH


def _base_response(request: httpx.Request, fault: str = "none") -> httpx.Response:
    if fault == "timeout":
        raise httpx.ReadTimeout("synthetic timeout")
    if fault == "malformed":
        return httpx.Response(200, json={"results": [{"unexpected": True}]})
    if fault == "http500":
        return httpx.Response(500, json={"detail": "synthetic upstream failure"})
    if request.url.path == SEARCH_PATH:
        return httpx.Response(
            200,
            json={
                "spending_level": "awards",
                "limit": json.loads(request.content)["limit"],
                "results": []
                if fault == "empty"
                else [
                    {
                        "internal_id": 1,
                        "generated_internal_id": "CONT_AWD_SYNTHETIC_1",
                        "Award ID": "SYNTHETIC_1",
                        "Recipient Name": "SYNTHETIC PUBLIC CONTRACTOR",
                        "Award Amount": "9007199254740993.01",
                        "Awarding Agency": "Department of Transportation",
                    }
                ],
                "page_metadata": {"page": 1, "hasNext": fault == "truncated"},
            },
        )
    return httpx.Response(
        200,
        json={
            "id": 1,
            "generated_unique_award_id": "CONT_AWD_SYNTHETIC_1",
            "category": "contract",
            "total_obligation": "9007199254740993.01",
        },
    )


def response(request: httpx.Request, fault: str = "none") -> httpx.Response:
    """Explicit offline test mutations; never applied to a real response."""
    result = _base_response(request, fault)
    if request.url.path == SEARCH_PATH and fault in {
        "notice11",
        "notice_unknown11",
        "notice_invalid_page11",
    }:
        from .response_contract_v2 import REVIEWED_TIME_NOTICE

        data = json.loads(result.content)
        data["messages"] = [REVIEWED_TIME_NOTICE]
        if fault == "notice_unknown11":
            data["messages"].append("SYNTHETIC_UNKNOWN_DO_NOT_OBEY")
        if fault == "notice_invalid_page11":
            data["page_metadata"]["page"] = 2
        return httpx.Response(200, json=data)
    if request.url.path == SEARCH_PATH and fault in {
        "null_fields",
        "wrong_page_v2",
        "wrong_limit_v2",
        "wrong_level_v2",
    }:
        data = json.loads(result.content)
        if fault == "null_fields":
            data["results"][0]["Recipient Name"] = None
            data["results"][0]["Awarding Agency"] = None
        elif fault == "wrong_page_v2":
            data["page_metadata"]["page"] = 2
        elif fault == "wrong_limit_v2":
            data["limit"] += 1
        elif fault == "wrong_level_v2":
            data["spending_level"] = "subawards"
        return httpx.Response(200, json=data)
    return result
