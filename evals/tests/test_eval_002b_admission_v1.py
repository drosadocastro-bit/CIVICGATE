"""Owned local-file admission tests; synthetic units have no USD equivalence."""

from __future__ import annotations

import hashlib
import socket
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from evals.harness.attempt_budget_v2 import AttemptBudget as AcceptedR4Budget
from evals.harness.live_attempt_budget_v1 import (
    R4_SOURCE_SHA256,
    BudgetError,
    BudgetExceeded,
    BudgetStopped,
    BudgetUnavailable,
    LiveAttemptBudget,
    RecoveryBlocked,
)
from evals.harness.monetary_admission_v1 import MonetaryAdmission, SyntheticLiabilityPolicy

HASH = "1" * 64
OTHER_HASH = "2" * 64
LOGICAL = "https://synthetic-provider.invalid"
WIRE = "http://127.0.0.1:65431"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("NETWORK_FORBIDDEN_IN_ADMISSION_UNIT_TEST")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def budget(tmp_path: Path) -> LiveAttemptBudget:
    return LiveAttemptBudget.create(
        tmp_path / "synthetic.sqlite",
        "SYNTHETIC-RUN",
        liability_policy=SyntheticLiabilityPolicy(total_limit_units=100),
    )


def context(budget: LiveAttemptBudget, observation: str = "OBS", role: str = "planner") -> None:
    budget.begin_observation(observation)
    if role == "judge":
        budget.reserve_mcp(observation, HASH)
        budget.admit_mcp(observation, HASH)
    budget.bind_request_context(
        observation,
        role,
        HASH,
        HASH,
        LOGICAL,
        WIRE,
        effective_invocation_sha256=HASH if role == "judge" else None,
    )


def reserve(
    budget: LiveAttemptBudget, observation: str = "OBS", role: str = "planner", **kwargs: Any
) -> Any:
    return budget.reserve(observation, role, "SYNTHETIC-MODEL", HASH, HASH, HASH, **kwargs)


def send_kwargs(role: str = "planner") -> dict[str, Any]:
    return dict(
        observation_id="OBS",
        role=role,
        request_sha256=HASH,
        schema_sha256=HASH,
        logical_origin=LOGICAL,
        wire_fixture_origin=WIRE,
        effective_invocation_sha256=HASH if role == "judge" else None,
    )


def test_accepted_r4_source_remains_exact() -> None:
    import evals.harness.attempt_budget_v2 as r4

    assert hashlib.sha256(Path(r4.__file__).read_bytes()).hexdigest() == R4_SOURCE_SHA256
    assert issubclass(LiveAttemptBudget, AcceptedR4Budget)


def test_existing_r4_store_is_rejected_without_migration(tmp_path: Path) -> None:
    path = tmp_path / "historical.sqlite"
    AcceptedR4Budget.create(path, "SYNTHETIC-RUN")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(BudgetUnavailable):
        LiveAttemptBudget(path, "SYNTHETIC-RUN")
    with pytest.raises(FileExistsError):
        LiveAttemptBudget.create(path, "SYNTHETIC-RUN")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_default_real_cost_interface_blocks_before_reservation(tmp_path: Path) -> None:
    ledger = LiveAttemptBudget.create(tmp_path / "blocked.sqlite", "SYNTHETIC-RUN")
    context(ledger)
    with pytest.raises(BudgetError, match="MONETARY_ADMISSION_BLOCKED"):
        reserve(ledger)
    result = ledger.snapshot()
    assert result["attempts"] == result["liability_reservations"] == result["send_leases"] == []
    assert result["liability_policy"]["verified_limits_state"] == "UNKNOWN"
    assert result["liability_policy"]["admission_state"] == "BLOCKED"


