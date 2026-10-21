"""Pure history tests: no PostgreSQL, transport, credentials, or policy calls."""

import copy
import hashlib
import math

import pytest

from civicgate.audit.postgres_history import (
    LedgerState,
    canonical,
    event_digest,
    replay,
)
from civicgate.governance.execution import OPERATION_SCOPE, POLICY_VERSION
from civicgate.mcp.http_identity import LocalHold

DOMAIN = {
    "issuer": "https://synthetic.invalid",
    "audience": "local-synthetic-ledger",
    "principal": "synthetic-caller",
    "service_identity": "synthetic-service",
}
DOMAIN_KEY = hashlib.sha256(canonical(DOMAIN).encode()).hexdigest()
REVISION = "a" * 40
SOURCE_SHA = "b" * 64
CONTEXT = DOMAIN | {"session": "session", "request": "http-request", "expires_at": 200}
CONTEXT.pop("service_identity")


def provision():
    return {
        "kind": "provision",
        "domain": DOMAIN,
        "source_revision": REVISION,
        "source_sha256": SOURCE_SHA,
        "version": 1,
    }


def event(kind, **fields):
    return {
        "kind": kind,
        "domain_key": DOMAIN_KEY,
        "epoch": 1,
        "owner_id": "owner-one",
        "instance": "instance-one",
        "source_revision": REVISION,
        "source_sha256": SOURCE_SHA,
        "time": 100,
        **fields,
    }


def begin(request_id="request-one"):
    return event("begin", request_id=request_id, context=CONTEXT)


def policy(decision="PERMIT", *, request_id="request-one", issued=None, error=None):
    return event(
        "policy",
        request_id=request_id,
        initial_decision=decision,
        reasons=["ALLOW"] if decision == "PERMIT" else ["PRIVATE_DATA"],
        binding_issued=(decision == "PERMIT") if issued is None else issued,
        binding_issuance_error=error,
    )


def intent(request_id="request-one"):
    return event(
        "intent",
        request_id=request_id,
        context=CONTEXT,
        authority={
            "authority_source": "DETERMINISTIC_POLICY_GATE",
            "decision": "PERMIT",
            "reasons": ["ALLOW"],
            "policy_version": POLICY_VERSION,
            "binding": {
                "request_id": request_id,
                "tool": "get_federal_award",
                "operation_scope": OPERATION_SCOPE,
                "policy_decision": "PERMIT",
                **{
                    key: "c" * 64
                    for key in (
                        "arguments_sha256",
                        "schema_sha256",
                        "policy_sha256",
                        "policy_facts_sha256",
                        "policy_context_sha256",
                        "binding_sha256",
                    )
                },
            },
        },
        containment_denials=0,
        dispatch_state="NOT_DISPATCHED",
    )


def finish(*, executed=True, decision="PERMIT", request_id="request-one", **overrides):
    return (
        event(
            "finish",
            request_id=request_id,
            denials=0,
            hold=False,
            final_decision=decision,
            phase="post_dispatch" if executed else "pre_dispatch",
            tool_executed=executed,
            dispatch_state="REQUEST_CONFIRMED" if executed else "NOT_DISPATCHED",
            response_state="RESPONSE_RECEIVED" if executed else "NO_RESPONSE",
            next_action="NONE" if executed else "STOP",
            pre_dispatch_verification="PASS" if executed else "NOT_REQUIRED",
            execution_boundary_error=None,
            binding_consumption="VERIFIED" if executed else "NOT_REQUIRED",
            attempt_metadata_available=executed,
            attempts=[
                {
                    "attempt": 1,
                    "max_attempts": 1,
                    "dispatch_state": "REQUEST_CONFIRMED",
                    "response_state": "RESPONSE_RECEIVED",
                    "status_code": 200,
                    "response_received": True,
                    "retry_decision": "NONE",
                }
            ]
            if executed
            else [],
            policy_reasons=["ALLOW"] if executed else ["PRIVATE_DATA"],
            error_codes=[],
        )
        | overrides
    )


