"""Versioned exact sentinel canonicalization; never an authority decision."""

from civicgate.models.governance import JudgeSignal

VERSION = "EXACT_SINGLE_NONE_V1"


def canonical_signal(signal: JudgeSignal) -> JudgeSignal:
    # Revalidate before considering the sentinel; no fuzzy strings, coercion,
    # filtering of real flags, deduplication or interpretation of rationale.
    checked = JudgeSignal.model_validate_json(signal.model_dump_json(), strict=True)
    if checked.flags == ["NONE"]:
        return checked.model_copy(update={"flags": []}, deep=True)
    return checked.model_copy(deep=True)
