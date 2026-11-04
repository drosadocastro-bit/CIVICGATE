"""DATA-01 immutability and deterministic synthetic-source controls only."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from evals.data01.generator import (
    DATA_PATH,
    DATASET_ID,
    DOT,
    FAA,
    dataset_bytes,
    fiscal_year,
    generate_dataset,
    load_dataset,
    validate_dataset,
)


def test_fixed_reference_is_byte_reproducible():
    original = DATA_PATH.read_bytes()
    assert original == dataset_bytes()
    assert dataset_bytes(generate_dataset()) == dataset_bytes(generate_dataset())
    assert len(load_dataset()["records"]) == 40
    assert DATA_PATH.read_bytes() == original


def test_provenance_is_fictional_and_not_real_government_evidence():
    data = load_dataset()
    assert data["classification"] == "SYNTHETIC"
    assert data["dataset_id"] == DATASET_ID
    for row in data["records"]:
        assert row["award_id"].startswith("SYN-")
        assert row["recipient_name"].startswith("Fictional ")
        assert row["provenance"] == {
            "classification": "SYNTHETIC",
            "source": DATASET_ID,
            "actual_government_record": False,
        }
        assert row["review_status"] == "UNREVIEWED"


@pytest.mark.parametrize(
    ("day", "expected"),
    [("2025-09-30", 2025), ("2025-10-01", 2026), ("2026-09-30", 2026), ("2026-10-01", 2027)],
)
def test_fiscal_year_boundaries(day, expected):
    assert fiscal_year(day) == expected
    assert day in {row["award_date"] for row in load_dataset()["records"]}


def test_required_positive_and_attribution_negative_controls_exist():
    records = load_dataset()["records"]
    positive = [
        row
        for row in records
        if row["awarding_agency"] == DOT
        and row["awarding_subagency"] == FAA
        and row["place_of_performance_state"] == "PR"
        and row["fiscal_year"] == 2026
        and row["award_type"] in {"A", "B", "C", "D"}
    ]
    assert len(positive) == 16
    assert {row["award_type"] for row in positive} == {"A", "B", "C", "D"}
    assert "SYN-FAA-PR-026" in {row["award_id"] for row in positive}
    funding_only = [
        row
        for row in records
        if row["funding_subagency"] == FAA and row["awarding_subagency"] != FAA
    ]
    assert {row["award_id"] for row in funding_only} == {
        "SYN-DOT-PR-018",
        "SYN-DOT-PR-019",
        "SYN-NASA-PR-020",
    }
    assert all(row not in positive for row in funding_only)
    assert any(row["place_of_performance_state"] != "PR" for row in records)
    assert any(row["fiscal_year"] != 2026 for row in records)
    assert any(row["award_type"] not in {"A", "B", "C", "D"} for row in records)


def test_source_amounts_remain_exact_decimal_strings():
    rows = {row["award_id"]: row for row in load_dataset()["records"]}
    assert all(type(row["award_amount"]) is str for row in rows.values())
    assert Decimal(rows["SYN-FAA-PR-006"]["award_amount"]) + Decimal(
        rows["SYN-FAA-PR-028"]["award_amount"]
    ) == Decimal("0.30")
    assert rows["SYN-FAA-PR-026"]["award_amount"] == "3250000.25"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("award_amount", 0.1),
        ("award_amount", "NaN"),
        ("award_amount", "1e6"),
        ("award_amount", "-1.00"),
        ("award_amount", "01.00"),
        ("fiscal_year", True),
        ("fiscal_year", 2025),
        ("award_date", "2026-02-30"),
        ("award_date", "20251001"),
        ("review_status", "PENDING_REVIEW"),
        ("award_type", "ADMIN"),
        ("place_of_performance_state", "ZZ"),
        ("recipient_name", "Real Contractor Inc"),
        ("awarding_agency", "Other Department"),
        ("funding_subagency", "Other Subagency"),
        ("award_id", "SYN-FAA-CA-001"),
        ("award_id", "SYN-NASA-PR-001"),
    ],
)
def test_invalid_or_mutated_source_records_rejected(field, value):
    data = generate_dataset()
    data["records"][0][field] = value
    with pytest.raises(ValueError):
        validate_dataset(data)


def test_unknown_and_missing_fields_and_duplicate_ids_rejected():
    for mutation in ("root-extra", "record-extra", "missing", "duplicate", "missing-record"):
        data = generate_dataset()
        if mutation == "root-extra":
            data["authority"] = "PERMIT"
        elif mutation == "record-extra":
            data["records"][0]["authority"] = "PERMIT"
        elif mutation == "missing":
            del data["records"][0]["award_amount"]
        elif mutation == "duplicate":
            data["records"][1] = copy.deepcopy(data["records"][0])
        else:
            data["records"].pop()
        with pytest.raises(ValueError):
            validate_dataset(data)


@pytest.mark.parametrize(("day", "year"), [("2023-10-01", 2024), ("2027-10-01", 2028)])
def test_schema_fiscal_year_range_is_enforced(day, year):
    data = generate_dataset()
    data["records"][0]["award_date"] = day
    data["records"][0]["fiscal_year"] = year
    with pytest.raises(ValueError, match="DATA01_FISCAL_YEAR"):
        validate_dataset(data)


@pytest.mark.parametrize("actual", [True, "false", 0, None])
def test_false_synthetic_provenance_is_rejected(actual):
    data = generate_dataset()
    data["records"][0]["provenance"]["actual_government_record"] = actual
    with pytest.raises(ValueError):
        validate_dataset(data)


def test_file_inventory_is_exact():
    manifest = json.loads(DATA_PATH.with_name("dataset_manifest_v1.json").read_bytes())
    assert manifest["classification"] == "SYNTHETIC"
    assert manifest["dataset_id"] == DATASET_ID
    assert {row["path"] for row in manifest["files"]} == {
        "awards_v1.json",
        "schema_v1.json",
        "generator.py",
    }
    for row in manifest["files"]:
        raw = DATA_PATH.with_name(row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]


def test_cli_never_overwrites_immutable_original(tmp_path):
    before = DATA_PATH.read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "evals.data01.generator", "--output", str(DATA_PATH)],
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )
    assert result.returncode != 0
    assert DATA_PATH.read_bytes() == before
    destination = tmp_path / "new-synthetic-copy.json"
    result = subprocess.run(
        [sys.executable, "-m", "evals.data01.generator", "--output", str(destination)],
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )
    assert result.returncode == 0
    assert destination.read_bytes() == before


def test_schema_declares_finite_locked_shape():
    schema = json.loads(DATA_PATH.with_name("schema_v1.json").read_bytes())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["classification"] == {"const": "SYNTHETIC"}
    assert schema["properties"]["records"]["minItems"] == 40
    assert schema["properties"]["records"]["maxItems"] == 40
    award = schema["$defs"]["award"]
    assert award["additionalProperties"] is False
    assert set(award["required"]) == set(generate_dataset()["records"][0])
    assert award["properties"]["award_amount"]["type"] == "string"
    assert award["properties"]["review_status"] == {"const": "UNREVIEWED"}
