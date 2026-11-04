"""Actual original ExecutionBoundary with versioned scope; no new issuer."""

from __future__ import annotations

import hashlib
import json

import pytest

from civicgate.governance.execution import ExecutionBoundary, ExecutionBoundaryError
from civicgate.governance.policy import PolicyFacts
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import Search
from evals.proposals.r022.faa_contract_v1 import (
    FAA_FY2026_PR_CONTRACT,
    FaaFy2026PrReadV1,
    example_query,
)
from evals.proposals.r022.stdio_v1 import CANONICAL_REQUEST

CONTEXT = (True, True, 0.85, 0)
JUDGE = JudgeSignal(
    available=True,
    classification="IN_SCOPE",
    confidence=0.99,
    flags=[],
    provider="SYNTHETIC_R022_BINDING_TEST",
)
TOOL = "find_federal_awards"


def canonical(obj):
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def boundary():
    return ExecutionBoundary(FAA_FY2026_PR_CONTRACT.registry, contract=FAA_FY2026_PR_CONTRACT)


def evaluation(owner, *, query=None, missing_facts=False):
    query = FaaFy2026PrReadV1.model_validate(
        example_query() if query is None else query
    ).model_dump(mode="json")
    facts = PolicyFacts(
        tool=TOOL,
        text=CANONICAL_REQUEST + "\n" + canonical(query),
        request_text=CANONICAL_REQUEST,
        arguments_json=None if missing_facts else canonical(query),
    )
    result = owner.evaluate(
        request_id="R022_SYNTHETIC_BINDING",
        facts=facts,
        judge=JUDGE,
        agent_k=KSignal(),
        threshold=0.85,
        arguments=query,
        policy_context=CONTEXT,
    )
    return result, query, facts


def consume(owner, envelope, query):
    return owner.consume(
        envelope,
        request_id="R022_SYNTHETIC_BINDING",
        tool=TOOL,
        arguments=query,
        policy_context=CONTEXT,
    )


def test_profile_permit_binds_every_effective_scope_field_and_actual_schema():
    owner = boundary()
    result, query, _ = evaluation(owner)
    assert result.policy.decision == "PERMIT" and result.envelope is not None
    binding = consume(owner, result.envelope, query)
    assert binding.arguments_json == canonical(query)
    assert json.loads(binding.arguments_json) == query
    for field in (
        "profile_id",
        "agency_tier",
        "agency_type",
        "agency_toptier_name",
        "awarding_agency",
        "fiscal_year",
        "start_date",
        "end_date",
        "date_semantics",
        "state_code",
        "award_types",
    ):
        assert json.loads(binding.arguments_json)[field] == query[field]
    assert binding.arguments_sha256 == hashlib.sha256(canonical(query).encode()).hexdigest()
    assert (
        binding.schema_sha256
        == hashlib.sha256(canonical(FaaFy2026PrReadV1.model_json_schema()).encode()).hexdigest()
    )
    assert (
        binding.policy_decision == "PERMIT"
        and binding.operation_scope == "PUBLIC_SPENDING_RESEARCH"
    )
    assert result.envelope.policy_version == "civicgate-mvp-1"


def test_consumed_profile_envelope_cannot_be_replayed():
    owner = boundary()
    result, query, _ = evaluation(owner)
    consume(owner, result.envelope, query)
    with pytest.raises(ExecutionBoundaryError, match="ENVELOPE_ALREADY_CONSUMED_OR_UNKNOWN"):
        consume(owner, result.envelope, query)


def test_separate_legacy_boundary_cannot_consume_profile_envelope():
    owner = boundary()
    result, query, _ = evaluation(owner)
    with pytest.raises(ExecutionBoundaryError, match="ENVELOPE_ALREADY_CONSUMED_OR_UNKNOWN"):
        consume(ExecutionBoundary(), result.envelope, query)
    # Refusal by another owner does not consume the real owner's retained object.
    assert consume(owner, result.envelope, query).arguments_json == canonical(query)


@pytest.mark.parametrize(
    "change",
    [
        {"profile_id": "legacy"},
        {"agency_tier": "toptier"},
        {"awarding_agency": "Department of Transportation"},
        {"agency_toptier_name": "Other Department"},
        {"state_code": "CA"},
        {"start_date": "2025-09-30"},
        {"end_date": "2026-10-01"},
        {"fiscal_year": 2025},
        {"limit": 5},
        {"award_types": ["A"]},
    ],
)
def test_scope_tampering_is_rejected_and_cannot_be_retried_with_original_arguments(change):
    owner = boundary()
    result, query, _ = evaluation(owner)
    with pytest.raises(ExecutionBoundaryError):
        consume(owner, result.envelope, dict(query, **change))
    with pytest.raises(ExecutionBoundaryError, match="ENVELOPE_ALREADY_CONSUMED_OR_UNKNOWN"):
        consume(owner, result.envelope, query)


def test_profile_boundary_requires_complete_policy_argument_context_before_issuance():
    owner = boundary()
    result, _, _ = evaluation(owner, missing_facts=True)
    assert result.policy.decision == "DENY" and result.envelope is None
    assert "INVALID_CONTRACT_SCOPE" in result.policy.reasons


def test_legacy_optional_argument_context_stays_supported_without_a_profile():
    owner = ExecutionBoundary()
    query = Search.model_validate(
        {"start_date": "2025-10-01", "end_date": "2026-09-30", "state_code": "PR"}
    ).model_dump(mode="json")
    result = owner.evaluate(
        request_id="R022_SYNTHETIC_LEGACY_BINDING",
        facts=PolicyFacts(tool=TOOL, text="public awards"),
        judge=JUDGE,
        agent_k=KSignal(),
        threshold=0.85,
        arguments=query,
        policy_context=CONTEXT,
    )
    assert result.policy.decision == "PERMIT" and result.envelope is not None
    bound = owner.consume(
        result.envelope,
        request_id="R022_SYNTHETIC_LEGACY_BINDING",
        tool=TOOL,
        arguments=query,
        policy_context=CONTEXT,
    )
    assert bound.arguments_json == canonical(query)
    assert (
        bound.schema_sha256
        != hashlib.sha256(canonical(FaaFy2026PrReadV1.model_json_schema()).encode()).hexdigest()
    )
