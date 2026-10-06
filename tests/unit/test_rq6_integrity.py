"""Synthetic evidence preservation, historical compatibility and selector controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from civicgate.rq6.artifacts import ArtifactStore, historical_leakage_status
from civicgate.rq6.core import ArtifactSnapshot, RQ6Error, decode_exact, exact_json, require, sha256
from civicgate.rq6.schemas import FIELDS, SCHEMA_VERSIONS, validate_artifact
from civicgate.rq6.source import json_value_slice
from civicgate.rq6.validators import (
    CONTROL_IDS,
    PreMappingFailureValidator,
    validate_v01,
    validate_v02,
)
from civicgate.rq6.workflow import BundleWorkflow

STAMP = "2026-01-01T00:00:00+00:00"


def rejecting_verifier_result(*args: Any) -> Any:
    return False


def verify_snapshot_readable(record: ArtifactSnapshot) -> None:
    record.data()


def historical_schema(data: dict[str, Any]) -> None:
    require(
        set(data) <= {"schema_version", "card_sha256", "leakage_validation"}
        and data.get("schema_version") == "synthetic-original-v1"
        and data.get("card_sha256") == "a" * 64,
        "ORIGINAL_SCHEMA_INVALID",
    )


def test_absent_historical_field_is_neither_fail_nor_retroactive_pass() -> None:
    raw = b'{"schema_version":"synthetic-original-v1","card_sha256":"' + b"a" * 64 + b'"}'
    before = bytes(raw)
    assert (
        historical_leakage_status(raw, sha256(raw), historical_schema)
        == "FIELD_NOT_PRESENT_IN_HISTORICAL_SCHEMA"
    )
    assert raw == before and "leakage_validation" not in decode_exact(raw)


@pytest.mark.parametrize("status", ["FAIL", "NOT_TESTABLE", "UNVERIFIED", None])
def test_present_historical_field_must_pass(status: str | None) -> None:
    raw = exact_json(
        {
            "schema_version": "synthetic-original-v1",
            "card_sha256": "a" * 64,
            "leakage_validation": status,
        }
    )
    with pytest.raises(RQ6Error, match="HISTORICAL_LEAKAGE_FAILURE"):
        historical_leakage_status(raw, sha256(raw), historical_schema)


def test_absence_cannot_bypass_historical_hash_or_schema() -> None:
    raw = b'{"schema_version":"wrong"}'
    with pytest.raises(RQ6Error, match="HASH_MISMATCH"):
        historical_leakage_status(raw, "f" * 64, historical_schema)
    with pytest.raises(RQ6Error, match="ORIGINAL_SCHEMA_INVALID"):
        historical_leakage_status(raw, sha256(raw), historical_schema)


def test_exact_source_spans_preserve_pretty_json_and_decimal_lexeme() -> None:
    raw = (
        b'{\n "outputs" : [ { "confidence" : 9e-1, "rationale":"'
        + "é  ".encode()
        + b'", "flags":["NONE","NONE"] } ]\n}'
    )
    value = json_value_slice(raw, ("outputs", 0))
    assert value.startswith(b'{ "confidence" : 9e-1')
    decoded = decode_exact(value)
    assert exact_json(decoded).startswith(b'{"confidence":9e-1')
    assert decoded["rationale"] == "é  " and decoded["flags"] == ["NONE", "NONE"]


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_source_parser_rejects_ambiguous_or_nonfinite_json(raw: bytes) -> None:
    with pytest.raises(RQ6Error):
        json_value_slice(raw, ("x",))


def test_missing_source_pointer_stops() -> None:
    with pytest.raises(RQ6Error, match="SOURCE_POINTER_MISSING"):
        json_value_slice(b'{"one":1}', ("two",))


def test_exclusive_store_detects_mutation_and_registration_conflict(tmp_path: Path) -> None:
    artifact = ArtifactSnapshot.build("synthetic", {"value": "exact"})
    store = ArtifactStore(tmp_path / "custody", verify_snapshot_readable)
    assert store.persist(artifact) == artifact
    copy = tmp_path / "copy.json"
    copy.write_bytes(artifact.payload_bytes)
    with pytest.raises(RQ6Error, match="IMMUTABLE_REGISTRATION_CONFLICT"):
        store.consume("different-kind", copy, artifact.sha256)
    object_path = tmp_path / "custody/objects" / f"{artifact.sha256}.json"
    object_path.write_bytes(b"corrupted")
    with pytest.raises(RQ6Error, match="PERSISTED_ARTIFACT_MUTATION"):
        store.get(artifact.sha256)


def manifest_fixture() -> tuple[bytes, list[dict[str, Any]]]:
    bundles: list[dict[str, Any]] = []
    for number in range(1, 7):
        source = exact_json({"synthetic_bundle": number})
        entry = {"position": number, "sha256": sha256(source)}
        bundles.append(
            {
                "manifest_entry": entry,
                "raw_source_bytes": source,
                "source_slots": [f"synthetic-slot-{number}"],
                "repeat_selectors": [
                    {"repeat_number": repeat, "exact_selector": {"slot": number, "repeat": repeat}}
                    for repeat in range(1, 4)
                ],
            }
        )
    return exact_json({"repeat_bundles": [bundle["manifest_entry"] for bundle in bundles]}), bundles


def test_v02_exact_manifest_order_not_filename_order() -> None:
    raw, bundles = manifest_fixture()
    validate_v02(raw, sha256(raw), bundles)
    with pytest.raises(RQ6Error, match="MANIFEST_ORDER_CHANGED"):
        validate_v02(raw, sha256(raw), list(reversed(bundles)))


@pytest.mark.parametrize(
    "defect", ["hash", "regroup", "repeat_order", "duplicate_selector", "source_hash"]
)
def test_v02_frozen_structure_stops_substantive_failure(defect: str) -> None:
    raw, bundles = manifest_fixture()
    digest = sha256(raw)
    if defect == "hash":
        digest = "f" * 64
    elif defect == "regroup":
        bundles[0]["source_slots"].append("another-slot")
    elif defect == "repeat_order":
        bundles[0]["repeat_selectors"].reverse()
    elif defect == "duplicate_selector":
        bundles[0]["repeat_selectors"][1]["exact_selector"] = bundles[0]["repeat_selectors"][0][
            "exact_selector"
        ]
    else:
        bundles[0]["raw_source_bytes"] = b"different"
    with pytest.raises(RQ6Error):
        validate_v02(raw, digest, bundles)


def test_v01_intact_counts_and_case_uniqueness() -> None:
    baseline = {"synthetic/file": "a" * 64}
    closures = [ArtifactSnapshot.build("synthetic", {"case_id": "one"})]
    validate_v01(
        baseline,
        baseline,
        closures,
        verify_snapshot_readable,
        expected_case_count=1,
        expected_file_count=1,
    )
    with pytest.raises(RQ6Error, match="HISTORICAL_MUTATION"):
        validate_v01(
            baseline,
            {},
            closures,
            lambda record: None,
            expected_case_count=1,
            expected_file_count=1,
        )
    with pytest.raises(RQ6Error, match="DUPLICATE_PRIMARY"):
        validate_v01(
            baseline,
            baseline,
            closures * 2,
            lambda record: None,
            expected_case_count=2,
            expected_file_count=1,
        )


def test_v01_verifier_false_is_not_success() -> None:
    baseline = {"synthetic/file": "a" * 64}
    closure = ArtifactSnapshot.build("synthetic", {"case_id": "one"})
    with pytest.raises(RQ6Error, match="INVALID_VERIFIER_CONTRACT"):
        validate_v01(
            baseline,
            baseline,
            [closure],
            rejecting_verifier_result,
            expected_case_count=1,
            expected_file_count=1,
        )


def test_schema_parity_with_exact_locked_contract() -> None:
    contract = json.loads(
        (Path(__file__).parents[2] / "docs/JUDGE_RQ6_AMENDMENT_001.json").read_bytes()
    )
    artifacts = contract["artifact_contracts"]
    for name, fields in FIELDS.items():
        assert fields == tuple(artifacts[name]["fields"])
        assert SCHEMA_VERSIONS[name] == artifacts[name].get("schema_version")
    assert CONTROL_IDS == tuple(item["id"] for item in contract["proposed_validators"])


def test_full_premapping_failure_closure_no_seed_or_alias(tmp_path: Path) -> None:
    manifest_hash = sha256(b"synthetic frozen manifest")
    failure = ArtifactSnapshot.build(
        "original_limitation",
        {
            "frozen_manifest_sha256": manifest_hash,
            "expected_evidence": ["primary", "r1", "r2", "r3"],
            "available_evidence": [],
            "missing_evidence": ["primary", "r1", "r2", "r3"],
            "unusable_evidence": [],
            "evidence_limitation_reasons": ["Synthetic source unavailable"],
            "relevant_hashes_or_validation_failures": [
                {"control": "source integrity", "result": "FAIL"}
            ],
            "stability_not_established_reason": "All scheduled evidence unavailable.",
            "validation_results": {"RQ6-V02": "FAIL"},
        },
    )
    failure_path = tmp_path / "original-failure.json"
    failure_path.write_bytes(failure.payload_bytes)
    binding = {
        "protocol_id": "CIVICGATE-JUDGE-COMPARISON-V1",
        "amendment_id": "CIVICGATE-RQ6-AMENDMENT-001",
        "package_id": "synthetic-package",
        "bundle_review_id": f"RQ6_CUSTODY_FAILURE:{manifest_hash}:1",
    }

    def original(record: ArtifactSnapshot) -> None:
        require(
            failure_path.read_bytes() == record.payload_bytes
            and sha256(record.payload_bytes) == record.sha256,
            "ORIGINAL_FAILURE_CHANGED",
        )

    verifier = PreMappingFailureValidator(
        binding, failure, original_failure_verifier=original, continuity_verifier=lambda: None
    )
    registry: dict[str, ArtifactSnapshot] = {}

    def persisted(record: ArtifactSnapshot) -> None:
        require(registry.get(record.sha256) == record, "UNPERSISTED_FAILURE_CLOSURE")
        verifier(record)

    flow = BundleWorkflow.pre_mapping_failure(
        protocol_id=binding["protocol_id"],
        amendment_id=binding["amendment_id"],
        package_id=binding["package_id"],
        frozen_manifest_sha256=manifest_hash,
        private_manifest_position=1,
        verifier=persisted,
    )
    data = {
        **binding,
        "schema_version": SCHEMA_VERSIONS["bundle_closure"],
        "frozen_manifest_position": 1,
        "applicable_primary_case_id": "synthetic-primary",
        "reviewer_unit_ids": [],
        "reviewer_artifact_hashes": [],
        "human_receipt_hashes": [],
        "unit_closure_hashes": [],
        "source_artifact_hashes": [],
        "primary_anchor_hashes": [],
        "stored_classifications": [],
        "stored_structured_flag_lists": [],
        "stored_confidences": [],
        "normalized_flag_sets": [],
        "alias_commitment_sha256": None,
        "unblind_receipt_sha256": None,
        "revealed_source_mapping": None,
        "frozen_rationale_variation_record": None,
        "rationale_variation_assessment_receipt_sha256": None,
        "per_model_primary_repeat_comparison": None,
        "confidence_descriptive_values_and_range": None,
        "review_status": "RQ6_REVIEW_COMPLETE",
        "stability_disposition": "INSUFFICIENT_REPEAT_EVIDENCE",
        "timestamps": {"closure": STAMP},
        "validation_results": {"RQ6-V02": "FAIL", "RQ6-V12": "PASS"},
        "provenance_hashes": [failure.sha256],
        "state": "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE",
        "reviewer_access_policy_sha256": "a" * 64,
        "authorized_identity_audience": ["synthetic custody authority"],
        **{
            key: value
            for key, value in failure.data().items()
            if key not in {"frozen_manifest_sha256", "validation_results"}
        },
    }
    validate_artifact("bundle_closure", data)
    closure = ArtifactSnapshot.build("bundle_closure", data)
    verifier(closure)
    registry[closure.sha256] = closure
    flow.close_insufficient(closure)
    assert flow.custody_only and flow.required_unit_ids == ()
    assert flow.state == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"
    data["validation_results"]["RQ6-V02"] = "PASS"
    with pytest.raises(RQ6Error, match="FAILURE_CONTROL_REWRITTEN"):
        verifier(ArtifactSnapshot.build("bundle_closure", data))


def premapping_partial_fixture(
    tmp_path: Path, *, with_confidence: bool = True
) -> tuple[PreMappingFailureValidator, dict[str, Any]]:
    """Existing synthetic own primary and physical custody bytes; no reviewer objects."""
    manifest_hash = sha256(b"synthetic pre-mapping frozen selection")
    binding = {
        "protocol_id": "CIVICGATE-JUDGE-COMPARISON-V1",
        "amendment_id": "CIVICGATE-RQ6-AMENDMENT-001",
        "package_id": "synthetic-partial-package",
        "bundle_review_id": f"RQ6_CUSTODY_FAILURE:{manifest_hash}:1",
    }
    output = {
        "classification": "IN_SCOPE",
        "flags": ["NONE"],
        "confidence": decode_exact(b"9e-1"),
        "rationale": "Synthetic immutable own-primary text.  ",
    }
    source_raw = exact_json({"own_primary": {"case_id": "synthetic-primary", "output": output}})
    primary_raw = json_value_slice(source_raw, ("own_primary",))
    source_hash, primary_hash = sha256(source_raw), sha256(primary_raw)
    source_path, primary_path = tmp_path / "source.json", tmp_path / "primary.json"
    source_path.write_bytes(source_raw)
    primary_path.write_bytes(primary_raw)
    failure_fields: dict[str, Any] = {
        "expected_evidence": ["primary", "r1", "r2", "r3"],
        "available_evidence": ["primary"],
        "missing_evidence": ["r1", "r2", "r3"],
        "unusable_evidence": [],
        "evidence_limitation_reasons": ["Three synthetic required repeats unavailable."],
        "relevant_hashes_or_validation_failures": [{"control": "RQ6-V02", "result": "FAIL"}],
        "stability_not_established_reason": "Required repeat coverage incomplete.",
        "validation_results": {"RQ6-V02": "FAIL"},
    }
    failure = ArtifactSnapshot.build(
        "original_limitation", {"frozen_manifest_sha256": manifest_hash, **failure_fields}
    )
    failure_path = tmp_path / "original-failure.json"
    failure_path.write_bytes(failure.payload_bytes)
    confidences = [output["confidence"]]
    context_fields: dict[str, Any] = {
        "frozen_manifest_position": 1,
        "applicable_primary_case_id": "synthetic-primary",
        "reviewer_access_policy_sha256": sha256(b"synthetic approved custody policy"),
        "authorized_identity_audience": ["synthetic custody authority"],
        "available_evidence": ["primary"],
        "source_artifact_hashes": [source_hash],
        "primary_anchor_hashes": [primary_hash],
        "stored_classifications": [output["classification"]],
        "stored_structured_flag_lists": [output["flags"]],
        "stored_confidences": confidences,
        "normalized_flag_sets": [[]],
        "confidence_descriptive_values_and_range": {
            "interpretation": "DESCRIPTIVE_ONLY",
            "values": confidences,
            "range": [min(confidences), max(confidences)],
        }
        if with_confidence
        else None,
    }
    context = ArtifactSnapshot.build(
        "premapping_available_evidence",
        {
            **binding,
            **context_fields,
            "frozen_manifest_sha256": manifest_hash,
            "provenance_hashes": [source_hash, primary_hash],
        },
    )
    context_path = tmp_path / "available-context.json"
    context_path.write_bytes(context.payload_bytes)

    def original(record: ArtifactSnapshot) -> None:
        require(record == failure, "ORIGINAL_FAILURE_CHANGED")
        require(failure_path.read_bytes() == record.payload_bytes, "ORIGINAL_FAILURE_CHANGED")

    def available(record: ArtifactSnapshot) -> None:
        require(
            record == context and context_path.read_bytes() == record.payload_bytes,
            "AVAILABLE_CONTEXT_CUSTODY_CHANGED",
        )
        current_source = source_path.read_bytes()
        current_primary = primary_path.read_bytes()
        require(
            sha256(current_source) == source_hash and sha256(current_primary) == primary_hash,
            "AVAILABLE_SOURCE_HASH_CHANGED",
        )
        require(
            json_value_slice(current_source, ("own_primary",)) == current_primary
            and decode_exact(current_primary)["case_id"]
            == context_fields["applicable_primary_case_id"]
            and exact_json(decode_exact(current_primary)["output"]) == exact_json(output),
            "AVAILABLE_FROZEN_SELECTION_CHANGED",
        )

    verifier = PreMappingFailureValidator(
        binding,
        failure,
        original_failure_verifier=original,
        continuity_verifier=lambda: None,
        available_evidence_context=context,
        available_evidence_verifier=available,
    )
    payload = {
        **binding,
        **context_fields,
        **failure_fields,
        "schema_version": SCHEMA_VERSIONS["bundle_closure"],
        "reviewer_unit_ids": [],
        "reviewer_artifact_hashes": [],
        "human_receipt_hashes": [],
        "unit_closure_hashes": [],
        "alias_commitment_sha256": None,
        "unblind_receipt_sha256": None,
        "revealed_source_mapping": None,
        "frozen_rationale_variation_record": None,
        "rationale_variation_assessment_receipt_sha256": None,
        "per_model_primary_repeat_comparison": None,
        "review_status": "RQ6_REVIEW_COMPLETE",
        "stability_disposition": "INSUFFICIENT_REPEAT_EVIDENCE",
        "timestamps": {"closure": STAMP},
        "validation_results": {"RQ6-V02": "FAIL", "RQ6-V12": "PASS"},
        "provenance_hashes": [failure.sha256, context.sha256, source_hash, primary_hash],
        "state": "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE",
    }
    return verifier, payload


@pytest.mark.parametrize("with_confidence", [False, True])
def test_premapping_partial_primary_remains_available_without_reviewer_objects(
    tmp_path: Path, with_confidence: bool
) -> None:
    verifier, payload = premapping_partial_fixture(tmp_path, with_confidence=with_confidence)
    closure = ArtifactSnapshot.build("bundle_closure", payload)
    verifier(closure)
    flow = BundleWorkflow.pre_mapping_failure(
        **{key: verifier.binding[key] for key in ("protocol_id", "amendment_id", "package_id")},
        frozen_manifest_sha256=verifier.failure_record.data()["frozen_manifest_sha256"],
        private_manifest_position=1,
        verifier=verifier,
    )
    flow.close_insufficient(closure)
    assert flow.custody_only and flow.required_unit_ids == ()
    assert flow.state == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"
    assert closure.data()["validation_results"] == {"RQ6-V02": "FAIL", "RQ6-V12": "PASS"}
    assert closure.data()["stored_structured_flag_lists"] == [["NONE"]]
    assert b'"stored_confidences":[9e-1]' in closure.payload_bytes
    assert closure.data()["alias_commitment_sha256"] is None


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_artifact_hashes", ["f" * 64]),
        ("primary_anchor_hashes", ["f" * 64]),
        ("stored_classifications", ["OUT_OF_SCOPE"]),
        ("stored_structured_flag_lists", [["PROVENANCE_RISK"]]),
        ("stored_confidences", [decode_exact(b"0.90")]),
        ("normalized_flag_sets", [["PROVENANCE_RISK"]]),
        ("authorized_identity_audience", ["unapproved synthetic recipient"]),
        ("applicable_primary_case_id", "another-primary"),
        ("reviewer_access_policy_sha256", "f" * 64),
        ("frozen_manifest_position", 2),
        ("provenance_hashes", ["f" * 64]),
        ("confidence_descriptive_values_and_range", {"interpretation": "SCORED"}),
    ],
)
def test_premapping_partial_closure_rejects_changed_verified_projection(
    tmp_path: Path, field: str, replacement: Any
) -> None:
    verifier, payload = premapping_partial_fixture(tmp_path)
    payload[field] = replacement
    with pytest.raises(RQ6Error):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


def test_premapping_available_context_requires_mandatory_verifier(tmp_path: Path) -> None:
    verifier, _ = premapping_partial_fixture(tmp_path)
    with pytest.raises(RQ6Error, match="AVAILABLE_CONTEXT_NOT_VERIFIED"):
        PreMappingFailureValidator(
            verifier.binding,
            verifier.failure_record,
            original_failure_verifier=verifier.original_failure_verifier,
            continuity_verifier=lambda: None,
            available_evidence_context=verifier.available_evidence_context,
        )


@pytest.mark.parametrize("defect", ["hash", "self-consistent-context", "physical-context"])
def test_premapping_available_context_is_immutable_and_hash_bound(
    tmp_path: Path, defect: str
) -> None:
    verifier, payload = premapping_partial_fixture(tmp_path)
    context = verifier.available_evidence_context
    assert context is not None
    if defect == "hash":
        verifier.available_evidence_context = ArtifactSnapshot(
            context.kind, context.payload_bytes + b" ", context.sha256
        )
    elif defect == "self-consistent-context":
        data = context.data()
        data["applicable_primary_case_id"] = "another-primary"
        verifier.available_evidence_context = ArtifactSnapshot.build(context.kind, data)
        payload["applicable_primary_case_id"] = "another-primary"
    else:
        (tmp_path / "available-context.json").write_bytes(b"corrupted synthetic context")
    with pytest.raises(RQ6Error):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


@pytest.mark.parametrize("filename", ["source.json", "primary.json"])
def test_premapping_available_context_rechecks_actual_custody_bytes(
    tmp_path: Path, filename: str
) -> None:
    verifier, payload = premapping_partial_fixture(tmp_path)
    (tmp_path / filename).write_bytes(b"corrupted synthetic source")
    with pytest.raises(RQ6Error, match="AVAILABLE_SOURCE_HASH_CHANGED"):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


def test_premapping_default_branch_does_not_trust_unverified_available_fields(
    tmp_path: Path,
) -> None:
    configured, payload = premapping_partial_fixture(tmp_path)
    verifier = PreMappingFailureValidator(
        configured.binding,
        configured.failure_record,
        original_failure_verifier=configured.original_failure_verifier,
        continuity_verifier=lambda: None,
    )
    with pytest.raises(RQ6Error, match="UNVERIFIED_AVAILABLE_EVIDENCE"):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


def test_premapping_available_verifier_cannot_silently_return_false(tmp_path: Path) -> None:
    verifier, payload = premapping_partial_fixture(tmp_path)
    verifier.available_evidence_verifier = lambda record: False  # type: ignore[assignment]
    with pytest.raises(RQ6Error, match="AVAILABLE_CONTEXT_VERIFIER_CONTRACT"):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


@pytest.mark.parametrize("gate", ["continuity_verifier", "original_failure_verifier"])
def test_premapping_required_verifier_false_is_not_success(tmp_path: Path, gate: str) -> None:
    verifier, payload = premapping_partial_fixture(tmp_path)
    setattr(verifier, gate, rejecting_verifier_result)
    with pytest.raises(RQ6Error, match="VERIFIER_CONTRACT"):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


def test_premapping_no_context_cannot_omit_known_available_primary(tmp_path: Path) -> None:
    configured, payload = premapping_partial_fixture(tmp_path)
    for field in (
        "source_artifact_hashes",
        "primary_anchor_hashes",
        "stored_classifications",
        "stored_structured_flag_lists",
        "stored_confidences",
        "normalized_flag_sets",
    ):
        payload[field] = []
    payload["confidence_descriptive_values_and_range"] = None
    payload["provenance_hashes"] = [configured.failure_record.sha256]
    verifier = PreMappingFailureValidator(
        configured.binding,
        configured.failure_record,
        original_failure_verifier=configured.original_failure_verifier,
        continuity_verifier=lambda: None,
    )
    with pytest.raises(RQ6Error, match="UNVERIFIED_AVAILABLE_EVIDENCE"):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))


@pytest.mark.parametrize("defect", ["unaccounted-primary", "unexpected-evidence"])
def test_premapping_no_context_requires_faithful_coverage_partition(
    tmp_path: Path, defect: str
) -> None:
    configured, payload = premapping_partial_fixture(tmp_path)
    failure_data = configured.failure_record.data()
    failure_data["available_evidence"] = []
    failure_data["missing_evidence"] = (
        ["r1", "r2", "r3"]
        if defect == "unaccounted-primary"
        else ["primary", "r1", "r2", "r3", "unexpected"]
    )
    failure = ArtifactSnapshot.build("original_limitation", failure_data)
    payload.update(
        {
            key: value
            for key, value in failure_data.items()
            if key not in {"frozen_manifest_sha256", "validation_results"}
        }
    )
    for field in (
        "source_artifact_hashes",
        "primary_anchor_hashes",
        "stored_classifications",
        "stored_structured_flag_lists",
        "stored_confidences",
        "normalized_flag_sets",
    ):
        payload[field] = []
    payload["confidence_descriptive_values_and_range"] = None
    payload["provenance_hashes"] = [failure.sha256]
    verifier = PreMappingFailureValidator(
        configured.binding,
        failure,
        original_failure_verifier=lambda record: require(record == failure, "FAILURE_CHANGED"),
        continuity_verifier=lambda: None,
    )
    with pytest.raises(RQ6Error, match="INSUFFICIENT_COVERAGE_PARTITION"):
        verifier(ArtifactSnapshot.build("bundle_closure", payload))
