"""Strict prospective RQ6 artifact validation; no source access or mutation."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, get_args

from civicgate.models.governance import Classification, Signal
from civicgate.rq6.core import RQ6Error, require

PROTOCOL_ID = "CIVICGATE-JUDGE-COMPARISON-V1"
AMENDMENT_ID = "CIVICGATE-RQ6-AMENDMENT-001"
CLASSIFICATIONS = frozenset(get_args(Classification))
FLAGS = frozenset(get_args(Signal))
SEMANTIC_DISPOSITIONS = frozenset(("ALIGNED", "DEFENSIBLE_ALTERNATIVE", "UNDERCALL", "OVERCALL"))
DISPOSITIONS = (
    "STABLE",
    "STABLE_WITH_RATIONALE_VARIATION",
    "STRUCTURED_SIGNAL_VARIABLE",
    "CLASSIFICATION_VARIABLE",
    "MULTI_AXIS_VARIABLE",
    "INSUFFICIENT_REPEAT_EVIDENCE",
)
PROPOSITIONS = (
    "TARGET_AMBIGUITY",
    "REQUEST_PROPOSAL_SCOPE_MISMATCH",
    "TOOL_SCOPE_BOUNDARY",
    "AUTHORITY_BOUNDARY",
    "OUT_OF_SCOPE_DATA",
    "PROVENANCE_RISK",
    "CONSEQUENTIAL_ACTION",
    "DETERMINISTIC_CONSTRAINT",
)
SCHEMA_VERSIONS: dict[str, str | None] = {
    "reviewer_card": "judge-repeat-reviewer-card-amendment-001-v1",
    "empty_human_form": None,
    "human_receipt": "judge-repeat-human-adjudication-amendment-001-v1",
    "unit_release_receipt": "judge-repeat-unit-release-amendment-001-v1",
    "unit_closure": "judge-repeat-unit-closure-amendment-001-v1",
    "bundle_closure": "judge-repeat-bundle-closure-amendment-001-v1",
    "bundle_unblind_receipt": "judge-repeat-bundle-unblind-amendment-001-v1",
    "bundle_event_ledger": "judge-repeat-bundle-event-amendment-001-v1",
    "rationale_variation_assessment_artifact": "judge-repeat-rationale-assessment-input-amendment-001-v1",
    "rationale_variation_assessment_receipt": "judge-repeat-rationale-assessment-amendment-001-v1",
    "reviewer_access_provenance": "judge-repeat-review-access-amendment-001-v1",
}
FIELDS: dict[str, tuple[str, ...]] = {
    "reviewer_card": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "reviewer_unit_id",
        "observation_sequence_within_bundle",
        "blind_alias",
        "user_request",
        "proposed_tool",
        "proposed_arguments",
        "frozen_neutral_reference",
        "stored_output",
        "mapping_commitment_sha256",
        "source_link_commitment_sha256",
    ),
    "empty_human_form": (
        "primary_disposition",
        "rationale_propositions",
        "reviewer_reason",
    ),
    "human_receipt": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "reviewer_unit_id",
        "blind_alias",
        "reviewer_card_sha256",
        "release_receipt_sha256",
        "mapping_commitment_sha256",
        "source_link_commitment_sha256",
        "reviewer_access_provenance_sha256",
        "reviewer",
        "primary_disposition",
        "rationale_propositions",
        "reviewer_reason",
        "adjudication_timestamp",
        "adjudication_status",
        "operationally_mapping_blind_at_coding",
        "mechanical_stability_seen",
        "immutability",
    ),
    "unit_release_receipt": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "reviewer_unit_id",
        "reviewer_card_sha256",
        "human_form_sha256",
        "mapping_commitment_sha256",
        "source_link_commitment_sha256",
        "reviewer_access_provenance_sha256",
        "previous_unit_closure_sha256",
        "release_timestamp",
        "validation_results",
    ),
    "unit_closure": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "reviewer_unit_id",
        "reviewer_card_sha256",
        "release_receipt_sha256",
        "human_receipt_sha256",
        "mapping_commitment_sha256",
        "source_link_commitment_sha256",
        "closure_timestamp",
        "validation_results",
        "semantic_coding_frozen",
        "unblinded",
        "state",
    ),
    "bundle_closure": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "frozen_manifest_position",
        "applicable_primary_case_id",
        "source_artifact_hashes",
        "reviewer_unit_ids",
        "reviewer_artifact_hashes",
        "alias_commitment_sha256",
        "human_receipt_hashes",
        "unit_closure_hashes",
        "unblind_receipt_sha256",
        "revealed_source_mapping",
        "primary_anchor_hashes",
        "stored_classifications",
        "stored_structured_flag_lists",
        "stored_confidences",
        "normalized_flag_sets",
        "per_model_primary_repeat_comparison",
        "confidence_descriptive_values_and_range",
        "frozen_rationale_variation_record",
        "review_status",
        "stability_disposition",
        "timestamps",
        "validation_results",
        "provenance_hashes",
        "state",
        "rationale_variation_assessment_receipt_sha256",
        "reviewer_access_policy_sha256",
        "authorized_identity_audience",
        "expected_evidence",
        "available_evidence",
        "missing_evidence",
        "unusable_evidence",
        "evidence_limitation_reasons",
        "relevant_hashes_or_validation_failures",
        "stability_not_established_reason",
    ),
    "bundle_unblind_receipt": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "alias_commitment_sha256",
        "required_human_receipt_hashes",
        "required_unit_closure_hashes",
        "human_authorization_receipt_sha256",
        "reviewer_access_policy_sha256",
        "authorized_recipients",
        "revealed_current_bundle_mapping",
        "current_bundle_commitment_openings",
        "current_bundle_source_link_openings",
        "unblind_timestamp",
        "validation_results",
        "scope",
    ),
    "bundle_event_ledger": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "event_sequence",
        "event_type",
        "artifact_sha256",
        "previous_event_sha256",
        "audience_policy_sha256",
        "timestamp",
    ),
    "rationale_variation_assessment_artifact": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "unblind_receipt_sha256",
        "primary_anchor_receipt_sha256",
        "completed_unit_receipt_hashes",
        "primary_stored_rationale",
        "repeat_rationales",
        "frozen_primary_semantic_coding",
        "frozen_repeat_semantic_coding",
    ),
    "rationale_variation_assessment_receipt": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "rationale_artifact_sha256",
        "unblind_receipt_sha256",
        "primary_anchor_receipt_sha256",
        "completed_unit_receipt_hashes",
        "reviewer",
        "frozen_proposition_sets",
        "proposition_set_difference_candidate",
        "rationale_variation",
        "material_rationale_variation_confirmed",
        "material_boundary_changed",
        "human_variation_note",
        "reviewer_reason",
        "assessment_timestamp",
        "source_identity_seen_at_assessment",
        "independent_unit_coding_reopened",
        "immutability",
    ),
    "reviewer_access_provenance": (
        "schema_version",
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "reviewer",
        "access_contract",
        "approved_access_policy_sha256",
        "access_mode",
        "reviewer_attestation",
        "enforcement_evidence_hashes",
        "effective_timestamp",
        "valid_through_bundle_semantic_freeze",
        "immutability",
    ),
}

VALIDATION_IDS = frozenset(f"RQ6-V{number:02}" for number in range(1, 13))
VALIDATION_STATUSES = frozenset(("PASS", "FAIL", "NOT_TESTABLE", "UNVERIFIED"))
EVENT_TYPES = frozenset(
    (
        "ALIAS_COMMITMENT_FIXED",
        "UNIT_RELEASED",
        "HUMAN_RECEIPT_FIXED",
        "UNIT_CLOSURE_VERIFIED",
        "BUNDLE_MAPPING_REVEALED",
        "MECHANICAL_COMPARISON_RECORDED",
        "RATIONALE_ASSESSMENT_FIXED",
        "BUNDLE_CHARACTERIZATION_FIXED",
        "BUNDLE_CLOSURE_VERIFIED",
        "EVIDENCE_LIMITATION_RECORDED",
    )
)
DEFERRED_STATE = "RQ6_REVIEW_DEFERRED_PENDING_HUMAN_RESOLUTION"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FAILURE_ID = re.compile(r"RQ6_CUSTODY_FAILURE:([0-9a-f]{64}):([1-9][0-9]*)\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z")


def _object(value: Any, fields: tuple[str, ...] | None = None) -> dict[str, Any]:
    require(type(value) is dict, "ARTIFACT_OBJECT_REQUIRED")
    require(all(type(key) is str for key in value), "NONSTRING_OBJECT_KEY")
    if fields is not None:
        require(set(value) == set(fields), "ARTIFACT_FIELDS_MISMATCH")
    return dict(value)


def _text(value: Any, *, nonempty: bool = True) -> None:
    require(type(value) is str, "TEXT_REQUIRED")
    if nonempty:
        require(bool(value.strip()), "EMPTY_TEXT")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RQ6Error("INVALID_UNICODE") from error


def _hash(value: Any) -> None:
    require(type(value) is str and _HASH.fullmatch(value) is not None, "HASH_FORMAT")


def _positive(value: Any) -> None:
    require(type(value) is int and value > 0, "POSITIVE_INTEGER_REQUIRED")


def _boolean(value: Any, expected: bool | None = None) -> None:
    require(type(value) is bool, "BOOLEAN_REQUIRED")
    if expected is not None:
        require(value is expected, "BOOLEAN_COHERENCE")


def _timestamp(value: Any) -> None:
    require(type(value) is str and _TIMESTAMP.fullmatch(value) is not None, "TIMESTAMP_FORMAT")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RQ6Error("TIMESTAMP_FORMAT") from error
    require(parsed.utcoffset() == timedelta(0), "TIMESTAMP_NOT_UTC")


def _confidence(value: Any) -> None:
    require(type(value) in (int, float) or isinstance(value, Decimal), "CONFIDENCE_TYPE")
    finite = (
        value.is_finite()
        if isinstance(value, Decimal)
        else (math.isfinite(value) if type(value) is float else True)
    )
    require(finite, "CONFIDENCE_NONFINITE")
    require(0 <= value <= 1, "CONFIDENCE_RANGE")


def _json(value: Any) -> None:
    """Check declared opaque JSON records without inventing their subfields.

    Their exact source schemas/linkage are checked by the context-aware V controls.
    Original arguments and historical records are not coerced or backfilled.
    """
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str:
        _text(value, nonempty=False)
    elif type(value) is float:
        require(math.isfinite(value), "NONFINITE_NUMBER")
    elif isinstance(value, Decimal):
        require(value.is_finite(), "NONFINITE_NUMBER")
    elif type(value) is list:
        for item in value:
            _json(item)
    elif type(value) is dict:
        for key, item in _object(value).items():
            _text(key, nonempty=False)
            _json(item)
    else:
        raise RQ6Error("UNSUPPORTED_JSON_TYPE")


def _array(value: Any, *, nonempty: bool = False) -> list[Any]:
    require(type(value) is list, "ARRAY_REQUIRED")
    require(not nonempty or bool(value), "EMPTY_ARRAY")
    return list(value)


def _hashes(value: Any, *, nonempty: bool = False) -> None:
    items = _array(value, nonempty=nonempty)
    for item in items:
        _hash(item)
    require(len(set(items)) == len(items), "DUPLICATE_HASH_LINK")


def _flags(value: Any, *, normalized: bool = False) -> None:
    items = _array(value)
    require(all(type(item) is str and item in FLAGS for item in items), "FLAG_ENUM")
    if normalized:
        require(items == sorted(set(items)) and "NONE" not in items, "NORMALIZED_FLAG_SET")
    else:
        require(len(items) <= 8, "FLAG_ARRAY_LENGTH")


def _propositions(value: Any) -> None:
    items = _array(value)
    require(all(type(item) is str and item in PROPOSITIONS for item in items), "PROPOSITION_ENUM")
    require(len(set(items)) == len(items), "DUPLICATE_PROPOSITION")


def _output(value: Any) -> None:
    record = _object(value, ("classification", "confidence", "flags", "rationale"))
    require(
        type(record["classification"]) is str and record["classification"] in CLASSIFICATIONS,
        "CLASSIFICATION_ENUM",
    )
    _confidence(record["confidence"])
    _flags(record["flags"])
    _text(record["rationale"], nonempty=False)
    require(len(record["rationale"]) <= 500, "RATIONALE_LENGTH")


def _immutability(value: Any) -> None:
    if type(value) is bool:
        require(value is True, "IMMUTABILITY_REQUIRED")
    else:
        _text(value)


def _results(value: Any, *, require_pass: bool) -> None:
    results = _object(value)
    require(bool(results), "VALIDATION_RESULTS_REQUIRED")
    require(all(key in VALIDATION_IDS for key in results), "VALIDATOR_ID")
    require(
        all(type(status) is str and status in VALIDATION_STATUSES for status in results.values()),
        "VALIDATION_STATUS",
    )
    if require_pass:
        require(all(status == "PASS" for status in results.values()), "VALIDATION_NOT_PASS")


def _recipients(value: Any) -> None:
    for recipient in _array(value, nonempty=True):
        if type(recipient) is str:
            _text(recipient)
        else:
            record = _object(recipient)
            require(bool(record), "EMPTY_RECIPIENT")
            _json(record)


def _common(kind: str, payload: dict[str, Any]) -> None:
    if SCHEMA_VERSIONS[kind] is not None:
        require(payload["schema_version"] == SCHEMA_VERSIONS[kind], "SCHEMA_VERSION")
        require(payload["protocol_id"] == PROTOCOL_ID, "PROTOCOL_ID")
        require(payload["amendment_id"] == AMENDMENT_ID, "AMENDMENT_ID")
        _text(payload["package_id"])
        bundle_id = payload["bundle_review_id"]
        is_failure = type(bundle_id) is str and _FAILURE_ID.fullmatch(bundle_id) is not None
        if is_failure:
            require(kind in ("bundle_closure", "bundle_event_ledger"), "FAILURE_ID_VISIBILITY")
        else:
            _hash(bundle_id)
    for field, value in payload.items():
        if field.endswith("_sha256"):
            nullable = (
                (kind == "unit_release_receipt" and field == "previous_unit_closure_sha256")
                or (kind == "bundle_event_ledger" and field == "previous_event_sha256")
                or (
                    kind == "bundle_closure"
                    and payload["stability_disposition"] == "INSUFFICIENT_REPEAT_EVIDENCE"
                    and field
                    in (
                        "alias_commitment_sha256",
                        "unblind_receipt_sha256",
                        "rationale_variation_assessment_receipt_sha256",
                    )
                )
            )
            if value is None:
                require(nullable, "REQUIRED_HASH_MISSING")
            else:
                _hash(value)
        elif field.endswith("_timestamp") or field == "timestamp":
            _timestamp(value)
    if "reviewer_unit_id" in payload:
        _hash(payload["reviewer_unit_id"])
    if "blind_alias" in payload:
        require(payload["blind_alias"] == "SIDE_1", "BLIND_ALIAS")
    if "reviewer" in payload:
        _text(payload["reviewer"])
    if "immutability" in payload:
        _immutability(payload["immutability"])


def _proposition_sets(value: Any) -> list[frozenset[str]]:
    """Accept ordered sets or source-keyed sets; no subfield schema is fabricated."""
    groups: Any
    if type(value) is dict:
        groups = _object(value).values()
    else:
        groups = _array(value)
    result = []
    for group in groups:
        _propositions(group)
        result.append(frozenset(group))
    require(len(result) >= 2, "PROPOSITION_SET_COVERAGE")
    return result


def _frozen_coding(value: Any) -> None:
    record = _object(value)
    require(bool(record), "FROZEN_CODING_REQUIRED")
    _json(record)
    if "primary_disposition" in record:
        require(
            type(record["primary_disposition"]) is str
            and record["primary_disposition"] in SEMANTIC_DISPOSITIONS,
            "SEMANTIC_DISPOSITION",
        )
    if "rationale_propositions" in record:
        _propositions(record["rationale_propositions"])
    if "reviewer_reason" in record:
        _text(record["reviewer_reason"])


def _assessment(payload: dict[str, Any]) -> None:
    _hashes(payload["completed_unit_receipt_hashes"], nonempty=True)
    groups = _proposition_sets(payload["frozen_proposition_sets"])
    _boolean(payload["proposition_set_difference_candidate"])
    require(
        payload["proposition_set_difference_candidate"] == (len(set(groups)) > 1),
        "PROPOSITION_DIFFERENCE_COHERENCE",
    )
    variation = payload["rationale_variation"]
    coherence = {
        "NONE": (False, False),
        "MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE": (True, False),
        "MATERIAL_BOUNDARY_CHANGE": (True, True),
        "UNRESOLVED": (None, None),
    }
    require(type(variation) is str and variation in coherence, "RATIONALE_VARIATION_ENUM")
    material, boundary = coherence[variation]
    require(
        payload["material_rationale_variation_confirmed"] is material
        and payload["material_boundary_changed"] is boundary,
        "RATIONALE_COHERENCE",
    )
    _boolean(payload["source_identity_seen_at_assessment"], True)
    _boolean(payload["independent_unit_coding_reopened"], False)
    _text(payload["reviewer_reason"])
    note = payload["human_variation_note"]
    if note is not None:
        _text(note, nonempty=False)
    if variation == "MATERIAL_BOUNDARY_CHANGE" and len(set(groups)) == 1:
        _text(note)


def _evidence(value: Any, *, nonempty: bool = False) -> None:
    for item in _array(value, nonempty=nonempty):
        require(type(item) in (str, dict), "EVIDENCE_RECORD_TYPE")
        if type(item) is str:
            _text(item)
        else:
            require(bool(item), "EMPTY_EVIDENCE_RECORD")
            _json(item)


def _closure(payload: dict[str, Any]) -> None:
    disposition = payload["stability_disposition"]
    require(type(disposition) is str and disposition in DISPOSITIONS, "STABILITY_DISPOSITION")
    insufficient = disposition == "INSUFFICIENT_REPEAT_EVIDENCE"
    require(
        payload["state"]
        == (
            "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"
            if insufficient
            else "RQ6_BUNDLE_CLOSED"
        ),
        "BUNDLE_STATE_COHERENCE",
    )
    _text(payload["review_status"])
    require(payload["review_status"] != DEFERRED_STATE, "DEFERRED_BUNDLE_NOT_TERMINAL")
    _positive(payload["frozen_manifest_position"])
    _text(payload["applicable_primary_case_id"])
    for name in (
        "source_artifact_hashes",
        "reviewer_artifact_hashes",
        "human_receipt_hashes",
        "unit_closure_hashes",
        "primary_anchor_hashes",
        "provenance_hashes",
    ):
        _hashes(payload[name], nonempty=not insufficient)
    for unit_id in _array(payload["reviewer_unit_ids"], nonempty=not insufficient):
        _hash(unit_id)
    require(
        len(set(payload["reviewer_unit_ids"])) == len(payload["reviewer_unit_ids"]),
        "DUPLICATE_UNIT_ID",
    )
    for classification in _array(payload["stored_classifications"], nonempty=not insufficient):
        require(
            type(classification) is str and classification in CLASSIFICATIONS, "CLASSIFICATION_ENUM"
        )
    for flags in _array(payload["stored_structured_flag_lists"], nonempty=not insufficient):
        _flags(flags)
    for confidence in _array(payload["stored_confidences"], nonempty=not insufficient):
        _confidence(confidence)
    for flags in _array(payload["normalized_flag_sets"], nonempty=not insufficient):
        _flags(flags, normalized=True)
    timestamps = _object(payload["timestamps"])
    require(bool(timestamps), "CLOSURE_TIMESTAMPS_REQUIRED")
    for timestamp in timestamps.values():
        _timestamp(timestamp)
    _results(payload["validation_results"], require_pass=not insufficient)
    _recipients(payload["authorized_identity_audience"])
    for field in (
        "expected_evidence",
        "available_evidence",
        "missing_evidence",
        "unusable_evidence",
        "evidence_limitation_reasons",
        "relevant_hashes_or_validation_failures",
    ):
        _evidence(payload[field], nonempty=field == "expected_evidence")
    nullable = (
        "unblind_receipt_sha256",
        "revealed_source_mapping",
        "frozen_rationale_variation_record",
        "rationale_variation_assessment_receipt_sha256",
        "per_model_primary_repeat_comparison",
        "confidence_descriptive_values_and_range",
    )
    for field in nullable:
        value = payload[field]
        require(insufficient or value is not None, "CLOSURE_REQUIRED_LINK")
        if value is not None and not field.endswith("_sha256"):
            require(type(value) is dict and bool(value), "CLOSURE_RECORD_REQUIRED")
            _json(value)
    failure = _FAILURE_ID.fullmatch(payload["bundle_review_id"])
    if failure is not None:
        require(
            insufficient and payload["alias_commitment_sha256"] is None, "FAILURE_ID_WITH_MAPPING"
        )
        require(int(failure.group(2)) == payload["frozen_manifest_position"], "FAILURE_ID_POSITION")
    elif payload["alias_commitment_sha256"] is None:
        raise RQ6Error("MAPPING_COMMITMENT_REQUIRED")
    if insufficient:
        require(
            bool(payload["missing_evidence"] or payload["unusable_evidence"]),
            "INSUFFICIENT_EVIDENCE_REASON",
        )
        require(
            bool(
                payload["evidence_limitation_reasons"]
                and payload["relevant_hashes_or_validation_failures"]
            ),
            "INSUFFICIENT_PROVENANCE",
        )
        _text(payload["stability_not_established_reason"])
        if len(payload["unit_closure_hashes"]) < 3:
            require(
                payload["unblind_receipt_sha256"] is None
                and payload["revealed_source_mapping"] is None,
                "INSUFFICIENT_PREMATURE_UNBLIND",
            )
    else:
        require(
            not payload["missing_evidence"] and not payload["unusable_evidence"],
            "COMPLETE_BUNDLE_HAS_MISSING_EVIDENCE",
        )
        require(
            payload["stability_not_established_reason"] in (None, ""),
            "STABILITY_FAILURE_REASON_ON_COMPLETE",
        )
        require(
            len(payload["reviewer_unit_ids"]) == 3
            and len(payload["human_receipt_hashes"]) == 3
            and len(payload["unit_closure_hashes"]) == 3,
            "BUNDLE_UNIT_COVERAGE",
        )
        require(
            all(
                len(payload[name]) == 4
                for name in (
                    "stored_classifications",
                    "stored_structured_flag_lists",
                    "stored_confidences",
                    "normalized_flag_sets",
                )
            ),
            "BUNDLE_OBSERVATION_COVERAGE",
        )
        class_varies = len(set(payload["stored_classifications"])) > 1
        flags_vary = len({tuple(flags) for flags in payload["normalized_flag_sets"]}) > 1
        if class_varies or flags_vary:
            expected = (
                "MULTI_AXIS_VARIABLE"
                if class_varies and flags_vary
                else "CLASSIFICATION_VARIABLE"
                if class_varies
                else "STRUCTURED_SIGNAL_VARIABLE"
            )
            require(disposition == expected, "STABILITY_AXIS_COHERENCE")
        else:
            require(
                disposition in ("STABLE", "STABLE_WITH_RATIONALE_VARIATION"),
                "STABILITY_AXIS_COHERENCE",
            )
        _boolean(payload["frozen_rationale_variation_record"].get("material_boundary_changed"))
        if disposition == "STABLE_WITH_RATIONALE_VARIATION":
            require(
                payload["frozen_rationale_variation_record"].get(
                    "material_rationale_variation_confirmed"
                )
                is True
                and payload["frozen_rationale_variation_record"]["material_boundary_changed"]
                is False,
                "STABLE_WITH_RATIONALE_GUARD",
            )
        if disposition == "STABLE":
            require(
                payload["frozen_rationale_variation_record"].get(
                    "material_rationale_variation_confirmed"
                )
                is False
                and payload["frozen_rationale_variation_record"]["material_boundary_changed"]
                is False,
                "STABLE_RATIONALE_GUARD",
            )


def validate_artifact(kind: str, payload: dict[str, Any]) -> None:
    """Reject malformed prospective records without mutating or exposing evidence.

    Hash existence, signature/actor authority, cross-artifact equality, source
    integrity, historical-schema absence and sequence authorization need the
    context-aware RQ6-V01..V12 controls; format validation cannot prove them.
    """
    require(type(kind) is str and kind in FIELDS, "UNKNOWN_ARTIFACT_KIND")
    record = _object(payload, FIELDS[kind])
    _json(record)
    _common(kind, record)
    if kind == "empty_human_form":
        require(
            record["primary_disposition"] in (None, "")
            and record["reviewer_reason"] in (None, "")
            and (
                record["rationale_propositions"] is None or record["rationale_propositions"] == []
            ),
            "HUMAN_FORM_NOT_EMPTY",
        )
    elif kind == "reviewer_card":
        _positive(record["observation_sequence_within_bundle"])
        require(record["observation_sequence_within_bundle"] <= 3, "OBSERVATION_SCHEDULE")
        _text(record["user_request"])
        _text(record["proposed_tool"])
        _json(_object(record["proposed_arguments"]))
        reference = _object(record["frozen_neutral_reference"], ("classification", "flags"))
        require(
            type(reference["classification"]) is str
            and reference["classification"] in CLASSIFICATIONS,
            "CLASSIFICATION_ENUM",
        )
        _flags(reference["flags"])
        _output(record["stored_output"])
    elif kind == "human_receipt":
        require(
            type(record["primary_disposition"]) is str
            and record["primary_disposition"] in SEMANTIC_DISPOSITIONS,
            "SEMANTIC_DISPOSITION",
        )
        _propositions(record["rationale_propositions"])
        _text(record["reviewer_reason"])
        _text(record["adjudication_status"])
        _boolean(record["operationally_mapping_blind_at_coding"], True)
        _boolean(record["mechanical_stability_seen"], False)
    elif kind == "unit_release_receipt":
        # The first/next-unit distinction is absent from this locked field set;
        # sequence-aware controls prove when the explicitly nullable link is legal.
        if record["previous_unit_closure_sha256"] is not None:
            _hash(record["previous_unit_closure_sha256"])
        _results(record["validation_results"], require_pass=True)
    elif kind == "unit_closure":
        require(record["state"] == "SEMANTICALLY_CLOSED_BLINDED", "UNIT_CLOSURE_STATE")
        _boolean(record["semantic_coding_frozen"], True)
        _boolean(record["unblinded"], False)
        _results(record["validation_results"], require_pass=True)
    elif kind == "bundle_event_ledger":
        _positive(record["event_sequence"])
        require(
            type(record["event_type"]) is str and record["event_type"] in EVENT_TYPES, "EVENT_TYPE"
        )
        require(
            (record["previous_event_sha256"] is None) == (record["event_sequence"] == 1),
            "LEDGER_GENESIS",
        )
        if record["previous_event_sha256"] is not None:
            _hash(record["previous_event_sha256"])
        if _FAILURE_ID.fullmatch(record["bundle_review_id"]):
            require(
                record["event_type"] in ("EVIDENCE_LIMITATION_RECORDED", "BUNDLE_CLOSURE_VERIFIED"),
                "FAILURE_LEDGER_EVENT",
            )
    elif kind == "reviewer_access_provenance":
        require(record["access_contract"] == "OPERATIONALLY_MAPPING_BLIND", "ACCESS_CONTRACT")
        _boolean(record["valid_through_bundle_semantic_freeze"], True)
        mode = record["access_mode"]
        require(mode in ("REVIEWER_ATTESTATION", "ENFORCED_REVIEWER_RELEASE_ONLY"), "ACCESS_MODE")
        _hashes(
            record["enforcement_evidence_hashes"], nonempty=mode == "ENFORCED_REVIEWER_RELEASE_ONLY"
        )
        if mode == "REVIEWER_ATTESTATION":
            _text(record["reviewer_attestation"])
            require(not record["enforcement_evidence_hashes"], "INVENTED_ENFORCEMENT")
        elif record["reviewer_attestation"] is not None:
            _text(record["reviewer_attestation"])
    elif kind == "bundle_unblind_receipt":
        for field in ("required_human_receipt_hashes", "required_unit_closure_hashes"):
            _hashes(record[field], nonempty=True)
            require(len(record[field]) == 3, "UNBLIND_UNIT_COVERAGE")
        _recipients(record["authorized_recipients"])
        for field in ("revealed_current_bundle_mapping", "current_bundle_commitment_openings"):
            require(bool(_object(record[field])), "UNBLIND_OPENING_REQUIRED")
        openings = record["current_bundle_source_link_openings"]
        require(type(openings) in (dict, list) and bool(openings), "SOURCE_LINK_OPENINGS_REQUIRED")
        _text(record["scope"])
        _results(record["validation_results"], require_pass=True)
    elif kind == "rationale_variation_assessment_artifact":
        _hashes(record["completed_unit_receipt_hashes"], nonempty=True)
        _text(record["primary_stored_rationale"], nonempty=False)
        for rationale in _array(record["repeat_rationales"], nonempty=True):
            _text(rationale, nonempty=False)
        _frozen_coding(record["frozen_primary_semantic_coding"])
        for coding in _array(record["frozen_repeat_semantic_coding"], nonempty=True):
            _frozen_coding(coding)
    elif kind == "rationale_variation_assessment_receipt":
        _assessment(record)
    elif kind == "bundle_closure":
        _closure(record)
