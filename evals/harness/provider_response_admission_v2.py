"""Strict synthetic chat-response contract, separate from HTTP delivery and authority.

These completion/usage requirements are a proposed evaluation admission contract.
They are not observations of a real provider, authenticated identities, billable
token ceilings, prices, or semantic-quality judgments.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import ValidationError

from civicgate.llm.live import _JudgeSignalWire
from civicgate.models.requests import Proposal


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _nonfinite(_value: str) -> Any:
    raise ValueError("NONFINITE_JSON_NUMBER")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("NONFINITE_JSON_NUMBER")
    return number


def strict_json_loads(raw: str | bytes) -> Any:
    """Decode unambiguous finite JSON without changing ordinary numeric values.

    ``parse_constant`` alone misses valid JSON exponents that overflow Python's
    float representation. Check float conversion and every decoded container;
    use an explicit stack so this check adds no recursive traversal limit.
    A decoder nesting overflow is a structured parse failure for every caller.
    """
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_object,
            parse_constant=_nonfinite,
            parse_float=_finite_float,
        )
    except RecursionError:
        raise ValueError("JSON_NESTING_EXCEEDS_DECODER_LIMIT") from None
    pending = [value]
    while pending:
        item = pending.pop()
        if type(item) is float and not math.isfinite(item):
            raise ValueError("NONFINITE_JSON_NUMBER")
        if type(item) is dict:
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
    return value


def evaluate_response(
    status_code: int, raw: bytes, *, requested_model: str, role: str
) -> dict[str, Any]:
    """Return bounded documentary facts; never turn an HTTP response into authority."""
    if role not in {"planner", "judge"} or type(raw) is not bytes:
        raise ValueError("PINNED_ROLE_AND_RESPONSE_BYTES_REQUIRED")
    facts: dict[str, Any] = {
        "http_status": status_code,
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "body_bytes": len(raw),
        "returned_model": None,
        "model_identity": "MISSING",
        "completion": "UNKNOWN",
        "refusal": "UNKNOWN",
        "usage": "UNKNOWN",
        "typed_schema": "NOT_PARSED",
        "contract": "FAIL",
        "errors": [],
    }
    errors: list[str] = facts["errors"]
    if type(status_code) is not int or not 200 <= status_code < 300:
        errors.append("HTTP_STATUS_NOT_SUCCESS")
    if len(raw) > 200_000:
        errors.append("RESPONSE_BODY_LIMIT")
        return facts
    try:
        body = strict_json_loads(raw)
    except (ValueError, UnicodeError):
        errors.append("INVALID_OR_AMBIGUOUS_RESPONSE_JSON")
        return facts
    if type(body) is not dict:
        errors.append("RESPONSE_OBJECT_REQUIRED")
        return facts
    returned = body.get("model")
    if type(returned) is str and 1 <= len(returned) <= 120:
        facts["returned_model"] = returned
        facts["model_identity"] = "MATCH" if returned == requested_model else "MISMATCH"
    elif returned is not None:
        facts["model_identity"] = "MALFORMED"
    if facts["model_identity"] != "MATCH":
        errors.append("REQUESTED_RETURNED_MODEL_NOT_MATCHED")
    usage = body.get("usage")
    if type(usage) is dict:
        names = ("prompt_tokens", "completion_tokens", "total_tokens")
        if all(type(usage.get(key)) is int and usage[key] >= 0 for key in names) and (
            usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"]
        ):
            facts["usage"] = "KNOWN"
        else:
            facts["usage"] = "INVALID"
    if facts["usage"] != "KNOWN":
        errors.append("USAGE_UNAVAILABLE_OR_INCONSISTENT")
    choices = body.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        errors.append("EXACTLY_ONE_CHOICE_REQUIRED")
        return facts
    choice = choices[0]
    facts["completion"] = "COMPLETE" if choice.get("finish_reason") == "stop" else "INCOMPLETE"
    if facts["completion"] != "COMPLETE":
        errors.append("TERMINAL_COMPLETION_NOT_ESTABLISHED")
    message = choice.get("message")
    if type(message) is not dict:
        errors.append("MESSAGE_OBJECT_REQUIRED")
        return facts
    refusal = message.get("refusal")
    facts["refusal"] = "ABSENT_OR_NULL" if refusal is None else "PRESENT"
    if refusal is not None:
        errors.append("REFUSAL_OR_UNSUPPORTED_REFUSAL_VALUE")
    if "tool_calls" in message or "function_call" in message:
        errors.append("UNSUPPORTED_RESPONSE_ACTION")
    content = message.get("content")
    try:
        if type(content) is not str or not content or len(content) > 200_000:
            raise ValueError("TYPED_CONTENT_REQUIRED")
        typed = strict_json_loads(content)
        schema = Proposal if role == "planner" else _JudgeSignalWire
        schema.model_validate(typed)
    except (ValueError, TypeError, ValidationError, RecursionError):
        facts["typed_schema"] = "FAIL"
        errors.append("TYPED_RESPONSE_SCHEMA_REJECTED")
    else:
        facts["typed_schema"] = "PASS"
    if not errors:
        facts["contract"] = "PASS"
    return facts
