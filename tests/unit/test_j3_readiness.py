"""Offline provider readiness; passing does not certify live interoperability.

Regression coverage for the previously observed J3 compatibility gaps.
No credentials, provider discovery requests or real HTTP transports are used.
"""

import json

import httpx
import pytest

from civicgate.llm.live import LiveJudgeProvider, ProviderError
from civicgate.models.requests import Proposal
from scripts import run_live_judge_benchmark as j2

REQUEST = "Find public awards in Puerto Rico."
PROPOSAL = Proposal(
    tool="find_federal_awards",
    arguments={"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"},
)
WIRE = {"classification": "IN_SCOPE", "confidence": 0.96, "flags": ["NONE"]}


def response_body(wire=WIRE, *, stop="end_turn"):
    return {
        "model": "claude-sonnet-5",
        "content": [{"type": "text", "text": json.dumps(wire)}],
        "stop_reason": stop,
        "usage": {"input_tokens": 31, "output_tokens": 17},
    }


def judge(handler, *, base_url="https://api.anthropic.com"):
    provider = LiveJudgeProvider(
        base_url,
        "claude-sonnet-5",
        "synthetic-credential",
        protocol="anthropic_messages",
        provider_name="anthropic",
        transport=httpx.MockTransport(handler),
    )
    provider.client.max_attempts = 1
    return provider


@pytest.mark.asyncio
async def test_anthropic_real_adapter_payload_and_exact_signal_fields():
    seen = []

    def respond(request):
        seen.append(request)
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.method == "POST"
        assert request.headers["x-api-key"] == "synthetic-credential"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["content-type"] == "application/json"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == {
            "model": "claude-sonnet-5",
            "max_tokens": 512,
            "system": j2._prompt(),
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {"request": REQUEST, "proposal": PROPOSAL.model_dump()}, sort_keys=True
                    ),
                }
            ],
        }
        return httpx.Response(200, json=response_body())

    provider = judge(respond)
    signal = await provider.assess(REQUEST, PROPOSAL)
    assert signal.model_dump(exclude={"rationale"}) == {
        **WIRE,
        "available": True,
        "provider": "anthropic",
    }
    assert len(seen) == 1
    assert provider.last_telemetry.prompt_tokens == 31
    assert provider.last_telemetry.completion_tokens == 17


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wire",
    [
        {},
        {"confidence": 0.96},
        {"classification": "IN_SCOPE"},
        WIRE | {"available": True},
        WIRE | {"provider": "model-claimed"},
        WIRE | {"decision": "PERMIT"},
        WIRE | {"authority_source": "MODEL"},
        WIRE | {"confidence": 1.1},
        WIRE | {"classification": "PERMIT"},
        WIRE | {"flags": ["INVENTED_FLAG"]},
    ],
)
async def test_anthropic_required_fields_and_internal_authority_boundary(wire):
    provider = judge(lambda _: httpx.Response(200, json=response_body(wire)))
    with pytest.raises(ProviderError, match="required schema") as error:
        await provider.assess(REQUEST, PROPOSAL)
    assert error.value.code == "MALFORMED_PROVIDER_RESPONSE"
    assert provider.last_telemetry.error_code == error.value.code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content", [[], [{"type": "text", "text": ""}], [{"type": "text", "text": "not JSON"}]]
)
async def test_anthropic_empty_or_malformed_content_cannot_be_an_assessment(content):
    provider = judge(lambda _: httpx.Response(200, json=response_body() | {"content": content}))
    with pytest.raises(ProviderError) as error:
        await provider.assess(REQUEST, PROPOSAL)
    assert error.value.code == "MALFORMED_PROVIDER_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize("types", [["thinking"], ["thinking", "redacted_thinking", "reasoning"]])
