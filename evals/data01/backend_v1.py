"""Synthetic HTTP data source for the unchanged legacy Channel A adapter.

No live HTTP client exists here. Dates select the fixture's award_date, not a
claim about USAspending's transaction/date_type semantics. Agency matching is
strictly against the toptier field: DOT is never silently interpreted as FAA.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
SEARCH_PATH = "/api/v2/search/spending_by_award/"
RECIPIENT_PATH = "/api/v2/recipient/"
SEARCH_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "generated_internal_id",
]


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DATA01_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _payload(request: httpx.Request) -> dict[str, Any]:
    if len(request.content) > 65_536:
        raise ValueError("DATA01_REQUEST_TOO_LARGE")
    result = json.loads(request.content, object_pairs_hook=_object)
    if type(result) is not dict:
        raise ValueError("DATA01_OBJECT_REQUIRED")
    return result


def _exact(value: Any, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("DATA01_UNSUPPORTED_PAYLOAD")
    return value


def _bounded_int(value: Any, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("DATA01_LIMIT_INVALID")
    return value


def _one(value: Any) -> Any:
    if type(value) is not list or len(value) != 1:
        raise ValueError("DATA01_ONE_FILTER_REQUIRED")
    return value[0]


def select_search(records: list[dict[str, Any]], payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Implement only the exact existing Search wire contract, with no extension."""
    _exact(payload, {"filters", "fields", "page", "limit", "sort", "order", "subawards"})
    _bounded_int(payload["limit"], 100)
    if (
        type(payload["page"]) is not int
        or payload["page"] != 1
        or payload["fields"] != SEARCH_FIELDS
        or payload["sort"] != "Award Amount"
        or payload["order"] != "desc"
        or payload["subawards"] is not False
    ):
        raise ValueError("DATA01_LEGACY_PAGE_CONTRACT_REQUIRED")
    filters = payload["filters"]
    if (
        type(filters) is not dict
        or not {"time_period", "award_type_codes"} <= set(filters)
        or set(filters)
        - {
            "time_period",
            "award_type_codes",
            "agencies",
            "recipient_search_text",
            "place_of_performance_locations",
        }
    ):
        raise ValueError("DATA01_UNSUPPORTED_FILTER")
    period = _exact(_one(filters["time_period"]), {"start_date", "end_date"})
    start, end = date.fromisoformat(period["start_date"]), date.fromisoformat(period["end_date"])
    if not 0 <= (end - start).days <= 366:
        raise ValueError("DATA01_DATE_RANGE_INVALID")
    types = filters["award_type_codes"]
    if (
        type(types) is not list
        or not 1 <= len(types) <= 12
        or any(
            type(item) is not str
            or item not in {"A", "B", "C", "D", "02", "03", "04", "05", "06", "09", "10", "11"}
            for item in types
        )
    ):
        raise ValueError("DATA01_AWARD_TYPES_INVALID")
    agency = None
    if "agencies" in filters:
        selected = _exact(_one(filters["agencies"]), {"type", "tier", "name"})
        if (
            selected["type"] != "awarding"
            or selected["tier"] != "toptier"
            or type(selected["name"]) is not str
            or not selected["name"]
        ):
            raise ValueError("DATA01_LEGACY_AWARDING_TOPTIER_ONLY")
        agency = selected["name"]
    recipient = None
    if "recipient_search_text" in filters:
        recipient = _one(filters["recipient_search_text"])
        if type(recipient) is not str or not recipient:
            raise ValueError("DATA01_RECIPIENT_FILTER_INVALID")
    state = None
    if "place_of_performance_locations" in filters:
        selected = _exact(_one(filters["place_of_performance_locations"]), {"country", "state"})
        if selected["country"] != "USA" or type(selected["state"]) is not str:
            raise ValueError("DATA01_LOCATION_INVALID")
        state = selected["state"]
    selected_records = [
        record
        for record in records
        if start <= date.fromisoformat(record["award_date"]) <= end
        and record["award_type"] in types
        and (agency is None or record["awarding_agency"] == agency)
        and (state is None or record["place_of_performance_state"] == state)
        and (recipient is None or recipient.casefold() in record["recipient_name"].casefold())
    ]
    # Stable source order is the tie-breaker, avoiding invented provider semantics.
    return sorted(selected_records, key=lambda row: Decimal(row["award_amount"]), reverse=True)


