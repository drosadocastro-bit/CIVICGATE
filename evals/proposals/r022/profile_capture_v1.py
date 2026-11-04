"""Read-only reconciliation for the new profile; never relaxes R3.2 admission.

This validates observed channels under trusted local instrumentation. Hashes and
matching logs do not authenticate a hostile host or independently prove intent.
Legacy captures are delegated to the unchanged historical validator.
"""

from __future__ import annotations

import re
from pathlib import Path

from civicgate.channel_b.faa_money_v1 import response_fingerprint
from civicgate.channel_b.faa_profile_v1 import parse_response_bytes
from civicgate.governance.execution import OPERATION_SCOPE, ExecutionBinding
from civicgate.models.requests import TOOLS, Proposal
from civicgate.models.responses import Envelope
from evals.harness.backend_capture_admission_v3 import (
    _duration,
    _policy,
    _read_stream,
    _terminal_shape,
    _timestamp,
    validate_backend_capture,
)
from evals.harness.evidence import canonical, sha256
from evals.harness.live_composition_v3 import _validate_observer_capture
from evals.harness.provider_response_admission_v2 import strict_json_loads
from evals.proposals.r022.faa_adapter_v1 import MAX_BYTES, validate_page
from evals.proposals.r022.faa_contract_v1 import FAA_FY2026_PR_CONTRACT, FaaFy2026PrReadV1

_HASH = re.compile(r"[a-f0-9]{64}")
PHASES = {
    "policy_preflight",
    "policy_issuance",
    "binding_issue",
    "binding_consume",
    "policy_post_result",
}


def _require(condition, reason):
    if not condition:
        raise ValueError("R022_CAPTURE_" + reason)


def _observer(events):
    _require(bool(events), "OBSERVER_MISSING")
    correlation = events[-1].get("correlation_id")
    _require(type(correlation) is str and 0 < len(correlation) <= 256, "CORRELATION_INVALID")
    _validate_observer_capture(events, correlation)
    seal, returned = events[-1], events[:-1]
    _require(seal.get("provenance") == "INSTRUMENT_OBSERVED", "OBSERVER_PROVENANCE_INVALID")
    _require(type(seal.get("coverage")) is dict, "OBSERVER_COVERAGE_INVALID")
    for event in returned:
        _require(event.get("phase") in PHASES, "OBSERVER_PHASE_INVALID")
        _require(
            event.get("provenance") == "INSTRUMENT_OBSERVED"
            and event.get("mechanism") == "CPYTHON_PROFILE_EXACT_SYNCHRONOUS_CODE_OBJECT",
            "OBSERVER_PROVENANCE_INVALID",
        )
        _duration(event.get("elapsed_ms"))
    for phase in PHASES:
        _require(
            type(seal["coverage"].get(phase, 0)) is int
            and seal["coverage"].get(phase, 0) == sum(r["phase"] == phase for r in returned),
            "OBSERVER_COVERAGE_MISMATCH",
        )
    return correlation, seal, returned


def _read_request(directory):
    path = directory / "backend-request.json"
    _require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 65_536,
        "BACKEND_REQUEST_UNAVAILABLE",
    )
    return strict_json_loads(path.read_bytes())


def _read_response(directory):
    raw_path, meta_path = (
        directory / "backend-response.bin",
        directory / "backend-response-meta.json",
    )
    _require(
        raw_path.is_file() and not raw_path.is_symlink() and raw_path.stat().st_size <= MAX_BYTES,
        "RESPONSE_BYTES_UNAVAILABLE",
    )
    _require(
        meta_path.is_file() and not meta_path.is_symlink() and meta_path.stat().st_size <= 4096,
        "RESPONSE_METADATA_UNAVAILABLE",
    )
    raw, meta = raw_path.read_bytes(), strict_json_loads(meta_path.read_bytes())
    _require(
        len(raw) <= MAX_BYTES
        and type(meta) is dict
        and set(meta) == {"status_code", "content_type"},
        "RESPONSE_METADATA_INVALID",
    )
    _require(
        type(meta["status_code"]) is int
        and 100 <= meta["status_code"] <= 599
        and type(meta["content_type"]) is str,
        "RESPONSE_METADATA_INVALID",
    )
    return raw, meta


