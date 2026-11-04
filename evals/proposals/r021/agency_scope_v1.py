"""PROPOSED_NOT_APPLIED: bounded agency-scope review signal for legacy Search.

This experimental profile can only add reasons for the existing deterministic
policy to review. It never issues authority, rewrites a name, widens a filter,
or enables FAA execution. DOT/NASA are the two explicit canonical toptier
identities in the synthetic DATA-01 profile, not a complete federal catalog.

Intended future production location, subject to human approval:
``civicgate.governance.agency_scope_v1``. Existing runtime files stay unchanged.
Only the legacy Channel A contract may use this proposal; a separately selected
InvocationContract must not be revalidated against the legacy TOOLS schema.
"""

from __future__ import annotations

import re

from civicgate.governance.request_risk import _NAMED_FIELD, _name_literal, _normalize
from civicgate.models.requests import TOOLS, Search

PROFILE_VERSION = "DATA01-LEGACY-AGENCY-REVIEW-v1-PROPOSED_NOT_APPLIED"
SEARCH_TOOLS = frozenset({"find_federal_awards", "summarize_federal_spending"})
CANONICAL_TOPTIER = frozenset(
    {"Department of Transportation", "National Aeronautics and Space Administration"}
)
SUBTIER_IDENTITIES = frozenset(
    {
        "federal aviation administration",
        "federal highway administration",
        "federal transit administration",
        "faa",
        "fhwa",
        "fta",
    }
)
TOPTIER_ALIASES = frozenset({"dot", "nasa"})
_BARE_SUBTIER = re.compile(
    r"\b(?:faa|fhwa|fta|federal aviation administration|"
    r"federal highway administration|federal transit administration)\b"
)
_BARE_TOPTIER_ALIAS = re.compile(r"\b(?:dot|nasa)\b")


def _identity_reason(name: str) -> str | None:
    if name in CANONICAL_TOPTIER:
        return None
    normalized = _normalize(name)
    if normalized in SUBTIER_IDENTITIES:
        return "AGENCY_SUBTIER_UNSUPPORTED_BY_LEGACY_CONTRACT"
    if normalized in TOPTIER_ALIASES or normalized in {
        _normalize(value) for value in CANONICAL_TOPTIER
    }:
        return "AGENCY_IDENTITY_REQUIRES_EXPLICIT_CANONICAL_SCOPE"
    return "AGENCY_IDENTITY_UNKNOWN_OR_AMBIGUOUS"


def agency_scope_reasons(request: str, tool: str, arguments_json: str | None) -> tuple[str, ...]:
    """Classify known agency scope; return review reasons, never a decision.

    The original request and exact typed proposal remain unchanged. Normalization
    is used only to recognize a reason to HOLD. It never promotes an alias or
    normalized identity into a canonical, executable argument. Names inside valid
    recipient literals are excluded from agency-intent marker detection.

    Open-vocabulary/paraphrased scope recognition is not certified. The unchanged
    request-risk grammar, literal/argument checks and hard-denial rules still apply.
    This proposal does not resolve arbitrary natural-language dates/geography.
    """
    if tool not in SEARCH_TOOLS:
        return ()
    if type(request) is not str or not 0 < len(request.strip()) <= 4000:
        return ("AGENCY_SCOPE_INPUT_UNAVAILABLE",)
    if type(arguments_json) is not str:
        return ("AGENCY_SCOPE_INPUT_UNAVAILABLE",)
    try:
        effective = TOOLS[tool].model_validate_json(arguments_json)
    except (ValueError, TypeError):
        return ("AGENCY_SCOPE_INPUT_UNAVAILABLE",)
    if not isinstance(effective, Search):
        return ("AGENCY_SCOPE_INPUT_UNAVAILABLE",)

    reasons: list[str] = []
    if effective.awarding_agency is not None:
        if reason := _identity_reason(effective.awarding_agency):
            reasons.append(reason)
    agency_literals: list[str] = []

    def hide_valid_name(match: re.Match[str]) -> str:
        value = _name_literal(match)
        if value is None:
            return match[0]
        if match["recipient_label"] is None:
            agency_literals.append(value)
        return match["field"]

    remaining = _normalize(_NAMED_FIELD.sub(hide_valid_name, request))
    for value in agency_literals:
        if reason := _identity_reason(value):
            reasons.append(reason)
    if len(set(agency_literals)) > 1:
        reasons.append("AGENCY_SCOPE_CONTRADICTORY")
    if _BARE_SUBTIER.search(remaining):
        reasons.append("AGENCY_SUBTIER_UNSUPPORTED_BY_LEGACY_CONTRACT")
    if _BARE_TOPTIER_ALIAS.search(remaining):
        reasons.append("AGENCY_IDENTITY_REQUIRES_EXPLICIT_CANONICAL_SCOPE")
    return tuple(dict.fromkeys(reasons))
