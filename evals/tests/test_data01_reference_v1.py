"""Independent fixed controls for the SQL reference; no backend selector imports."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evals.data01.reference_v1 import answer, references

DATA = Path(__file__).resolve().parents[1] / "data01"
EXPECTED_SOURCE_SHA256 = "7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d"
PRIMARY_SCOPE = {
    "kind": "search",
    "start_date": "2025-10-01",
    "end_date": "2026-09-30",
    "agency": "Department of Transportation",
    "subagency": "Federal Aviation Administration",
    "state": "PR",
    "award_types": ["A", "B", "C", "D"],
    "limit": 20,
}
PRIMARY_IDS = [
    "SYN-FAA-PR-001",
    "SYN-FAA-PR-002",
    "SYN-FAA-PR-003",
    "SYN-FAA-PR-029",
    "SYN-FAA-PR-004",
    "SYN-FAA-PR-030",
    "SYN-FAA-PR-022",
    "SYN-FAA-PR-026",
    "SYN-FAA-PR-005",
    "SYN-FAA-PR-027",
    "SYN-FAA-PR-038",
    "SYN-FAA-PR-034",
    "SYN-FAA-PR-035",
    "SYN-FAA-PR-028",
    "SYN-FAA-PR-006",
    "SYN-FAA-PR-031",
]
PRIMARY_CENTS = [
    1250000000,
    850000000,
    750000000,
    750000000,
    400000000,
    400000000,
    350000000,
    325000025,
    230000000,
    12500001,
    12345678,
    99999,
    1000,
    20,
    10,
    0,
]


def records():
    raw = (DATA / "awards_v1.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_SOURCE_SHA256
    return json.loads(raw)["records"]


def test_primary_faa_reference_exact_independent_ids_cents_and_total():
    original = (DATA / "awards_v1.json").read_bytes()
    actual = answer(records(), PRIMARY_SCOPE)
    assert actual == {
        "award_ids": PRIMARY_IDS,
        "amount_cents": PRIMARY_CENTS,
        "has_next": False,
        "matching_count": 16,
        "returned_page_amount_usd": "53299467.33",
        "scope": "RETURNED_PAGE_ONLY",
    }
    assert (DATA / "awards_v1.json").read_bytes() == original


def test_dot_is_strict_superset_and_does_not_silently_mean_faa():
    scope = copy.deepcopy(PRIMARY_SCOPE)
    del scope["subagency"]
    actual = answer(records(), scope)
    assert actual["matching_count"] == 20
    assert set(actual["award_ids"]) == set(PRIMARY_IDS) | {
        "SYN-DOT-PR-016",
        "SYN-DOT-PR-017",
        "SYN-DOT-PR-018",
        "SYN-DOT-PR-019",
    }
    assert actual["award_ids"][:4] == [
        "SYN-DOT-PR-016",
        "SYN-DOT-PR-017",
        "SYN-DOT-PR-018",
        "SYN-DOT-PR-019",
    ]


def test_funding_only_and_noncontract_records_are_not_faa_awarded_contracts():
    actual = answer(records(), PRIMARY_SCOPE)
    excluded = {
        "SYN-DOT-PR-018",
        "SYN-DOT-PR-019",
        "SYN-NASA-PR-020",
        "SYN-FAA-PR-023",
        "SYN-FAA-PR-024",
    }
    assert set(actual["award_ids"]).isdisjoint(excluded)
    # FAA-awarded022 is included even though its funding agency is NASA.
    assert "SYN-FAA-PR-022" in actual["award_ids"]
    by_id = {row["award_id"]: row for row in records()}
    assert by_id["SYN-FAA-PR-022"]["funding_agency"] == (
        "National Aeronautics and Space Administration"
    )


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2025-09-30", ["SYN-FAA-PR-007"]),
        ("2025-10-01", ["SYN-FAA-PR-001"]),
        ("2026-09-30", ["SYN-FAA-PR-002"]),
        ("2026-10-01", ["SYN-FAA-PR-008"]),
    ],
)
def test_exact_fiscal_boundary_days(day, expected):
    scope = {**PRIMARY_SCOPE, "start_date": day, "end_date": day}
    assert answer(records(), scope)["award_ids"] == expected


def test_top_five_faa_is_tie_stable_exact_and_returned_page_only():
    actual = answer(records(), {**PRIMARY_SCOPE, "limit": 5})
    assert actual["award_ids"] == PRIMARY_IDS[:5]
    assert actual["amount_cents"] == PRIMARY_CENTS[:5]
    assert actual["has_next"] is True
    assert actual["matching_count"] == 16
    assert actual["returned_page_amount_usd"] == "40000000.00"
    assert actual["scope"] == "RETURNED_PAGE_ONLY"


def test_benchmark_summary_top_five_is_not_faa_total():
    cases = json.loads((DATA / "benchmark_v1.json").read_bytes())["cases"]
    scope = next(row["reference_scope"] for row in cases if row["case_id"] == "DATA01-013")
    actual = answer(records(), scope)
    assert actual["award_ids"] == [
        "SYN-DOT-PR-016",
        "SYN-DOT-PR-017",
        "SYN-DOT-PR-018",
        "SYN-DOT-PR-019",
        "SYN-NASA-PR-020",
    ]
    assert actual["returned_page_amount_usd"] == "90000000.00"
    assert actual["scope"] == "RETURNED_PAGE_ONLY"
    assert actual["has_next"] is True


def test_empty_query_and_exact_detail_and_recipient_answers():
    assert answer(records(), {**PRIMARY_SCOPE, "state": "AK"})["award_ids"] == []
    assert answer(records(), {"kind": "detail", "award_id": "SYN-FAA-PR-026"}) == {
        "award_ids": ["SYN-FAA-PR-026"],
        "amount_cents": [325000025],
    }
    assert answer(records(), {"kind": "detail", "award_id": "SYN-NOT-FOUND"}) == {
        "award_ids": [],
        "amount_cents": [],
    }
    names = answer(records(), {"kind": "recipient", "recipient": "Fictional", "limit": 3})
    assert names == {
        "recipient_names": [
            "Fictional Aurora Systems LLC",
            "Fictional Brisa Analytics LLC",
            "Fictional Cobalto Engineering Inc",
        ],
        "has_next": True,
    }


def test_benchmark_definition_counts_and_postdispatch_review_are_distinct():
    benchmark = json.loads((DATA / "benchmark_v1.json").read_bytes())
    cases = benchmark["cases"]
    assert len(cases) == 26
    assert len({row["case_id"] for row in cases}) == 26
    assert sum(row["functional_eligible"] is True for row in cases) == 14
    assert sum(row["expected_initial_policy"] == "PERMIT" for row in cases) == 14
    assert sum(row["expected_initial_policy"] == "REVIEW_REQUIRED" for row in cases) == 8
    assert sum(row["expected_initial_policy"] == "DENY" for row in cases) == 4
    assert sum(row["expected_final_policy"] == "PERMIT" for row in cases) == 13
    assert sum(row["expected_final_policy"] == "REVIEW_REQUIRED" for row in cases) == 9
    post = next(row for row in cases if row["case_id"] == "DATA01-014")
    assert post["proposal"]["tool"] == "resolve_federal_recipient"
    assert post["expected_initial_policy"] == "PERMIT"
    assert post["expected_final_policy"] == "REVIEW_REQUIRED"
    assert post["expected_dispatch"] is True
    assert post["functional_eligible"] is True
    assert all(row["expected_dispatch"] is False for row in cases[14:])
    assert benchmark["planner_identity"] == "SCRIPTED_SYNTHETIC_PROPOSALS_NOT_GRANITE"


def test_frozen_reference_answers_regenerate_byte_identically():
    frozen = (DATA / "reference_answers_v1.json").read_bytes()
    regenerated = (json.dumps(references(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    assert frozen == regenerated
    parsed = json.loads(frozen)
    assert parsed["classification"] == "SYNTHETIC"
    assert parsed["human_golden_acceptance"] == "PENDING"
    assert len(parsed["cases"]) == 26


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"kind": "write"},
        {**PRIMARY_SCOPE, "funding_agency": "Federal Aviation Administration"},
        {**PRIMARY_SCOPE, "limit": -1},
        {**PRIMARY_SCOPE, "limit": 0},
        {**PRIMARY_SCOPE, "limit": True},
        {**PRIMARY_SCOPE, "limit": 101},
        {**PRIMARY_SCOPE, "start_date": "2026-10-01", "end_date": "2026-09-30"},
        {**PRIMARY_SCOPE, "start_date": "2025-02-30"},
        {**PRIMARY_SCOPE, "start_date": "20251001"},
        {**PRIMARY_SCOPE, "award_types": "ABCD"},
        {**PRIMARY_SCOPE, "award_types": ["ADMIN"]},
        {**PRIMARY_SCOPE, "award_types": []},
        {"kind": "detail", "award_id": "SYN-FAA-PR-026", "limit": 1},
        {"kind": "recipient", "recipient": "Fictional", "limit": True},
    ],
)
def test_malformed_or_unsupported_reference_scope_rejected(scope):
    with pytest.raises(ValueError):
        answer(records(), scope)
