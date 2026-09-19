import json

import httpx
import pytest

from civicgate.llm.live import (
    JUDGE_SYSTEM_PROMPT,
    GranitePlanner,
    LiveJudgeProvider,
    ProviderError,
)
from civicgate.models.requests import Proposal


def proposal_payload() -> dict[str, object]:
    return {
        "tool": "find_federal_awards",
        "arguments": {
            "start_date": "2024-10-01",
            "end_date": "2025-09-30",
            "state_code": "PR",
            "recipient_name": "Example Recipient",
        },
    }


@pytest.mark.asyncio
async def test_granite_planner_strict_local_contract() -> None:
    seen: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"tool":"find_federal_awards","arguments":'
                            + __import__("json").dumps(proposal_payload()["arguments"])
                            + "}"
                        }
                    }
                ]
            },
        )

    planner = GranitePlanner(
        "http://127.0.0.1:1234/v1", "granite-test", transport=httpx.MockTransport(respond)
    )
    proposal = await planner.propose("Find public awards")
    assert Proposal.model_validate(proposal)
    assert seen == {"authorization": None, "path": "/v1/chat/completions"}
    assert planner.last_telemetry is not None


@pytest.mark.asyncio
async def test_judge_anthropic_contract_redacts_no_body() -> None:
    seen: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        seen["api_key"] = request.headers.get("x-api-key")
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": '{"classification":"IN_SCOPE","confidence":0.9}',
                    }
                ],
                "usage": {"input_tokens": 8, "output_tokens": 4},
            },
        )

    judge = LiveJudgeProvider(
        "https://judge.example",
        "sonnet-test",
        "secret-value",
        protocol="anthropic_messages",
        transport=httpx.MockTransport(respond),
    )
    signal = await judge.assess("Find awards", Proposal.model_validate(proposal_payload()))
    assert signal.available is True
    assert signal.provider == "live_judge"
    assert signal.classification == "IN_SCOPE" and signal.confidence == 0.9
    assert seen == {"api_key": "secret-value", "path": "/v1/messages"}


@pytest.mark.asyncio
async def test_judge_empty_object_is_rejected_not_accepted_as_low_confidence() -> None:
    """Regression test: a parseable-but-empty response must not become a silently
    'successful' INSUFFICIENT_INFORMATION/available=True assessment. It is a
    malformed provider response, distinguishing 'the provider responded' from
    'the provider gave a real assessment'.
    """

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}})

    judge = LiveJudgeProvider(
        "https://judge.example",
        "sonnet-test",
        "secret-value",
        protocol="anthropic_messages",
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(ProviderError) as error:
        await judge.assess("Find awards", Proposal.model_validate(proposal_payload()))
    assert error.value.code == "MALFORMED_PROVIDER_RESPONSE"
    assert judge.last_telemetry is not None
    assert judge.last_telemetry.error_code == "MALFORMED_PROVIDER_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_compatible", "anthropic_messages"])
async def test_judge_prompt_includes_wire_schema(protocol: str) -> None:
    """Both transports receive the complete, parseable wire schema in the system prompt."""
    from civicgate.llm.live import _JudgeSignalWire

    seen: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        content = '{"classification":"IN_SCOPE","confidence":0.9}'
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]}
            if protocol == "openai_compatible"
            else {"content": [{"type": "text", "text": content}]},
        )

    judge = LiveJudgeProvider(
        "https://judge.example",
        "gpt-test",
        "secret-value",
        protocol=protocol,
        transport=httpx.MockTransport(respond),
    )
    await judge.assess("Find awards", Proposal.model_validate(proposal_payload()))
    body = seen["body"]
    system_content = (
        body["messages"][0]["content"] if protocol == "openai_compatible" else body["system"]
    )
    assert system_content.startswith(JUDGE_SYSTEM_PROMPT)
    schema = json.loads(system_content[len(JUDGE_SYSTEM_PROMPT) :])
    assert schema == _JudgeSignalWire.model_json_schema()
    assert schema["required"] == ["classification", "confidence"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai_compatible", "anthropic_messages"])
@pytest.mark.parametrize("extra", [{"available": True}, {"provider": "model-claimed-provider"}])
async def test_judge_rejects_model_supplied_availability_and_provider(
    protocol: str, extra: dict[str, object]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"classification": "IN_SCOPE", "confidence": 0.9} | extra)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]}
            if protocol == "openai_compatible"
            else {"content": [{"type": "text", "text": content}]},
        )

    judge = LiveJudgeProvider(
        "https://judge.example",
        "judge-test",
        "synthetic-key",
        protocol=protocol,
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(ProviderError) as error:
        await judge.assess("Find awards", Proposal.model_validate(proposal_payload()))
    assert error.value.code == "MALFORMED_PROVIDER_RESPONSE"


@pytest.mark.asyncio
async def test_live_provider_rejects_malformed_output() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    planner = GranitePlanner(
        "http://localhost:1234/v1", "granite-test", transport=httpx.MockTransport(respond)
    )
    with pytest.raises(ProviderError) as error:
        await planner.propose("Find awards")
    assert error.value.code == "MALFORMED_PROVIDER_RESPONSE"
    assert planner.last_telemetry is not None
    assert planner.last_telemetry.error_code == "MALFORMED_PROVIDER_RESPONSE"
