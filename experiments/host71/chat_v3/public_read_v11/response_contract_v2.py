"""Version11: exact reviewed notice for fixed host query; all other validation retained."""

from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, NoReturn

import httpx

from chat_v3.public_read_v11.adapter import PublicReadAdapter
from chat_v3.public_read_v11.contract import DOT
from civicgate.adapters.usaspending import RequestOutcome
from civicgate.channel_b.faa_money_v1 import amount_text

ROW_FIELDS = {
    "internal_id",
    "generated_internal_id",
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
}
ROW_METADATA = {"agency_slug", "awarding_agency_id"}
TOP_FIELDS = {"spending_level", "limit", "results", "page_metadata", "messages"}
PAGE_FIELDS = {"page", "hasNext", "last_record_unique_id", "last_record_sort_value"}
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z", re.ASCII)


@dataclass
class ValidationState:
    entered: bool = False
    message_review: dict[str, Any] | None = None
    diagnostic: dict[str, str] | None = None


_validation: ContextVar[ValidationState | None] = ContextVar("response_contract_v2", default=None)


class ContractFailure(ValueError):
    """Only code-controlled categories and locations; never rejected values."""

    def __init__(self, category: str, location: str, expected: str) -> None:
        super().__init__("RESPONSE_CONTRACT_REJECTED")
        self.diagnostic = {
            "stage": "SEARCH_RESPONSE_CONTRACT",
            "category": category,
            "location": location,
            "expected": expected,
        }


def reject(category: str, location: str, expected: str) -> NoReturn:
    raise ContractFailure(category, location, expected)


def text(value: Any, location: str, *, nullable: bool = False, limit: int = 300) -> None:
    if nullable and value is None:
        return
    if type(value) is not str:
        reject("type_error", location, "string_or_null" if nullable else "string")
    if not 0 < len(value) <= limit or any(ord(char) < 32 for char in value):
        reject("string_constraint", location, "bounded_nonempty_text_without_controls")


def positive_int(value: Any, location: str) -> None:
    if type(value) is not int or value <= 0:
        reject("integer_constraint", location, "positive_integer")


def keys(value: Any, required: set[str], allowed: set[str], location: str) -> None:
    if type(value) is not dict:
        reject("type_error", location, "object")
    for key in sorted(required):
        if key not in value:
            reject("missing", location + "." + key, "required_field")
    if set(value) - allowed:
        # Never serialize the unexpected, possibly sensitive field name.
        reject("extra_forbidden", location + ".<unexpected>", "documented_projection")


