"""Literal within-source characterization; no evidence reading or semantic inference."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from civicgate.rq6.core import RQ6Error, require

STABILITY_DISPOSITIONS = (
    "STABLE",
    "STABLE_WITH_RATIONALE_VARIATION",
    "STRUCTURED_SIGNAL_VARIABLE",
    "CLASSIFICATION_VARIABLE",
    "MULTI_AXIS_VARIABLE",
    "INSUFFICIENT_REPEAT_EVIDENCE",
)
DEFERRED = "RQ6_REVIEW_DEFERRED_PENDING_HUMAN_RESOLUTION"
_VARIATION = {
    "NONE": False,
    "MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE": False,
    "MATERIAL_BOUNDARY_CHANGE": True,
    "UNRESOLVED": None,
}


def normalize_flags(raw: list[str]) -> tuple[str, ...]:
    require(
        type(raw) is list and all(type(flag) is str and bool(flag) for flag in raw), "INVALID_FLAGS"
    )
    flags = set(raw)
    require("NONE" not in flags or flags == {"NONE"}, "MIXED_NONE_FLAGS")
    return () if flags == {"NONE"} else tuple(sorted(flags))


@dataclass(frozen=True)
class Observation:
    classification: str
    flags: list[str]
    confidence: int | float | Decimal
    usable: bool = True


def _usable(value: Any) -> bool:
    if not isinstance(value, Observation) or value.usable is not True:
        return False
    if type(value.classification) is not str or not value.classification:
        return False
    if type(value.flags) is not list or not all(type(x) is str and bool(x) for x in value.flags):
        return False
    confidence = value.confidence
    if type(confidence) not in (int, float) and not isinstance(confidence, Decimal):
        return False
    if isinstance(confidence, Decimal) and not confidence.is_finite():
        return False
    if type(confidence) is float and not math.isfinite(confidence):
        return False
    return 0 <= confidence <= 1


def characterize(
    primary: Observation | None,
    repeats: list[Observation | None] | list[Observation],
    *,
    expected_repeat_count: int,
    rationale_variation: str,
    material_boundary_changed: bool | None,
) -> dict[str, Any]:
    """Apply the six frozen rules to supplied observations and human findings only.

    Rationale inputs are the exact four assessment values, not lexical/model inference.
    This pure result never grants release, unblind or administrative closure authority.
    """
    require(
        type(expected_repeat_count) is int and expected_repeat_count > 0,
        "INVALID_EXPECTED_REPEAT_COUNT",
    )
    require(type(repeats) is list, "INVALID_REPEAT_COLLECTION")
    require(
        type(rationale_variation) is str and rationale_variation in _VARIATION,
        "INVALID_RATIONALE_VARIATION",
    )
    require(
        material_boundary_changed is _VARIATION[rationale_variation], "INCOHERENT_RATIONALE_FINDING"
    )
    supplied = [primary, *repeats]
    valid = [item for item in supplied if _usable(item)]
    confidences = [item.confidence for item in valid if isinstance(item, Observation)]
    result: dict[str, Any] = {
        "stability_disposition": None,
        "review_status": "RQ6_REVIEW_COMPLETE",
        "confidence_interpretation": "DESCRIPTIVE_ONLY",
        "confidence_values": confidences,
        "confidence_range": [min(confidences), max(confidences)] if confidences else None,
    }
    if len(repeats) != expected_repeat_count or len(valid) != len(supplied):
        result["stability_disposition"] = "INSUFFICIENT_REPEAT_EVIDENCE"
        return result
    if rationale_variation == "UNRESOLVED":
        result["review_status"] = DEFERRED
        return result
    observations = [item for item in supplied if isinstance(item, Observation)]
    try:
        flag_sets = {normalize_flags(item.flags) for item in observations}
    except RQ6Error as exc:
        if str(exc) != "MIXED_NONE_FLAGS":
            raise
        result["review_status"] = DEFERRED
        return result
    classification_varies = len({item.classification for item in observations}) > 1
    flags_vary = len(flag_sets) > 1
    if classification_varies and flags_vary:
        result["stability_disposition"] = "MULTI_AXIS_VARIABLE"
    elif classification_varies:
        result["stability_disposition"] = "CLASSIFICATION_VARIABLE"
    elif flags_vary:
        result["stability_disposition"] = "STRUCTURED_SIGNAL_VARIABLE"
    elif material_boundary_changed is True or rationale_variation == "UNRESOLVED":
        result["review_status"] = DEFERRED
    elif rationale_variation == "MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE":
        result["stability_disposition"] = "STABLE_WITH_RATIONALE_VARIATION"
    else:
        result["stability_disposition"] = "STABLE"
    return result