def test_supplied_money_and_provenance_are_not_external_verification() -> None:
    value = MonetaryAdmission(
        currency="SYNTHETIC-NOT-USD",
        budget_limit="10",
        input_price_per_token="0.1",
        output_price_per_token="0.2",
        max_input_tokens=10,
        max_output_tokens=10,
        provenance="SYNTHETIC_FAKE_PROVENANCE",
    ).document()
    assert value["missing_or_invalid_inputs"] == []
    assert value["admission_state"] == "BLOCKED"
    assert value["verified_limits_state"] == "UNKNOWN"
    assert value["supplied_provenance_is_external_verification"] is False
    assert value["real_provider_activation"] is False


@pytest.mark.parametrize("amount", [None, "NaN", "Infinity", "-1", 3.4])
def test_invalid_or_absent_monetary_limits_stay_unknown(amount: Any) -> None:
    result = MonetaryAdmission(budget_limit=amount).document()
    assert "budget_limit" in result["missing_or_invalid_inputs"]
    assert result["admission_state"] == "BLOCKED"


def test_planner_needs_acknowledged_open_and_persisted_context(budget: LiveAttemptBudget) -> None:
    with pytest.raises(RecoveryBlocked):
        budget.bind_request_context("OBS", "planner", HASH, HASH, LOGICAL, WIRE)
    budget.begin_observation("OBS")
    with pytest.raises(BudgetError, match="PERSISTED_ROLE_CONTEXT_REQUIRED"):
        reserve(budget)
    assert budget.snapshot()["attempts"] == []


def test_judge_needs_matching_admitted_effective_invocation(budget: LiveAttemptBudget) -> None:
    budget.begin_observation("OBS")
    for state in ("MISSING", "RESERVED", "ADMITTED"):
        if state == "RESERVED":
            budget.reserve_mcp("OBS", HASH)
        if state == "ADMITTED":
            budget.admit_mcp("OBS", HASH)
        with pytest.raises(BudgetError, match="JUDGE_MATCHING_MCP_ADMISSION_REQUIRED"):
            budget.bind_request_context(
                "OBS",
                "judge",
                HASH,
                HASH,
                LOGICAL,
                WIRE,
                effective_invocation_sha256=OTHER_HASH,
            )
        assert budget.snapshot()["request_contexts"] == []
    budget.bind_request_context(
        "OBS", "judge", HASH, HASH, LOGICAL, WIRE, effective_invocation_sha256=HASH
    )
    assert len(budget.snapshot()["request_contexts"]) == 1


def test_reservation_and_liability_and_lease_commit_together(budget: LiveAttemptBudget) -> None:
    context(budget)
    item = reserve(budget)
    snapshot = LiveAttemptBudget(budget.path, budget.run_id).snapshot()
    assert snapshot["attempts"][0]["state"] == "RESERVED"
    assert snapshot["liability_reservations"][0]["attempt_id"] == item.attempt_id
    assert snapshot["send_leases"][0]["attempt_id"] == item.attempt_id
    assert snapshot["send_leases"][0]["state"] == "AVAILABLE"
    assert snapshot["reserved_liability_units"] == 1


def test_sql_failure_rolls_back_all_three_reservation_parts(budget: LiveAttemptBudget) -> None:
    context(budget)
    with sqlite3.connect(budget.path) as connection:
        connection.execute(
            "CREATE TRIGGER synthetic_fail BEFORE INSERT ON send_leases "
            "BEGIN SELECT RAISE(ABORT,'SYNTHETIC_INSERT_FAILURE'); END"
        )
    with pytest.raises(BudgetUnavailable):
        reserve(budget)
    snapshot = budget.snapshot()
    assert (
        snapshot["attempts"] == snapshot["liability_reservations"] == snapshot["send_leases"] == []
    )


def test_synthetic_cost_exhaustion_stops_without_partial_reservation(tmp_path: Path) -> None:
    ledger = LiveAttemptBudget.create(
        tmp_path / "small.sqlite",
        "SYNTHETIC-RUN",
        liability_policy=SyntheticLiabilityPolicy(
            total_limit_units=1, per_attempt_upper_bound_units={"planner": 2, "judge": 1}
        ),
    )
    context(ledger)
    with pytest.raises(BudgetExceeded, match="SYNTHETIC_LIABILITY_BUDGET_EXHAUSTED"):
        reserve(ledger)
    result = ledger.snapshot()
    assert result["stopped"]
    assert result["attempts"] == result["liability_reservations"] == result["send_leases"] == []