def rows(events):
    result = []
    previous = ""
    for sequence, item in enumerate(events, 1):
        payload = canonical(item)
        digest = event_digest(previous, payload)
        result.append((sequence, item["kind"], item.get("request_id"), payload, previous, digest))
        previous = digest
    return result


def validate(events):
    return replay(rows(events), DOMAIN_KEY, DOMAIN, REVISION, SOURCE_SHA)


def permitted():
    return [provision(), event("boot"), begin(), policy(), intent(), finish()]


@pytest.mark.parametrize("value", [math.nan, math.inf, object(), {"bad": math.nan}])
def test_canonical_never_leaks_serialization_value_or_type_errors(value):
    with pytest.raises(LocalHold):
        canonical(value)


def test_canonical_and_digest_match_local_formula():
    payload = canonical({"z": 1, "a": "é"})
    assert payload == '{"a":"\\u00e9","z":1}'
    assert (
        event_digest("previous", payload)
        == hashlib.sha256(("previous" + payload).encode()).hexdigest()
    )


def test_genesis_is_idle_and_does_not_construct_authority():
    state = validate([provision()])
    assert state == LedgerState(sequence=1, digest=rows([provision()])[0][-1])


@pytest.mark.parametrize("decision", ["DENY", "REVIEW_REQUIRED"])
def test_pre_dispatch_nonpermit_finishes_without_intent(decision):
    state = validate(
        [
            provision(),
            event("boot"),
            begin(),
            policy(decision),
            finish(executed=False, decision=decision),
        ]
    )
    assert state.active is None and state.initial_decision is None
    assert not state.held and state.seen == {"request-one"}


@pytest.mark.parametrize("decision", ["PERMIT", "REVIEW_REQUIRED"])
def test_known_dispatch_and_post_review_keep_authorization_phases(decision):
    evidence = permitted()
    evidence[-1] = finish(decision=decision)
    state = validate(evidence)
    assert evidence[3]["initial_decision"] == "PERMIT"
    assert not state.held and state.owner_active
    assert state.phase is None and not state.binding_issued


def test_candidate_intent_can_finish_with_failed_consumption_and_zero_dispatch():
    evidence = permitted()
    evidence[-1] = finish(
        executed=False,
        decision="DENY",
        pre_dispatch_verification="FAIL",
        execution_boundary_error="ENVELOPE_EXPIRED",
        binding_consumption="NOT_ESTABLISHED",
    )
    assert not validate(evidence).held


def test_containment_and_seen_request_ids_survive_clean_epoch_restart():
    evidence = [
        provision(),
        event("boot"),
        begin(),
        policy("DENY"),
        finish(executed=False, decision="DENY", denials=2),
        event("close"),
        event("boot", epoch=2, owner_id="owner-two", instance="instance-two"),
    ]
    state = validate(evidence)
    assert state.denials == 2 and not state.held
    assert state.epoch == 2 and state.owner_id == "owner-two"
    assert state.seen == {"request-one"}
    evidence.append(begin() | {"epoch": 2, "owner_id": "owner-two", "instance": "instance-two"})
    with pytest.raises(LocalHold):
        validate(evidence)


def test_hold_after_finish_preserves_completed_outcome_and_blocks_clean_close():
    evidence = permitted()
    original = copy.deepcopy(evidence[-1])
    evidence.append(
        event(
            "hold",
            request_id=None,
            reason="INCOMPLETE_CALL",
            dispatch_state="DISPATCH_UNKNOWN",
            response_state="TRANSPORT_ERROR",
            hold=True,
        )
    )
    state = validate(evidence)
    assert state.held and state.active is None
    assert evidence[-2] == original
    with pytest.raises(LocalHold):
        validate(evidence + [event("close")])


@pytest.mark.parametrize(
    "field,value", [("epoch", 2), ("owner_id", "foreign"), ("instance", "foreign")]
)
def test_operational_events_cannot_change_current_owner_binding(field, value):
    with pytest.raises(LocalHold):
        validate([provision(), event("boot"), begin() | {field: value}])


