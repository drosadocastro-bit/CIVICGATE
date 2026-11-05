"""Optional local Granite planner stays one-send, exact-identity, and inactive."""

from __future__ import annotations

import json

import httpx
import pytest

from civicgate.evidence_console.chat_planner_v1 import (
    LocalGraniteChatConfig,
    prepare_local_granite_planner,
)
from civicgate.llm.live import GranitePlanner, ProviderError


def response(model: str | None = "granite-local") -> dict[str, object]:
    value: dict[str, object] = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "tool": "find_federal_awards",
                            "arguments": {
                                "start_date": "2025-10-01",
                                "end_date": "2026-09-30",
                                "state_code": "PR",
                            },
                        }
                    )
                }
            }
        ]
    }
    if model is not None:
        value["model"] = model
    return value


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:1234/v1",
        "http://localhost:1234/v1",
        "http://192.0.2.1:1234/v1",
        "http://127.0.0.1:1234",
        "http://127.0.0.1:1234/other",
        "http://user@127.0.0.1:1234/v1",
        "http://127.0.0.1:1234/v1?token=x",
    ],
)
def test_granite_preflight_requires_exact_numeric_loopback_contract(url) -> None:
    with pytest.raises(ValueError, match="LOOPBACK_ENDPOINT_REQUIRED"):
        LocalGraniteChatConfig(url, "granite-local")


@pytest.mark.parametrize("model", ["", " granite", "granite ", "bad\nmodel"])
def test_granite_preflight_requires_exact_model_id(model) -> None:
    with pytest.raises(ValueError, match="MODEL_ID_REQUIRED"):
        LocalGraniteChatConfig("http://127.0.0.1:1234/v1", model)


@pytest.mark.asyncio
async def test_exact_returned_model_accepts_one_typed_proposal() -> None:
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(200, json=response())

    planner = prepare_local_granite_planner(
        LocalGraniteChatConfig("http://127.0.0.1:1234/v1", "granite-local"),
        transport=httpx.MockTransport(handler),
    )
    proposal = await planner.propose("Show public federal awards.")
    assert proposal.tool == "find_federal_awards"
    assert len(attempts) == 1
    assert planner.metadata["host_selected"] is True
    assert planner.metadata["fallback"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("returned", [None, "different-model"])
async def test_missing_or_mismatched_model_identity_is_rejected(returned) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json=response(returned))

    planner = prepare_local_granite_planner(
        LocalGraniteChatConfig("http://127.0.0.1:1234/v1", "granite-local"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        await planner.propose("Show public awards.")
    assert caught.value.code == "MODEL_IDENTITY_MISMATCH"
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["503", "transport"])
async def test_optional_chat_planner_never_retries(failure) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if failure == "transport":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(503)

    planner = prepare_local_granite_planner(
        LocalGraniteChatConfig("http://127.0.0.1:1234/v1", "granite-local"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderError) as caught:
        await planner.propose("Show public awards.")
    assert caught.value.code == "PROVIDER_UNAVAILABLE"
    assert attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_attempts"),
    [
        ("retryable_status", 2),
        ("transport_error", 2),
        ("missing_model", 1),
        ("different_model", 1),
    ],
)
async def test_shared_legacy_planner_retains_original_retry_and_identity_contract(
    mode: str, expected_attempts: int
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if mode == "retryable_status" and attempts == 1:
            return httpx.Response(503)
        if mode == "transport_error" and attempts == 1:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        returned_model = "different-model" if mode == "different_model" else None
        return httpx.Response(200, json=response(returned_model))

    planner = GranitePlanner(
        "http://127.0.0.1:1234/v1",
        "granite-local",
        transport=httpx.MockTransport(handler),
    )
    proposal = await planner.propose("Show public awards.")
    assert proposal.tool == "find_federal_awards"
    assert attempts == expected_attempts
