"""Bounded free-text OFFLINE intake. Unknown intent is not execution authority."""

import re

from .common import MODE


def route(question, record, owner):
    if not record.get("free_text_read", False) or owner != "HOST_HOLD":
        return owner, False
    if record.get("mode") != MODE or record.get("live_authorization") != "HOLD":
        raise ValueError("FREE_TEXT_LIVE_NOT_ADMITTED")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        return "HOST_HOLD", False
    # This is credential hygiene, not a complete sensitive-data detector.
    if re.search(
        r"(?i)(bearer\s|nvapi-|sk-[a-z0-9]{12}|[a-z]:[\\/]|https?://|[\x00-\x1f])", question
    ):
        return "HOST_HOLD", False
    # Discovery/planning/advisory may occur; a host negative boundary ensures
    # that an unrecognized offline fixture cannot issue a binding or dispatch.
    return "CHANNEL_A_READ", True


def fixture_owner(question, record, owner):
    """Only omit the READ example's final ASCII period, in opt-in offline mocks.

    Do not rewrite the request or apply this alias to LIVE/public/WRITE scopes.
    """
    from .catalog import READ

    if (
        owner == "HOST_HOLD"
        and question == READ[:-1]
        and record.get("free_text_read") is True
        and record.get("mode") == MODE
        and record.get("live_authorization") == "HOLD"
    ):
        return "CHANNEL_A_READ"
    return owner
