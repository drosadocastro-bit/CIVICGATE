"""SYNTHETIC ONLY: pure P0 evidence assessment, never an admission coordinator.

The independent verifier is a trusted *test dependency*, not remote authentication.
There is no adapter, credential, binding issuer, clock, store or dispatch interface.
Reassessing a fixture is not consuming an event or reserving an operational attempt.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.models.governance import Decision, JudgeSignal, KSignal
from civicgate.models.requests import TOOLS

SyntheticID = Annotated[str, Field(pattern=r"^synthetic-[A-Za-z0-9_-]{1,100}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Tick = Annotated[int, Field(ge=0)]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class SyntheticRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class Identity(SyntheticRecord):
    issuer: Literal["https://synthetic.invalid"]
    audience: Literal["synthetic-b2b-p01"]
    caller: SyntheticID
    caller_kind: Literal["USER", "MACHINE"]
    service_principal: SyntheticID
    proxy: SyntheticID
    session: SyntheticID
    credential_reference: SyntheticID
    instance: SyntheticID
    expires_at: Tick


class Operation(SyntheticRecord):
    operation_id: SyntheticID
    original_request: Text
    tool: Annotated[str, Field(min_length=1, max_length=100)]
    arguments_json: Annotated[str, Field(min_length=2, max_length=8000)]


class Attempt(SyntheticRecord):
    attempt_id: SyntheticID
    operation_id: SyntheticID
    initial_policy: Decision
    intent: Literal["NOT_COMMITTED", "COMMITTED", "UNKNOWN"]
    delegation: Literal["NOT_DELEGATED", "DELEGATED", "UNKNOWN"]
    outcome: Literal[
        "TECHNICAL_FAILURE_NOT_DISPATCHED",
        "DISPATCH_UNKNOWN",
        "RESPONSE_RECEIVED",
        "POLICY_STOP",
        "INCOMPLETE",
    ]
    terminal: bool
    recorded_at: Tick


class Evidence(SyntheticRecord):
    scope: Literal["SYNTHETIC_ONLY"]
    producer: SyntheticID
    observed_at: Tick
    identity: Identity
    operation: Operation
    attempts: Annotated[tuple[Attempt, ...], Field(min_length=1, max_length=32)]
    recovery_hold: bool
    binding_reference: SyntheticID | None


class SyntheticTrustFacts(SyntheticRecord):
    """Independent fixture assertions. No defaults or inferred empty known history."""

    scope: Literal["SYNTHETIC_ONLY"]
    history_coverage: Literal["SYNTHETIC_SCENARIO_ONLY"]
    expected_sha256: Digest
    producer: SyntheticID
    identity: Identity
    operation: Operation
    attempt_ids: Annotated[tuple[SyntheticID, ...], Field(min_length=1, max_length=32)]
    observed_at: Tick
    valid_until: Tick
    caller_authenticated: bool
    trusted_proxy: bool
    app_access: bool
    machine_authorized: bool
    recovery_hold: bool
    held_operations: frozenset[SyntheticID]
    used_operations: frozenset[SyntheticID]
    used_sessions: frozenset[SyntheticID]
    revoked_credentials: frozenset[SyntheticID]


class SyntheticVerifier(Protocol):
    def verify(self, raw: bytes) -> SyntheticTrustFacts | None:
        """Resolve independent fixture evidence; never trust payload self-attestation."""


@dataclass(frozen=True)
class Assessment:
    evidence_verification: Literal["FAILED", "SYNTHETIC_VERIFIED"]
    admission: Literal["STOP", "HOLD", "REJECTED", "ELIGIBILITY_ASSESSMENT_ONLY"]
    reason: str
    b_policy_reached: bool = False
    b_policy_decision: Decision | None = None
    b_policy_reasons: tuple[str, ...] = ()
    recovery_disposition: Literal["STOP", "HOLD", "ASSESSMENT_ONLY_NO_EXECUTION"] = "HOLD"
    scope: Literal["SYNTHETIC_ONLY"] = field(default="SYNTHETIC_ONLY", init=False)
    binding_issued: Literal[False] = field(default=False, init=False)
    adapter_dispatches: Literal[0] = field(default=0, init=False)
    result_disposition: Literal["NO_RESULT"] = field(default="NO_RESULT", init=False)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON field")
        obj[key] = value
    return obj


def _nonfinite(value: str) -> object:
    raise ValueError("non-finite JSON value")


def _json(raw: bytes | str) -> object:
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)


def _failure(reason: str, *, identity: bool = False) -> Assessment:
    return Assessment("FAILED", "REJECTED" if identity else "HOLD", reason)


def _history_error(evidence: Evidence, trust: SyntheticTrustFacts) -> str | None:
    attempts = evidence.attempts
    ids = tuple(a.attempt_id for a in attempts)
    if ids != trust.attempt_ids or len(ids) != len(set(ids)):
        return "INCOMPLETE_OR_REUSED_ATTEMPT_HISTORY"
    previous = -1
    for a in attempts:
        if a.operation_id != evidence.operation.operation_id:
            return "FOREIGN_OPERATION_HISTORY"
        if not previous <= a.recorded_at <= evidence.observed_at:
            return "CONTRADICTORY_HISTORY_TIME"
        previous = a.recorded_at
        if a.initial_policy != "PERMIT" and (
            a.intent != "NOT_COMMITTED" or a.delegation != "NOT_DELEGATED"
        ):
            return "CONTRADICTORY_POLICY_AND_TRANSPORT"
        if a.delegation == "DELEGATED" and a.intent != "COMMITTED":
            return "DELEGATION_WITHOUT_CONFIRMED_INTENT"
        if a.outcome == "TECHNICAL_FAILURE_NOT_DISPATCHED" and (
            a.initial_policy != "PERMIT"
            or not a.terminal
            or a.delegation != "NOT_DELEGATED"
            or a.intent == "UNKNOWN"
        ):
            return "UNSUPPORTED_NOT_DISPATCHED"
        if a.outcome == "POLICY_STOP" and (a.initial_policy == "PERMIT" or not a.terminal):
            return "CONTRADICTORY_POLICY_STOP"
        if a.outcome == "RESPONSE_RECEIVED" and (a.delegation != "DELEGATED" or not a.terminal):
            return "RESPONSE_WITHOUT_DISPATCH"
    return None


def assess(
    raw: bytes | None,
    verifier: SyntheticVerifier,
    *,
    now: int,
    channel_b_available: bool = False,
    inspect_b_policy: bool = False,
    judge: JudgeSignal | None = None,
    agent_k: KSignal | None = None,
) -> Assessment:
    """Assess a synthetic snapshot without changing it or acquiring any authority.

    Availability is deliberately irrelevant. inspect_b_policy is a diagnostic
    switch, not an admitted attempt. Even a policy PERMIT cannot issue a binding.
    The caller of this pure function is the trusted test harness, not a remote API.
    """
    if type(now) is not int or now < 0:
        return _failure("INVALID_SYNTHETIC_CLOCK")
    if raw is None or type(raw) is not bytes or not 0 < len(raw) <= 65536:
        return _failure("MISSING_OR_OVERSIZED_EVIDENCE")
    try:
        _json(raw)  # Reject duplicate keys/non-finite values before schema parsing.
        evidence = Evidence.model_validate_json(raw)
    except (ValueError, RecursionError):
        return _failure("MALFORMED_EVIDENCE")
    try:
        trust = verifier.verify(raw)
    except Exception:
        return _failure("SYNTHETIC_VERIFIER_UNAVAILABLE")
    if not isinstance(trust, SyntheticTrustFacts):
        return _failure("NO_INDEPENDENT_SYNTHETIC_TRUST")
    # Revalidate even a dependency using model_construct/copy without validation.
    try:
        trust = SyntheticTrustFacts.model_validate_json(trust.model_dump_json(warnings="error"))
    except (ValueError, TypeError, RecursionError):
        return _failure("INVALID_SYNTHETIC_TRUST_FACTS")
    if hashlib.sha256(raw).hexdigest() != trust.expected_sha256:
        return _failure("INDEPENDENT_IDENTITY_MISMATCH")
    if evidence.producer != trust.producer or evidence.operation != trust.operation:
        return _failure("PRODUCER_OR_OPERATION_MISMATCH")
    if (
        evidence.observed_at != trust.observed_at
        or not trust.observed_at <= now < trust.valid_until
        or not 0 < trust.valid_until - trust.observed_at <= 300
    ):
        return _failure("STALE_OR_CONTRADICTORY_OBSERVATION")
    identity = evidence.identity
    if identity != trust.identity:
        return _failure("CALLER_SESSION_OR_TOKEN_MISMATCH", identity=True)
    if not (trust.caller_authenticated and trust.trusted_proxy and trust.app_access):
        return _failure("UNVERIFIED_INGRESS_OR_APP_ACCESS", identity=True)
    if identity.caller == identity.service_principal:
        return _failure("CALLER_SERVICE_PRINCIPAL_CONFUSION", identity=True)
    if identity.caller_kind == "MACHINE" and not trust.machine_authorized:
        return _failure("MACHINE_CALLER_NOT_AUTHORIZED", identity=True)
    if identity.expires_at <= now or identity.credential_reference in trust.revoked_credentials:
        return _failure("EXPIRED_OR_REVOKED_SYNTHETIC_CREDENTIAL", identity=True)
    if identity.session in trust.used_sessions:
        return _failure("REPLAYED_SYNTHETIC_SESSION", identity=True)
    if evidence.binding_reference is not None:
        return _failure("TRANSFERRED_BINDING_FORBIDDEN", identity=True)
    history_error = _history_error(evidence, trust)
    if history_error:
        return _failure(history_error)
    if evidence.recovery_hold != trust.recovery_hold:
        return _failure("CONTRADICTORY_RECOVERY_STATE")
    if any(a.initial_policy == "DENY" for a in evidence.attempts):
        return Assessment(
            "SYNTHETIC_VERIFIED", "STOP", "CHANNEL_A_DENY", recovery_disposition="STOP"
        )
    if any(a.initial_policy == "REVIEW_REQUIRED" for a in evidence.attempts):
        return Assessment("SYNTHETIC_VERIFIED", "HOLD", "CHANNEL_A_PRE_DISPATCH_REVIEW")
    if (
        trust.recovery_hold
        or evidence.operation.operation_id in trust.held_operations
        or evidence.operation.operation_id in trust.used_operations
    ):
        return Assessment("SYNTHETIC_VERIFIED", "HOLD", "RECOVERY_OR_REPLAY_HOLD")
    if any(a.outcome == "DISPATCH_UNKNOWN" for a in evidence.attempts):
        return Assessment("SYNTHETIC_VERIFIED", "HOLD", "DISPATCH_UNKNOWN")
    if any(
        a.outcome != "TECHNICAL_FAILURE_NOT_DISPATCHED"
        or not a.terminal
        or a.delegation != "NOT_DELEGATED"
        for a in evidence.attempts
    ):
        return Assessment("SYNTHETIC_VERIFIED", "HOLD", "NO_COMPLETE_NOT_DISPATCHED_PROOF")
    if not inspect_b_policy:
        return Assessment(
            "SYNTHETIC_VERIFIED",
            "ELIGIBILITY_ASSESSMENT_ONLY",
            "SYNTHETIC_NOT_DISPATCHED",
            recovery_disposition="ASSESSMENT_ONLY_NO_EXECUTION",
        )
    return _inspect_policy(evidence.operation, judge, agent_k)


def _inspect_policy(
    operation: Operation, judge: JudgeSignal | None, agent_k: KSignal | None
) -> Assessment:
    """Reuse the existing pure policy function; never import ExecutionBoundary."""
    valid = False
    arguments_json: str | None = None
    try:
        arguments = _json(operation.arguments_json)
        if operation.tool in TOOLS:
            validated = TOOLS[operation.tool].model_validate(arguments)
            arguments_json = json.dumps(
                validated.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            valid = True
    except (ValueError, TypeError, RecursionError, ValidationError):
        pass
    result = evaluate(
        PolicyFacts(
            tool=operation.tool,
            text=operation.original_request,
            request_text=operation.original_request,
            arguments_json=arguments_json,
            valid_input=valid,
        ),
        judge if judge is not None else JudgeSignal(),
        agent_k if agent_k is not None else KSignal(),
    )
    if result.decision == "DENY":
        return Assessment(
            "SYNTHETIC_VERIFIED",
            "STOP",
            "B_POLICY_DENY",
            True,
            result.decision,
            tuple(result.reasons),
            "STOP",
        )
    if result.decision == "REVIEW_REQUIRED":
        return Assessment(
            "SYNTHETIC_VERIFIED",
            "HOLD",
            "B_POLICY_REVIEW_REQUIRED",
            True,
            result.decision,
            tuple(result.reasons),
        )
    return Assessment(
        "SYNTHETIC_VERIFIED",
        "ELIGIBILITY_ASSESSMENT_ONLY",
        "B_PERMIT_IS_NOT_EXECUTION",
        True,
        result.decision,
        tuple(result.reasons),
        "ASSESSMENT_ONLY_NO_EXECUTION",
    )