@pytest.mark.parametrize("prefix", [[], [provision()], [provision(), event("boot"), begin()]])
def test_finish_cannot_precede_its_policy(prefix):
    with pytest.raises(LocalHold):
        validate(prefix + [finish()])


def test_executed_finish_requires_intent():
    with pytest.raises(LocalHold):
        validate([provision(), event("boot"), begin(), policy(), finish()])


@pytest.mark.parametrize("decision", ["DENY", "REVIEW_REQUIRED"])
def test_nonpermit_policy_cannot_record_intent(decision):
    with pytest.raises(LocalHold):
        validate([provision(), event("boot"), begin(), policy(decision), intent()])


def test_duplicate_policy_and_boot_without_close_are_rejected():
    with pytest.raises(LocalHold):
        validate([provision(), event("boot"), begin(), policy(), policy()])
    with pytest.raises(LocalHold):
        validate([provision(), event("boot"), event("boot", epoch=2)])


@pytest.mark.parametrize("change", ["expired", "session", "extra", "principal"])
def test_context_validity_uses_recorded_event_time_and_exact_identity(change):
    evidence = permitted()
    context = dict(CONTEXT)
    if change == "expired":
        context["expires_at"] = 100
    elif change == "session":
        context["session"] = "different-session"
    elif change == "extra":
        context["token"] = "forbidden-field"
    else:
        context["principal"] = "foreign"
    evidence[4] = intent() | {"context": context}
    with pytest.raises(LocalHold):
        validate(evidence)
    # Fixture timestamps are long expired today. Historical replay is still valid.
    assert validate(permitted()).sequence == 6


@pytest.mark.parametrize("change", ["extra", "reasons", "digest", "tool", "request_id"])
def test_candidate_authority_is_exact_audit_metadata_only(change):
    evidence = permitted()
    candidate = copy.deepcopy(evidence[4])
    if change == "extra":
        candidate["authority"]["binding"]["arguments_json"] = "{}"
    elif change == "reasons":
        candidate["authority"]["reasons"] = ["CONTRADICTORY_REASON"]
    elif change == "digest":
        candidate["authority"]["binding"]["binding_sha256"] = "not-a-digest"
    elif change == "tool":
        candidate["authority"]["binding"]["tool"] = "unregistered"
    else:
        candidate["authority"]["binding"]["request_id"] = "foreign"
    evidence[4] = candidate
    with pytest.raises(LocalHold):
        validate(evidence)


@pytest.mark.parametrize("missing", ["hold", "dispatch_state", "next_action"])
def test_unknown_outcome_requires_hold_and_normalized_dispatch_state(missing):
    evidence = permitted()
    outcome = finish(
        hold=True,
        dispatch_state="DISPATCH_UNKNOWN",
        response_state="TRANSPORT_ERROR",
        next_action="HUMAN_REVIEW_REQUIRED",
    )
    outcome["attempts"][0].update(
        dispatch_state="DISPATCH_UNKNOWN",
        response_state="TRANSPORT_ERROR",
        status_code=None,
        response_received=False,
        retry_decision="RETRY_BLOCKED",
    )
    evidence[-1] = outcome
    assert validate(evidence).held
    evidence[-1] = outcome | {missing: finish()[missing]}
    with pytest.raises(LocalHold):
        validate(evidence)


def test_missing_attempt_metadata_is_uncertainty_and_actual_response_is_preserved():
    evidence = permitted()
    evidence[-1] = finish(
        attempts=[],
        attempt_metadata_available=False,
        dispatch_state="DISPATCH_UNKNOWN",
        hold=True,
        next_action="HUMAN_REVIEW_REQUIRED",
    )
    assert validate(evidence).held
    assert evidence[-1]["response_state"] == "RESPONSE_RECEIVED"


@pytest.mark.parametrize("change", ["retry", "count", "metadata", "credential", "bool_number"])
def test_attempts_reject_retries_and_unprojected_fields(change):
    evidence = permitted()
    if change == "retry":
        evidence[-1]["attempts"][0]["retry_decision"] = "RETRY_ALLOWED"
    elif change == "count":
        evidence[-1]["attempts"][0]["max_attempts"] = 3
    elif change == "metadata":
        evidence[-1]["attempt_metadata_available"] = False
    elif change == "credential":
        evidence[-1]["attempts"][0]["raw_response"] = "forbidden-field"
    else:
        evidence[-1]["attempts"][0]["attempt"] = True
    with pytest.raises(LocalHold):
        validate(evidence)


