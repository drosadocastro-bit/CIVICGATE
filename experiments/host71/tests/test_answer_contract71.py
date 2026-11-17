"""No transport or host runtime imports: pure request/response fixtures."""

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "chat_v3" / "answer_contract71.py"
spec = importlib.util.spec_from_file_location("answer_contract71_under_test", MODULE)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


@pytest.fixture
def payload():
    return {
        "question": c.u_QUESTION,
        "records": [
            {
                "record_id": f"R{i}",
                "award_id": f"AWARD_{i}",
                "recipient_name": f"CONTRACTOR {i}",
                "award_amount": f"{i}00.00",
                "awarding_agency": "Department of Defense",
            }
            for i in range(1, 6)
        ],
    }


def envelope(payload):
    claims = [
        {
            "id": f"C{i}",
            "text": f"For {r['award_id']}, the page lists {r['recipient_name']}; recorded Award Amount {r['award_amount']}, agency {r['awarding_agency']}.",
            "citations": [
                {"record_id": r["record_id"], "field": field, "value": r[field]}
                for field in c.FIELDS
            ],
        }
        for i, r in enumerate(payload["records"], 1)
    ]
    return {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 1,
        "model": c.MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "logprobs": None,
                "message": {
                    "role": "assistant",
                    "content": c.canonical({"claims": claims}).decode(),
                    "refusal": None,
                    "tool_calls": None,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


def test_request_contract(payload):
    body = c.body(payload)
    assert body["model"] == c.MODEL
    assert body["max_tokens"] == 2000 and body["reasoning_budget"] == 256
    assert body["stream"] is False and body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "tools" not in body and "tool_choice" not in body
    wire = c.parse(body["messages"][1]["content"])
    assert wire["record_facts"] == payload["records"]
    assert wire["query_filter"]["classification"] == "SEARCH_CONTEXT_NOT_AWARD_EVIDENCE"
    assert set(wire) == {"record_facts", "query_filter", "scope"}


def test_valid_draft_is_not_certified(payload):
    result = c.validate(c.canonical(envelope(payload)), payload)
    assert result["status"] == "REVIEW_REQUIRED", result
    assert len(result["claims"]) == 5
    assert all(len(claim["citations"]) == 4 for claim in result["claims"])
    for key in (
        "approved",
        "live_allowed",
        "release_allowed",
        "publication_allowed",
        "verified_answer",
        "retry_allowed",
    ):
        assert result[key] is False
    assert result["semantic_status"] == "NOT_VERIFIED"
    assert result["usage"]["billing_verified"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "model",
        "length",
        "tool",
        "usage",
        "bad_cite",
        "missing_cite",
        "date",
        "place",
        "extra",
        "cross_record",
        "bad_number",
        "duplicate_key",
        "invalid",
        "empty",
        "oversize",
    ],
)
def test_negative_responses_fail_closed(payload, fault):
    env = envelope(payload)
    claims = c.parse(env["choices"][0]["message"]["content"])["claims"]
    if fault == "model":
        env["model"] = "other"
    elif fault == "length":
        env["choices"][0]["finish_reason"] = "length"
    elif fault == "tool":
        env["choices"][0]["message"]["tool_calls"] = [{"name": "write"}]
    elif fault == "usage":
        env["usage"]["prompt_tokens_details"]["cached_tokens"] = 101
    elif fault == "bad_cite":
        claims[0]["citations"][0]["value"] = "invented"
    elif fault == "missing_cite":
        claims[0]["citations"].pop()
    elif fault == "date":
        claims[0]["text"] += " In 2026."
    elif fault == "place":
        claims[0]["text"] += " In Puerto Rico."
    elif fault == "extra":
        claims[0]["extra"] = True
    elif fault == "cross_record":
        claims[0]["citations"][0] = claims[1]["citations"][0]
    elif fault == "bad_number":
        claims[0]["text"] += " 9999."
    env["choices"][0]["message"]["content"] = c.canonical({"claims": claims}).decode()
    if fault == "duplicate_key":
        env["choices"][0]["message"]["content"] = '{"claims":[],"claims":[]}'
    raw = c.canonical(env)
    if fault == "invalid":
        raw = b"not-json"
    if fault == "empty":
        raw = b""
    if fault == "oversize":
        raw = b" " * (c.MAX_BYTES + 1)
    assert c.validate(raw, payload)["status"] == "WITHHELD"


def test_missing_usage_not_inferred(payload):
    env = envelope(payload)
    del env["usage"]
    result = c.validate(c.canonical(env), payload)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["usage"]["status"] == "UNKNOWN_NOT_INFERRED"


def test_duplicate_outer_key(payload):
    raw = c.canonical(envelope(payload))
    raw = b'{"choices":[],' + raw[1:]
    assert c.validate(raw, payload)["status"] == "WITHHELD"


def test_wrong_question_has_no_request(payload):
    payload["question"] = "other question"
    with pytest.raises(ValueError):
        c.body(payload)


# Shared public fixture builder for transport-mocked integration tests.
fixture_envelope = envelope
