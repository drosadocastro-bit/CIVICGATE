"""Host-owned offline examples. Text editing never creates an approval."""

from __future__ import annotations

import re
from typing import Any

from .public_read_v11.contract import EXAMPLE as PUBLIC_READ

READ = "Show public federal awards in Puerto Rico from 2025-01-01 to 2025-02-01."
DATA = (
    'Find public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2026.'
)
WRITE = "Mark synthetic award SYN-FAA-PR-001 as pending review and attach a reviewer note."
OVERLAY = "Read synthetic review state for SYN-FAA-PR-001."
DENY = "Blacklist this contractor from future federal work."
REVIEW = "Which contractor should we choose?"

CATALOG = (
    {"id": "data", "title": "Dataset Access · FAA / FY2026 / PR", "question": DATA},
    {"id": "read", "title": "Service READ · Public awards", "question": READ},
    {"id": "write", "title": "Synthetic WRITE · Pending review", "question": WRITE},
    {"id": "deny", "title": "DENY · Prohibited intent", "question": DENY},
    {"id": "review", "title": "REVIEW_REQUIRED · Unresolved decision", "question": REVIEW},
    {"id": "overlay", "title": "Overlay READ · Verify review state", "question": OVERLAY},
)
READ_PROPOSAL: dict[str, Any] = {
    "tool": "find_federal_awards",
    "arguments": {
        "start_date": "2025-01-01",
        "end_date": "2025-02-01",
        "state_code": "PR",
        "limit": 5,
    },
}


def select_owner(question: str) -> str:
    """Conservative host router, not a new policy or semantic approval system.

    Only the exact DATA intake reaches its scoped owner. Edited FAA or WRITE
    intentions have no legacy fallback. Unsupported text is a host refusal;
    it must not be displayed as a Gateway policy decision.
    """
    if question == PUBLIC_READ:
        return "PUBLIC_API_READ"
    if question == DATA:
        return "FAA_DATA01"
    if question == OVERLAY or question == WRITE:
        return "WRITE01"
    if re.search(
        r"\b(faa|aviation|write|review state|reviewer note|pending review)\b", question, re.I
    ):
        return "HOST_HOLD"
    if question in {READ, DENY, REVIEW}:
        return "CHANNEL_A_READ"
    return "HOST_HOLD"
