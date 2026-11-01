"""Read-only reconciliation of one synthetic Gateway's backend primary capture.

The existing observer and audit identify the actual bound invocation. The older
dispatch/HTTP streams carry no request or observation IDs, so their attribution
uses that invocation's exact typed query, fixed adapter protocol and timestamps.
Those absent IDs are never invented. This is local evidence admission, not an
authority issuer, hostile-host authentication, or live backend verification.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from civicgate.adapters.usaspending import BASE_URL
from civicgate.governance.execution import OPERATION_SCOPE, ExecutionBinding
from civicgate.models.provenance import fingerprint
from civicgate.models.requests import TOOLS, Award, Recipient, Search
from evals.harness.evidence import canonical, sha256
from evals.harness.live_composition_v3 import _validate_observer_capture
from evals.harness.provider_response_admission_v2 import strict_json_loads

MAX_STREAM_BYTES = 4_000_000
MAX_STREAM_ROWS = 4097
_HASH = re.compile(r"[a-f0-9]{64}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("BACKEND_CAPTURE_" + reason)


def _read_stream(directory: Path, name: str) -> list[dict[str, Any]]:
    path = directory / name
    _require(path.is_file() and not path.is_symlink(), "STREAM_UNAVAILABLE")
    _require(path.stat().st_size <= MAX_STREAM_BYTES, "STREAM_TOO_LARGE")
    raw = path.read_bytes()
    _require(len(raw) <= MAX_STREAM_BYTES, "STREAM_TOO_LARGE")
    _require(not raw or raw.endswith(b"\n"), "STREAM_TRUNCATED")
    lines = raw.splitlines()
    _require(len(lines) <= MAX_STREAM_ROWS and all(lines), "STREAM_ROWS_INVALID")
    rows = [strict_json_loads(line) for line in lines]
    _require(all(type(row) is dict for row in rows), "STREAM_OBJECT_REQUIRED")
    return rows


def _timestamp(value: Any) -> datetime:
    _require(type(value) is str, "TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("BACKEND_CAPTURE_TIMESTAMP_INVALID") from None
    _require(parsed.utcoffset() == timedelta(0), "TIMESTAMP_INVALID")
    return parsed


def _duration(value: Any) -> None:
    _require(
        type(value) in {int, float} and math.isfinite(value) and value >= 0,
        "DURATION_INVALID",
    )


def _policy(value: Any) -> None:
    _require(
        type(value) is dict
        and set(value) == {"decision", "reasons"}
        and value["decision"] in {"DENY", "REVIEW_REQUIRED", "PERMIT"}
        and type(value["reasons"]) is list
        and all(type(reason) is str for reason in value["reasons"]),
        "POLICY_INVALID",
    )


def _expected_http(query: Search | Award | Recipient) -> tuple[str, str, Any]:
    """The original adapter's three fixed protocol shapes; no request is sent."""
    if isinstance(query, Search):
        filters: dict[str, Any] = {
            "time_period": [{"start_date": str(query.start_date), "end_date": str(query.end_date)}],
            "award_type_codes": query.award_types,
        }
        if query.recipient_name:
            filters["recipient_search_text"] = [query.recipient_name]
        if query.awarding_agency:
            filters["agencies"] = [
                {"type": "awarding", "tier": "toptier", "name": query.awarding_agency}
            ]
        if query.state_code:
            filters["place_of_performance_locations"] = [
                {"country": "USA", "state": query.state_code}
            ]
        return (
            "search",
            "/api/v2/search/spending_by_award/",
            {
                "filters": filters,
                "fields": [
                    "Award ID",
                    "Recipient Name",
                    "Award Amount",
                    "Awarding Agency",
                    "generated_internal_id",
                ],
                "page": 1,
                "limit": query.limit,
                "sort": "Award Amount",
                "order": "desc",
                "subawards": False,
            },
        )
    if isinstance(query, Award):
        return "detail", f"/api/v2/awards/{query.award_id}/", None
    return (
        "recipients",
        "/api/v2/recipient/",
        {
            "keyword": query.recipient_name,
            "limit": query.limit,
            "page": 1,
            "sort": "name",
            "order": "asc",
            "award_type": "all",
        },
    )