def _terminal(attempt, http_finish, adapter_finish, response):
    """New adapter's exact single-attempt branches, not fixture-name shortcuts."""
    _terminal_shape(attempt)
    _require(attempt["attempt"] == attempt["max_attempts"] == 1, "ATTEMPT_CAPACITY_INVALID")
    _require(attempt["retry_after_seconds"] is None, "RETRY_AFTER_UNSUPPORTED")
    _require(
        response["attempt_count"] == 1 and response["attempt_metadata_available"] is True,
        "ATTEMPT_METADATA_MISMATCH",
    )
    _require(
        attempt["dispatch_state"] == response["dispatch_state"]
        and attempt["response_state"] == response["response_state"],
        "DISPATCH_STATE_CONTRADICTION",
    )
    status = http_finish.get("status_code")
    _require(attempt["status_code"] == status, "HTTP_STATUS_CONTRADICTION")
    if attempt["exception_type"] is None:
        _require(
            attempt["retry_decision"] == "NONE" and attempt["retry_reason"] == "success",
            "SUCCESS_RETRY_CONTRADICTION",
        )
        _require(
            attempt["response_received"] is True
            and status == 200
            and attempt["dispatch_state"] == "REQUEST_CONFIRMED"
            and attempt["response_state"] == "RESPONSE_RECEIVED",
            "SUCCESS_TRANSPORT_CONTRADICTION",
        )
        _require(
            http_finish["error_class"] is None and adapter_finish["error_class"] is None,
            "SUCCESS_COMPONENT_CONTRADICTION",
        )
        _require(
            response["status"] == "OK"
            and response["result"] is not None
            and response["verification_state"] == "RESULT_VERIFIED"
            and not response["errors"],
            "SUCCESS_RESULT_CONTRADICTION",
        )
        return
    _require(
        type(attempt["exception_type"]) is str and attempt["exception_type"], "EXCEPTION_INVALID"
    )
    _require(
        attempt["retry_decision"] == "RETRY_BLOCKED"
        and attempt["retry_reason"] == "single synthetic profile attempt; no retry",
        "ERROR_RETRY_CONTRADICTION",
    )
    _require(
        adapter_finish["error_class"] == "AdapterError"
        and response["status"] == "ERROR"
        and response["result"] is None
        and response["verification_state"] != "RESULT_VERIFIED"
        and response["errors"],
        "ERROR_RESULT_CONTRADICTION",
    )
    codes = {e["code"] for e in response["errors"]}
    if http_finish["error_class"] is not None:
        _require(
            attempt["exception_type"] == http_finish["error_class"], "HTTP_EXCEPTION_CONTRADICTION"
        )
        _require(
            attempt["response_received"] is False
            and status is None
            and attempt["dispatch_state"] == "DISPATCH_UNKNOWN"
            and attempt["response_state"] == "TRANSPORT_ERROR",
            "UNKNOWN_DELIVERY_CONTRADICTION",
        )
        _require(
            bool(codes & {"TIMEOUT", "NETWORK_ERROR"})
            and response["verification_state"] == "RESULT_UNKNOWN",
            "TRANSPORT_ERROR_CLASSIFICATION_MISMATCH",
        )
    else:
        # A returned HTTP200 can precede a later attribution/typed/body failure.
        _require(
            type(status) is int
            and attempt["response_received"] is True
            and attempt["dispatch_state"] == "REQUEST_CONFIRMED"
            and attempt["response_state"] == "RESPONSE_RECEIVED",
            "POST_HTTP_VALIDATION_CONTRADICTION",
        )
        _require(
            "CONFLICTING_SOURCE_RESULTS" in codes
            and response["verification_state"] == "FAILED_VALIDATION",
            "VALIDATION_ERROR_CLASSIFICATION_MISMATCH",
        )