def test_send_requires_started_and_first_headers_lease_is_one_use(
    budget: LiveAttemptBudget,
) -> None:
    context(budget)
    item = reserve(budget)
    with pytest.raises(BudgetError, match="STARTED_ATTEMPT"):
        budget.consume_send_lease(**send_kwargs())
    budget.start(item)
    budget.assert_send_admissible(**send_kwargs())
    assert budget.snapshot()["send_leases"][0]["state"] == "AVAILABLE"
    receipt = budget.consume_send_lease(**send_kwargs())
    assert receipt.attempt_id == item.attempt_id
    assert receipt.request_sha256 == HASH
    assert receipt.acknowledged_at_utc
    with pytest.raises(BudgetError, match="ALREADY_CONSUMED"):
        budget.consume_send_lease(**send_kwargs())
    with pytest.raises(BudgetError, match="ALREADY_CONSUMED"):
        budget.assert_send_admissible(**send_kwargs())


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("request_sha256", OTHER_HASH),
        ("schema_sha256", OTHER_HASH),
        ("logical_origin", "https://other.invalid"),
        ("wire_fixture_origin", "http://127.0.0.1:65430"),
        ("effective_invocation_sha256", OTHER_HASH),
    ],
)
def test_send_mismatch_preserves_unconsumed_lease(
    budget: LiveAttemptBudget, field: str, replacement: str
) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    kwargs = send_kwargs()
    kwargs[field] = replacement
    with pytest.raises(BudgetError, match="CONTEXT_MISMATCH"):
        budget.consume_send_lease(**kwargs)
    assert budget.snapshot()["send_leases"][0]["state"] == "AVAILABLE"


def test_judge_mcp_terminal_before_send_rejects_without_consuming(
    budget: LiveAttemptBudget,
) -> None:
    context(budget, role="judge")
    item = reserve(budget, role="judge")
    budget.start(item)
    budget.finish_mcp("OBS", "CLIENT_RESPONSE_OBSERVED")
    with pytest.raises(BudgetError, match="JUDGE_MATCHING_MCP_ADMISSION_REQUIRED"):
        budget.consume_send_lease(**send_kwargs("judge"))
    assert budget.snapshot()["send_leases"][0]["state"] == "AVAILABLE"


def test_cost_proof_removed_before_send_rejects(budget: LiveAttemptBudget) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    with sqlite3.connect(budget.path) as connection:
        connection.execute("DELETE FROM liability_reservations")
    with pytest.raises(BudgetError, match="LIABILITY_RESERVATION_REQUIRED"):
        budget.consume_send_lease(**send_kwargs())
    assert budget.snapshot()["send_leases"][0]["state"] == "AVAILABLE"


def test_terminal_known_response_never_erases_open_or_refunds(budget: LiveAttemptBudget) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    budget.consume_send_lease(**send_kwargs())
    budget.finish(item, "RESPONSE_OBSERVED")
    reopened = LiveAttemptBudget(budget.path, budget.run_id)
    assert reopened.snapshot()["observation_fences"][0]["state"] == "OPEN"
    assert reopened.snapshot()["reserved_liability_units"] == 1
    assert reopened.snapshot()["send_leases"][0]["state"] == "CONSUMED"
    with pytest.raises(RecoveryBlocked):
        reopened.begin_observation("OTHER")
    with pytest.raises(RecoveryBlocked):
        reopened.ensure_recoverable()