async def test_sonnet_selects_text_after_nontext_without_exposing_thinking(types):
    body = response_body()
    body["content"] = [
        {"type": kind, "thinking": "SYNTHETIC_PRIVATE_THINKING"} for kind in types
    ] + body["content"]
    provider = judge(lambda _: httpx.Response(200, json=body))
    signal = await provider.assess(REQUEST, PROPOSAL)
    assert signal.model_dump(exclude={"rationale"}) == WIRE | {
        "available": True,
        "provider": "anthropic",
    }
    assert "SYNTHETIC_PRIVATE_THINKING" not in signal.model_dump_json()
    assert "SYNTHETIC_PRIVATE_THINKING" not in json.dumps(provider.last_telemetry.as_dict())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop", "code"),
    [
        ("max_tokens", "PROVIDER_RESPONSE_INCOMPLETE"),
        ("refusal", "PROVIDER_REFUSAL"),
        (None, "MALFORMED_PROVIDER_RESPONSE"),
        ("stop", "MALFORMED_PROVIDER_RESPONSE"),
        ("tool_use", "MALFORMED_PROVIDER_RESPONSE"),
        ("pause_turn", "MALFORMED_PROVIDER_RESPONSE"),
    ],
)
async def test_sonnet_requires_completed_nonrefused_end_turn(stop, code):
    """A valid JSON body is not proof of complete/non-refused interoperability."""
    provider = judge(lambda _: httpx.Response(200, json=response_body(stop=stop)))
    with pytest.raises(ProviderError) as error:
        await provider.assess(REQUEST, PROPOSAL)
    assert error.value.code == code
    assert provider.last_telemetry.error_code == code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "PROVIDER_HTTP_ERROR"),
        (401, "PROVIDER_HTTP_ERROR"),
        (429, "PROVIDER_UNAVAILABLE"),
        (500, "PROVIDER_UNAVAILABLE"),
    ],
)
async def test_anthropic_errors_explicit_with_one_attempt_and_no_protocol_fallback(status, code):
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(status, json={"error": {"type": "synthetic_error"}})

    provider = judge(respond)
    with pytest.raises(ProviderError) as error:
        await provider.assess(REQUEST, PROPOSAL)
    assert error.value.code == code
    assert calls == ["https://api.anthropic.com/v1/messages"]


@pytest.mark.asyncio
async def test_luna_payload_still_exact_frozen_j2_profile():
    case = {"request": REQUEST, "tool": PROPOSAL.tool, "arguments": PROPOSAL.arguments}

    def respond(request):
        assert str(request.url) == j2.ENDPOINT
        assert json.loads(request.content) == j2._payload(case)
        assert "x-api-key" not in request.headers
        assert "anthropic-version" not in request.headers
        assert request.headers["authorization"] == "Bearer synthetic-credential"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(WIRE)}}]})

    provider = LiveJudgeProvider(
        j2.BASE_URL, j2.MODEL, "synthetic-credential", transport=httpx.MockTransport(respond)
    )
    await provider.assess(REQUEST, PROPOSAL)


def test_neutral_observer_retains_anthropic_names_and_exposed_usage():
    metadata = j2.observe_judge_response(
        httpx.Response(200, headers={"request-id": "synthetic-request"}, json=response_body()),
        "synthetic-credential",
        protocol="anthropic_messages",
        requested_model="claude-sonnet-5",
    )
    assert metadata["http_status"] == 200
    assert metadata["returned_model"] == "claude-sonnet-5"
    assert metadata["request_id"] == "synthetic-request"
    assert metadata["requested_model"] == "claude-sonnet-5"
    assert metadata["finish_reason"] is None
    assert metadata["stop_reason"] == metadata["finish_or_stop_reason"] == "end_turn"
    assert metadata["input_tokens"] == 31 and metadata["output_tokens"] == 17
    assert metadata["total_tokens"] is metadata["reasoning_tokens"] is None
    assert metadata["wire_validation"] == metadata["response_validation"] == "PASS"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        None,
        {},
        "not a list",
        [None],
        [{"type": "thinking", "thinking": "ignored"}],
        [{"type": "text", "text": 3}],
        [
            {"type": "text", "text": "{"},
            {"type": "text", "text": '"classification":"IN_SCOPE","confidence":0.96}'},
        ],
        [{"type": "text", "text": json.dumps(WIRE)}] * 2,
    ],
)
async def test_malformed_or_multiple_text_blocks_are_not_repaired(content):
    provider = judge(lambda _: httpx.Response(200, json=response_body() | {"content": content}))
    with pytest.raises(ProviderError) as error:
        await provider.assess(REQUEST, PROPOSAL)
    assert error.value.code == "MALFORMED_PROVIDER_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("https://api.anthropic.com", "another-anthropic-model"),
        ("https://proxy.example", "claude-sonnet-5"),
    ],
)
async def test_sonnet_sampling_and_stop_changes_do_not_apply_outside_exact_profile(base_url, model):
    def respond(request):
        payload = json.loads(request.content)
        assert payload["temperature"] == 0 and payload["max_tokens"] == 512
        assert "top_p" not in payload and "top_k" not in payload
        assert "thinking" not in payload and "output_config" not in payload
        return httpx.Response(200, json=response_body(stop=None))

    provider = LiveJudgeProvider(
        base_url,
        model,
        "synthetic-credential",
        protocol="anthropic_messages",
        transport=httpx.MockTransport(respond),
    )
    assert (await provider.assess(REQUEST, PROPOSAL)).available


