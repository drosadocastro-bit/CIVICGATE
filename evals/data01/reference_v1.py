"""Independent relational reference, not the HTTP fixture selector or policy.

Only new DATA-01 synthetic records are read. SQLite is in-memory/read-only in
purpose; it never opens the custody databases or implements a mutable service.
Algorithmic independence is not independent human golden-reference acceptance.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent


def answer(records: list[dict], scope: dict) -> dict:
    """Exact reference IDs, deterministic ties and cents, from semantic scope."""
    allowed = {
        "start_date",
        "end_date",
        "agency",
        "subagency",
        "state",
        "award_types",
        "recipient",
        "limit",
        "award_id",
        "kind",
    }
    if (
        type(scope) is not dict
        or set(scope) - allowed
        or type(scope.get("kind")) is not str
        or scope.get("kind") not in {"search", "detail", "recipient"}
    ):
        raise ValueError("DATA01_REFERENCE_SCOPE_UNSUPPORTED")
    kind = scope["kind"]
    required = {"detail": {"kind", "award_id"}, "recipient": {"kind", "recipient", "limit"}}
    if kind in required and set(scope) != required[kind]:
        raise ValueError("DATA01_REFERENCE_FIELDS_INVALID")
    for key in ("agency", "subagency", "state", "recipient", "award_id"):
        if (
            key in scope
            and scope[key] is not None
            and (type(scope[key]) is not str or not scope[key].strip())
        ):
            raise ValueError("DATA01_REFERENCE_TEXT_INVALID")
    if kind != "detail":
        limit = scope.get("limit")
        if type(limit) is not int or not 1 <= limit <= (25 if kind == "recipient" else 100):
            raise ValueError("DATA01_REFERENCE_LIMIT_INVALID")
    if kind == "search":
        if not {"kind", "start_date", "end_date", "limit"} <= set(scope) or {"award_id"} & set(
            scope
        ):
            raise ValueError("DATA01_REFERENCE_FIELDS_INVALID")
        try:
            start, end = (date.fromisoformat(scope[key]) for key in ("start_date", "end_date"))
            if (
                start.isoformat() != scope["start_date"]
                or end.isoformat() != scope["end_date"]
                or not 0 <= (end - start).days <= 366
            ):
                raise ValueError("DATA01_REFERENCE_DATES_INVALID")
        except (TypeError, ValueError) as exc:
            raise ValueError("DATA01_REFERENCE_DATES_INVALID") from exc
        types = scope.get("award_types", ["A", "B", "C", "D"])
        if (
            type(types) is not list
            or not 1 <= len(types) <= 12
            or any(
                type(t) is not str
                or t not in {"A", "B", "C", "D", "02", "03", "04", "05", "06", "09", "10", "11"}
                for t in types
            )
        ):
            raise ValueError("DATA01_REFERENCE_TYPES_INVALID")
    with sqlite3.connect(":memory:") as db:
        db.execute(
            "CREATE TABLE awards (id TEXT PRIMARY KEY, recipient TEXT, agency TEXT, "
            "subagency TEXT, state TEXT, type TEXT, date TEXT, cents INTEGER)"
        )
        db.executemany(
            "INSERT INTO awards VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r["award_id"],
                    r["recipient_name"],
                    r["awarding_agency"],
                    r["awarding_subagency"],
                    r["place_of_performance_state"],
                    r["award_type"],
                    r["award_date"],
                    int(Decimal(r["award_amount"]) * 100),
                )
                for r in records
            ],
        )
        if scope["kind"] == "detail":
            rows = db.execute(
                "SELECT id, cents FROM awards WHERE id = ?", (scope["award_id"],)
            ).fetchall()
            return {"award_ids": [r[0] for r in rows], "amount_cents": [r[1] for r in rows]}
        if scope["kind"] == "recipient":
            names = db.execute(
                "SELECT DISTINCT recipient FROM awards WHERE "
                "instr(lower(recipient), lower(?)) > 0 ORDER BY recipient",
                (scope["recipient"],),
            ).fetchall()
            limit = scope["limit"]
            return {
                "recipient_names": [r[0] for r in names[:limit]],
                "has_next": len(names) > limit,
            }
        clauses, values = ["date >= ?", "date <= ?"], [scope["start_date"], scope["end_date"]]
        for key, column in (("agency", "agency"), ("subagency", "subagency"), ("state", "state")):
            if scope.get(key) is not None:
                clauses.append(column + " = ?")
                values.append(scope[key])
        if scope.get("recipient") is not None:
            clauses.append("instr(lower(recipient), lower(?)) > 0")
            values.append(scope["recipient"])
        types = scope.get("award_types", ["A", "B", "C", "D"])
        clauses.append("type IN (" + ",".join("?" for _ in types) + ")")
        values.extend(types)
        result = db.execute(
            "SELECT id, cents FROM awards WHERE "
            + " AND ".join(clauses)
            + " ORDER BY cents DESC, id ASC",
            values,
        ).fetchall()
        page = result[: scope["limit"]]
        return {
            "award_ids": [r[0] for r in page],
            "amount_cents": [r[1] for r in page],
            "has_next": len(result) > scope["limit"],
            "matching_count": len(result),
            "returned_page_amount_usd": format(Decimal(sum(r[1] for r in page)) / 100, ".2f"),
            "scope": "RETURNED_PAGE_ONLY",
        }


def references() -> dict:
    data = json.loads((HERE / "awards_v1.json").read_bytes())
    benchmark = json.loads((HERE / "benchmark_v1.json").read_bytes())
    return {
        "version": 1,
        "classification": "SYNTHETIC",
        "method": "INDEPENDENT_SQLITE_REFERENCE",
        "human_golden_acceptance": "PENDING",
        "cases": [
            {
                "case_id": case["case_id"],
                "answer": answer(data["records"], case["reference_scope"])
                if case["reference_scope"] is not None
                else None,
            }
            for case in benchmark["cases"]
        ],
    }