def normalize_search(raw: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the bounded selected projection before inherited Pydantic parsing."""
    keys(raw, TOP_FIELDS - {"messages"}, TOP_FIELDS, "response")
    if raw["spending_level"] != "awards" or type(raw["spending_level"]) is not str:
        reject("identity_mismatch", "response.spending_level", "awards")
    positive_int(raw["limit"], "response.limit")
    if raw["limit"] != payload["limit"]:
        reject("request_mismatch", "response.limit", "requested_limit")
    if "messages" in raw:
        messages = raw["messages"]
        if type(messages) is not list or len(messages) > 8:
            reject("type_or_size_error", "response.messages", "bounded_array_of_strings")
        for message in messages:
            text(message, "response.messages[]", limit=512)
        if messages:
            state = _validation.get()
            review = {
                "version": "MESSAGE_REVIEW_V11",
                "classification": "HELD_UNREVIEWED",
                "count": len(messages),
            }
            if state is not None:
                state.message_review = review
            if messages != [REVIEWED_TIME_NOTICE] or not reviewed_query_range(payload):
                reject(
                    "upstream_messages_unreviewed",
                    "response.messages",
                    "exact_reviewed_notice_and_fixed_valid_query",
                )
            review.update(
                classification="INFORMATIONAL_EXACT",
                message_sha256=REVIEWED_NOTICE_SHA256,
                upstream_commit=REVIEWED_UPSTREAM_COMMIT,
            )
            # This classification does not grant permission or skip remaining checks.
    page = raw["page_metadata"]
    keys(page, {"page", "hasNext"}, PAGE_FIELDS, "response.page_metadata")
    positive_int(page["page"], "response.page_metadata.page")
    if page["page"] != payload["page"]:
        reject("request_mismatch", "response.page_metadata.page", "requested_page")
    if type(page["hasNext"]) is not bool:
        reject("type_error", "response.page_metadata.hasNext", "boolean")
    if "last_record_unique_id" in page:
        positive_int(page["last_record_unique_id"], "response.page_metadata.last_record_unique_id")
    if "last_record_sort_value" in page:
        text(page["last_record_sort_value"], "response.page_metadata.last_record_sort_value")
    rows = raw["results"]
    if type(rows) is not list or len(rows) > raw["limit"]:
        reject("type_or_size_error", "response.results", "bounded_array")
    if not rows and page["hasNext"]:
        reject("pagination_conflict", "response.page_metadata", "nonempty_page_if_has_next")
    result = []
    ids: set[int] = set()
    generated: set[str] = set()
    previous: Decimal | None = None
    for row in rows:
        location = "response.results[]"
        keys(row, ROW_FIELDS, ROW_FIELDS | ROW_METADATA, location)
        positive_int(row["internal_id"], location + ".internal_id")
        text(row["generated_internal_id"], location + ".generated_internal_id", limit=200)
        if SAFE_ID.fullmatch(row["generated_internal_id"]) is None:
            reject(
                "identifier_format", location + ".generated_internal_id", "safe_award_identifier"
            )
        if row["internal_id"] in ids or row["generated_internal_id"] in generated:
            reject("duplicate_identity", location, "unique_award_identity")
        ids.add(row["internal_id"])
        generated.add(row["generated_internal_id"])
        text(row["Award ID"], location + ".Award ID", limit=200)
        text(row["Recipient Name"], location + ".Recipient Name", nullable=True)
        text(row["Awarding Agency"], location + ".Awarding Agency", nullable=True)
        if payload["filters"].get("agencies") and row["Awarding Agency"] != DOT:
            reject("identity_mismatch", location + ".Awarding Agency", "requested_awarding_toptier")
        if "agency_slug" in row:
            text(row["agency_slug"], location + ".agency_slug", nullable=True)
        if "awarding_agency_id" in row and row["awarding_agency_id"] is not None:
            positive_int(row["awarding_agency_id"], location + ".awarding_agency_id")
        try:
            amount = amount_text(row["Award Amount"])
        except ValueError:
            reject(
                "invalid_monetary_value", location + ".Award Amount", "finite_exact_bounded_decimal"
            )
        value = Decimal(amount)
        if previous is not None and value > previous:
            reject("sort_conflict", location + ".Award Amount", "descending_award_amount")
        previous = value
        result.append({key: row[key] for key in sorted(ROW_FIELDS)} | {"Award Amount": amount})
    return {"results": result, "page_metadata": {"hasNext": page["hasNext"]}}


class OfflineResponseContractV2(PublicReadAdapter):
    """Reuse bounded V1 transport with a corrected search validator in mocks only."""

    def __init__(self, *, transport: httpx.MockTransport) -> None:
        super().__init__(mode="OFFLINE", transport=transport)
        self.validation_diagnostic: dict[str, str] | None = None

    def _admit_request(self, path, payload):
        if self.mode != "OFFLINE" or type(self.transport) is not httpx.MockTransport:
            raise ValueError("OFFLINE_RESPONSE_CANDIDATE_ONLY")

    @staticmethod
    def _validate_raw(raw: Any, payload: dict[str, Any] | None) -> None:
        state = _validation.get()
        if state is not None:
            state.entered = True
        if payload is None:
            # Detail contract is deliberately unchanged and out of this correction.
            PublicReadAdapter._validate_raw(raw, payload)
            return
        try:
            normalized = normalize_search(raw, payload)
        except ContractFailure as error:
            if state is not None:
                state.diagnostic = error.diagnostic
            raise
        raw.clear()
        raw.update(normalized)

    async def _request(self, path: str, payload: dict[str, Any] | None = None) -> RequestOutcome:
        self._admit_request(path, payload)
        before = len(self.observations)
        state = ValidationState()
        token = _validation.set(state)
        try:
            return await super()._request(path, payload)
        finally:
            _validation.reset(token)
            self.validation_diagnostic = state.diagnostic
            if len(self.observations) > before:
                observation = self.observations[-1]
                if self.validation_diagnostic is not None:
                    diagnostic = dict(self.validation_diagnostic)
                elif observation["outcome"] == "RESPONSE_VALIDATED":
                    diagnostic = {"stage": "BOUNDED_RESPONSE_VALIDATOR", "category": "accepted"}
                elif observation["body_sha256"] and not state.entered:
                    # V1 groups JSON syntax, duplicate keys, depth and numeric-token
                    # errors; do not invent a more precise parser cause here.
                    diagnostic = {"stage": "JSON_DECODING", "category": "json_or_token_rejected"}
                else:
                    diagnostic = {"stage": "TRANSPORT_OR_DETAIL", "category": "withheld"}
                observation["validation_diagnostic_v2"] = diagnostic
                if state.message_review is not None:
                    observation["message_review_v11"] = dict(state.message_review)


class SingleLiveReadV2(OfflineResponseContractV2):
    """Host-only exact public READ. No injected transport, detail, or alternate query."""

    def _validate_live_construction(self):
        pass  # Only this exact-request subclass admits construction; no I/O here.

    def __init__(self, *, live_authorized: bool = False):
        if live_authorized is not True:
            raise ValueError("PUBLIC_API_LIVE_NOT_AUTHORIZED")
        PublicReadAdapter.__init__(self, mode="LIVE", live_authorized=True)
        self.validation_diagnostic = None

    def _admit_request(self, path, payload):
        from .contract import SEARCH_PATH

        if (
            self.mode != "LIVE"
            or self.transport is not None
            or path != SEARCH_PATH
            or payload != LIVE_PAYLOAD
        ):
            raise ValueError("LIVE09_EXACT_QUERY_REQUIRED")


LIVE_PAYLOAD = {
    "filters": {
        "time_period": [{"start_date": "2025-10-01", "end_date": "2026-09-30"}],
        "award_type_codes": ["A", "B", "C", "D"],
        "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
    },
    "fields": [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Awarding Agency",
        "generated_internal_id",
    ],
    "page": 1,
    "limit": 5,
    "sort": "Award Amount",
    "order": "desc",
    "subawards": False,
}


REVIEWED_UPSTREAM_COMMIT = "c2b82690eb044e130afc80b546343a2af0b4af1a"
REVIEWED_TIME_NOTICE = (
    "For searches, time period start and end dates are currently limited to an earliest date of "
    "2007-10-01.  For data going back to 2000-10-01, use either the Custom "
    "Award Download feature on the website or one of our download or bulk_download API endpoints as "
    "listed on https://api.usaspending.gov/docs/endpoints. "
)
REVIEWED_NOTICE_SHA256 = hashlib.sha256(REVIEWED_TIME_NOTICE.encode()).hexdigest()


def reviewed_query_range(payload):
    # Explicitly limited to this approved host query, not a general warning bypass.
    if payload != LIVE_PAYLOAD:
        return False
    period = payload["filters"]["time_period"][0]
    try:
        start = date.fromisoformat(period["start_date"])
        end = date.fromisoformat(period["end_date"])
    except (TypeError, ValueError):
        return False
    return date(2007, 10, 1) <= start <= end <= date(2027, 9, 30)