def test_known_no_send_retains_liability_and_lease(budget: LiveAttemptBudget) -> None:
    context(budget)
    item = reserve(budget)
    budget.finish(item, "RESERVATION_NO_SEND")
    assert budget.snapshot()["reserved_liability_units"] == 1
    assert budget.snapshot()["send_leases"][0]["state"] == "AVAILABLE"
    with pytest.raises(BudgetError, match="STARTED_ATTEMPT"):
        budget.consume_send_lease(**send_kwargs())


def test_unknown_no_refund_and_no_automatic_retry(budget: LiveAttemptBudget) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    budget.finish(item, "COMPLETION_UNKNOWN")
    assert budget.snapshot()["reserved_liability_units"] == 1
    with pytest.raises(BudgetStopped):
        reserve(budget, retry_count=1, retry_reason="SYNTHETIC_UNKNOWN")


def test_failed_stop_after_open_still_fences_restart(
    budget: LiveAttemptBudget, monkeypatch: pytest.MonkeyPatch
) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    budget.finish(item, "RESPONSE_OBSERVED")

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise BudgetUnavailable("SYNTHETIC_STOP_WRITE_FAILURE")

    monkeypatch.setattr(budget, "stop", unavailable)
    with pytest.raises(BudgetUnavailable):
        budget.stop("SYNTHETIC_STOP")
    reopened = LiveAttemptBudget(budget.path, budget.run_id)
    assert reopened.snapshot()["stopped"] is False
    assert reopened.snapshot()["observation_fences"][0]["state"] == "OPEN"
    with pytest.raises(RecoveryBlocked):
        reopened.begin_observation("NEW")


@pytest.mark.parametrize(
    "wire",
    [
        "https://127.0.0.1:1234",
        "http://localhost:1234",
        "http://example.com:1234",
        "http://127.0.0.1",
        "http://127.0.0.1:1234/path",
    ],
)
def test_nonowned_wire_shape_rejected(budget: LiveAttemptBudget, wire: str) -> None:
    budget.begin_observation("OBS")
    with pytest.raises(ValueError):
        budget.bind_request_context("OBS", "planner", HASH, HASH, LOGICAL, wire)
    assert budget.snapshot()["request_contexts"] == []


def test_shared_exact_six_observations_and_twelve_attempts_per_role(
    budget: LiveAttemptBudget,
) -> None:
    for index in range(6):
        observation = f"SYNTHETIC-OBS-{index}"
        context(budget, observation)
        for role in ("planner", "judge"):
            if role == "judge":
                context(budget, observation, role)
            for retry in (0, 1):
                item = reserve(
                    budget,
                    observation,
                    role,
                    retry_count=retry,
                    retry_reason="SYNTHETIC_EXPLICIT_KNOWN_RESPONSE" if retry else None,
                )
                budget.start(item)
                kwargs = send_kwargs(role)
                kwargs["observation_id"] = observation
                budget.consume_send_lease(**kwargs)
                budget.finish(item, "RESPONSE_OBSERVED")
        budget.finish_mcp(observation, "CLIENT_RESPONSE_OBSERVED")
        budget.close_safe_observation(observation, HASH)
    result = budget.snapshot()
    assert result["counts"] == {"planner": 12, "judge": 12}
    assert result["observation_count"] == 6
    assert result["reserved_liability_units"] == 24
    assert len(result["send_leases"]) == 24
    assert all(row["state"] == "CONSUMED" for row in result["send_leases"])
    with pytest.raises(BudgetExceeded, match="OBSERVATION_BUDGET_EXHAUSTED"):
        budget.begin_observation("SYNTHETIC-SEVENTH")
    assert budget.snapshot()["stopped"]


@pytest.mark.parametrize(
    "caps,observations",
    [
        ({"planner": 13, "judge": 12}, 6),
        ({"planner": 12, "judge": 13}, 6),
        ({"planner": 12, "judge": 12}, 7),
    ],
)
def test_accepted_absolute_ceilings_cannot_be_raised(
    tmp_path: Path,
    caps: dict[str, int],
    observations: int,
) -> None:
    with pytest.raises(ValueError):
        LiveAttemptBudget.create(
            tmp_path / "invalid.sqlite",
            "SYNTHETIC-RUN",
            role_caps=caps,
            max_observations=observations,
            liability_policy=SyntheticLiabilityPolicy(total_limit_units=100),
        )
    assert not (tmp_path / "invalid.sqlite").exists()


