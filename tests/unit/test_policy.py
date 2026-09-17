from dataclasses import replace

import pytest
from pydantic import ValidationError

from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import Award, Search

GOOD = JudgeSignal(classification="IN_SCOPE", confidence=0.99, available=True, provider="test")
FACTS = PolicyFacts(tool="find_federal_awards", text="public awards")


@pytest.mark.parametrize(
    "change,decision",
    [
        ({}, "PERMIT"),
        ({"tool": "hidden"}, "DENY"),
        ({"text": "blacklist contractor"}, "DENY"),
        ({"valid_input": False}, "DENY"),
        ({"public_source": False}, "DENY"),
        ({"capability": "PROCUREMENT"}, "DENY"),
        ({"bounded": False}, "REVIEW_REQUIRED"),
        ({"provenance_available": False}, "REVIEW_REQUIRED"),
        ({"adapter_available": False}, "REVIEW_REQUIRED"),
        ({"review_reason": "CONFLICTING_SOURCE_RESULTS"}, "REVIEW_REQUIRED"),
    ],
)
def test_determinism_and_precedence(change: dict[str, object], decision: str) -> None:
    facts = replace(FACTS, **change)
    results = [evaluate(facts, GOOD, KSignal()).model_dump_json() for _ in range(100)]
    assert len(set(results)) == 1
    assert evaluate(facts, GOOD, KSignal()).decision == decision


@pytest.mark.parametrize(
    "signal",
    [
        JudgeSignal(),
        GOOD.model_copy(update={"confidence": 0.5}),
        GOOD.model_copy(update={"classification": "AMBIGUOUS"}),
        GOOD.model_copy(update={"flags": ["PROVENANCE_RISK"]}),
    ],
)
def test_uncertain_semantics_never_permit(signal: JudgeSignal) -> None:
    assert evaluate(FACTS, signal, KSignal()).decision == "REVIEW_REQUIRED"


def test_agent_k_conflict_cannot_grant_authority() -> None:
    assert evaluate(FACTS, GOOD, KSignal(containment=True)).decision == "DENY"
    assert evaluate(replace(FACTS, text="debar this company"), GOOD, KSignal()).decision == "DENY"


@pytest.mark.parametrize(
    "patch",
    [
        {"limit": 101},
        {"limit": True},
        {"start_date": "bad"},
        {"end_date": "2020-01-01"},
        {"end_date": "2030-01-01"},
        {"state_code": "ZZ"},
        {"award_types": []},
        {"award_types": ["07"]},
        {"authority": "PERMIT"},
    ],
)
def test_search_bounds(search_args: dict[str, object], patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Search.model_validate(search_args | patch)


@pytest.mark.parametrize("value", ["../private", "https://other.example/x", "a/b", "a?token=x"])
def test_award_path_restriction(value: str) -> None:
    with pytest.raises(ValidationError):
        Award(award_id=value)
