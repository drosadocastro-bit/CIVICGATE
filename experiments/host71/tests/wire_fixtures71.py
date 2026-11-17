from chat_v3 import answer_contract71 as c


def fixture_envelope(payload):
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
