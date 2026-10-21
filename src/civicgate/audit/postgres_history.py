"""Pure validation of local synthetic PostgreSQL ledger evidence.

Replay projects recorded facts; it does not issue authority, reevaluate policy,
clear holds, or compare historical credentials with the current wall clock.
"""

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Any

from civicgate.governance.execution import OPERATION_SCOPE, POLICY_VERSION
from civicgate.mcp.http_identity import LocalHold
from civicgate.models.requests import TOOLS

MAX_EVENTS = 10_000
MAX_PAYLOAD_BYTES = 16_384
DECISIONS = {"PERMIT", "DENY", "REVIEW_REQUIRED"}
DISPATCH_STATES = {
    "NOT_DISPATCHED",
    "DISPATCH_ATTEMPTED",
    "REQUEST_CONFIRMED",
    "DISPATCH_UNKNOWN",
}
RESPONSE_STATES = {"NO_RESPONSE", "RESPONSE_RECEIVED", "TRANSPORT_ERROR"}
NEXT_ACTIONS = {"NONE", "RETRY_BLOCKED", "HUMAN_REVIEW_REQUIRED", "STOP"}
COMMON = {
    "kind",
    "domain_key",
    "epoch",
    "owner_id",
    "instance",
    "source_revision",
    "source_sha256",
    "time",
}
FIELDS = {
    "boot": set(),
    "close": set(),
    "begin": {"request_id", "context"},
    "policy": {
        "request_id",
        "initial_decision",
        "reasons",
        "binding_issued",
        "binding_issuance_error",
    },
    "intent": {
        "request_id",
        "context",
        "authority",
        "containment_denials",
        "dispatch_state",
    },
    "finish": {
        "request_id",
        "denials",
        "hold",
        "final_decision",
        "phase",
        "tool_executed",
        "dispatch_state",
        "response_state",
        "next_action",
        "pre_dispatch_verification",
        "execution_boundary_error",
        "binding_consumption",
        "attempt_metadata_available",
        "attempts",
        "policy_reasons",
        "error_codes",
    },
    "hold": {"request_id", "reason", "dispatch_state", "response_state", "hold"},
}
CONTEXT_FIELDS = {"principal", "issuer", "audience", "session", "request", "expires_at"}
AUTHORITY_FIELDS = {"authority_source", "decision", "reasons", "policy_version", "binding"}
BINDING_FIELDS = {
    "request_id",
    "tool",
    "arguments_sha256",
    "schema_sha256",
    "operation_scope",
    "policy_decision",
    "policy_sha256",
    "policy_facts_sha256",
    "policy_context_sha256",
    "binding_sha256",
}
ATTEMPT_FIELDS = {
    "attempt",
    "max_attempts",
    "dispatch_state",
    "response_state",
    "status_code",
    "response_received",
    "retry_decision",
}


@dataclass(frozen=True)
class LedgerState:
    epoch: int = 0
    owner_id: str | None = None
    owner_active: bool = False
    denials: int = 0
    held: bool = False
    sequence: int = 0
    digest: str = ""
    active: str | None = None
    phase: str | None = None
    initial_decision: str | None = None
    binding_issued: bool = False
    seen: frozenset[str] = frozenset()


