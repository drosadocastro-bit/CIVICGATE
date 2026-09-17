import json

import httpx
import pytest

from civicgate.adapters.usaspending import AdapterError, USAspending
from civicgate.models.requests import Award, Recipient, Search


@pytest.mark.parametrize(
    "status,body,code",
    [
        (404, {}, "NOT_FOUND"),
        (400, {}, "UPSTREAM_REJECTED"),
        (302, {}, "UPSTREAM_REJECTED"),
        (500, {}, "UPSTREAM_UNAVAILABLE"),
        (429, {}, "UPSTREAM_UNAVAILABLE"),
        (200, {}, "MALFORMED_RESPONSE"),
        (200, {"results": [], "page_metadata": {}}, "MALFORMED_RESPONSE"),
        (
            200,
            {"results": [{"Award Amount": "NaN"}], "page_metadata": {"hasNext": False}},
            "MALFORMED_RESPONSE",
        ),
    ],
)
async def test_failure_classes(
    status: int, body: dict[str, object], code: str, search_args: dict[str, object]
) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=body)

    adapter = USAspending(httpx.MockTransport(respond))
    with pytest.raises(AdapterError, match=code):
        await adapter.search(Search.model_validate(search_args))
    assert len(calls) == (3 if status in (429, 500) else 1)


async def test_mapping_and_empty_success(search_args: dict[str, object]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["filters"]["place_of_performance_locations"] == [
            {"country": "USA", "state": "PR"}
        ]
        assert body["filters"]["agencies"] == [
            {"type": "awarding", "tier": "toptier", "name": "Department of Energy"}
        ]
        assert body["page"] == 1 and body["limit"] == 20
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"results": [], "page_metadata": {"hasNext": False}})

    batch = await USAspending(httpx.MockTransport(respond)).search(
        Search.model_validate(search_args | {"awarding_agency": "Department of Energy"})
    )
    assert batch.records == []
    assert batch.provenance.records_returned == 0
    assert batch.provenance.source_type == "PUBLIC_GOVERNMENT_API"


@pytest.mark.parametrize("failure", ["timeout", "network", "html", "oversize", "invalid_json"])
async def test_transport_containment(failure: str, search_args: dict[str, object]) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("test")
        if failure == "network":
            raise httpx.ConnectError("test")
        return httpx.Response(
            200,
            content=(b"x" * 2_000_001 if failure == "oversize" else b"<html>bad"),
            headers={"content-type": "text/html" if failure == "html" else "application/json"},
        )

    with pytest.raises(AdapterError):
        await USAspending(httpx.MockTransport(respond)).search(Search.model_validate(search_args))
    assert len(calls) <= 3


async def test_detail_identity_mismatch() -> None:
    adapter = USAspending(
        httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "id": 2,
                    "generated_unique_award_id": "OTHER",
                    "category": "contract",
                    "total_obligation": 20,
                },
            )
        )
    )
    with pytest.raises(AdapterError, match="MALFORMED_RESPONSE"):
        await adapter.detail(Award(award_id="1"))


async def test_recipient_contract_required() -> None:
    adapter = USAspending(
        httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"results": [{"name": "Acme"}], "page_metadata": {"hasNext": False}}
            )
        )
    )
    with pytest.raises(AdapterError):
        await adapter.recipients(Recipient(recipient_name="Acme"))
