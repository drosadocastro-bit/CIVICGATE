"""Read-only verification of pinned history; sealed values are hashed, never decoded."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from civicgate.rq6.core import ArtifactSnapshot, require, sha256
from civicgate.rq6.validators import validate_literal_leakage, validate_v01

LOCKED_HASHES = {
    "JUDGE_RQ6_AMENDMENT_001.md": "5a19676158b299437652bc2ea4a94d4f9613a5b38568c8a96bc3c2799c09ae19",
    "JUDGE_RQ6_AMENDMENT_001.json": "f44ead6460f7086965d4d54dccef9d32bf265ea7146ca12c313703963b5dd619",
    "JUDGE_RQ6_AMENDMENT_001_LOCK.json": "3ec06104daa780f5c76b62166c46fd9ff331c112d7b198cadda06c9edfa00e32",
}


def verify_locked_contract(docs: Path) -> dict[str, Any]:
    for name, digest in LOCKED_HASHES.items():
        require(sha256((docs / name).read_bytes()) == digest, "LOCKED_DOCUMENT_HASH_MISMATCH")
    amendment = json.loads((docs / "JUDGE_RQ6_AMENDMENT_001.json").read_bytes())
    lock = json.loads((docs / "JUDGE_RQ6_AMENDMENT_001_LOCK.json").read_bytes())
    require(
        lock["approved"] is True
        and lock["locked"] is True
        and lock["state"] == "CIVICGATE_RQ6_AMENDMENT_001_LOCKED",
        "INVALID_LOCK_RECEIPT",
    )
    require(lock["human_lock"]["authorized_by"] == "Danny", "LOCK_ACTOR_MISMATCH")
    require(
        lock["approved_document_version"]
        == {
            "markdown": LOCKED_HASHES["JUDGE_RQ6_AMENDMENT_001.md"],
            "json": LOCKED_HASHES["JUDGE_RQ6_AMENDMENT_001.json"],
        },
        "LOCK_PAIR_MISMATCH",
    )
    parent = docs / "JUDGE_COMPARISON_PROTOCOL_V1.json"
    require(
        sha256(parent.read_bytes()) == lock["parent_protocol_commitments"]["protocol_json_sha256"],
        "PARENT_LINEAGE_MISMATCH",
    )
    parent_data = json.loads(parent.read_bytes())
    require(
        parent_data["human_lock"]["authorized_by"] == lock["human_lock"]["authorized_by"],
        "LOCK_ACTOR_LINEAGE_MISMATCH",
    )
    for field in ("protocol_id", "package_id", "amendment_id"):
        require(amendment[field] == lock[field], "LOCK_IDENTITY_MISMATCH")
    return dict(lock)


def raw_inventory(root: Path) -> dict[str, str]:
    inventory: dict[str, str] = {}
    for path in root.rglob("*"):
        require(not path.is_symlink(), "HISTORICAL_SYMLINK")
        if path.is_file():
            inventory[path.relative_to(root).as_posix()] = sha256(path.read_bytes())
    return inventory


def verify_package_history(
    root: Path, expected: Mapping[str, str], lock: Mapping[str, Any]
) -> dict[str, Any]:
    """No private mapping, seed or repeat-output file is parsed, even for diagnostics."""
    actual = raw_inventory(root)
    require(dict(expected) == actual and len(actual) == 524, "HISTORICAL_PACKAGE_MUTATION")
    commitments = lock["parent_protocol_commitments"]
    manifest_path = root / "reviewer_sealed" / "manifest.json"
    require(
        sha256(manifest_path.read_bytes()) == commitments["reviewer_manifest_sha256"],
        "FROZEN_MANIFEST_MISMATCH",
    )
    manifest = json.loads(manifest_path.read_bytes())  # Structural metadata only.
    require(
        manifest["protocol_id"] == lock["protocol_id"]
        and manifest["package_id"] == lock["package_id"],
        "PACKAGE_IDENTITY_MISMATCH",
    )
    require(
        manifest["seed_commitment_sha256"] == commitments["seed_commitment_sha256"],
        "SEED_COMMITMENT_MISMATCH",
    )
    require(
        actual["operator_private/mapping.json"] == commitments["private_mapping_sha256"],
        "PRIVATE_MAPPING_HASH_MISMATCH",
    )
    require(
        len(manifest["repeat_bundles"]) == 6
        and all(
            row["release_status"] == "SEALED_NOT_RELEASED" for row in manifest["repeat_bundles"]
        ),
        "REPEATS_NOT_SEALED",
    )
    index = set(actual.values())
    closures = tuple(
        ArtifactSnapshot("historical_primary_closure", path.read_bytes(), sha256(path.read_bytes()))
        for path in (root / "case_closures").glob("*.json")
    )

    def closure_schema(record: ArtifactSnapshot) -> None:
        data = record.data()
        require(
            data["protocol_id"] == lock["protocol_id"] and data["package_id"] == lock["package_id"],
            "HISTORICAL_CLOSURE_IDENTITY",
        )
        require("COMPLETE_UNBLINDED" in data["closure_status"], "PRIMARY_NOT_CLOSED")
        # These original hash links predate RQ6, so no new RQ6 fields are imposed.
        for field in ("source_card_hashes", "decision_receipt_hashes", "release_receipt_hashes"):
            for digest in data.get(field, {}).values():
                require(digest in index, "HISTORICAL_CLOSURE_LINK_BROKEN")
        require(data["unblind_receipt_hash"] in index, "HISTORICAL_UNBLIND_LINK_BROKEN")

    validate_v01(expected, actual, closures, closure_schema)
    require(
        commitments["case_27_closure_sha256"] in {record.sha256 for record in closures},
        "CASE_27_CLOSURE_MISMATCH",
    )
    # Check original release schemas through their frozen exact byte hashes and
    # original links, without backfilling later wrapper-generation fields.
    absent = 0
    present = 0
    receipts = 0
    for path in (root / "reviewer_released").rglob("*release*.json"):
        data = json.loads(path.read_bytes())
        if "leakage_validation" in data:
            require(data["leakage_validation"] == "PASS", "HISTORICAL_LEAKAGE_FAILURE")
            present += 1
        else:
            absent += 1
        require(
            data["protocol_id"] == lock["protocol_id"] and data["package_id"] == lock["package_id"],
            "HISTORICAL_RECEIPT_IDENTITY",
        )
        for field, value in data.items():
            if field.endswith("card_sha256"):
                require(value in index, "HISTORICAL_RECEIPT_LINK_BROKEN")
        receipts += 1
    require(receipts == 81, "HISTORICAL_RECEIPT_COVERAGE")
    for path in (root / "reviewer_released").rglob("card.json"):
        validate_literal_leakage(json.loads(path.read_bytes()), ())
    return {
        "historical_files_verified": len(actual),
        "primary_cases_closed": len(closures),
        "remaining_sealed_primary_cards": 0,
        "remaining_sealed_repeat_bundles": 6,
        "historical_release_receipts_verified": receipts,
        "historical_explicit_leakage_PASS": present,
        "FIELD_NOT_PRESENT_IN_HISTORICAL_SCHEMA": absent,
        "repeat_content_decoded": False,
        "historical_evidence_modified": False,
    }