def response_facts() -> dict[str, Any]:
    return {
        "http_status": 200,
        "body_sha256": HASH,
        "body_bytes": 42,
        "returned_model": "SYNTHETIC-MODEL",
        "model_identity": "MATCH",
        "completion": "COMPLETE",
        "refusal": "ABSENT_OR_NULL",
        "usage": "UNKNOWN",
        "typed_schema": "NOT_PARSED",
        "contract": "FAIL",
        "errors": ["USAGE_UNKNOWN"],
    }


def test_response_facts_are_acknowledged_once_and_do_not_imply_acceptance(
    budget: LiveAttemptBudget,
) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    with pytest.raises(BudgetError, match="CONSUMED_SEND_LEASE_REQUIRED"):
        budget.record_response_facts(
            observation_id="OBS", role="planner", request_sha256=HASH, facts=response_facts()
        )
    budget.consume_send_lease(**send_kwargs())
    receipt = budget.record_response_facts(
        observation_id="OBS", role="planner", request_sha256=HASH, facts=response_facts()
    )
    result = budget.snapshot()
    assert receipt.attempt_id == item.attempt_id
    assert receipt.acknowledged_at_utc
    assert result["response_facts"][0]["facts_sha256"] == receipt.facts_sha256
    assert result["response_facts"][0]["facts"]["usage"] == "UNKNOWN"
    assert result["response_facts"][0]["facts"]["contract"] == "FAIL"
    assert result["attempts"][0]["state"] == "IN_FLIGHT"
    assert result["observation_fences"][0]["state"] == "OPEN"
    with pytest.raises(BudgetError, match="ALREADY_ACKNOWLEDGED"):
        budget.record_response_facts(
            observation_id="OBS", role="planner", request_sha256=HASH, facts=response_facts()
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("http_status", True),
        ("http_status", 99),
        ("body_sha256", "UNKNOWN"),
        ("body_bytes", -1),
        ("returned_model", "X" * 201),
        ("model_identity", "PASS"),
        ("completion", None),
        ("refusal", False),
        ("usage", "ASSUMED"),
        ("typed_schema", "UNKNOWN"),
        ("contract", "UNKNOWN"),
        ("errors", ["X"] * 17),
    ],
)
def test_response_fact_validation_rejects_ambiguity_before_writes(
    budget: LiveAttemptBudget,
    field: str,
    value: Any,
) -> None:
    facts = response_facts()
    facts[field] = value
    with pytest.raises(ValueError):
        budget.record_response_facts(
            observation_id="OBS", role="planner", request_sha256=HASH, facts=facts
        )
    assert budget.snapshot()["response_facts"] == []


def test_failed_response_facts_write_leaves_started_consumed_custody_unknown(
    budget: LiveAttemptBudget,
) -> None:
    context(budget)
    item = reserve(budget)
    budget.start(item)
    budget.consume_send_lease(**send_kwargs())
    with sqlite3.connect(budget.path) as connection:
        connection.execute(
            "CREATE TRIGGER synthetic_response_failure BEFORE INSERT ON response_facts "
            "BEGIN SELECT RAISE(ABORT,'SYNTHETIC_RESPONSE_FACTS_FAILURE'); END"
        )
    with pytest.raises(BudgetUnavailable):
        budget.record_response_facts(
            observation_id="OBS", role="planner", request_sha256=HASH, facts=response_facts()
        )
    result = LiveAttemptBudget(budget.path, budget.run_id).snapshot()
    assert result["response_facts"] == []
    assert result["attempts"][0]["state"] == "IN_FLIGHT"
    assert result["send_leases"][0]["state"] == "CONSUMED"
    assert result["observation_fences"][0]["state"] == "OPEN"
