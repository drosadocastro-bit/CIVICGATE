"""Only synthetic artifacts: no repeat package files, source outputs or entropy."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest

from civicgate.rq6.core import RQ6Error
from civicgate.rq6.schemas import (
    AMENDMENT_ID,
    FIELDS,
    PROTOCOL_ID,
    SCHEMA_VERSIONS,
    validate_artifact,
)

H = "a" * 64
HASHES = [str(number) * 64 for number in range(1, 4)]
TIME = "2026-10-06T18:00:00.000000+00:00"


def synthetic_artifact(kind: str) -> dict[str, Any]:
    """Complete synthetic examples for each exact prospective field set."""
    values: dict[str, Any] = {
        "schema_version": SCHEMA_VERSIONS[kind],
        "protocol_id": PROTOCOL_ID,
        "amendment_id": AMENDMENT_ID,
        "package_id": "synthetic-package",
        "bundle_review_id": H,
        "reviewer_unit_id": "b" * 64,
        "blind_alias": "SIDE_1",
        "observation_sequence_within_bundle": 1,
        "user_request": "Synthetic visible request.",
        "proposed_tool": "synthetic_tool",
        "proposed_arguments": {"recipient": "  Synthetic  ", "count": 1},
        "frozen_neutral_reference": {"classification": "IN_SCOPE", "flags": []},
        "stored_output": {
            "classification": "IN_SCOPE",
            "confidence": Decimal("0.5000"),
            "flags": ["AMBIGUOUS_TARGET", "AMBIGUOUS_TARGET"],
            "rationale": "  Synthetic rationale.\n",
        },
        "primary_disposition": "ALIGNED",
        "rationale_propositions": ["TARGET_AMBIGUITY"],
        "reviewer_reason": "  Independent synthetic human reason.\n",
        "reviewer": "synthetic-human",
        "adjudication_status": "FROZEN",
        "operationally_mapping_blind_at_coding": True,
        "mechanical_stability_seen": False,
        "immutability": "Immutable synthetic record.",
        "previous_unit_closure_sha256": None,
        "release_timestamp": TIME,
        "adjudication_timestamp": TIME,
        "closure_timestamp": TIME,
        "semantic_coding_frozen": True,
        "unblinded": False,
        "state": "SEMANTICALLY_CLOSED_BLINDED",
        "validation_results": {"RQ6-V07": "PASS"},
        "required_human_receipt_hashes": HASHES,
        "required_unit_closure_hashes": HASHES,
        "authorized_recipients": ["synthetic-authority"],
        "revealed_current_bundle_mapping": {"SIDE_1": "synthetic-source"},
        "current_bundle_commitment_openings": {"synthetic_opening": "test-only"},
        "current_bundle_source_link_openings": [{"synthetic_link": "test-only"}],
        "unblind_timestamp": TIME,
        "scope": "Current synthetic bundle only.",
        "event_sequence": 1,
        "event_type": "ALIAS_COMMITMENT_FIXED",
        "previous_event_sha256": None,
        "timestamp": TIME,
        "completed_unit_receipt_hashes": HASHES,
        "primary_stored_rationale": "Synthetic primary rationale.",
        "repeat_rationales": ["Synthetic repeat rationale."] * 3,
        "frozen_primary_semantic_coding": {
            "rationale_propositions": ["TARGET_AMBIGUITY"],
            "reviewer_reason": "Historical synthetic text.",
        },
        "frozen_repeat_semantic_coding": [
            {
                "rationale_propositions": ["TARGET_AMBIGUITY"],
                "reviewer_reason": "Frozen synthetic reason.",
            }
        ]
        * 3,
        "frozen_proposition_sets": [["TARGET_AMBIGUITY"]] * 4,
        "proposition_set_difference_candidate": False,
        "rationale_variation": "NONE",
        "material_rationale_variation_confirmed": False,
        "material_boundary_changed": False,
        "human_variation_note": None,
        "assessment_timestamp": TIME,
        "source_identity_seen_at_assessment": True,
        "independent_unit_coding_reopened": False,
        "access_contract": "OPERATIONALLY_MAPPING_BLIND",
        "access_mode": "REVIEWER_ATTESTATION",
        "reviewer_attestation": "Only sanitized synthetic release artifacts used.",
        "enforcement_evidence_hashes": [],
        "effective_timestamp": TIME,
        "valid_through_bundle_semantic_freeze": True,
        "frozen_manifest_position": 1,
        "applicable_primary_case_id": "synthetic-case",
        "source_artifact_hashes": [H],
        "reviewer_unit_ids": HASHES,
        "reviewer_artifact_hashes": HASHES,
        "human_receipt_hashes": HASHES,
        "unit_closure_hashes": HASHES,
        "revealed_source_mapping": {"SIDE_1": "synthetic-source"},
        "primary_anchor_hashes": [H],
        "stored_classifications": ["IN_SCOPE"] * 4,
        "stored_structured_flag_lists": [[]] * 4,
        "stored_confidences": [Decimal("0.50")] * 4,
        "normalized_flag_sets": [[]] * 4,
        "per_model_primary_repeat_comparison": {"classification_changed": False},
        "confidence_descriptive_values_and_range": {
            "values": [Decimal("0.50")] * 4,
            "range": Decimal("0.00"),
        },
        "frozen_rationale_variation_record": {
            "material_rationale_variation_confirmed": False,
            "material_boundary_changed": False,
        },
        "review_status": "RESOLVED",
        "stability_disposition": "STABLE",
        "timestamps": {"closure": TIME},
        "provenance_hashes": [H],
        "authorized_identity_audience": ["synthetic-custodian"],
        "expected_evidence": [
            "synthetic-primary",
            "synthetic-repeat-1",
            "synthetic-repeat-2",
            "synthetic-repeat-3",
        ],
        "available_evidence": [
            "synthetic-primary",
            "synthetic-repeat-1",
            "synthetic-repeat-2",
            "synthetic-repeat-3",
        ],
        "missing_evidence": [],
        "unusable_evidence": [],
        "evidence_limitation_reasons": [],
        "relevant_hashes_or_validation_failures": [],
        "stability_not_established_reason": None,
    }
    if kind == "bundle_closure":
        values["state"] = "RQ6_BUNDLE_CLOSED"
    result = {
        field: deepcopy(values.get(field, H if field.endswith("_sha256") else None))
        for field in FIELDS[kind]
    }
    if kind == "empty_human_form":
        result = {"primary_disposition": None, "rationale_propositions": [], "reviewer_reason": ""}
    return result


def insufficient_artifact() -> dict[str, Any]:
    result = synthetic_artifact("bundle_closure")
    result.update(
        {
            "bundle_review_id": f"RQ6_CUSTODY_FAILURE:{H}:1",
            "alias_commitment_sha256": None,
            "state": "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE",
            "stability_disposition": "INSUFFICIENT_REPEAT_EVIDENCE",
            "missing_evidence": ["synthetic-repeat-3"],
            "available_evidence": [],
            "evidence_limitation_reasons": ["Synthetic unrecoverable observation."],
            "relevant_hashes_or_validation_failures": [{"RQ6-V05": "FAIL"}],
            "stability_not_established_reason": "Required repeat unavailable.",
            "validation_results": {"RQ6-V05": "FAIL", "RQ6-V12": "PASS"},
        }
    )
    for field in (
        "unblind_receipt_sha256",
        "revealed_source_mapping",
        "frozen_rationale_variation_record",
        "rationale_variation_assessment_receipt_sha256",
        "per_model_primary_repeat_comparison",
        "confidence_descriptive_values_and_range",
    ):
        result[field] = None
    for field in (
        "reviewer_unit_ids",
        "reviewer_artifact_hashes",
        "human_receipt_hashes",
        "unit_closure_hashes",
        "source_artifact_hashes",
        "primary_anchor_hashes",
        "stored_classifications",
        "stored_structured_flag_lists",
        "stored_confidences",
        "normalized_flag_sets",
    ):
        result[field] = []
    return result


@pytest.mark.parametrize("kind", list(FIELDS))
def test_all_declared_synthetic_schemas_accept_without_mutation(kind: str) -> None:
    artifact = synthetic_artifact(kind)
    original = deepcopy(artifact)
    validate_artifact(kind, artifact)
    assert artifact == original


@pytest.mark.parametrize("kind", list(FIELDS))
def test_exact_field_set_rejects_missing_and_extra_fields(kind: str) -> None:
    artifact = synthetic_artifact(kind)
    artifact["source_identity"] = "SEALED_SYNTHETIC_IDENTITY"
    with pytest.raises(RQ6Error, match="ARTIFACT_FIELDS_MISMATCH") as error:
        validate_artifact(kind, artifact)
    assert "SEALED_SYNTHETIC_IDENTITY" not in str(error.value)
    del artifact["source_identity"]
    del artifact[FIELDS[kind][0]]
    with pytest.raises(RQ6Error, match="ARTIFACT_FIELDS_MISMATCH"):
        validate_artifact(kind, artifact)


@pytest.mark.parametrize("value", [True, "0.5", Decimal("NaN"), float("inf"), -0.1, 1.1])
def test_confidence_rejects_coercion_nonfinite_and_out_of_range(value: Any) -> None:
    artifact = synthetic_artifact("reviewer_card")
    artifact["stored_output"]["confidence"] = value
    with pytest.raises(RQ6Error):
        validate_artifact("reviewer_card", artifact)


def test_preserves_exact_decimal_text_and_duplicate_flag_representation() -> None:
    artifact = synthetic_artifact("reviewer_card")
    output = artifact["stored_output"]
    confidence = output["confidence"]
    validate_artifact("reviewer_card", artifact)
    assert output["confidence"] is confidence
    assert str(confidence) == "0.5000"
    assert output["flags"] == ["AMBIGUOUS_TARGET", "AMBIGUOUS_TARGET"]
    assert output["rationale"] == "  Synthetic rationale.\n"


def test_decimal_subclass_ingestion_keeps_numeric_evidence() -> None:
    class SyntheticDecimal(Decimal):
        pass

    artifact = synthetic_artifact("reviewer_card")
    confidence = SyntheticDecimal("0.5000")
    artifact["stored_output"]["confidence"] = confidence
    validate_artifact("reviewer_card", artifact)
    assert artifact["stored_output"]["confidence"] is confidence


@pytest.mark.parametrize(
    "field,value",
    [
        ("classification", ["IN_SCOPE"]),
        ("flags", ["SYNONYM_FLAG"]),
        ("rationale", 1),
        ("rationale", "x" * 501),
    ],
)
def test_reviewer_output_nested_types_and_source_schema_limits(field: str, value: Any) -> None:
    artifact = synthetic_artifact("reviewer_card")
    artifact["stored_output"][field] = value
    with pytest.raises(RQ6Error):
        validate_artifact("reviewer_card", artifact)


def test_nested_source_identity_is_not_a_reviewer_output_field() -> None:
    artifact = synthetic_artifact("reviewer_card")
    artifact["stored_output"]["provider"] = "synthetic-source"
    with pytest.raises(RQ6Error, match="ARTIFACT_FIELDS_MISMATCH"):
        validate_artifact("reviewer_card", artifact)


@pytest.mark.parametrize(
    "field,value",
    [
        ("primary_disposition", "ALIGNED"),
        ("rationale_propositions", ["TARGET_AMBIGUITY"]),
        ("reviewer_reason", "Prefilled judgment"),
    ],
)
def test_empty_form_never_prefills_human_judgment(field: str, value: Any) -> None:
    artifact = synthetic_artifact("empty_human_form")
    artifact[field] = value
    with pytest.raises(RQ6Error, match="HUMAN_FORM_NOT_EMPTY"):
        validate_artifact("empty_human_form", artifact)


@pytest.mark.parametrize(
    "field,value",
    [
        ("operationally_mapping_blind_at_coding", False),
        ("mechanical_stability_seen", True),
        ("immutability", False),
        ("rationale_propositions", ["TARGET_AMBIGUITY"] * 2),
        ("primary_disposition", "DEFER_FOR_HUMAN_REVIEW"),
    ],
)
def test_human_receipt_cannot_weaken_independent_coding(field: str, value: Any) -> None:
    artifact = synthetic_artifact("human_receipt")
    artifact[field] = value
    with pytest.raises(RQ6Error):
        validate_artifact("human_receipt", artifact)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mapping_commitment_sha256", None),
        ("mapping_commitment_sha256", "A" * 64),
        ("reviewer_unit_id", "plain-unit-id"),
        ("observation_sequence_within_bundle", True),
        ("observation_sequence_within_bundle", 4),
    ],
)
def test_required_crypto_and_sequence_fields_are_strict(field: str, value: Any) -> None:
    artifact = synthetic_artifact("reviewer_card")
    artifact[field] = value
    with pytest.raises(RQ6Error):
        validate_artifact("reviewer_card", artifact)


@pytest.mark.parametrize(
    "timestamp", ["2026-10-06", "2026-10-06T18:00:00-04:00", "2026-02-31T18:00:00Z", 123]
)
def test_timestamps_require_valid_utc(timestamp: Any) -> None:
    artifact = synthetic_artifact("human_receipt")
    artifact["adjudication_timestamp"] = timestamp
    with pytest.raises(RQ6Error):
        validate_artifact("human_receipt", artifact)


def test_ledger_genesis_and_positive_integer_are_not_optional() -> None:
    artifact = synthetic_artifact("bundle_event_ledger")
    artifact["event_sequence"] = 2
    with pytest.raises(RQ6Error, match="LEDGER_GENESIS"):
        validate_artifact("bundle_event_ledger", artifact)
    artifact["previous_event_sha256"] = H
    validate_artifact("bundle_event_ledger", artifact)
    artifact["event_sequence"] = True
    with pytest.raises(RQ6Error, match="POSITIVE_INTEGER_REQUIRED"):
        validate_artifact("bundle_event_ledger", artifact)


def test_access_enforcement_requires_real_evidence_and_attestation_does_not_invent_it() -> None:
    artifact = synthetic_artifact("reviewer_access_provenance")
    artifact["enforcement_evidence_hashes"] = [H]
    with pytest.raises(RQ6Error, match="INVENTED_ENFORCEMENT"):
        validate_artifact("reviewer_access_provenance", artifact)
    artifact["access_mode"] = "ENFORCED_REVIEWER_RELEASE_ONLY"
    artifact["reviewer_attestation"] = None
    validate_artifact("reviewer_access_provenance", artifact)
    artifact["enforcement_evidence_hashes"] = []
    with pytest.raises(RQ6Error, match="EMPTY_ARRAY"):
        validate_artifact("reviewer_access_provenance", artifact)


@pytest.mark.parametrize(
    "variation,material,boundary",
    [
        ("NONE", False, False),
        ("MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE", True, False),
        ("MATERIAL_BOUNDARY_CHANGE", True, True),
        ("UNRESOLVED", None, None),
    ],
)
def test_assessment_locked_coherence_and_no_reopening(
    variation: str,
    material: bool | None,
    boundary: bool | None,
) -> None:
    artifact = synthetic_artifact("rationale_variation_assessment_receipt")
    artifact.update(
        {
            "rationale_variation": variation,
            "material_rationale_variation_confirmed": material,
            "material_boundary_changed": boundary,
            "human_variation_note": "Justified synthetic material boundary finding.",
        }
    )
    validate_artifact("rationale_variation_assessment_receipt", artifact)
    artifact["independent_unit_coding_reopened"] = True
    with pytest.raises(RQ6Error, match="BOOLEAN_COHERENCE"):
        validate_artifact("rationale_variation_assessment_receipt", artifact)


def test_same_propositions_material_boundary_requires_justified_note() -> None:
    artifact = synthetic_artifact("rationale_variation_assessment_receipt")
    artifact.update(
        {
            "rationale_variation": "MATERIAL_BOUNDARY_CHANGE",
            "material_rationale_variation_confirmed": True,
            "material_boundary_changed": True,
        }
    )
    with pytest.raises(RQ6Error, match="TEXT_REQUIRED"):
        validate_artifact("rationale_variation_assessment_receipt", artifact)


def test_proposition_difference_is_candidate_not_automatic_confirmation() -> None:
    artifact = synthetic_artifact("rationale_variation_assessment_receipt")
    artifact["frozen_proposition_sets"][1] = ["AUTHORITY_BOUNDARY"]
    with pytest.raises(RQ6Error, match="PROPOSITION_DIFFERENCE_COHERENCE"):
        validate_artifact("rationale_variation_assessment_receipt", artifact)
    artifact["proposition_set_difference_candidate"] = True
    validate_artifact("rationale_variation_assessment_receipt", artifact)
    assert artifact["material_rationale_variation_confirmed"] is False


def test_assessment_external_workflow_effects_are_not_receipt_fields() -> None:
    artifact = synthetic_artifact("rationale_variation_assessment_receipt")
    artifact["review_status"] = "RQ6_REVIEW_DEFERRED_PENDING_HUMAN_RESOLUTION"
    with pytest.raises(RQ6Error, match="ARTIFACT_FIELDS_MISMATCH"):
        validate_artifact("rationale_variation_assessment_receipt", artifact)


def test_insufficient_closure_retains_failure_without_fabricated_units_or_unblind() -> None:
    artifact = insufficient_artifact()
    validate_artifact("bundle_closure", artifact)
    assert artifact["validation_results"]["RQ6-V05"] == "FAIL"
    assert artifact["human_receipt_hashes"] == []
    assert artifact["alias_commitment_sha256"] is None
    artifact["unblind_receipt_sha256"] = H
    with pytest.raises(RQ6Error, match="INSUFFICIENT_PREMATURE_UNBLIND"):
        validate_artifact("bundle_closure", artifact)


@pytest.mark.parametrize(
    "field,value",
    [
        ("missing_evidence", []),
        ("stability_not_established_reason", ""),
        ("frozen_manifest_position", 2),
    ],
)
def test_insufficient_closure_must_explain_and_bind_failure(field: str, value: Any) -> None:
    artifact = insufficient_artifact()
    artifact[field] = value
    with pytest.raises(RQ6Error):
        validate_artifact("bundle_closure", artifact)


def test_failure_id_never_appears_in_reviewer_card() -> None:
    artifact = synthetic_artifact("reviewer_card")
    artifact["bundle_review_id"] = f"RQ6_CUSTODY_FAILURE:{H}:1"
    with pytest.raises(RQ6Error, match="FAILURE_ID_VISIBILITY"):
        validate_artifact("reviewer_card", artifact)


def test_terminal_closure_rejects_seventh_enum_defer_and_missing_unblind() -> None:
    artifact = synthetic_artifact("bundle_closure")
    artifact["stability_disposition"] = "DEFER_FOR_HUMAN_REVIEW"
    with pytest.raises(RQ6Error, match="STABILITY_DISPOSITION"):
        validate_artifact("bundle_closure", artifact)
    artifact = synthetic_artifact("bundle_closure")
    artifact["unblind_receipt_sha256"] = None
    with pytest.raises(RQ6Error, match="REQUIRED_HASH_MISSING"):
        validate_artifact("bundle_closure", artifact)


def test_stable_with_rationale_variation_cannot_hide_changed_boundary() -> None:
    artifact = synthetic_artifact("bundle_closure")
    artifact["stability_disposition"] = "STABLE_WITH_RATIONALE_VARIATION"
    artifact["frozen_rationale_variation_record"] = {
        "material_rationale_variation_confirmed": True,
        "material_boundary_changed": True,
    }
    with pytest.raises(RQ6Error, match="STABLE_WITH_RATIONALE_GUARD"):
        validate_artifact("bundle_closure", artifact)


def test_stable_closure_cannot_hide_variable_classification() -> None:
    artifact = synthetic_artifact("bundle_closure")
    artifact["stored_classifications"][1] = "AMBIGUOUS"
    with pytest.raises(RQ6Error, match="STABILITY_AXIS_COHERENCE"):
        validate_artifact("bundle_closure", artifact)


def test_historical_primary_coding_is_not_backfilled_with_new_fields() -> None:
    artifact = synthetic_artifact("rationale_variation_assessment_artifact")
    original = deepcopy(artifact["frozen_primary_semantic_coding"])
    validate_artifact("rationale_variation_assessment_artifact", artifact)
    assert artifact["frozen_primary_semantic_coding"] == original
    assert "operationally_mapping_blind_at_coding" not in original