def validate_capture(evidence_dir, expected_request, proposal, registry, owner, envelope):
    directory = Path(evidence_dir)
    _require(directory.is_dir() and not directory.is_symlink(), "DIRECTORY_UNAVAILABLE")
    _require(
        isinstance(proposal, Proposal) and type(expected_request) is str,
        "EXPECTED_INVOCATION_REQUIRED",
    )
    events = _read_stream(directory, "governance-observations.jsonl")
    correlation, seal, returned = _observer(events)
    if owner == "legacy-control":
        _require(registry is TOOLS, "LEGACY_REGISTRY_MISMATCH")
        return validate_backend_capture(
            directory,
            correlation,
            events,
            expected_request=expected_request,
            expected_tool=proposal.tool,
            expected_arguments=proposal.arguments,
            expected_request_id=envelope.request_id if envelope is not None else None,
            expected_envelope=envelope,
        )
    _require(
        owner == "strict" and registry is FAA_FY2026_PR_CONTRACT.registry,
        "TRUSTED_PROFILE_REGISTRY_REQUIRED",
    )
    audit, dispatch, backend, components = (
        _read_stream(directory, name)
        for name in ("audit.jsonl", "dispatch.jsonl", "http-attempts.jsonl", "components.jsonl")
    )
    result = {
        "state": "NO_GATEWAY_ACTIVITY",
        "request_id": None,
        "dispatch": dispatch,
        "backend": backend,
        "components": components,
        "audit": audit,
        "correlation_id": correlation,
        "historical_r32_validator_used": False,
    }
    if envelope is None:
        _require(
            not returned and not audit and not dispatch and not backend and not components,
            "UNKNOWN_RECEIPT_WITH_ACTIVITY",
        )
        _require(
            not (directory / "backend-request.json").exists(),
            "INGRESS_BACKEND_REQUEST_CONTRADICTION",
        )
        _require(
            not (directory / "backend-response.bin").exists()
            and not (directory / "backend-response-meta.json").exists(),
            "INGRESS_BACKEND_RESPONSE_CONTRADICTION",
        )
        # SDK/host admission facts and conservative OPEN custody are checked by
        # the composition; this absence is not a fabricated DENY or authority.
        return result
    _require(isinstance(envelope, Envelope) and bool(returned), "OBSERVED_ENVELOPE_REQUIRED")
    _require(proposal.tool == "find_federal_awards", "TOOL_OUTSIDE_PROFILE")
    scope = FaaFy2026PrReadV1.model_validate(proposal.arguments)
    effective = scope.model_dump(mode="json")
    request_id = envelope.request_id
    _require(
        all(r.get("request_id") == request_id for r in returned + audit), "REQUEST_ID_MISMATCH"
    )
    stages = [row.get("stage") for row in audit]
    _require(
        stages
        in (
            ["proposal", "policy", "completed"],
            ["proposal", "policy", "execution_started", "completed"],
        ),
        "AUDIT_STAGE_SEQUENCE",
    )
    times = [_timestamp(row.get("timestamp")) for row in audit]
    seal_time = _timestamp(seal.get("timestamp_utc"))
    _require(times == sorted(times) and times[-1] <= seal_time, "AUDIT_TIME_ORDER")
    proposal_row, policy_row, completed = audit[0], audit[1], audit[-1]
    _require(
        proposal_row.get("user_request") == expected_request
        and proposal_row.get("proposal") == {"tool": proposal.tool, "arguments": effective},
        "ORIGINAL_REQUEST_OR_ARGUMENTS_MISMATCH",
    )
    facts, policy = policy_row.get("facts"), policy_row.get("policy")
    _policy(policy)
    _require(
        type(facts) is dict
        and facts.get("tool") == proposal.tool
        and facts.get("request_text") == expected_request,
        "POLICY_CONTEXT_MISMATCH",
    )
    _require(
        type(facts.get("arguments_json")) is str
        and strict_json_loads(facts["arguments_json"]) == effective,
        "POLICY_ARGUMENTS_MISMATCH",
    )
    phases = {phase: [r for r in returned if r["phase"] == phase] for phase in PHASES}
    _require(
        all(len(phases[p]) == 1 for p in ("policy_preflight", "policy_issuance", "binding_issue"))
        and len(phases["binding_consume"]) <= 1
        and len(phases["policy_post_result"]) <= 1,
        "OBSERVER_PHASE_CARDINALITY",
    )
    for phase in ("policy_preflight", "policy_issuance", "policy_post_result"):
        for row in phases[phase]:
            _require(
                row.get("status") == "RETURNED_POLICY" and row.get("binding") is None,
                "OBSERVER_POLICY_INVALID",
            )
            _policy(row.get("policy"))
    issued, issuance = phases["binding_issue"][0], phases["policy_issuance"][0]
    _require(issued.get("policy") == issuance.get("policy") == policy, "ISSUANCE_POLICY_MISMATCH")
    _require(
        phases["policy_preflight"][0]["call_index"] < issued["call_index"] < issuance["call_index"],
        "POLICY_CALL_ORDER",
    )
    response = completed.get("response")
    observed = envelope.model_dump(mode="json")
    _require(response == observed, "CLIENT_COMPLETED_ENVELOPE_CONTRADICTION")
    _require(
        completed.get("tool_executed") is observed["tool_executed"]
        and type(completed.get("attempts")) is list,
        "COMPLETED_EXECUTION_MISMATCH",
    )
    result["request_id"] = request_id
    if policy["decision"] != "PERMIT":
        _require(
            stages == ["proposal", "policy", "completed"]
            and not phases["binding_consume"]
            and not phases["policy_post_result"],
            "HELD_GOVERNANCE_CONTRADICTION",
        )
        _require(
            issued.get("status") == "NO_BINDING"
            and issued.get("binding") is None
            and policy_row.get("binding_issued") is False,
            "HELD_BINDING_CONTRADICTION",
        )
        _require(
            not dispatch
            and not backend
            and not components
            and not (directory / "backend-request.json").exists(),
            "HELD_DISPATCH_CONTRADICTION",
        )
        _require(
            not (directory / "backend-response.bin").exists()
            and not (directory / "backend-response-meta.json").exists(),
            "HELD_BACKEND_RESPONSE_CONTRADICTION",
        )
        _require(
            observed["decision"] == policy["decision"]
            and observed["status"] == "BLOCKED"
            and observed["result"] is None
            and observed["provenance"] is None
            and not observed["tool_executed"]
            and observed["dispatch_state"] == "NOT_DISPATCHED"
            and observed["response_state"] == "NO_RESPONSE"
            and observed["verification_state"] == "UNVERIFIED"
            and observed["attempt_count"] == 0
            and completed["attempts"] == []
            and completed.get("pre_dispatch_verification") == "NOT_REQUIRED",
            "HELD_RESPONSE_CONTRADICTION",
        )
        result["state"] = "PRE_DISPATCH_HELD"
        return result
    _require(
        stages == ["proposal", "policy", "execution_started", "completed"]
        and len(phases["binding_consume"]) == 1,
        "BOUND_PATH_INCOMPLETE",
    )
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
        "BINDING_CHANNEL_MISMATCH",
    )
    _require(consumed["call_index"] > issuance["call_index"], "CONSUMPTION_CALL_ORDER")
    fields = {
        "request_id": request_id,
        "tool": proposal.tool,
        "arguments_sha256": sha256(canonical(effective)),
        "schema_sha256": sha256(canonical(registry[proposal.tool].model_json_schema())),
        "operation_scope": OPERATION_SCOPE,
        "policy_decision": "PERMIT",
        "policy_sha256": sha256(canonical(policy)),
        "policy_facts_sha256": sha256(canonical(facts)),
    }
    _require(
        all(binding.get(key) == value for key, value in fields.items()),
        "BINDING_SCOPE_OR_SCHEMA_MISMATCH",
    )
    _require(
        type(binding.get("policy_context_sha256")) is str
        and _HASH.fullmatch(binding["policy_context_sha256"]) is not None,
        "BINDING_CONTEXT_INVALID",
    )
    expected_binding = ExecutionBinding(
        **fields,
        arguments_json=canonical(effective).decode(),
        policy_context_sha256=binding["policy_context_sha256"],
    ).audit_record()
    _require(binding == expected_binding, "BINDING_DIGEST_MISMATCH")
    _require(
        started.get("tool") == proposal.tool
        and started.get("execution_authority") == policy
        and observed["tool_executed"] is True
        and completed.get("pre_dispatch_verification") == "PASS",
        "EXECUTION_AUDIT_MISMATCH",
    )
    _require(len(dispatch) == len(backend) == 1 and len(components) == 2, "DISPATCH_CARDINALITY")
    entry, http_entry = dispatch[0], backend[0]
    _require(
        set(entry) == {"timestamp_utc", "synthetic", "phase", "method", "query"}
        and entry["synthetic"] is True
        and entry["phase"] == "entered"
        and entry["method"] == "find_profile"
        and entry["query"] == effective,
        "ADAPTER_QUERY_MISMATCH",
    )
    _require(
        set(http_entry)
        == {"timestamp_utc", "synthetic", "phase", "method", "request_path", "request_body_sha256"}
        and http_entry["synthetic"] is True
        and http_entry["phase"] == "entered"
        and http_entry["method"] == "POST"
        and http_entry["request_path"] == "/api/v2/search/spending_by_award/"
        and http_entry["request_body_sha256"] == sha256(scope.wire_bytes()),
        "HTTP_SCOPE_MISMATCH",
    )
    _require(_read_request(directory) == scope.payload(), "BACKEND_BODY_SCOPE_MISMATCH")
    http_finish, adapter_finish = components
    http_keys = {"timestamp_utc", "synthetic", "component", "phase", "error_class"}
    _require(
        set(http_finish)
        == http_keys | ({"status_code"} if http_finish.get("error_class") is None else set()),
        "HTTP_FINISH_SHAPE",
    )
    _require(set(adapter_finish) == http_keys, "ADAPTER_FINISH_SHAPE")
    _require(
        http_finish.get("component") == "synthetic_http"
        and adapter_finish.get("component") == "adapter",
        "COMPONENT_ORDER",
    )
    for row in components:
        _require(
            row.get("synthetic") is True
            and row.get("phase") == "finish"
            and (row.get("error_class") is None or type(row["error_class"]) is str),
            "COMPONENT_SHAPE",
        )
    sequence = [
        times[2],
        _timestamp(entry["timestamp_utc"]),
        _timestamp(http_entry["timestamp_utc"]),
        _timestamp(http_finish["timestamp_utc"]),
        _timestamp(adapter_finish["timestamp_utc"]),
        times[-1],
        seal_time,
    ]
    _require(sequence == sorted(sequence), "COMPONENT_TIME_ORDER")
    attempts = completed["attempts"]
    _require(
        len(attempts) == 1
        and type(attempts[0]) is dict
        and completed.get("attempt_metadata_available") is True,
        "TERMINAL_ATTEMPT_MISSING",
    )
    _terminal(attempts[0], http_finish, adapter_finish, observed)
    if http_finish["error_class"] is None:
        raw_response, response_metadata = _read_response(directory)
        _require(
            response_metadata["status_code"] == http_finish["status_code"],
            "RESPONSE_STATUS_MISMATCH",
        )
        result["observed_response_sha256"] = sha256(raw_response)
        if attempts[0]["exception_type"] is None:
            _require(
                response_metadata["content_type"].split(";")[0].strip() == "application/json",
                "RESPONSE_CONTENT_TYPE_MISMATCH",
            )
            _require(envelope.provenance is not None, "SUCCESS_PROVENANCE_MISSING")
            _require(
                envelope.provenance.query_fingerprint == scope.query_fingerprint(),
                "QUERY_FINGERPRINT_MISMATCH",
            )
            _require(
                envelope.provenance.response_fingerprint
                == response_fingerprint(parse_response_bytes(raw_response)),
                "RESPONSE_FINGERPRINT_MISMATCH",
            )
            # The unchanged exact parser/money fingerprint and new profile page
            # validator join physical bytes, immutable fixture truth, complete
            # query, provenance and the independently observed client result.
            page = validate_page(scope, raw_response, envelope.provenance)
            _require(
                observed["result"]
                == {
                    "records": [r.model_dump(mode="json", exclude_unset=True) for r in page.results]
                },
                "SUCCESS_RESPONSE_PROJECTION_MISMATCH",
            )
            result["response_admission"] = "VALIDATED_PROFILE_BYTES_AND_PROVENANCE"
        else:
            _require(
                envelope.provenance is None and observed["result"] is None,
                "FAILED_RESPONSE_MUST_NOT_HAVE_VERIFIED_PROJECTION",
            )
            result["response_admission"] = "OBSERVED_BYTES_NOT_RELEASED_AS_VERIFIED_RESULT"
    else:
        _require(
            not (directory / "backend-response.bin").exists()
            and not (directory / "backend-response-meta.json").exists(),
            "NO_RESPONSE_EXCEPTION_HAS_RESPONSE_BYTES",
        )
        _require(envelope.provenance is None, "UNKNOWN_RESPONSE_HAS_PROVENANCE")
        result["response_admission"] = "NO_RESPONSE_DELIVERY_UNKNOWN"
    post = phases["policy_post_result"]
    if post:
        _require(
            post[0]["call_index"] > consumed["call_index"]
            and post[0]["policy"]
            == {
                "decision": observed["decision"],
                "reasons": observed["governance"]["policy_reasons"],
            },
            "POST_RESULT_POLICY_MISMATCH",
        )
    else:
        _require(
            observed["decision"] == policy["decision"]
            and observed["governance"]["policy_reasons"] == policy["reasons"],
            "FINAL_POLICY_WITHOUT_OBSERVED_EVALUATION",
        )
    result["state"] = "BOUND_SINGLE_PROFILE_ATTEMPT"
    return result