def canonical(value: Any) -> str:
    """Use the local journal's canonical JSON format and safe exception type."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except Exception as exc:
        raise LocalHold("HISTORY_SERIALIZATION_INVALID") from exc


def event_digest(previous: str, payload: str) -> str:
    """Hash exact canonical payload bytes with the preceding digest."""
    try:
        _require(type(previous) is str and type(payload) is str)
        return hashlib.sha256((previous + payload).encode("utf-8")).hexdigest()
    except LocalHold:
        raise
    except Exception as exc:
        raise LocalHold("HISTORY_DIGEST_INVALID") from exc


def _require(condition: bool) -> None:
    if not condition:
        raise LocalHold("HISTORY_INVALID")


def _text(value: Any, maximum: int = 256) -> None:
    _require(type(value) is str and 0 < len(value) <= maximum)


def _sha(value: Any, length: int = 64) -> None:
    _require(
        type(value) is str
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _integer(value: Any, minimum: int = 0) -> None:
    _require(type(value) is int and value >= minimum)


def _code(value: Any, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    _text(value, 128)
    _require(value[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    _require(all(character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in value))


def _codes(value: Any) -> None:
    _require(type(value) is list and len(value) <= 128)
    for code in value:
        _code(code)


def _context(value: Any, domain: dict[str, Any], event_time: int | float) -> None:
    _require(type(value) is dict and set(value) == CONTEXT_FIELDS)
    for key in ("principal", "issuer", "audience"):
        _require(value[key] == domain[key])
    for key in ("session", "request"):
        _text(value[key], 128)
    _integer(value["expires_at"], 1)
    _require(value["expires_at"] > event_time)


def _authority(value: Any, request_id: str, reasons: list[str]) -> None:
    _require(type(value) is dict and set(value) == AUTHORITY_FIELDS)
    _require(value["authority_source"] == "DETERMINISTIC_POLICY_GATE")
    _require(value["decision"] == "PERMIT" and value["policy_version"] == POLICY_VERSION)
    _codes(value["reasons"])
    _require(value["reasons"] == reasons)
    binding = value["binding"]
    _require(type(binding) is dict and set(binding) == BINDING_FIELDS)
    _require(binding["request_id"] == request_id and binding["tool"] in TOOLS)
    _require(binding["operation_scope"] == OPERATION_SCOPE)
    _require(binding["policy_decision"] == "PERMIT")
    for key in BINDING_FIELDS:
        if key.endswith("_sha256"):
            _sha(binding[key])


def _attempts(value: Any, available: bool) -> None:
    _require(type(value) is list and len(value) <= 1)
    _require(available == bool(value))
    for attempt in value:
        _require(type(attempt) is dict and set(attempt) == ATTEMPT_FIELDS)
        _require(type(attempt["attempt"]) is int and attempt["attempt"] == 1)
        _require(type(attempt["max_attempts"]) is int and attempt["max_attempts"] == 1)
        _require(attempt["dispatch_state"] in DISPATCH_STATES - {"NOT_DISPATCHED"})
        _require(attempt["response_state"] in RESPONSE_STATES)
        _require(type(attempt["response_received"]) is bool)
        _require(attempt["response_received"] == (attempt["response_state"] == "RESPONSE_RECEIVED"))
        _require(attempt["retry_decision"] in {"NONE", "RETRY_BLOCKED"})
        status = attempt["status_code"]
        if attempt["response_received"]:
            _require(type(status) is int and 100 <= status <= 599)
        else:
            _require(status is None)


def _finish(event: dict[str, Any], state: LedgerState) -> LedgerState:
    _require(state.phase in {"policy", "intent"})
    for key in ("hold", "tool_executed", "attempt_metadata_available"):
        _require(type(event[key]) is bool)
    _integer(event["denials"])
    _require(event["denials"] >= state.denials)
    _require(event["final_decision"] in DECISIONS)
    _require(event["dispatch_state"] in DISPATCH_STATES)
    _require(event["response_state"] in RESPONSE_STATES)
    _require(event["next_action"] in NEXT_ACTIONS)
    verification = event["pre_dispatch_verification"]
    consumption = {"PASS": "VERIFIED", "FAIL": "NOT_ESTABLISHED", "NOT_REQUIRED": "NOT_REQUIRED"}
    _require(verification in consumption)
    _require(event["binding_consumption"] == consumption[verification])
    _code(event["execution_boundary_error"], nullable=True)
    _codes(event["policy_reasons"])
    _codes(event["error_codes"])
    _attempts(event["attempts"], event["attempt_metadata_available"])
    if event["attempt_metadata_available"]:
        final_attempt = event["attempts"][-1]
        _require(event["response_state"] == final_attempt["response_state"])
        _require(
            event["dispatch_state"] == final_attempt["dispatch_state"]
            or event["dispatch_state"] == "DISPATCH_UNKNOWN"
        )
    executed = event["tool_executed"]
    _require(event["phase"] == ("post_dispatch" if executed else "pre_dispatch"))
    if executed:
        _require(state.phase == "intent" and state.initial_decision == "PERMIT")
        _require(state.binding_issued and verification == "PASS")
        _require(event["execution_boundary_error"] is None)
        unknown = (
            not event["attempt_metadata_available"]
            or event["dispatch_state"] != "REQUEST_CONFIRMED"
            or event["response_state"] != "RESPONSE_RECEIVED"
            or any(
                attempt["dispatch_state"] == "DISPATCH_UNKNOWN"
                or attempt["response_state"] == "TRANSPORT_ERROR"
                for attempt in event["attempts"]
            )
        )
        if unknown:
            _require(event["hold"] and event["dispatch_state"] == "DISPATCH_UNKNOWN")
            _require(event["next_action"] == "HUMAN_REVIEW_REQUIRED")
    else:
        _require(event["dispatch_state"] == "NOT_DISPATCHED")
        _require(event["response_state"] == "NO_RESPONSE")
        _require(not event["attempt_metadata_available"] and not event["attempts"])
        _require(verification != "PASS")
        _require(state.initial_decision != "PERMIT" or verification == "FAIL")
        if verification == "FAIL":
            _require(event["execution_boundary_error"] is not None)
        if state.initial_decision != "PERMIT":
            _require(event["final_decision"] == state.initial_decision)
    return replace(
        state,
        denials=event["denials"],
        held=state.held or event["hold"],
        active=None,
        phase=None,
        initial_decision=None,
        binding_issued=False,
    )


def replay(
    rows: list[tuple[Any, ...]],
    domain_key: str,
    domain: dict[str, Any],
    revision: str,
    source_sha: str,
) -> LedgerState:
    """Validate complete ordered evidence and project its last recorded state.

    Open or held histories return their state so an append can be validated;
    the backend must separately refuse recovery admission for that state.
    """
    try:
        return _replay(rows, domain_key, domain, revision, source_sha)
    except LocalHold:
        raise
    except Exception as exc:
        # Gateway's inner adapter handler catches ValueError/TypeError. Never
        # expose either for evidence failures, including hostile JSON shapes.
        raise LocalHold("HISTORY_INVALID") from exc


def _replay(
    rows: list[tuple[Any, ...]],
    domain_key: str,
    domain: dict[str, Any],
    revision: str,
    source_sha: str,
) -> LedgerState:
    _require(type(rows) is list and 0 < len(rows) <= MAX_EVENTS)
    _sha(domain_key)
    _sha(revision, 40)
    _sha(source_sha)
    _require(
        type(domain) is dict
        and set(domain) == {"issuer", "audience", "principal", "service_identity"}
    )
    for value in domain.values():
        _text(value)
    _require(domain["principal"] != domain["service_identity"])
    _require(domain_key == hashlib.sha256(canonical(domain).encode("utf-8")).hexdigest())
    state = LedgerState()
    previous_kind: str | None = None
    instance: str | None = None
    active_context: dict[str, Any] | None = None
    policy_reasons: list[str] = []
    for row in rows:
        _require(type(row) is tuple and len(row) == 6)
        seq, kind, request_id, payload, previous, digest = row
        _integer(seq, 1)
        _require(seq == state.sequence + 1)
        _require(type(payload) is str and len(payload.encode("utf-8")) <= MAX_PAYLOAD_BYTES)
        _require(type(kind) is str)
        _require(previous == state.digest)
        _sha(digest)
        _require(digest == event_digest(previous, payload))
        event = json.loads(payload)
        _require(type(event) is dict and canonical(event) == payload and event.get("kind") == kind)
        if seq == 1:
            _require(request_id is None)
            _require(type(event.get("version")) is int)
            _require(
                event
                == {
                    "kind": "provision",
                    "domain": domain,
                    "source_revision": revision,
                    "source_sha256": source_sha,
                    "version": 1,
                }
            )
        else:
            _require(kind in FIELDS and set(event) == COMMON | FIELDS[kind])
            _require(event["domain_key"] == domain_key)
            _require(event["source_revision"] == revision and event["source_sha256"] == source_sha)
            _integer(event["epoch"], 1)
            _text(event["owner_id"], 128)
            _text(event["instance"])
            event_time = event["time"]
            _require(type(event_time) in {int, float} and math.isfinite(event_time))
            _require(request_id == event.get("request_id"))
            if kind == "boot":
                _require(previous_kind in {"provision", "close"})
                _require(not state.held and not state.owner_active and state.active is None)
                _require(event["epoch"] == state.epoch + 1)
                state = replace(
                    state,
                    epoch=event["epoch"],
                    owner_id=event["owner_id"],
                    owner_active=True,
                )
                instance = event["instance"]
            else:
                _require(state.owner_active and event["epoch"] == state.epoch)
                _require(event["owner_id"] == state.owner_id and event["instance"] == instance)
                _require(not state.held or kind == "hold")
                if kind == "close":
                    _require(state.active is None)
                    state = replace(state, owner_id=None, owner_active=False)
                elif kind == "begin":
                    _require(state.active is None)
                    _text(request_id, 128)
                    _require(request_id not in state.seen)
                    _context(event["context"], domain, event_time)
                    active_context = event["context"]
                    state = replace(
                        state,
                        active=request_id,
                        phase="begin",
                        seen=state.seen | {request_id},
                    )
                elif kind == "hold":
                    _require(request_id == state.active)
                    _require(event["reason"] == "INCOMPLETE_CALL" and event["hold"] is True)
                    _require(event["dispatch_state"] == "DISPATCH_UNKNOWN")
                    _require(event["response_state"] == "TRANSPORT_ERROR")
                    state = replace(state, held=True)
                else:
                    _require(state.active is not None and request_id == state.active)
                    if kind == "policy":
                        _require(state.phase == "begin")
                        _require(event["initial_decision"] in DECISIONS)
                        _codes(event["reasons"])
                        _require(type(event["binding_issued"]) is bool)
                        _code(event["binding_issuance_error"], nullable=True)
                        _require(
                            event["initial_decision"] == "PERMIT" or not event["binding_issued"]
                        )
                        _require(
                            not event["binding_issued"] or event["binding_issuance_error"] is None
                        )
                        policy_reasons = event["reasons"]
                        state = replace(
                            state,
                            phase="policy",
                            initial_decision=event["initial_decision"],
                            binding_issued=event["binding_issued"],
                        )
                    elif kind == "intent":
                        _require(state.phase == "policy")
                        _require(state.initial_decision == "PERMIT" and state.binding_issued)
                        _context(event["context"], domain, event_time)
                        _require(event["context"] == active_context)
                        _integer(event["containment_denials"])
                        _require(event["containment_denials"] == state.denials)
                        _require(event["dispatch_state"] == "NOT_DISPATCHED")
                        _authority(event["authority"], request_id, policy_reasons)
                        state = replace(state, phase="intent")
                    elif kind == "finish":
                        state = _finish(event, state)
                        active_context = None
                        policy_reasons = []
        state = replace(state, sequence=seq, digest=digest)
        previous_kind = kind
    return state