def fixture_transport() -> httpx.MockTransport:
    """Load verified, fictional source bytes once; return a MockTransport only."""
    from evals.data01.generator import validate_dataset

    # This earlier dataset manifest is an identity reference, never an authority
    # pin or authentication. A separately recorded final inventory anchors it.
    manifest = json.loads(
        (HERE / "dataset_manifest_v1.json").read_bytes(), object_pairs_hook=_object
    )
    references = [row for row in manifest["files"] if row["path"] == "awards_v1.json"]
    raw = (HERE / "awards_v1.json").read_bytes()
    if (
        len(references) != 1
        or references[0]["bytes"] != len(raw)
        or references[0]["sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError("DATA01_DATASET_IDENTITY_MISMATCH")
    document = json.loads(raw, object_pairs_hook=_object)
    validate_dataset(document)
    records = document["records"]
    indexed = {record["award_id"]: (index + 1, record) for index, record in enumerate(records)}

    def respond(request: httpx.Request) -> httpx.Response:
        try:
            if request.url.scheme != "https" or request.url.host != "api.usaspending.gov":
                raise ValueError("DATA01_LOGICAL_ORIGIN_INVALID")
            if request.url.query:
                raise ValueError("DATA01_QUERY_STRING_UNSUPPORTED")
            if request.url.path == SEARCH_PATH and request.method == "POST":
                payload = _payload(request)
                selected = select_search(records, payload)
                rows = [
                    {
                        "internal_id": indexed[row["award_id"]][0],
                        "generated_internal_id": row["award_id"],
                        "Award ID": row["award_id"],
                        "Recipient Name": row["recipient_name"],
                        "Award Amount": row["award_amount"],
                        "Awarding Agency": row["awarding_agency"],
                    }
                    for row in selected[: payload["limit"]]
                ]
                return httpx.Response(
                    200,
                    json={
                        "results": rows,
                        "page_metadata": {"hasNext": len(selected) > payload["limit"]},
                    },
                )
            if request.url.path == RECIPIENT_PATH and request.method == "POST":
                payload = _exact(
                    _payload(request), {"keyword", "limit", "page", "sort", "order", "award_type"}
                )
                limit = _bounded_int(payload["limit"], 25)
                if (
                    type(payload["keyword"]) is not str
                    or not payload["keyword"]
                    or type(payload["page"]) is not int
                    or payload["page"] != 1
                    or payload["sort"] != "name"
                    or payload["order"] != "asc"
                    or payload["award_type"] != "all"
                ):
                    raise ValueError("DATA01_RECIPIENT_PAYLOAD_INVALID")
                names = sorted(
                    {
                        row["recipient_name"]
                        for row in records
                        if payload["keyword"].casefold() in row["recipient_name"].casefold()
                    }
                )
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "id": "SYN-REC-" + hashlib.sha256(name.encode()).hexdigest()[:12],
                                "name": name,
                                "uei": None,
                                "recipient_level": "R",
                            }
                            for name in names[:limit]
                        ],
                        "page_metadata": {"hasNext": len(names) > limit},
                    },
                )
            if request.method == "GET" and request.url.path.startswith("/api/v2/awards/"):
                prefix = "/api/v2/awards/"
                award_id = request.url.path.removeprefix(prefix).removesuffix("/")
                selected = indexed.get(award_id)
                if selected is None and award_id.isdecimal():
                    index = int(award_id)
                    if 1 <= index <= len(records):
                        selected = (index, records[index - 1])
                if request.url.path != prefix + award_id + "/" or selected is None:
                    return httpx.Response(404, json={"error": "SYNTHETIC_AWARD_NOT_FOUND"})
                index, record = selected
                return httpx.Response(
                    200,
                    json={
                        "id": index,
                        "generated_unique_award_id": record["award_id"],
                        "category": "contract"
                        if record["award_type"] in {"A", "B", "C", "D"}
                        else "grant",
                        "total_obligation": record["award_amount"],
                    },
                )
            return httpx.Response(404, json={"error": "SYNTHETIC_ENDPOINT_NOT_SUPPORTED"})
        except (ValueError, TypeError, KeyError) as exc:
            return httpx.Response(400, json={"error": str(exc), "synthetic": True})

    return httpx.MockTransport(respond)
