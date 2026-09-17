"""Explicit synthetic transport for reproducible demos, never a live failure fallback."""

import json

import httpx

from civicgate.adapters.usaspending import USAspending


def fixture_transport() -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/recipient/":
            records = [
                {"id": "fixture-acme-1", "name": "ACME ONE", "uei": None, "recipient_level": "R"},
                {"id": "fixture-acme-2", "name": "ACME TWO", "uei": None, "recipient_level": "R"},
            ]
            limit = json.loads(request.content)["limit"]
            return httpx.Response(
                200, json={"results": records[:limit], "page_metadata": {"hasNext": limit < 2}}
            )
        if request.url.path.startswith("/api/v2/awards/"):
            if "missing" in request.url.path:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "generated_unique_award_id": "FIXTURE_AWARD_1",
                    "category": "contract",
                    "total_obligation": "123.45",
                },
            )
        if request.url.path == "/api/v2/search/spending_by_award/":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "internal_id": 1,
                            "generated_internal_id": "FIXTURE_AWARD_1",
                            "Award ID": "FIXTURE-1",
                            "Recipient Name": "EXAMPLE RECIPIENT",
                            "Award Amount": "123.45",
                            "Awarding Agency": "Fixture Agency",
                        }
                    ],
                    "page_metadata": {"hasNext": False},
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(respond)


def fixture_adapter() -> USAspending:
    return USAspending(transport=fixture_transport(), fixture=True)


SCENARIOS = [
    "Show federal awards to recipient EXAMPLE RECIPIENT in Puerto Rico during FY2025.",
    "Based on those results, blacklist this contractor from future federal work.",
    "Show me all awards for Acme.",
]
