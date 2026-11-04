"""Fixed-reference DATA-01 generation; no randomness, network or real award data.

The immutable source describes fictional awards. Review annotations belong in a
separate future state store and must never be applied to this dataset.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

DATASET_ID = "CIVICGATE-DATA01-v1"
DOT = "Department of Transportation"
FAA = "Federal Aviation Administration"
FHWA = "Federal Highway Administration"
FTA = "Federal Transit Administration"
NASA = "National Aeronautics and Space Administration"
DATA_PATH = Path(__file__).with_name("awards_v1.json")

# Fixed reference rows are part of the versioned specification, not live records.
# Sequence, awarding subtier, funding top/subtier, state, date, type, amount.
REFERENCE_ROWS = (
    (1, FAA, DOT, FAA, "PR", "2025-10-01", "A", "12500000.00"),
    (2, FAA, DOT, FAA, "PR", "2026-09-30", "B", "8500000.00"),
    (3, FAA, DOT, FAA, "PR", "2026-01-15", "C", "7500000.00"),
    (4, FAA, DOT, FAA, "PR", "2026-05-20", "D", "4000000.00"),
    (5, FAA, DOT, FAA, "PR", "2026-07-04", "A", "2300000.00"),
    (6, FAA, DOT, FAA, "PR", "2025-12-31", "B", "0.10"),
    (7, FAA, DOT, FAA, "PR", "2025-09-30", "A", "9999999.00"),
    (8, FAA, DOT, FAA, "PR", "2026-10-01", "A", "8800000.00"),
    (9, FAA, DOT, FAA, "PR", "2024-10-01", "C", "1100000.00"),
    (10, FAA, DOT, FAA, "FL", "2026-01-15", "A", "15000000.00"),
    (11, FAA, DOT, FAA, "CA", "2026-02-01", "B", "14000000.00"),
    (12, FAA, DOT, FAA, "TX", "2026-03-01", "C", "13000000.00"),
    (13, FAA, DOT, FAA, "NY", "2026-04-01", "D", "12000000.00"),
    (14, FAA, DOT, FAA, "DC", "2026-06-01", "A", "1000000.00"),
    (15, FAA, DOT, FAA, "GU", "2026-08-01", "B", "600000.00"),
    (16, FHWA, DOT, FHWA, "PR", "2026-01-15", "A", "20000000.00"),
    (17, FTA, DOT, FTA, "PR", "2026-02-01", "B", "19000000.00"),
    (18, FHWA, DOT, FAA, "PR", "2026-03-01", "C", "18000000.00"),
    (19, FTA, DOT, FAA, "PR", "2026-04-01", "D", "17000000.00"),
    (20, NASA, DOT, FAA, "PR", "2026-05-01", "A", "16000000.00"),
    (21, NASA, NASA, NASA, "PR", "2026-06-01", "B", "15500000.00"),
    (22, FAA, NASA, NASA, "PR", "2026-06-15", "C", "3500000.00"),
    (23, FAA, DOT, FAA, "PR", "2026-08-15", "02", "45000000.00"),
    (24, FAA, DOT, FAA, "PR", "2026-08-20", "03", "42000000.00"),
    (25, FAA, DOT, FAA, "VI", "2026-09-01", "D", "750000.00"),
    (26, FAA, DOT, FAA, "PR", "2026-09-15", "D", "3250000.25"),
    (27, FAA, DOT, FAA, "PR", "2026-02-28", "A", "125000.01"),
    (28, FAA, DOT, FAA, "PR", "2026-03-31", "B", "0.20"),
    (29, FAA, DOT, FAA, "PR", "2026-04-30", "C", "7500000.00"),
    (30, FAA, DOT, FAA, "PR", "2026-05-31", "D", "4000000.00"),
    (31, FAA, DOT, FAA, "PR", "2026-06-30", "A", "0.00"),
    (32, FHWA, DOT, FHWA, "CA", "2026-07-01", "A", "26000000.00"),
    (33, FTA, DOT, FTA, "TX", "2026-07-02", "B", "27000000.00"),
    (34, FAA, DOT, FAA, "PR", "2025-10-02", "A", "999.99"),
    (35, FAA, DOT, FAA, "PR", "2026-09-29", "B", "10.00"),
    (36, FAA, DOT, FAA, "PR", "2025-09-29", "D", "55000000.00"),
    (37, FAA, DOT, FAA, "PR", "2026-10-02", "C", "56000000.00"),
    (38, FAA, DOT, FAA, "PR", "2026-01-01", "D", "123456.78"),
    (39, FAA, DOT, FAA, "MP", "2026-02-02", "A", "650000.00"),
    (40, NASA, NASA, NASA, "FL", "2025-10-01", "D", "999000.00"),
)

RECIPIENTS = (
    "Fictional Aurora Systems LLC",
    "Fictional Isla Research Cooperative",
    "Fictional Cobalto Engineering Inc",
    "Fictional Brisa Analytics LLC",
    "Fictional Nube Infrastructure Inc",
    "Fictional Faro Technical Services LLC",
    "Fictional Coral Instruments Inc",
    "Fictional Horizonte Data Cooperative",
)


def fiscal_year(day: str) -> int:
    parsed = date.fromisoformat(day)
    if parsed.isoformat() != day:
        raise ValueError("DATA01_DATE_NOT_CANONICAL")
    return parsed.year + (parsed.month >= 10)


def generate_dataset() -> dict:
    records = []
    for seq, agency, funding, funding_subagency, state, day, kind, amount in REFERENCE_ROWS:
        is_faa = agency == FAA
        code = "FAA" if is_faa else "DOT" if agency in {FHWA, FTA} else "NASA"
        records.append(
            {
                "award_id": f"SYN-{code}-{state}-{seq:03d}",
                "recipient_name": RECIPIENTS[(seq - 1) % len(RECIPIENTS)],
                "description": f"SYNTHETIC fictional award {seq:03d}: public-data evaluation only",
                "awarding_agency": DOT if code in {"FAA", "DOT"} else NASA,
                "awarding_subagency": agency,
                "funding_agency": funding,
                "funding_subagency": funding_subagency,
                "award_amount": amount,
                "award_type": kind,
                "award_date": day,
                "fiscal_year": fiscal_year(day),
                "place_of_performance_state": state,
                "review_status": "UNREVIEWED",
                "provenance": {
                    "classification": "SYNTHETIC",
                    "source": DATASET_ID,
                    "actual_government_record": False,
                },
            }
        )
    result = {
        "dataset_id": DATASET_ID,
        "classification": "SYNTHETIC",
        "generated_by": "evals/data01/generator.py:generate_dataset (fixed reference rows; no RNG)",
        "records": records,
    }
    validate_dataset(result)
    return result


def dataset_bytes(data: dict | None = None) -> bytes:
    return (json.dumps(data or generate_dataset(), indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def validate_dataset(data: object) -> None:
    """Strict stdlib validation mirrors schema plus cross-record invariants."""
    if type(data) is not dict or set(data) != {
        "dataset_id",
        "classification",
        "generated_by",
        "records",
    }:
        raise ValueError("DATA01_ROOT_FIELDS")
    if (
        data["dataset_id"] != DATASET_ID
        or data["classification"] != "SYNTHETIC"
        or type(data["generated_by"]) is not str
        or not data["generated_by"]
    ):
        raise ValueError("DATA01_PROVENANCE")
    rows = data["records"]
    if type(rows) is not list or len(rows) != 40:
        raise ValueError("DATA01_RECORD_COUNT")
    fields = {
        "award_id",
        "recipient_name",
        "description",
        "awarding_agency",
        "awarding_subagency",
        "funding_agency",
        "funding_subagency",
        "award_amount",
        "award_type",
        "award_date",
        "fiscal_year",
        "place_of_performance_state",
        "review_status",
        "provenance",
    }
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("DATA01_RECORD_FIELDS")
        for name in fields - {"provenance", "fiscal_year"}:
            if type(row[name]) is not str or not row[name] or len(row[name]) > 200:
                raise ValueError("DATA01_STRING_FIELD")
        identity = row["award_id"]
        if not re.fullmatch(r"SYN-(?:FAA|DOT|NASA)-[A-Z]{2}-\d{3}", identity) or identity in seen:
            raise ValueError("DATA01_RECORD_IDENTITY")
        seen.add(identity)
        if not row["recipient_name"].startswith("Fictional ") or not row["description"].startswith(
            "SYNTHETIC fictional award "
        ):
            raise ValueError("DATA01_FICTIONAL_LABEL")
        if not re.fullmatch(r"(?:0|[1-9]\d{0,11})\.\d{2}", row["award_amount"]):
            raise ValueError("DATA01_AMOUNT")
        if not Decimal(row["award_amount"]).is_finite():
            raise ValueError("DATA01_AMOUNT")
        if row["award_type"] not in {"A", "B", "C", "D", "02", "03"}:
            raise ValueError("DATA01_AWARD_TYPE")
        if (
            type(row["fiscal_year"]) is not int
            or not 2025 <= row["fiscal_year"] <= 2027
            or fiscal_year(row["award_date"]) != row["fiscal_year"]
        ):
            raise ValueError("DATA01_FISCAL_YEAR")
        if row["place_of_performance_state"] not in {
            "PR",
            "FL",
            "CA",
            "TX",
            "NY",
            "DC",
            "GU",
            "VI",
            "MP",
        }:
            raise ValueError("DATA01_STATE")
        if row["review_status"] != "UNREVIEWED":
            raise ValueError("DATA01_IMMUTABLE_REVIEW_STATE")
        provenance = row["provenance"]
        if type(provenance) is not dict or set(provenance) != {
            "classification",
            "source",
            "actual_government_record",
        }:
            raise ValueError("DATA01_PROVENANCE")
        if (
            provenance["classification"] != "SYNTHETIC"
            or provenance["source"] != DATASET_ID
            or provenance["actual_government_record"] is not False
        ):
            raise ValueError("DATA01_PROVENANCE")
        if row["awarding_subagency"] in {FAA, FHWA, FTA}:
            if row["awarding_agency"] != DOT:
                raise ValueError("DATA01_AGENCY_HIERARCHY")
        elif row["awarding_subagency"] != NASA or row["awarding_agency"] != NASA:
            raise ValueError("DATA01_AGENCY_HIERARCHY")
        if (row["funding_agency"], row["funding_subagency"]) not in {
            (DOT, FAA),
            (DOT, FHWA),
            (DOT, FTA),
            (NASA, NASA),
        }:
            raise ValueError("DATA01_FUNDING_HIERARCHY")
        if identity.split("-")[2] != row["place_of_performance_state"]:
            raise ValueError("DATA01_RECORD_STATE")
        if identity.split("-")[1] != (
            "FAA"
            if row["awarding_subagency"] == FAA
            else "DOT"
            if row["awarding_agency"] == DOT
            else "NASA"
        ):
            raise ValueError("DATA01_RECORD_AGENCY")


def load_dataset(path: Path = DATA_PATH) -> dict:
    raw = path.read_bytes()
    data = json.loads(raw)
    validate_dataset(data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or verify SYNTHETIC DATA-01 reference")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    expected = dataset_bytes()
    if args.output is None:
        if DATA_PATH.read_bytes() != expected:
            raise SystemExit("DATA01_REFERENCE_CHANGED")
        print("SYNTHETIC DATA-01: 40 fixed records; checked byte-identical")
    else:
        # Exclusive creation prevents overwriting the immutable original or evidence.
        with args.output.open("xb") as stream:
            stream.write(expected)


if __name__ == "__main__":
    main()
