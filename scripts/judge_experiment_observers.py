"""Bounded provider-native observations; never repair or infer a semantic signal."""

import json

from pydantic import TypeAdapter, ValidationError

from civicgate.llm.live import _JudgeSignalWire
from scripts import diagnose_j3_run001_failures as diagnostic
from scripts import run_j3_amendment_001 as historical

engine = historical.parent.engine


def observe_wire(text, secret):
    """Same structural evidence contract as J3-AMEND-001, after native completion."""
    result = {
        "json_parseable": None,
        "parsed_json_type": None,
        "top_level_fields": None,
        "field_types": None,
        "field_count": None,
        "metadata_truncated": False,
        "validation_errors": [],
        "validation_error_count": None,
        "wire_validation": "NOT_EVALUABLE",
        "extraction_error_code": None,
        "schema_valid_semantic_fields": None,
        "rationale_length": None,
        "unvalidated_wire_semantic_fields": None,
    }
    if text is None:
        return result
    try:
        parsed = json.loads(text)
    except ValueError:
        result.update(json_parseable=False, wire_validation="FAIL")
        return result
    result.update(json_parseable=True, parsed_json_type=type(parsed).__name__)
    if isinstance(parsed, dict):
        items = list(parsed.items())[:64]
        result.update(
            top_level_fields=[diagnostic.safe_name(k, secret) for k, _ in items],
            field_types=[
                {"field": diagnostic.safe_name(k, secret), "type": type(v).__name__}
                for k, v in items
            ],
            field_count=len(parsed),
            metadata_truncated=len(parsed) > 64,
            rationale_length=len(parsed["rationale"])
            if isinstance(parsed.get("rationale"), str)
            else None,
        )
    try:
        wire = _JudgeSignalWire.model_validate(parsed)
    except ValidationError as error:
        errors = error.errors(include_input=False, include_context=False, include_url=False)
        result.update(
            wire_validation="FAIL",
            validation_error_count=len(errors),
            metadata_truncated=result["metadata_truncated"] or len(errors) > 64,
            validation_errors=[
                {
                    "loc": [
                        v if type(v) is int else diagnostic.safe_name(v, secret) for v in e["loc"]
                    ],
                    "type": diagnostic.safe_name(e["type"], secret),
                    "message_code": diagnostic.safe_name(e["type"], secret),
                }
                for e in errors[:64]
            ],
        )
        if isinstance(parsed, dict):
            fields, invalid = {}, []
            for name in ("classification", "confidence", "flags"):
                if name not in parsed:
                    continue
                field = _JudgeSignalWire.model_fields[name]
                adapter = TypeAdapter(
                    field.rebuild_annotation(), config=_JudgeSignalWire.model_config
                )
                try:
                    fields[name] = adapter.validate_python(parsed[name])
                except ValidationError:
                    invalid.append(name)
            result["unvalidated_wire_semantic_fields"] = {
                "label": "UNVALIDATED_WIRE_SEMANTIC_FIELDS",
                "limitations": ["EXPLORATORY", "NON-AUTHORITATIVE", "NOT A JUDGESIGNAL"],
                "fields": fields,
                "invalid_individual_fields": invalid,
            }
    else:
        result.update(
            wire_validation="PASS",
            validation_error_count=0,
            schema_valid_semantic_fields=diagnostic.sanitized_signal(wire, secret),
        )
    return result


class AnthropicObserver:
    def observe(self, response, secret, profile):
        metadata = engine.observe_judge_response(
            response, secret, protocol=profile.protocol, requested_model=profile.model
        )
        structural = historical.structural_evidence(response, secret)
        native = metadata.get("stop_reason")
        state = {"end_turn": "COMPLETE", "max_tokens": "INCOMPLETE", "refusal": "REFUSED"}.get(
            native, "UNKNOWN"
        )
        return metadata, structural, state


class OpenAIObserver:
    def observe(self, response, secret, profile):
        metadata = {
            "http_status": response.status_code,
            "request_id": engine._safe_text(response.headers.get("x-request-id"), secret),
            "returned_model": None,
            "finish_reason": None,
            "content_present": None,
            "refusal_present": None,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "reasoning_tokens": None,
            "error_type": None,
            "error_code": None,
            "error_param": None,
        }
        structural = observe_wire(None, secret)
        state = "UNKNOWN"
        try:
            body = response.json()
        except ValueError:
            structural["extraction_error_code"] = "PROVIDER_BODY_NOT_JSON"
            body = None
        if isinstance(body, dict):
            metadata["returned_model"] = engine._safe_text(body.get("model"), secret)
            usage = body.get("usage")
            if isinstance(usage, dict):
                for native, normalized in (
                    ("prompt_tokens", "input_tokens"),
                    ("completion_tokens", "output_tokens"),
                    ("total_tokens", "total_tokens"),
                ):
                    metadata[normalized] = engine._number(usage.get(native))
                details = usage.get("completion_tokens_details")
                if isinstance(details, dict):
                    metadata["reasoning_tokens"] = engine._number(details.get("reasoning_tokens"))
            error = body.get("error")
            if isinstance(error, dict):
                for field in ("type", "code", "param"):
                    metadata["error_" + field] = engine._safe_text(error.get(field), secret)
            choices = body.get("choices")
            if response.status_code < 400 and isinstance(choices, list) and choices:
                choice = choices[0]
                if isinstance(choice, dict):
                    native = engine._safe_text(choice.get("finish_reason"), secret)
                    metadata["finish_reason"] = native
                    message = choice.get("message")
                    if isinstance(message, dict):
                        text = message.get("content")
                        refusal = bool(message.get("refusal")) or native == "content_filter"
                        metadata.update(
                            content_present=isinstance(text, str) and bool(text),
                            refusal_present=refusal,
                        )
                        # Length has precedence as in the historical max_tokens path.
                        state = (
                            "INCOMPLETE"
                            if native == "length"
                            else "REFUSED"
                            if refusal
                            else "COMPLETE"
                            if native == "stop"
                            else "UNKNOWN"
                        )
                        if state == "COMPLETE" and isinstance(text, str):
                            structural = observe_wire(text, secret)
        elif body is not None:
            structural["extraction_error_code"] = "PROVIDER_BODY_NOT_OBJECT"
        if structural["wire_validation"] == "NOT_EVALUABLE":
            structural["extraction_error_code"] = structural["extraction_error_code"] or {
                "INCOMPLETE": "PROVIDER_RESPONSE_INCOMPLETE",
                "REFUSED": "PROVIDER_REFUSAL",
            }.get(state, "MALFORMED_PROVIDER_RESPONSE")
        metadata.update(
            json_parseable=structural["json_parseable"],
            wire_validation=structural["wire_validation"],
        )
        return metadata, structural, state


def observer_for(profile):
    return AnthropicObserver() if profile.protocol == "anthropic_messages" else OpenAIObserver()
