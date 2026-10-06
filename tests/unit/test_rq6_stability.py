from copy import deepcopy
from decimal import Decimal

import pytest

from civicgate.rq6.core import RQ6Error, decode_exact, exact_json
from civicgate.rq6.stability import (
    DEFERRED,
    STABILITY_DISPOSITIONS,
    Observation,
    characterize,
    normalize_flags,
)


def observation(
    classification="SYNTHETIC_CLASS", flags=None, confidence=Decimal("0.9600"), usable=True
):
    return Observation(classification, [] if flags is None else flags, confidence, usable)


def assess(primary, repeats, variation="NONE", boundary=False, expected=3):
    return characterize(
        primary,
        repeats,
        expected_repeat_count=expected,
        rationale_variation=variation,
        material_boundary_changed=boundary,
    )


def test_only_exact_flag_representation_changes_and_empty_sentinel():
    flags = ["B", "A", "A"]
    assert normalize_flags(flags) == ("A", "B")
    assert flags == ["B", "A", "A"]
    assert (
        normalize_flags([]) == normalize_flags(["NONE"]) == normalize_flags(["NONE", "NONE"]) == ()
    )
    assert normalize_flags(["A", "a"]) == ("A", "a")
    with pytest.raises(RQ6Error, match="MIXED_NONE_FLAGS"):
        normalize_flags(["NONE", "A"])
    with pytest.raises(RQ6Error, match="INVALID_FLAGS"):
        normalize_flags([True])


@pytest.mark.parametrize(
    ("classification", "flags", "disposition"),
    [
        ("SYNTHETIC_CLASS", [], "STABLE"),
        ("SYNTHETIC_CLASS", ["A"], "STRUCTURED_SIGNAL_VARIABLE"),
        ("OTHER_SYNTHETIC_CLASS", [], "CLASSIFICATION_VARIABLE"),
        ("OTHER_SYNTHETIC_CLASS", ["A"], "MULTI_AXIS_VARIABLE"),
    ],
)
def test_exact_categorical_axes(classification, flags, disposition):
    primary = observation()
    repeats = [observation(), observation(classification, flags), observation()]
    assert assess(primary, repeats)["stability_disposition"] == disposition


def test_confidence_preserves_exact_scale_and_never_selects_disposition():
    primary = observation(confidence=Decimal("0.9600"))
    repeats = [
        observation(confidence=Decimal("0.01")),
        observation(confidence=Decimal("1.000")),
        observation(confidence=Decimal("0.5000")),
    ]
    original = deepcopy((primary, repeats))
    result = assess(primary, repeats)
    assert result["stability_disposition"] == "STABLE"
    assert result["confidence_interpretation"] == "DESCRIPTIVE_ONLY"
    assert [str(v) for v in result["confidence_values"]] == ["0.9600", "0.01", "1.000", "0.5000"]
    assert [str(v) for v in result["confidence_range"]] == ["0.01", "1.000"]
    assert (primary, repeats) == original


def test_parsed_confidence_lexemes_remain_exact_and_confidence_neutral():
    values = decode_exact(b"[0.90,9e-1,0.9000,9.00E-1]")
    result = assess(
        observation(confidence=values[0]), [observation(confidence=value) for value in values[1:]]
    )
    assert result["stability_disposition"] == "STABLE"
    assert exact_json(result["confidence_values"]) == b"[0.90,9e-1,0.9000,9.00E-1]"


@pytest.mark.parametrize(
    "primary,repeats",
    [
        (None, [observation(), observation(), observation()]),
        (observation(), [observation(), None, observation()]),
        (observation(), [observation(), observation(usable=False), observation()]),
        (observation(), [observation(), observation()]),
        (observation(), [observation(), observation(), observation(), observation()]),
        (observation(confidence=Decimal("NaN")), [observation(), observation(), observation()]),
    ],
)
def test_required_evidence_insufficient_precedence(primary, repeats):
    result = assess(primary, repeats, variation="MATERIAL_BOUNDARY_CHANGE", boundary=True)
    assert result["stability_disposition"] == "INSUFFICIENT_REPEAT_EVIDENCE"


def test_missing_evidence_not_repaired_by_later_identical_repeats():
    assert assess(observation(usable=False), [observation()] * 3)["stability_disposition"] == (
        "INSUFFICIENT_REPEAT_EVIDENCE"
    )


def test_human_material_variation_requires_frozen_boundary_guard():
    primary = observation()
    repeats = [observation()] * 3
    result = assess(primary, repeats, "MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE", False)
    assert result["stability_disposition"] == "STABLE_WITH_RATIONALE_VARIATION"
    result = assess(primary, repeats, "MATERIAL_BOUNDARY_CHANGE", True)
    assert result["stability_disposition"] is None and result["review_status"] == DEFERRED
    assert (
        len(STABILITY_DISPOSITIONS) == 6 and "DEFER_FOR_HUMAN_REVIEW" not in STABILITY_DISPOSITIONS
    )


def test_unresolved_human_finding_defers_even_with_variable_axes():
    result = assess(observation(), [observation("OTHER", ["A"])] * 3, "UNRESOLVED", None)
    assert result["stability_disposition"] is None and result["review_status"] == DEFERRED


def test_mixed_none_is_preserved_and_defers_not_silently_dropped():
    bad = observation(flags=["NONE", "A"])
    result = assess(observation(), [observation(), bad, observation()])
    assert result["stability_disposition"] is None and result["review_status"] == DEFERRED
    assert bad.flags == ["NONE", "A"]


def test_incoherent_human_assessment_is_rejected_not_repaired():
    with pytest.raises(RQ6Error, match="INCOHERENT_RATIONALE_FINDING"):
        assess(observation(), [observation()] * 3, "NONE", True)
    with pytest.raises(RQ6Error, match="INVALID_RATIONALE_VARIATION"):
        assess(observation(), [observation()] * 3, "DEFER_FOR_HUMAN_REVIEW", None)
    with pytest.raises(RQ6Error, match="INVALID_EXPECTED_REPEAT_COUNT"):
        assess(observation(), [], expected=True)
