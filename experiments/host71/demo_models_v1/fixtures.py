"""Explicit offline fixtures, never selected as fallback after a live failure."""

import json
from typing import Any

import httpx

from .contract import CASES, JUDGE, PLANNERS

FAKE_KEY = "synthetic-demo-credential-not-a-real-key-735192"


def planner_fixture(provider: str, case: str, fault: str = "none") -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        value = json.loads(request.content)
        assert value["messages"][-1]["content"] == CASES[case]["request"]
        proposal: dict[str, Any] = CASES[case]["proposal"]
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic transport error")
        if fault == "malformed":
            proposal = {"tool": "find_federal_awards", "arguments": {"limit": "wrong"}}
        if provider == "nemotron":
            assert "tools" in value and "response_format" not in value
            assert value["chat_template_kwargs"] == {"enable_thinking": False}
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "offline_1",
                        "type": "function",
                        "function": {
                            "name": proposal["tool"],
                            "arguments": json.dumps(proposal["arguments"]),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            assert value["response_format"] == {"type": "json_object"} and "tools" not in value
            message = {"role": "assistant", "content": json.dumps(proposal)}
            finish = "stop"
        return httpx.Response(
            200,
            json={
                "model": PLANNERS[provider],
                "choices": [{"message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 40},
            },
        )

    return httpx.MockTransport(respond)


def judge_fixture(fault: str = "none") -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == JUDGE and payload["max_completion_tokens"] == 512
        assert not {"temperature", "top_p", "max_tokens", "tools"} & set(payload)
        if fault == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        signal = {
            "classification": "IN_SCOPE",
            "confidence": 0.99,
            "flags": [],
            "rationale": "Offline fixture; not a real Luna assessment.",
        }
        if fault == "secret_echo":
            signal["rationale"] = FAKE_KEY
        return httpx.Response(
            200,
            json={
                "model": JUDGE,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(signal)},
                    }
                ],
                "usage": {"prompt_tokens": 300, "completion_tokens": 50},
            },
        )

    return httpx.MockTransport(respond)


def backend_response(malformed: bool = False) -> dict[str, Any]:
    if malformed:
        return {"results": "invalid", "page_metadata": {"hasNext": False}}
    return {
        "results": [
            {
                "internal_id": 1,
                "generated_internal_id": "SYNTHETIC_DEMO_1",
                "Award ID": "SYNTHETIC_DEMO_1",
                "Recipient Name": "Synthetic public recipient",
                "Award Amount": "1234.00",
                "Awarding Agency": "Synthetic agency",
            }
        ],
        "page_metadata": {"hasNext": False},
    }