def _validate(
    directory: Path,
    observation_id: str,
    events: list[dict[str, Any]],
    expected_request: str | None,
    expected_tool: str | None,
    expected_arguments: dict[str, Any] | None,
    expected_request_id: str | None,
) -> dict[str, Any]:
    _require(directory.is_dir() and not directory.is_symlink(), "DIRECTORY_UNAVAILABLE")
    observed = _read_stream(directory, "governance-observations.jsonl")
    _require(observed == events, "OBSERVER_SNAPSHOT_MISMATCH")
    _validate_observer_capture(observed, observation_id)
    dispatch = _read_stream(directory, "dispatch.jsonl")
    backend = _read_stream(directory, "http-attempts.jsonl")
    components = _read_stream(directory, "components.jsonl")
    audit = _read_stream(directory, "audit.jsonl")
    result = {
        "state": "NO_GOVERNANCE_ACTIVITY",
        "request_id": None,
        "dispatch": dispatch,
        "backend": backend,
        "components": components,
        "audit": audit,
    }
    returns, seal = observed[:-1], observed[-1]
    seal_time = _timestamp(seal.get("timestamp_utc"))
    _require(seal.get("provenance") == "INSTRUMENT_OBSERVED", "OBSERVER_PROVENANCE_INVALID")
    _require(type(seal.get("coverage")) is dict, "OBSERVER_COVERAGE_INVALID")
    allowed_phases = {
        "policy_preflight",
        "policy_issuance",
        "binding_issue",
        "binding_consume",
        "policy_post_result",
    }
    for row in returns:
        _require(row.get("phase") in allowed_phases, "OBSERVER_PHASE_INVALID")
        _require(row.get("provenance") == "INSTRUMENT_OBSERVED", "OBSERVER_PROVENANCE_INVALID")
        _require(
            row.get("mechanism") == "CPYTHON_PROFILE_EXACT_SYNCHRONOUS_CODE_OBJECT",
            "OBSERVER_MECHANISM_INVALID",
        )
        _duration(row.get("elapsed_ms"))
    for phase in allowed_phases:
        count = sum(row["phase"] == phase for row in returns)
        captured_count = seal["coverage"].get(phase, 0)
        _require(
            type(captured_count) is int and captured_count == count, "OBSERVER_COVERAGE_MISMATCH"
        )
    if not returns:
        _require(not audit and not dispatch and not backend and not components, "UNBOUND_ACTIVITY")
        _require(expected_request_id is None, "REQUEST_ID_MISSING")
        return result

    request_ids = {row.get("request_id") for row in returns}
    _require(len(request_ids) == 1, "OBSERVER_REQUEST_ID_MISMATCH")
    request_id = next(iter(request_ids))
    _require(type(request_id) is str and 0 < len(request_id) <= 256, "REQUEST_ID_INVALID")
    _require(
        expected_request_id is None or request_id == expected_request_id, "REQUEST_ID_MISMATCH"
    )
    _require(all(row.get("request_id") == request_id for row in audit), "AUDIT_REQUEST_ID_MISMATCH")
    result["request_id"] = request_id
    stages = [row.get("stage") for row in audit]
    _require(
        stages
        in (
            ["proposal", "policy", "completed"],
            ["proposal", "policy", "execution_started", "completed"],
        ),
        "AUDIT_STAGES_INCOMPLETE",
    )
    times = [_timestamp(row.get("timestamp")) for row in audit]
    _require(times == sorted(times) and times[-1] <= seal_time, "AUDIT_TIMESTAMP_ORDER")
    proposal, policy_row, completed = audit[0], audit[1], audit[-1]
    invocation = proposal.get("proposal")
    _require(
        type(invocation) is dict and set(invocation) == {"tool", "arguments"}, "PROPOSAL_INVALID"
    )
    assert type(invocation) is dict  # Type narrowing after the retained runtime check.
    tool, arguments, request = (
        invocation["tool"],
        invocation["arguments"],
        proposal.get("user_request"),
    )
    _require(
        type(tool) is str and type(arguments) is dict and type(request) is str, "PROPOSAL_INVALID"
    )
    _require(expected_request is None or request == expected_request, "USER_REQUEST_MISMATCH")
    _require(expected_tool is None or tool == expected_tool, "TOOL_MISMATCH")
    try:
        query = TOOLS[tool].model_validate(arguments) if tool in TOOLS else None
    except ValidationError:
        # Invalid/unknown proposals can be legitimate pre-dispatch denials. They
        # cannot proceed through the bound-dispatch branch below.
        query = None
    effective = query.model_dump(mode="json") if query is not None else arguments
    _require(arguments == effective, "EFFECTIVE_ARGUMENTS_NOT_CAPTURED")
    if expected_arguments is not None:
        wanted = (
            TOOLS[tool].model_validate(expected_arguments).model_dump(mode="json")
            if query
            else expected_arguments
        )
        _require(effective == wanted, "EXPECTED_ARGUMENTS_MISMATCH")
    facts, policy = policy_row.get("facts"), policy_row.get("policy")
    _policy(policy)
    assert type(policy) is dict
    _require(
        type(facts) is dict and facts.get("tool") == tool and facts.get("request_text") == request,
        "POLICY_INVOCATION_MISMATCH",
    )
    assert type(facts) is dict
    if query is None:
        _require(facts.get("arguments_json") is None, "POLICY_ARGUMENTS_MISMATCH")
    else:
        _require(type(facts.get("arguments_json")) is str, "POLICY_ARGUMENTS_MISSING")
        _require(
            strict_json_loads(facts["arguments_json"]) == effective, "POLICY_ARGUMENTS_MISMATCH"
        )
    phases = {phase: [row for row in returns if row["phase"] == phase] for phase in allowed_phases}
    _require(
        all(
            len(phases[phase]) == 1
            for phase in ("policy_preflight", "policy_issuance", "binding_issue")
        ),
        "OBSERVER_REQUIRED_PHASE_MISSING_OR_DUPLICATED",
    )
    _require(
        len(phases["binding_consume"]) <= 1 and len(phases["policy_post_result"]) <= 1,
        "OBSERVER_PHASE_DUPLICATED",
    )
    for phase in ("policy_preflight", "policy_issuance", "policy_post_result"):
        for row in phases[phase]:
            _require(
                row.get("status") == "RETURNED_POLICY" and row.get("binding") is None,
                "OBSERVER_POLICY_RETURN_INVALID",
            )
            _policy(row.get("policy"))
    issuance, issued = phases["policy_issuance"][0], phases["binding_issue"][0]
    _require(
        issuance["policy"] == policy and issued.get("policy") == policy, "ISSUANCE_POLICY_MISMATCH"
    )
    _require(issued["call_index"] < issuance["call_index"], "ISSUANCE_CALL_ORDER")
    _require(
        phases["policy_preflight"][0]["call_index"] < issued["call_index"], "PREFLIGHT_CALL_ORDER"
    )
    response = completed.get("response")
    _require(
        type(response) is dict
        and response.get("request_id") == request_id
        and response.get("tool") == tool,
        "COMPLETED_INVOCATION_MISMATCH",
    )
    assert type(response) is dict
    _require(
        type(response.get("tool_executed")) is bool
        and completed.get("tool_executed") is response["tool_executed"],
        "COMPLETED_EXECUTION_MISMATCH",
    )
    _require(type(completed.get("attempts")) is list, "COMPLETED_ATTEMPTS_INVALID")

    if policy["decision"] != "PERMIT":
        _require(
            stages == ["proposal", "policy", "completed"]
            and not phases["binding_consume"]
            and not phases["policy_post_result"],
            "HELD_CAPTURE_CONTRADICTION",
        )
        _require(
            issued.get("status") == "NO_BINDING"
            and issued.get("binding") is None
            and policy_row.get("binding_issued") is False,
            "HELD_BINDING_CONTRADICTION",
        )
        _require(not dispatch and not backend and not components, "HELD_BACKEND_ACTIVITY")
        _require(
            response.get("decision") == policy["decision"]
            and response["tool_executed"] is False
            and response.get("dispatch_state") == "NOT_DISPATCHED"
            and response.get("attempt_count") == 0
            and completed["attempts"] == []
            and completed.get("pre_dispatch_verification") == "NOT_REQUIRED",
            "HELD_COMPLETION_CONTRADICTION",
        )
        result["state"] = "PRE_DISPATCH_HELD"
        return result

    _require(
        query is not None
        and len(phases["binding_consume"]) == 1
        and stages == ["proposal", "policy", "execution_started", "completed"],
        "BOUND_DISPATCH_CAPTURE_INCOMPLETE",
    )
    assert query is not None
    consumed, started = phases["binding_consume"][0], audit[2]
    binding = issued.get("binding")
    _require(
        issued.get("status") == "ISSUED"
        and consumed.get("status") == "VERIFIED_CONSUMED"
        and consumed.get("policy") is None
        and type(binding) is dict
        and consumed.get("binding") == binding
        and started.get("execution_binding") == binding
        and policy_row.get("binding_issued") is True,
        "BINDING_CAPTURE_MISMATCH",
    )
    assert type(binding) is dict
    _require(consumed["call_index"] > issuance["call_index"], "CONSUMPTION_CALL_ORDER")
    arguments_json = canonical(effective).decode("utf-8")
    binding_fields = {
        "request_id": request_id,
        "tool": tool,
        "arguments_sha256": sha256(canonical(effective)),
        "schema_sha256": sha256(canonical(TOOLS[tool].model_json_schema())),
        "operation_scope": OPERATION_SCOPE,
        "policy_decision": "PERMIT",
        "policy_sha256": sha256(canonical(policy)),
        "policy_facts_sha256": sha256(canonical(facts)),
    }
    _require(
        all(binding.get(key) == value for key, value in binding_fields.items()),
        "BINDING_IDENTITY_MISMATCH",
    )
    _require(
        type(binding.get("policy_context_sha256")) is str
        and _HASH.fullmatch(binding["policy_context_sha256"]) is not None,
        "BINDING_CONTEXT_HASH_INVALID",
    )
    expected_binding = ExecutionBinding(
        **binding_fields,
        arguments_json=arguments_json,
        policy_context_sha256=binding["policy_context_sha256"],
    ).audit_record()
    _require(binding == expected_binding, "BINDING_HASH_MISMATCH")
    _require(
        started.get("tool") == tool and started.get("execution_authority") == policy,
        "EXECUTION_AUDIT_MISMATCH",
    )
    _require(
        response["tool_executed"] is True and completed.get("pre_dispatch_verification") == "PASS",
        "BOUND_COMPLETION_CONTRADICTION",
    )
    _require(
        len(dispatch) == len(backend) == 1 and len(components) == 2, "BACKEND_CARDINALITY_MISMATCH"
    )
    entry, attempt = dispatch[0], backend[0]
    method, path, payload = _expected_http(query)
    http_method = "GET" if payload is None else "POST"
    # HTTPX is the original adapter's serializer, including UTF-8 and GET emptiness.
    expected_body_hash = sha256(httpx.Request(http_method, BASE_URL + path, json=payload).content)
    _require(
        set(entry) == {"timestamp_utc", "synthetic", "phase", "entry_index", "method", "query"}
        and entry.get("synthetic") is True
        and entry.get("phase") == "entered"
        and type(entry.get("entry_index")) is int
        and entry["entry_index"] == 1
        and entry.get("method") == method
        and entry.get("query") == effective,
        "DISPATCH_IDENTITY_MISMATCH",
    )
    _require(
        set(attempt)
        == {
            "timestamp_utc",
            "synthetic",
            "phase",
            "attempt_index",
            "method",
            "request_path",
            "request_body_sha256",
            "mode",
        }
        and attempt.get("synthetic") is True
        and attempt.get("phase") == "entered"
        and type(attempt.get("attempt_index")) is int
        and attempt["attempt_index"] == 1
        and attempt.get("method") == http_method
        and attempt.get("request_path") == path
        and attempt.get("request_body_sha256") == expected_body_hash,
        "HTTP_IDENTITY_MISMATCH",
    )
    http_finish, adapter_finish = components
    _require(
        set(http_finish)
        == {
            "timestamp_utc",
            "synthetic",
            "component",
            "phase",
            "attempt_index",
            "elapsed_ms",
            "status_code",
            "error_class",
            "mode",
        }
        and http_finish.get("component") == "synthetic_http"
        and http_finish.get("attempt_index") == 1
        and type(http_finish.get("attempt_index")) is int,
        "HTTP_FINISH_IDENTITY_MISMATCH",
    )
    _require(
        set(adapter_finish)
        == {
            "timestamp_utc",
            "synthetic",
            "component",
            "phase",
            "entry_index",
            "method",
            "elapsed_ms",
            "error_class",
            "mode",
        }
        and adapter_finish.get("component") == "adapter"
        and adapter_finish.get("entry_index") == 1
        and type(adapter_finish.get("entry_index")) is int
        and adapter_finish.get("method") == method,
        "ADAPTER_FINISH_IDENTITY_MISMATCH",
    )
    for row in components:
        _require(
            row.get("synthetic") is True
            and row.get("phase") == "finish"
            and row.get("mode") == attempt.get("mode")
            and (row.get("error_class") is None or type(row["error_class"]) is str),
            "COMPONENT_FINISH_MISMATCH",
        )
        _duration(row.get("elapsed_ms"))
    _require(
        attempt.get("mode")
        in {
            "normal",
            "malformed",
            "timeout",
            "output_injection",
            "audit_failure",
            "missing_provenance",
        },
        "BACKEND_MODE_INVALID",
    )
    sequence = [
        times[2],
        _timestamp(entry.get("timestamp_utc")),
        _timestamp(attempt.get("timestamp_utc")),
        _timestamp(http_finish.get("timestamp_utc")),
        _timestamp(adapter_finish.get("timestamp_utc")),
        times[-1],
        seal_time,
    ]
    _require(sequence == sorted(sequence), "BACKEND_TIMESTAMP_ORDER")
    attempts = completed["attempts"]
    _require(len(attempts) == 1 and type(attempts[0]) is dict, "AUDIT_ATTEMPT_INCOMPLETE")
    final_attempt = attempts[0]
    _require(
        type(final_attempt.get("attempt")) is int
        and final_attempt["attempt"] == 1
        and type(final_attempt.get("max_attempts")) is int
        and final_attempt["max_attempts"] == 1
        and final_attempt.get("status_code") == http_finish.get("status_code")
        and response.get("attempt_count") == 1
        and response.get("attempt_metadata_available") is True
        and completed.get("attempt_metadata_available") is True
        and response.get("dispatch_state") == final_attempt.get("dispatch_state")
        and response.get("response_state") == final_attempt.get("response_state"),
        "AUDIT_ATTEMPT_MISMATCH",
    )
    _duration(final_attempt.get("elapsed_ms"))
    _require(
        type(http_finish.get("status_code")) is int or http_finish.get("status_code") is None,
        "HTTP_STATUS_INVALID",
    )
    if http_finish["error_class"] is None:
        _require(
            http_finish["status_code"] == 200 and final_attempt.get("response_received") is True,
            "HTTP_COMPLETION_MISMATCH",
        )
    else:
        _require(
            final_attempt.get("exception_type") == http_finish["error_class"],
            "HTTP_EXCEPTION_MISMATCH",
        )
    provenance = response.get("provenance")
    if provenance is not None:
        expected_query_hash = fingerprint(
            {"method": http_method, "url": BASE_URL + path, "body": payload}
        )
        _require(
            type(provenance) is dict
            and provenance.get("query_fingerprint") == expected_query_hash
            and provenance.get("endpoint") == BASE_URL + path,
            "PROVENANCE_REQUEST_MISMATCH",
        )
    if phases["policy_post_result"]:
        post = phases["policy_post_result"][0]
        _require(
            post["call_index"] > consumed["call_index"]
            and post["policy"]["decision"] == response.get("decision"),
            "POST_RESULT_POLICY_MISMATCH",
        )
    else:
        _require(response.get("decision") == "PERMIT", "FINAL_POLICY_MISMATCH")
    result["state"] = "BOUND_BACKEND_CAPTURED"
    return result


def validate_backend_capture(
    directory: Path,
    observation_id: str,
    events: list[dict[str, Any]],
    *,
    expected_request: str | None = None,
    expected_tool: str | None = None,
    expected_arguments: dict[str, Any] | None = None,
    expected_request_id: str | None = None,
) -> dict[str, Any]:
    """Admit complete local captures or raise a payload-free ``ValueError``.

    Optional expected values are independently observed invocation constraints.
    A valid capture may describe failed validation or unknown execution results;
    this function never declares a safe completion or closes an observation.
    """
    try:
        return _validate(
            directory,
            observation_id,
            events,
            expected_request,
            expected_tool,
            expected_arguments,
            expected_request_id,
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
    ) as exc:
        if type(exc) is ValueError and str(exc).startswith("BACKEND_CAPTURE_"):
            raise
        raise ValueError("BACKEND_CAPTURE_INVALID_OR_UNAVAILABLE") from None
