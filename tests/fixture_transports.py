"""Stateful transports used only by the reproducible evaluation fixtures."""

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx


def _search_body(amount: str, generated_id: str = "FIXTURE_AWARD_1") -> dict[str, Any]:
    return {
        "results": [
            {
                "internal_id": 1,
                "generated_internal_id": generated_id,
                "Award ID": "FIXTURE-1",
                "Recipient Name": "EXAMPLE RECIPIENT",
                "Award Amount": amount,
                "Awarding Agency": "Fixture Agency",
            }
        ],
        "page_metadata": {"hasNext": False},
    }


class _FailingStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        raise httpx.ReadTimeout("simulated mid-response timeout")
        yield b""

    async def aclose(self) -> None:
        return None


def five_hundred_then_success() -> httpx.MockTransport:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=_search_body("123.45"))

    return httpx.MockTransport(respond)


def timeout_then_changed_snapshot() -> httpx.MockTransport:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=_FailingStream(),
            )
        return httpx.Response(200, json=_search_body("999.99", "CHANGED_AWARD_SNAPSHOT"))

    return httpx.MockTransport(respond)


FACTORY_REGISTRY: dict[str, Callable[[], httpx.MockTransport]] = {
    "five_hundred_then_success": five_hundred_then_success,
    "timeout_then_changed_snapshot": timeout_then_changed_snapshot,
}


def build_transport(name: str) -> httpx.MockTransport:
    try:
        return FACTORY_REGISTRY[name]()
    except KeyError as exc:
        raise ValueError(f"Unknown fixture transport factory: {name}") from exc
