"""Narrow host scope, using the existing Proposal and tool schemas unchanged."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from civicgate.audit.trace import redact
from civicgate.models.requests import Award, Proposal, Search

ORIGIN = "https://api.usaspending.gov"
SEARCH_PATH = "/api/v2/search/spending_by_award/"
DOT = "Department of Transportation"
EXAMPLE = "Show 5 public federal contract awards in Puerto Rico from 2025-10-01 to 2026-09-30."
FIND = re.compile(
    r"Show (?P<limit>[1-9]|1[0-9]|20) public federal contract awards in Puerto Rico"
    r'(?: for agency "(?P<agency>Department of Transportation)")?'
    r" from (?P<start>\d{4}-\d{2}-\d{2}) to (?P<end>\d{4}-\d{2}-\d{2})\.?"
)
GET = re.compile(r"Get public federal award (?P<id>[A-Za-z0-9][A-Za-z0-9_.-]{0,199})\.?$")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_intake(request: str) -> bool:
    return (
        isinstance(request, str)
        and 0 < len(request) <= 4000
        and len(request.encode()) <= 16000
        and "\0" not in request
        and redact(request) == request
    )


def save(path: Path, value: Any) -> str:
    raw = canonical(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return digest(raw)


def expected_proposal(request: str) -> Proposal | None:
    """Deliberately explicit grammar; no fuzzy FAA/DOT inference or scope widening."""
    found = FIND.fullmatch(request)
    if found:
        args = Search.model_validate_json(
            json.dumps(
                {
                    "start_date": found["start"],
                    "end_date": found["end"],
                    "state_code": "PR",
                    "limit": int(found["limit"]),
                    "awarding_agency": found["agency"],
                    "award_types": ["A", "B", "C", "D"],
                }
            ),
            strict=True,
        )
        return Proposal(tool="find_federal_awards", arguments=args.model_dump(mode="json"))
    found = GET.fullmatch(request)
    if found:
        # A trailing full stop is intentionally not stripped from an identifier.
        award = Award(award_id=found["id"])
        return Proposal(tool="get_federal_award", arguments=award.model_dump(mode="json"))
    return None


def scope_reason(request: str, proposal: Proposal) -> str | None:
    try:
        expected = expected_proposal(request)
        if expected is None:
            return "PUBLIC_READ_INTENT_UNREPRESENTABLE"
        model = Search if expected.tool == "find_federal_awards" else Award
        actual = model.model_validate_json(json.dumps(proposal.arguments), strict=True)
        if proposal.tool != expected.tool or actual.model_dump(mode="json") != expected.arguments:
            return "PUBLIC_READ_PROPOSAL_SCOPE_MISMATCH"
    except ValueError:
        return "PUBLIC_READ_ARGUMENTS_INVALID"
    return None


class BoundedReadPlanner:
    """Scripted existing AgentModel seam, never represented as Granite or Luna."""

    async def propose(self, request: str) -> Proposal:
        expected = expected_proposal(request)
        if expected is not None:
            return expected
        # A held candidate deliberately goes to the real policy. Host scope rejects
        # it before binding; this is not a fallback response from the data source.
        return Proposal(
            tool="find_federal_awards",
            arguments={
                "start_date": "2025-10-01",
                "end_date": "2026-09-30",
                "state_code": "PR",
                "limit": 5,
            },
        )
