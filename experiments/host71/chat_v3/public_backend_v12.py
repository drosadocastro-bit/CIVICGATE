"""Host-only fixed public backend; no browser-selected authority or fallback."""

import json

from civicgate.models.requests import Search

from .catalog import PUBLIC_READ
from .public_read_v11.contract import expected_proposal

BACKEND = "USASPENDING_FIXED_READ_V11"


def require_scope(budget, question, owner):
    profile = getattr(budget, "profile", None)
    if profile is not None and profile.backend == "NO_EXECUTION":
        if question != profile.fixed_question or owner != "CHANNEL_A_READ":
            raise ValueError("NEGATIVE_HOST_SCOPE_REQUIRED")
    public = profile is not None and profile.backend == BACKEND
    if public:
        if (
            not profile.smoke_read_only
            or profile.public_api_attempt_limit != 1
            or question != PUBLIC_READ
            or owner != "PUBLIC_API_READ"
        ):
            raise ValueError("PUBLIC_HOST_SCOPE_REQUIRED")
    elif owner == "PUBLIC_API_READ":
        raise ValueError("PUBLIC_BACKEND_NOT_ADMITTED")
    return public


def require_proposal(request, proposal):
    expected = expected_proposal(PUBLIC_READ)
    if request != PUBLIC_READ or proposal.tool != expected.tool:
        raise ValueError("PUBLIC_PROPOSAL_SCOPE_MISMATCH")
    actual = Search.model_validate_json(json.dumps(proposal.arguments), strict=True).model_dump(
        mode="json"
    )
    if actual != expected.arguments:
        raise ValueError("PUBLIC_PROPOSAL_SCOPE_MISMATCH")
