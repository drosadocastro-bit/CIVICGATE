"""Explicit mock responses for a new chat demonstration, not model accuracy."""

import json
from typing import Any

import httpx
from demo_models_v1.contract import PLANNERS


def planner_response(
    provider: str, question: str, proposal: dict[str, Any], fault: str = "none"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if payload["messages"][-1]["content"] != question:
            raise ValueError("ORIGINAL_REQUEST_CHANGED")
        if fault == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC_TIMEOUT")
        value = (
            proposal
            if fault != "malformed"
            else {"tool": "find_federal_awards", "arguments": {"limit": "wrong"}}
        )
        if provider == "nemotron":
            if "response_format" in payload or not payload.get("tools"):
                raise ValueError("NATIVE_TOOL_CONTRACT_REQUIRED")
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "offline_chat_1",
                        "type": "function",
                        "function": {
                            "name": value["tool"],
                            "arguments": json.dumps(value["arguments"]),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            if payload.get("response_format") != {"type": "json_object"}:
                raise ValueError("GRANITE_JSON_CONTRACT_REQUIRED")
            message = {"role": "assistant", "content": json.dumps(value)}
            finish = "stop"
        return httpx.Response(
            200,
            json={
                "model": "wrong-model" if fault == "model" else PLANNERS[provider],
                "choices": [{"message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 40},
            },
        )

    return httpx.MockTransport(handler)


def public_judge_fixture(fault):
    from demo_models_v1.fixtures import judge_fixture

    base = judge_fixture("none")

    def reply(request):
        response = base.handle_request(request)
        data = json.loads(response.content)
        signal = json.loads(data["choices"][0]["message"]["content"])
        signal["classification"] = "AMBIGUOUS" if fault == "public_review" else "OUT_OF_SCOPE"
        data["choices"][0]["message"]["content"] = json.dumps(signal)
        return httpx.Response(200, json=data)

    return httpx.MockTransport(reply)