@pytest.mark.parametrize(
    ("stop", "code"),
    [
        ("max_tokens", "PROVIDER_RESPONSE_INCOMPLETE"),
        ("refusal", "PROVIDER_REFUSAL"),
        (None, "MALFORMED_PROVIDER_RESPONSE"),
        ("tool_use", "MALFORMED_PROVIDER_RESPONSE"),
    ],
)
def test_neutral_observer_never_accepts_incomplete_or_refused_sonnet(stop, code):
    meta = j2.observe_judge_response(
        httpx.Response(200, json=response_body(stop=stop)),
        "synthetic-credential",
        protocol="anthropic_messages",
        requested_model="claude-sonnet-5",
    )
    assert meta["response_validation"] == "FAIL"
    assert meta["wire_validation"] == "NOT_EVALUABLE"
    assert meta["response_error_code"] == code
    assert meta["finish_or_stop_reason"] == stop


@pytest.mark.parametrize(
    "body",
    [
        response_body({}),
        response_body() | {"content": []},
        response_body() | {"content": [{"type": "text", "text": "not-json"}]},
        response_body()
        | {"content": [{"type": "thinking", "thinking": "SYNTHETIC_PRIVATE_THINKING"}]},
    ],
)
def test_neutral_observer_rejects_invalid_text_without_storing_provider_content(body):
    meta = j2.observe_judge_response(
        httpx.Response(200, json=body),
        "synthetic-credential",
        protocol="anthropic_messages",
        requested_model="claude-sonnet-5",
    )
    assert meta["response_validation"] == "FAIL"
    assert meta["wire_validation"] != "PASS"
    assert "SYNTHETIC_PRIVATE_THINKING" not in json.dumps(meta)
    assert "content" not in meta and "body" not in meta and "headers" not in meta


def test_neutral_observer_missing_metadata_is_null_and_error_fields_are_sanitized():
    meta = j2.observe_judge_response(
        httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "code": "synthetic-credential",
                    "param": "max_tokens",
                    "message": "must not be retained",
                }
            },
        ),
        "different-synthetic-secret",
        protocol="anthropic_messages",
        requested_model=None,
    )
    assert meta["error_type"] == "invalid_request_error" and meta["error_param"] == "max_tokens"
    assert meta["requested_model"] is meta["returned_model"] is meta["input_tokens"] is None
    assert meta["output_tokens"] is meta["request_id"] is None
    assert "must not be retained" not in json.dumps(meta)
    with pytest.raises(j2.BenchmarkAbort, match="SECRET_IN_METADATA"):
        j2.observe_judge_response(
            httpx.Response(400, json={"error": {"param": "synthetic-secret"}}),
            "synthetic-secret",
            protocol="anthropic_messages",
            requested_model=None,
        )


def test_neutral_openai_observation_preserves_legacy_evidence_shape():
    response = httpx.Response(
        200,
        headers={"x-request-id": "synthetic-request"},
        json={
            "model": "returned-openai-model",
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(WIRE)}}],
            "usage": {"prompt_tokens": 31, "completion_tokens": 17, "total_tokens": 48},
        },
    )
    neutral = j2.observe_judge_response(
        response,
        "synthetic-credential",
        protocol="openai_compatible",
        requested_model="gpt-5.6-luna",
    )
    assert neutral["finish_reason"] == neutral["finish_or_stop_reason"] == "stop"
    assert neutral["stop_reason"] is None and neutral["response_validation"] == "PASS"
    assert neutral["requested_model"] != neutral["returned_model"]
    legacy = j2._response_metadata(response, "synthetic-credential")
    assert legacy == j2._openai_response_metadata(response, "synthetic-credential")
    assert all(neutral[k] == v for k, v in legacy.items())