@pytest.mark.parametrize("change", ["hash", "gap", "noncanonical", "shape", "column"])
def test_row_integrity_errors_fail_closed(change):
    evidence = rows(permitted())
    selected = list(evidence[-1])
    if change == "hash":
        selected[-1] = "0" * 64
    elif change == "gap":
        selected[0] += 1
    elif change == "noncanonical":
        selected[3] += " "
        selected[-1] = event_digest(selected[-2], selected[3])
    elif change == "shape":
        selected.pop()
    else:
        selected[2] = "foreign-request"
    evidence[-1] = tuple(selected)
    with pytest.raises(LocalHold):
        replay(evidence, DOMAIN_KEY, DOMAIN, REVISION, SOURCE_SHA)


@pytest.mark.parametrize("change", ["extra", "bad_time", "version_bool", "oversize", "unhashable"])
def test_malformed_schema_types_never_escape_as_value_or_type_errors(change):
    evidence = permitted()
    if change == "extra":
        evidence[1]["credential"] = "forbidden-field"
    elif change == "bad_time":
        evidence[1]["time"] = True
    elif change == "version_bool":
        evidence[0]["version"] = True
    elif change == "oversize":
        evidence[1]["instance"] = "x" * 17_000
    else:
        evidence[3]["initial_decision"] = []
    with pytest.raises(LocalHold):
        validate(evidence)


def test_denials_cannot_decrease_or_impersonate_boolean_count():
    for invalid in (-1, True):
        evidence = permitted()
        evidence[-1]["denials"] = invalid
        with pytest.raises(LocalHold):
            validate(evidence)


def test_payload_bound_and_empty_or_excessive_history():
    for evidence in ([], rows([provision()]) * 10_001):
        with pytest.raises(LocalHold):
            replay(evidence, DOMAIN_KEY, DOMAIN, REVISION, SOURCE_SHA)


@pytest.mark.parametrize("invalid", ["not-a-domain-hash", "c" * 64])
def test_domain_key_is_bound_to_exact_stable_domain(invalid):
    with pytest.raises(LocalHold):
        replay(rows([provision()]), invalid, DOMAIN, REVISION, SOURCE_SHA)


@pytest.mark.parametrize("field", ["owner_id", "request_id"])
def test_schema_identifier_bounds_are_enforced_before_recovery(field):
    evidence = [provision(), event("boot"), begin()]
    evidence[1 if field == "owner_id" else 2][field] = "x" * 129
    with pytest.raises(LocalHold):
        validate(evidence)


@pytest.mark.parametrize("change", ["received", "missing_status", "unexpected_status"])
def test_attempt_response_flags_and_status_presence_are_consistent(change):
    evidence = permitted()
    attempt = evidence[-1]["attempts"][0]
    if change == "received":
        attempt["response_received"] = False
    elif change == "missing_status":
        attempt["status_code"] = None
    else:
        attempt.update(response_state="TRANSPORT_ERROR", response_received=False)
    with pytest.raises(LocalHold):
        validate(evidence)


@pytest.mark.parametrize(
    "field,value", [("response_state", "NO_RESPONSE"), ("dispatch_state", "DISPATCH_ATTEMPTED")]
)
def test_finish_cannot_contradict_projected_last_attempt(field, value):
    evidence = permitted()
    evidence[-1][field] = value
    with pytest.raises(LocalHold):
        validate(evidence)


def test_normalized_unknown_dispatch_can_preserve_received_response():
    evidence = permitted()
    evidence[-1].update(
        dispatch_state="DISPATCH_UNKNOWN", hold=True, next_action="HUMAN_REVIEW_REQUIRED"
    )
    assert validate(evidence).held
    assert evidence[-1]["response_state"] == "RESPONSE_RECEIVED"
