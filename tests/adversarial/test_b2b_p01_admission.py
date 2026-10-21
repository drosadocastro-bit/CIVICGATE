"""Independent synthetic fixture authority for P0-01..10; no real trust source.

Fixture construction hashes invented bytes ONLY to predeclare test expectations.
The assessment never enrolls payloads or promotes a calculated hash into trust.
No fixture describes an actual Channel A invocation or Databricks identity.
"""

import ast
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, asdict, dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from civicgate.governance.policy import evaluate
from civicgate.models.governance import JudgeSignal, KSignal
from experiments import b2b_p01_admission_v1 as harness
from experiments.b2b_p01_admission_v1 import (
    Assessment,
    Identity,
    Operation,
    SyntheticTrustFacts,
    assess,
)

GOOD = JudgeSignal(classification="IN_SCOPE", confidence=1, available=True, provider="synthetic")


def encode(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def document() -> dict[str, Any]:
    return {
        "scope": "SYNTHETIC_ONLY",
        "producer": "synthetic-independent-fixture",
        "observed_at": 100,
        "identity": {
            "issuer": "https://synthetic.invalid",
            "audience": "synthetic-b2b-p01",
            "caller": "synthetic-caller",
            "caller_kind": "USER",
            "service_principal": "synthetic-service",
            "proxy": "synthetic-proxy",
            "session": "synthetic-session",
            "credential_reference": "synthetic-token-reference",
            "instance": "synthetic-instance",
            "expires_at": 200,
        },
        "operation": {
            "operation_id": "synthetic-logical-operation",
            "original_request": "Get public awards",
            "tool": "get_federal_award",
            "arguments_json": '{"award_id":"SYNTHETIC-1"}',
        },
        "attempts": [
            {
                "attempt_id": "synthetic-attempt-one",
                "operation_id": "synthetic-logical-operation",
                "initial_policy": "PERMIT",
                "intent": "NOT_COMMITTED",
                "delegation": "NOT_DELEGATED",
                "outcome": "TECHNICAL_FAILURE_NOT_DISPATCHED",
                "terminal": True,
                "recorded_at": 99,
            }
        ],
        "recovery_hold": False,
        "binding_reference": None,
    }


@dataclass(frozen=True)
class FixtureVerifier:
    """Exact pre-enrolled synthetic fixture; unregistered bytes have no endorsement."""

    raw: bytes
    facts: SyntheticTrustFacts

    def verify(self, raw: bytes) -> SyntheticTrustFacts | None:
        return self.facts if raw == self.raw else None


def fixture(doc: dict[str, Any] | None = None, /, **external: Any) -> tuple[bytes, FixtureVerifier]:
    d = document() if doc is None else doc
    raw = encode(d)
    values: dict[str, Any] = {
        "scope": "SYNTHETIC_ONLY",
        "history_coverage": "SYNTHETIC_SCENARIO_ONLY",
        "expected_sha256": hashlib.sha256(raw).hexdigest(),
        "producer": d["producer"],
        "identity": Identity.model_validate(d["identity"]),
        "operation": Operation.model_validate(d["operation"]),
        "attempt_ids": tuple(a["attempt_id"] for a in d["attempts"]),
        "observed_at": 100,
        "valid_until": 150,
        "caller_authenticated": True,
        "trusted_proxy": True,
        "app_access": True,
        "machine_authorized": False,
        "recovery_hold": False,
        "held_operations": frozenset(),
        "used_operations": frozenset(),
        "used_sessions": frozenset(),
        "revoked_credentials": frozenset(),
    }
    values.update(external)
    return raw, FixtureVerifier(raw, SyntheticTrustFacts.model_validate(values))


def scenario(number: int) -> tuple[bytes | None, FixtureVerifier, dict[str, Any]]:
    d = document()
    options: dict[str, Any] = {"now": 110, "judge": GOOD}
    external: dict[str, Any] = {}
    if number in (1, 2):
        d["attempts"][0].update(
            initial_policy="DENY" if number == 1 else "REVIEW_REQUIRED", outcome="POLICY_STOP"
        )
        options.update(channel_b_available=True, inspect_b_policy=True)
    elif number == 3:
        d["attempts"][0].update(
            intent="COMMITTED", delegation="DELEGATED", outcome="DISPATCH_UNKNOWN", terminal=False
        )
    elif number == 5:
        options["now"] = 150
    elif number == 6:
        external["trusted_proxy"] = False
    elif number == 7:
        d["identity"]["caller"] = d["identity"]["service_principal"]
    elif number == 8:
        external["used_sessions"] = frozenset({"synthetic-session"})
    elif number == 9:
        options.update(inspect_b_policy=True, agent_k=KSignal(containment=True))
    elif number == 10:
        options.update(inspect_b_policy=True, judge=JudgeSignal())
    raw, verifier = fixture(d, **external)
    return raw, verifier, options


EXPECTED = [
    ("STOP", "CHANNEL_A_DENY", False, None, "SYNTHETIC_VERIFIED"),
    ("HOLD", "CHANNEL_A_PRE_DISPATCH_REVIEW", False, None, "SYNTHETIC_VERIFIED"),
    ("HOLD", "DISPATCH_UNKNOWN", False, None, "SYNTHETIC_VERIFIED"),
    ("ELIGIBILITY_ASSESSMENT_ONLY", "SYNTHETIC_NOT_DISPATCHED", False, None, "SYNTHETIC_VERIFIED"),
    ("HOLD", "STALE_OR_CONTRADICTORY_OBSERVATION", False, None, "FAILED"),
    ("REJECTED", "UNVERIFIED_INGRESS_OR_APP_ACCESS", False, None, "FAILED"),
    ("REJECTED", "CALLER_SERVICE_PRINCIPAL_CONFUSION", False, None, "FAILED"),
    ("REJECTED", "REPLAYED_SYNTHETIC_SESSION", False, None, "FAILED"),
    ("STOP", "B_POLICY_DENY", True, "DENY", "SYNTHETIC_VERIFIED"),
    ("HOLD", "B_POLICY_REVIEW_REQUIRED", True, "REVIEW_REQUIRED", "SYNTHETIC_VERIFIED"),
]


def assert_inert(result: Assessment) -> None:
    assert result.binding_issued is False
    assert result.adapter_dispatches == 0
    assert result.result_disposition == "NO_RESULT"
    assert result.scope == "SYNTHETIC_ONLY"


@pytest.mark.parametrize("number", range(1, 11), ids=lambda n: f"P0-{n:02d}")
def test_required_scenarios(number: int, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    original = evaluate

    def observe(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(harness, "evaluate", observe)
    raw, verifier, options = scenario(number)
    result = assess(raw, verifier, **options)
    assert (
        result.admission,
        result.reason,
        result.b_policy_reached,
        result.b_policy_decision,
        result.evidence_verification,
    ) == EXPECTED[number - 1]
    assert len(calls) == int(result.b_policy_reached)
    assert_inert(result)


@pytest.mark.parametrize("available", [False, True])
def test_availability_cannot_change_denial(available: bool) -> None:
    raw, verifier, options = scenario(1)
    options["channel_b_available"] = available
    result = assess(raw, verifier, **options)
    assert result.admission == "STOP" and not result.b_policy_reached


@pytest.mark.parametrize(
    "bad",
    [None, b"", b"{", b"null", b"[]", b"x" * 65537],
    ids=["missing", "empty", "truncated", "null", "array", "oversized"],
)
def test_absent_or_malformed_evidence_holds(bad: bytes | None) -> None:
    _, verifier = fixture()
    result = assess(bad, verifier, now=110, inspect_b_policy=True)
    assert result.admission == "HOLD" and not result.b_policy_reached


@pytest.mark.parametrize(
    "field,value", [("is_verified", True), ("sha256", "a" * 64), ("PERMIT", True)]
)
def test_payload_cannot_self_attest(field: str, value: object) -> None:
    raw, verifier = fixture()
    d = json.loads(raw)
    d[field] = value
    result = assess(encode(d), verifier, now=110)
    assert result.reason == "MALFORMED_EVIDENCE"


def test_tamper_and_self_computed_hash_do_not_enroll_bytes() -> None:
    raw, verifier = fixture()
    d = json.loads(raw)
    d["producer"] = "synthetic-forged"
    forged = encode(d)
    assert hashlib.sha256(forged).hexdigest() != verifier.facts.expected_sha256
    assert assess(forged, verifier, now=110).reason == "NO_INDEPENDENT_SYNTHETIC_TRUST"


def test_dependency_cannot_accidentally_attest_other_bytes() -> None:
    raw, verifier = fixture(expected_sha256="0" * 64)
    assert assess(raw, verifier, now=110).reason == "INDEPENDENT_IDENTITY_MISMATCH"


@pytest.mark.parametrize("failure", [None, RuntimeError("synthetic outage"), {"is_verified": True}])
def test_missing_faulty_or_untyped_verifier_fails_closed(failure: Any) -> None:
    class Broken:
        def verify(self, raw: bytes) -> Any:
            if isinstance(failure, Exception):
                raise failure
            return failure

    result = assess(fixture()[0], Broken(), now=110, inspect_b_policy=True)
    assert result.admission == "HOLD" and not result.b_policy_reached


@pytest.mark.parametrize("field", ["caller_authenticated", "trusted_proxy", "app_access"])
def test_independent_ingress_requirements(field: str) -> None:
    raw, verifier = fixture(**{field: False})
    assert assess(raw, verifier, now=110).reason == "UNVERIFIED_INGRESS_OR_APP_ACCESS"


@pytest.mark.parametrize(
    "field", ["caller", "service_principal", "proxy", "session", "credential_reference", "instance"]
)
def test_coherently_hashed_foreign_identity_still_rejected(field: str) -> None:
    d = document()
    original_identity = Identity.model_validate(d["identity"])
    d["identity"][field] = "synthetic-foreign"
    raw, verifier = fixture(d, identity=original_identity)
    assert assess(raw, verifier, now=110).reason == "CALLER_SESSION_OR_TOKEN_MISMATCH"


@pytest.mark.parametrize("authorized", [False, True])
def test_machine_caller_requires_separate_fixture_authorization(authorized: bool) -> None:
    d = document()
    d["identity"]["caller_kind"] = "MACHINE"
    raw, verifier = fixture(d, machine_authorized=authorized)
    result = assess(raw, verifier, now=110)
    assert result.admission == ("ELIGIBILITY_ASSESSMENT_ONLY" if authorized else "REJECTED")
    assert_inert(result)


@pytest.mark.parametrize("expiry", [0, 109, 110])
def test_expired_at_assessment_or_after_queue(expiry: int) -> None:
    d = document()
    d["identity"]["expires_at"] = expiry
    raw, verifier = fixture(d)
    assert assess(raw, verifier, now=110).reason == "EXPIRED_OR_REVOKED_SYNTHETIC_CREDENTIAL"


def test_known_revocation_blocks() -> None:
    raw, verifier = fixture(revoked_credentials=frozenset({"synthetic-token-reference"}))
    assert assess(raw, verifier, now=110).admission == "REJECTED"


@pytest.mark.parametrize(
    "claim",
    [
        "synthetic-A-binding",
        "synthetic-foreign-binding",
        "synthetic-consumed-binding",
        "synthetic-expired-binding",
    ],
)
def test_any_transferred_binding_claim_is_rejected(claim: str) -> None:
    d = document()
    d["binding_reference"] = claim
    raw, verifier = fixture(d)
    assert assess(raw, verifier, now=110).reason == "TRANSFERRED_BINDING_FORBIDDEN"


@pytest.mark.parametrize("field", ["held_operations", "used_operations"])
def test_new_attempt_identifier_does_not_escape_logical_hold(field: str) -> None:
    d = document()
    d["attempts"][0]["attempt_id"] = "synthetic-new-attempt"
    raw, verifier = fixture(d, **{field: frozenset({"synthetic-logical-operation"})})
    assert assess(raw, verifier, now=110).reason == "RECOVERY_OR_REPLAY_HOLD"


@pytest.mark.parametrize("claimed,trusted", [(True, True), (False, True), (True, False)])
def test_recovery_hold_cannot_be_discarded(claimed: bool, trusted: bool) -> None:
    d = document()
    d["recovery_hold"] = claimed
    raw, verifier = fixture(d, recovery_hold=trusted)
    result = assess(raw, verifier, now=110)
    assert result.admission == "HOLD"
    assert result.reason == (
        "RECOVERY_OR_REPLAY_HOLD" if claimed == trusted else "CONTRADICTORY_RECOVERY_STATE"
    )


@pytest.mark.parametrize("now", [99, 150, 151])
def test_snapshot_freshness_boundaries(now: int) -> None:
    raw, verifier = fixture()
    assert assess(raw, verifier, now=now).reason == "STALE_OR_CONTRADICTORY_OBSERVATION"


@pytest.mark.parametrize(
    "change",
    [
        {"terminal": False},
        {"delegation": "DELEGATED", "intent": "COMMITTED"},
        {"delegation": "UNKNOWN"},
        {"intent": "UNKNOWN"},
        {"initial_policy": "DENY", "intent": "COMMITTED"},
        {"recorded_at": 101},
        {"operation_id": "synthetic-other-operation"},
    ],
)
def test_coherently_pinned_contradictions_cannot_claim_no_dispatch(change: dict[str, Any]) -> None:
    d = document()
    d["attempts"][0].update(change)
    raw, verifier = fixture(d)
    result = assess(raw, verifier, now=110, inspect_b_policy=True)
    assert result.admission == "HOLD" and result.evidence_verification == "FAILED"
    assert not result.b_policy_reached


def test_independent_complete_history_prevents_omitted_subattempt() -> None:
    raw, verifier = fixture(attempt_ids=("synthetic-hidden-attempt", "synthetic-attempt-one"))
    assert assess(raw, verifier, now=110).reason == "INCOMPLETE_OR_REUSED_ATTEMPT_HISTORY"


@pytest.mark.parametrize(
    "first", ["DENY", "REVIEW_REQUIRED", "DISPATCH_UNKNOWN", "RESPONSE_RECEIVED", "INCOMPLETE"]
)
def test_earlier_attempt_not_hidden_by_later_technical_failure(first: str) -> None:
    d = document()
    a = copy.deepcopy(d["attempts"][0])
    a.update(attempt_id="synthetic-earlier", recorded_at=98)
    if first in {"DENY", "REVIEW_REQUIRED"}:
        a.update(initial_policy=first, outcome="POLICY_STOP")
    else:
        a.update(outcome=first, intent="COMMITTED", delegation="DELEGATED")
    d["attempts"].insert(0, a)
    raw, verifier = fixture(d)
    result = assess(raw, verifier, now=110)
    assert result.admission == ("STOP" if first == "DENY" else "HOLD")


@pytest.mark.parametrize("mutation", ["duplicate", "reordered", "empty"])
def test_history_order_and_uniqueness(mutation: str) -> None:
    d = document()
    if mutation == "empty":
        raw, verifier = fixture()
        d["attempts"] = []
        assert assess(encode(d), verifier, now=110).reason == "MALFORMED_EVIDENCE"
        return
    a = copy.deepcopy(d["attempts"][0])
    if mutation == "reordered":
        a.update(attempt_id="synthetic-earlier", recorded_at=98)
    d["attempts"].append(a)
    raw, verifier = fixture(d)
    assert assess(raw, verifier, now=110).admission == "HOLD"


@pytest.mark.parametrize(
    "invalid",
    ["duplicate", "nan", "boolean-tick", "wrong-bool", "extra-nested", "missing", "wrong-issuer"],
)
def test_strict_parser(invalid: str) -> None:
    raw, verifier = fixture()
    d = json.loads(raw)
    if invalid == "duplicate":
        raw = raw.replace(b'"observed_at":100', b'"observed_at":100,"observed_at":100')
    elif invalid == "nan":
        raw = raw.replace(b'"observed_at":100', b'"observed_at":NaN')
    else:
        if invalid == "boolean-tick":
            d["observed_at"] = True
        elif invalid == "wrong-bool":
            d["recovery_hold"] = "false"
        elif invalid == "extra-nested":
            d["identity"]["verified"] = True
        elif invalid == "missing":
            del d["attempts"]
        elif invalid == "wrong-issuer":
            d["identity"]["issuer"] = "https://untrusted.invalid"
        raw = encode(d)
    assert assess(raw, verifier, now=110).reason == "MALFORMED_EVIDENCE"


@pytest.mark.parametrize(
    "operation",
    [
        {"tool": "hidden_admin_tool"},
        {"arguments_json": '{"award_id":null}'},
        {"arguments_json": '{"award_id":"X","award_id":"Y"}'},
        {"original_request": "Execute payment."},
    ],
)
def test_real_policy_denies_invalid_or_prohibited_proposals(operation: dict[str, str]) -> None:
    d = document()
    d["operation"].update(operation)
    raw, verifier = fixture(d)
    result = assess(raw, verifier, now=110, inspect_b_policy=True, judge=GOOD)
    assert result.b_policy_decision == "DENY" and result.admission == "STOP"
    assert_inert(result)


@pytest.mark.parametrize(
    "signal", [JudgeSignal(), JudgeSignal(classification="AMBIGUOUS", confidence=1, available=True)]
)
def test_unavailable_or_conflicting_judge_keeps_review(signal: JudgeSignal) -> None:
    raw, verifier = fixture()
    assert (
        assess(raw, verifier, now=110, inspect_b_policy=True, judge=signal).b_policy_decision
        == "REVIEW_REQUIRED"
    )


def test_real_policy_permit_is_only_an_inert_diagnostic() -> None:
    raw, verifier = fixture()
    result = assess(raw, verifier, now=110, inspect_b_policy=True, judge=GOOD)
    assert (
        result.b_policy_decision == "PERMIT" and result.admission == "ELIGIBILITY_ASSESSMENT_ONLY"
    )
    assert result.recovery_disposition == "ASSESSMENT_ONLY_NO_EXECUTION"
    assert_inert(result)
    with pytest.raises(FrozenInstanceError):
        result.binding_issued = True  # type: ignore[misc, assignment]
    with pytest.raises(TypeError):
        Assessment("FAILED", "HOLD", "x", binding_issued=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        verifier.facts.identity.caller = "synthetic-other"


def test_pure_repeat_assessment_does_not_consume_or_modify_history() -> None:
    raw, verifier = fixture()
    before = verifier.facts.model_dump_json()
    first = assess(raw, verifier, now=110)
    assert first == assess(raw, verifier, now=110)
    assert verifier.facts.model_dump_json() == before
    assert not hasattr(harness, "advance") and not hasattr(harness, "dispatch")


@pytest.mark.parametrize("bad_clock", [True, -1, 110.0, "110"])
def test_untyped_clock_is_not_a_time_attestation(bad_clock: Any) -> None:
    raw, verifier = fixture()
    assert assess(raw, verifier, now=bad_clock).reason == "INVALID_SYNTHETIC_CLOCK"


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_id", "synthetic-relabelled"),
        ("original_request", "Execute payment."),
        ("tool", "resolve_federal_recipient"),
        ("arguments_json", '{"award_id":"DIFFERENT"}'),
    ],
)
def test_coherent_digest_does_not_override_independent_operation_binding(
    field: str, value: str
) -> None:
    d = document()
    original_operation = Operation.model_validate(d["operation"])
    d["operation"][field] = value
    raw, verifier = fixture(d, operation=original_operation)
    assert assess(raw, verifier, now=110).reason == "PRODUCER_OR_OPERATION_MISMATCH"


def test_independent_producer_and_observation_bindings() -> None:
    raw, verifier = fixture(producer="synthetic-other-producer")
    assert assess(raw, verifier, now=110).reason == "PRODUCER_OR_OPERATION_MISMATCH"
    raw, verifier = fixture(observed_at=101)
    assert assess(raw, verifier, now=110).reason == "STALE_OR_CONTRADICTORY_OBSERVATION"


def test_independent_verifier_cannot_bypass_type_validation() -> None:
    raw, verifier = fixture()
    malformed = verifier.facts.model_copy(update={"caller_authenticated": "true"})
    assert (
        assess(raw, FixtureVerifier(raw, malformed), now=110).reason
        == "INVALID_SYNTHETIC_TRUST_FACTS"
    )


def test_assessments_cannot_reach_authority_adapter_network_or_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from civicgate.adapters.usaspending import USAspending
    from civicgate.governance.execution import ExecutionBoundary

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("P0.1 reached a forbidden side effect")

    cases = [scenario(n) for n in range(1, 11)]
    raw, verifier = fixture()
    cases.append((raw, verifier, {"now": 110, "inspect_b_policy": True, "judge": GOOD}))
    with monkeypatch.context() as patch:
        patch.setattr(ExecutionBoundary, "evaluate", forbidden)
        patch.setattr(USAspending, "__init__", forbidden)
        patch.setattr("socket.socket.connect", forbidden)
        patch.setattr("builtins.open", forbidden)
        patch.setattr(Path, "write_bytes", forbidden)
        patch.setattr(Path, "write_text", forbidden)
        for case_raw, case_verifier, options in cases:
            assert_inert(assess(case_raw, case_verifier, **options))


def test_harness_imports_no_execution_network_or_storage_path() -> None:
    tree = ast.parse(Path(harness.__file__).read_text(encoding="utf-8"))
    modules = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert modules <= {
        "hashlib",
        "json",
        "dataclasses",
        "typing",
        "pydantic",
        "civicgate.governance.policy",
        "civicgate.models.governance",
        "civicgate.models.requests",
    }


def evidence_matrix() -> list[dict[str, Any]]:
    """Test runner may serialize this outside the source tree; not a live interface."""
    rows = []
    for number in range(1, 11):
        raw, verifier, options = scenario(number)
        result = assess(raw, verifier, **options)
        rows.append({"scenario": f"P0-{number:02d}", **asdict(result)})
    return rows
