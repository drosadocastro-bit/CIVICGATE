"""RQ6-V01..V12: fail-closed evidence checks, independent of model inference."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from civicgate.rq6.core import ArtifactSnapshot, exact_json, require, sha256

CONTROL_IDS = tuple(f"RQ6-V{number:02d}" for number in range(1, 13))


class PreMappingFailureValidator:
    """Custody-only V12 branch with no mapping object, seed or opaque reviewer IDs.

    The immutable original limitation record supplies coverage and failed controls;
    closure PASS certifies faithful recording, never converts source FAIL to PASS.
    It cannot grant release or reveal authority. An optional immutable custody
    context retains available source/primary observations without reviewer IDs.
    Its mandatory verifier must recheck the context and every provenance object's
    physical bytes, frozen source selection and applicable own-primary identity.
    """

    def __init__(
        self,
        binding: Mapping[str, str],
        failure_record: ArtifactSnapshot,
        *,
        original_failure_verifier: Callable[[ArtifactSnapshot], None],
        continuity_verifier: Callable[[], None],
        available_evidence_context: ArtifactSnapshot | None = None,
        available_evidence_verifier: Callable[[ArtifactSnapshot], None] | None = None,
    ) -> None:
        require(
            available_evidence_context is None or available_evidence_verifier is not None,
            "RQ6-V12_AVAILABLE_CONTEXT_NOT_VERIFIED",
        )
        self.binding = dict(binding)
        self.failure_record = failure_record
        self.original_failure_verifier = original_failure_verifier
        self.continuity_verifier = continuity_verifier
        self.available_evidence_context = available_evidence_context
        self.available_evidence_verifier = available_evidence_verifier

    def __call__(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.schemas import validate_artifact

        require(self.continuity_verifier() is None, "RQ6-V01_INVALID_VERIFIER_CONTRACT")
        require(
            self.original_failure_verifier(self.failure_record) is None,
            "RQ6-V12_INVALID_FAILURE_VERIFIER_CONTRACT",
        )
        require(artifact.kind == "bundle_closure", "PREMAPPING_REVIEWER_OPERATION_PROHIBITED")
        data = artifact.data()
        validate_artifact("bundle_closure", data)
        require(
            all(data.get(key) == value for key, value in self.binding.items()),
            "RQ6-V12_FAILURE_BINDING",
        )
        match = re.fullmatch(
            r"RQ6_CUSTODY_FAILURE:([0-9a-f]{64}):([1-9][0-9]*)", data["bundle_review_id"]
        )
        require(match is not None, "RQ6-V12_FAILURE_IDENTIFIER")
        assert match is not None
        require(data["frozen_manifest_position"] == int(match.group(2)), "RQ6-V12_FAILURE_POSITION")
        require(
            data["stability_disposition"] == "INSUFFICIENT_REPEAT_EVIDENCE"
            and data["alias_commitment_sha256"] is None,
            "RQ6-V12_PREMAPPING_STATE",
        )
        failure = self.failure_record.data()
        require(failure["frozen_manifest_sha256"] == match.group(1), "RQ6-V12_FAILURE_MANIFEST")
        for field in (
            "expected_evidence",
            "available_evidence",
            "missing_evidence",
            "unusable_evidence",
            "evidence_limitation_reasons",
            "relevant_hashes_or_validation_failures",
            "stability_not_established_reason",
        ):
            require(
                exact_json(data[field]) == exact_json(failure[field]),
                "RQ6-V12_FAILURE_RECONSTRUCTION",
            )
        require(
            data["validation_results"] == {**failure["validation_results"], "RQ6-V12": "PASS"},
            "RQ6-V12_FAILURE_CONTROL_REWRITTEN",
        )
        self._coverage(data)
        for field in (
            "reviewer_unit_ids",
            "reviewer_artifact_hashes",
            "human_receipt_hashes",
            "unit_closure_hashes",
        ):
            require(data[field] == [], "RQ6-V12_FABRICATED_PREMAPPING_EVIDENCE")
        for field in (
            "unblind_receipt_sha256",
            "revealed_source_mapping",
            "frozen_rationale_variation_record",
            "rationale_variation_assessment_receipt_sha256",
            "per_model_primary_repeat_comparison",
        ):
            require(data[field] is None, "RQ6-V12_FABRICATED_OPERATION")
        if self.available_evidence_context is not None:
            self._available_context(data, failure)
            return
        require(data["available_evidence"] == [], "RQ6-V12_UNVERIFIED_AVAILABLE_EVIDENCE")
        for field in (
            "source_artifact_hashes",
            "primary_anchor_hashes",
            "stored_classifications",
            "stored_structured_flag_lists",
            "stored_confidences",
            "normalized_flag_sets",
        ):
            require(data[field] == [], "RQ6-V12_FABRICATED_PREMAPPING_EVIDENCE")
        require(
            data["confidence_descriptive_values_and_range"] is None,
            "RQ6-V12_FABRICATED_OPERATION",
        )
        require(
            data["provenance_hashes"] == [self.failure_record.sha256], "RQ6-V12_FAILURE_PROVENANCE"
        )

    def _available_context(self, data: dict[str, Any], failure: dict[str, Any]) -> None:
        from civicgate.rq6.stability import normalize_flags

        context_record = self.available_evidence_context
        verifier = self.available_evidence_verifier
        require(
            context_record is not None and verifier is not None,
            "RQ6-V12_AVAILABLE_CONTEXT_NOT_VERIFIED",
        )
        assert context_record is not None and verifier is not None
        require(
            context_record.kind == "premapping_available_evidence",
            "RQ6-V12_AVAILABLE_CONTEXT_KIND",
        )
        context = context_record.data()
        require(verifier(context_record) is None, "RQ6-V12_AVAILABLE_CONTEXT_VERIFIER_CONTRACT")
        projected_fields = (
            "frozen_manifest_position",
            "applicable_primary_case_id",
            "reviewer_access_policy_sha256",
            "authorized_identity_audience",
            "available_evidence",
            "source_artifact_hashes",
            "primary_anchor_hashes",
            "stored_classifications",
            "stored_structured_flag_lists",
            "stored_confidences",
            "normalized_flag_sets",
            "confidence_descriptive_values_and_range",
        )
        require(
            set(context)
            == set(self.binding)
            | set(projected_fields)
            | {"frozen_manifest_sha256", "provenance_hashes"},
            "RQ6-V12_AVAILABLE_CONTEXT_FIELDS",
        )
        require(
            all(context.get(key) == value for key, value in self.binding.items())
            and context["frozen_manifest_sha256"] == failure["frozen_manifest_sha256"],
            "RQ6-V12_AVAILABLE_CONTEXT_BINDING",
        )
        require(
            all(
                exact_json(data[field]) == exact_json(context[field]) for field in projected_fields
            ),
            "RQ6-V12_AVAILABLE_CONTEXT_CHANGED",
        )
        observations = len(data["available_evidence"])
        require(
            len({exact_json(item) for item in data["available_evidence"]}) == observations
            and all(
                len(data[field]) == observations
                for field in (
                    "stored_classifications",
                    "stored_structured_flag_lists",
                    "stored_confidences",
                    "normalized_flag_sets",
                )
            ),
            "RQ6-V12_AVAILABLE_OBSERVATION_COVERAGE",
        )
        require(
            data["normalized_flag_sets"]
            == [list(normalize_flags(flags)) for flags in data["stored_structured_flag_lists"]],
            "RQ6-V12_AVAILABLE_FLAG_SETS",
        )
        if data["confidence_descriptive_values_and_range"] is not None:
            values = data["stored_confidences"]
            require(
                exact_json(data["confidence_descriptive_values_and_range"])
                == exact_json(
                    {
                        "interpretation": "DESCRIPTIVE_ONLY",
                        "values": values,
                        "range": [min(values), max(values)] if values else None,
                    }
                ),
                "RQ6-V12_FABRICATED_PARTIAL_CONFIDENCES",
            )
        provenance = context["provenance_hashes"]
        require(
            type(provenance) is list
            and all(
                type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                for digest in provenance
            )
            and len(set(provenance)) == len(provenance)
            and set(data["source_artifact_hashes"] + data["primary_anchor_hashes"])
            <= set(provenance),
            "RQ6-V12_AVAILABLE_PROVENANCE",
        )
        expected_provenance = [self.failure_record.sha256, context_record.sha256, *provenance]
        require(
            data["provenance_hashes"] == list(dict.fromkeys(expected_provenance)),
            "RQ6-V12_FAILURE_PROVENANCE",
        )

    @staticmethod
    def _coverage(data: dict[str, Any]) -> None:
        coverage = {
            key: {exact_json(item) for item in data[key]}
            for key in (
                "expected_evidence",
                "available_evidence",
                "missing_evidence",
                "unusable_evidence",
            )
        }
        require(
            not (
                coverage["available_evidence"]
                & (coverage["missing_evidence"] | coverage["unusable_evidence"])
            )
            and coverage["available_evidence"]
            | coverage["missing_evidence"]
            | coverage["unusable_evidence"]
            == coverage["expected_evidence"],
            "RQ6-V12_INSUFFICIENT_COVERAGE_PARTITION",
        )


@dataclass(frozen=True)
class FrozenSource:
    """Exact selected bytes supplied by authorized custody, never discovered by style."""

    raw_artifact: bytes
    raw_output_slice: bytes
    context_bytes: bytes
    neutral_bytes: bytes
    selector_bytes: bytes
    source_link_opening_bytes: bytes
    output_pointer: tuple[str | int, ...]
    context_pointer: tuple[str | int, ...]
    neutral_pointer: tuple[str | int, ...]


def validate_v01(
    expected_files: Mapping[str, str],
    actual_files: Mapping[str, str],
    closures: Sequence[ArtifactSnapshot],
    closure_verifier: Callable[[ArtifactSnapshot], None],
    *,
    expected_case_count: int = 27,
    expected_file_count: int = 524,
) -> None:
    require(len(expected_files) == expected_file_count, "RQ6-V01_BASELINE_COVERAGE")
    require(dict(actual_files) == dict(expected_files), "RQ6-V01_HISTORICAL_MUTATION")
    require(len(closures) == expected_case_count, "RQ6-V01_PRIMARY_COVERAGE")
    case_ids: set[str] = set()
    for closure in closures:
        result = cast(Callable[[ArtifactSnapshot], object], closure_verifier)(closure)
        require(result is None, "RQ6-V01_INVALID_VERIFIER_CONTRACT")
        data = closure.data()
        case_id = data["case_id"]
        require(case_id not in case_ids, "RQ6-V01_DUPLICATE_PRIMARY")
        case_ids.add(case_id)


def validate_v02(
    raw_manifest: bytes, expected_hash: str, frozen_bundles: Sequence[Mapping[str, Any]]
) -> None:
    from civicgate.rq6.core import decode_exact

    require(sha256(raw_manifest) == expected_hash, "RQ6-V02_MANIFEST_HASH")
    manifest = decode_exact(raw_manifest)
    require(type(manifest) is dict, "RQ6-V02_MANIFEST_SCHEMA")
    require(
        [bundle["manifest_entry"] for bundle in frozen_bundles] == manifest["repeat_bundles"],
        "RQ6-V02_MANIFEST_ORDER_CHANGED",
    )
    require(len(frozen_bundles) == 6, "RQ6-V02_BUNDLE_COUNT")
    selectors: set[bytes] = set()
    for bundle in frozen_bundles:
        require(
            sha256(bundle["raw_source_bytes"]) == bundle["manifest_entry"]["sha256"],
            "RQ6-V02_SOURCE_HASH",
        )
        require(len(bundle["source_slots"]) == 1, "RQ6-V02_UNEXPECTED_REGROUPING")
        observations = bundle["repeat_selectors"]
        require(
            [item["repeat_number"] for item in observations] == [1, 2, 3],
            "RQ6-V02_FROZEN_REPEAT_ORDER",
        )
        for item in observations:
            selector = exact_json(item["exact_selector"])
            require(selector not in selectors, "RQ6-V02_DUPLICATE_SELECTOR")
            selectors.add(selector)


def validate_literal_leakage(payload: Mapping[str, Any], forbidden_literals: Sequence[str]) -> None:
    # Generic public words (such as provider timeout) are not identity metadata.
    text = exact_json(dict(payload)).decode("utf-8")
    require(
        re.search(r"(?i)\bgpt-(?:5\.6|6)(?:-[a-z]+)?\b", text) is None,
        "RQ6-V03_LITERAL_IDENTITY_LEAK",
    )
    require(
        all(not value or value not in text for value in forbidden_literals),
        "RQ6-V03_LITERAL_IDENTITY_LEAK",
    )


class ValidatorSuite:
    """Trusted custody supplies immutable context and separately approved authority hashes.

    An artifact's self-asserted PASS or approved flag never grants authority. The
    trusted authorization allowlist must come from the human approval boundary.
    All references resolve to rehashed snapshots; there are no default success
    callbacks or inferred historical controls.
    """

    def __init__(
        self,
        binding: Mapping[str, str],
        *,
        mapping: ArtifactSnapshot,
        sources: Mapping[str, FrozenSource],
        primary_anchor: ArtifactSnapshot,
        access_policy_sha256: str,
        approved_authority_hashes: frozenset[str],
        forbidden_literals: tuple[str, ...] = (),
        used_seeds: tuple[str, ...] = (),
        used_nonces: tuple[str, ...] = (),
        existing_ids: tuple[str, ...] = (),
        source_integrity_verifier: Callable[[], None],
        custody_resolver: Callable[[str], ArtifactSnapshot],
        frozen_selection: tuple[tuple[bytes, tuple[str | int, ...]], ...],
        primary_case_id: str,
        enforcement_evidence_resolver: Callable[[str], bytes] | None = None,
        evidence_limitation: ArtifactSnapshot | None = None,
    ) -> None:
        self.binding = dict(binding)
        self.mapping = mapping
        self.sources = dict(sources)
        self.primary_anchor = primary_anchor
        self.primary_case_id = primary_case_id
        self.enforcement_evidence_resolver = enforcement_evidence_resolver
        self.evidence_limitation = evidence_limitation
        self.access_policy_sha256 = access_policy_sha256
        self.approved_authority_hashes = approved_authority_hashes
        self.forbidden_literals = forbidden_literals
        self.used_seeds, self.used_nonces, self.existing_ids = used_seeds, used_nonces, existing_ids
        self.source_integrity_verifier = source_integrity_verifier
        self.custody_resolver = custody_resolver
        self.frozen_selection = frozen_selection
        require(
            len(frozen_selection) == 3 and len({pointer for _, pointer in frozen_selection}) == 3,
            "RQ6-V02_SELECTOR_BIJECTION",
        )
        self._records: dict[str, ArtifactSnapshot] = {}
        self._frozen_receipts: dict[str, bytes] = {}
        self._closed_unit_receipts: dict[str, str] = {}
        self._unit_objects: dict[tuple[str, str], str] = {}

    def register(self, artifact: ArtifactSnapshot) -> ArtifactSnapshot:
        self(artifact)
        require(self.custody_resolver(artifact.sha256) == artifact, "REFERENCE_NOT_PERSISTED")
        if artifact.kind in {
            "reviewer_card",
            "unit_release_receipt",
            "human_receipt",
            "unit_closure",
        }:
            unit = artifact.data()["reviewer_unit_id"]
            prior_hash = self._unit_objects.get((artifact.kind, unit))
            require(
                prior_hash is None or prior_hash == artifact.sha256,
                "IMMUTABLE_UNIT_ARTIFACT_CONFLICT",
            )
            self._unit_objects[(artifact.kind, unit)] = artifact.sha256
        previous = self._records.get(artifact.sha256)
        require(previous is None or previous == artifact, "IMMUTABLE_ARTIFACT_CONFLICT")
        self._records[artifact.sha256] = artifact
        if artifact.kind == "unit_closure":
            data = artifact.data()
            receipt = self.get(data["human_receipt_sha256"], "human_receipt")
            self._closed_unit_receipts[data["reviewer_unit_id"]] = receipt.sha256
            self._frozen_receipts[receipt.sha256] = receipt.payload_bytes
        return artifact

    def get(self, digest: str, kind: str | None = None) -> ArtifactSnapshot:
        require(digest in self._records, "REFERENCE_NOT_PERSISTED")
        artifact = self._records[digest]
        artifact.data()
        require(self.custody_resolver(digest) == artifact, "PERSISTED_ARTIFACT_MUTATION")
        require(kind is None or artifact.kind == kind, "REFERENCE_KIND_MISMATCH")
        return artifact

    def __call__(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.schemas import FIELDS, validate_artifact

        data = artifact.data()
        helper_fields = {
            "alias_commitment": {
                "mapping_commitment_sha256",
                "reviewer_access_policy_sha256",
                "algorithm_version",
                "commitment_timestamp",
            },
            "operation_authorization": {
                "operation",
                "reviewer_unit_id",
                "reviewer",
                "authorized_recipients",
                "approved",
                "timestamp",
            },
            "mechanical_comparison": {
                "unblind_receipt_sha256",
                "primary_anchor_receipt_sha256",
                "observation_count",
                "class_changed",
                "flags_changed",
                "confidences",
                "normalized_flag_sets",
            },
            "bundle_characterization": {
                "mechanical_comparison_sha256",
                "rationale_variation_assessment_receipt_sha256",
                "stability_disposition",
                "review_status",
            },
        }
        if artifact.kind in helper_fields:
            allowed = set(self.binding) | helper_fields[artifact.kind]
            if (
                artifact.kind == "operation_authorization"
                and data.get("operation") == "bundle_open"
            ):
                allowed.add("private_manifest_position")
            require(set(data) == allowed, "HELPER_UNDECLARED_OR_MISSING_FIELD")
            for field, item in data.items():
                if field.endswith("_sha256"):
                    require(
                        type(item) is str and re.fullmatch(r"[0-9a-f]{64}", item) is not None,
                        "HELPER_HASH_TYPE",
                    )
                if field in {"timestamp", "commitment_timestamp"}:
                    require(type(item) is str, "HELPER_TIMESTAMP_TYPE")
                    try:
                        stamp = datetime.fromisoformat(item)
                    except ValueError as error:
                        raise ValueError("HELPER_TIMESTAMP_FORMAT") from error
                    require(stamp.utcoffset() == timedelta(0), "HELPER_TIMESTAMP_NOT_UTC")
                if field in {"approved", "class_changed", "flags_changed"}:
                    require(type(item) is bool, "HELPER_BOOLEAN_TYPE")
                if field in {"observation_count", "private_manifest_position"}:
                    require(type(item) is int and item > 0, "HELPER_POSITION_TYPE")
        if artifact.kind in FIELDS:
            validate_artifact(artifact.kind, data)
        require(
            artifact.kind == "empty_human_form"
            or all(data.get(key) == value for key, value in self.binding.items()),
            "RQ6-V11_CROSS_BUNDLE",
        )
        handlers: dict[str, Callable[[ArtifactSnapshot], None]] = {
            "reviewer_access_provenance": self.v03,
            "alias_commitment": self.v04,
            "reviewer_card": self.v05,
            "unit_release_receipt": self.v06,
            "human_receipt": self.v07,
            "unit_closure": self.v08,
            "bundle_unblind_receipt": self.v09,
            "mechanical_comparison": self.v10,
            "rationale_variation_assessment_artifact": self.v10,
            "rationale_variation_assessment_receipt": self.v10,
            "bundle_characterization": self.v10,
            "bundle_closure": self.v12,
            "operation_authorization": self.authority,
            "primary_anchor": self.verify_primary_anchor,
            "bundle_event_ledger": self.verify_event,
            "evidence_limitation": self.verify_limitation,
        }
        require(artifact.kind in FIELDS or artifact.kind in handlers, "UNKNOWN_ARTIFACT_KIND")
        if artifact.kind in handlers:
            handlers[artifact.kind](artifact)

    def authority(self, artifact: ArtifactSnapshot) -> None:
        require(artifact.sha256 in self.approved_authority_hashes, "UNAPPROVED_AUTHORITY_RECEIPT")
        require(artifact.data().get("approved") is True, "UNAPPROVED_AUTHORITY_RECEIPT")

    def verify_primary_anchor(self, artifact: ArtifactSnapshot) -> None:
        require(artifact == self.primary_anchor, "RQ6-V10_OTHER_PRIMARY")
        require(self.source_integrity_verifier() is None, "RQ6-V02_INVALID_VERIFIER_CONTRACT")

    def verify_limitation(self, artifact: ArtifactSnapshot) -> None:
        require(
            self.evidence_limitation is not None and artifact == self.evidence_limitation,
            "RQ6-V12_UNPINNED_FAILURE_RECORD",
        )
        data = artifact.data()
        require(
            bool(data.get("missing_evidence") or data.get("unusable_evidence")),
            "RQ6-V12_NO_LIMITATION",
        )
        require(
            bool(data.get("relevant_hashes_or_validation_failures")),
            "RQ6-V12_MISSING_FAILURE_PROVENANCE",
        )

    def verify_event(self, artifact: ArtifactSnapshot) -> None:
        data = artifact.data()
        expected_kind = {
            "ALIAS_COMMITMENT_FIXED": "alias_commitment",
            "UNIT_RELEASED": "unit_release_receipt",
            "HUMAN_RECEIPT_FIXED": "human_receipt",
            "UNIT_CLOSURE_VERIFIED": "unit_closure",
            "BUNDLE_MAPPING_REVEALED": "bundle_unblind_receipt",
            "MECHANICAL_COMPARISON_RECORDED": "mechanical_comparison",
            "RATIONALE_ASSESSMENT_FIXED": "rationale_variation_assessment_receipt",
            "BUNDLE_CHARACTERIZATION_FIXED": "bundle_characterization",
            "BUNDLE_CLOSURE_VERIFIED": "bundle_closure",
        }.get(data["event_type"])
        self.get(data["artifact_sha256"], expected_kind)
        require(
            data["audience_policy_sha256"] == self.access_policy_sha256, "EVENT_AUDIENCE_MISMATCH"
        )

    def v03(self, artifact: ArtifactSnapshot) -> None:
        data = artifact.data()
        require(
            data["approved_access_policy_sha256"] == self.access_policy_sha256,
            "RQ6-V03_ACCESS_POLICY_MISMATCH",
        )
        for digest in data["enforcement_evidence_hashes"]:
            require(
                self.enforcement_evidence_resolver is not None,
                "RQ6-V03_ENFORCEMENT_NOT_ESTABLISHED",
            )
            assert self.enforcement_evidence_resolver is not None
            require(
                sha256(self.enforcement_evidence_resolver(digest)) == digest,
                "RQ6-V03_ENFORCEMENT_HASH_MISMATCH",
            )
        validate_literal_leakage(data, self.forbidden_literals)

    def v04(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.core import decode_exact
        from civicgate.rq6.crypto import UNIT_ID_FIELDS, opaque_unit_id, verify_mapping_commitment

        require(self.source_integrity_verifier() is None, "RQ6-V02_INVALID_VERIFIER_CONTRACT")
        mapping = self.mapping.data()
        require(
            all(mapping.get(key) == value for key, value in self.binding.items()),
            "RQ6-V04_MAPPING_BINDING",
        )
        data = artifact.data()
        require(
            data["algorithm_version"] == "civicgate-rq6-bundle-alias-v1",
            "RQ6-V04_ALGORITHM_MISMATCH",
        )
        validate_literal_leakage(data, self.forbidden_literals)
        verify_mapping_commitment(
            mapping,
            data["mapping_commitment_sha256"],
            used_seeds=self.used_seeds,
            used_nonces=self.used_nonces,
            existing_ids=self.existing_ids,
        )
        require(
            data["reviewer_access_policy_sha256"] == self.access_policy_sha256,
            "RQ6-V04_POLICY_MISMATCH",
        )
        require(
            mapping["reviewer_access_policy_sha256"] == self.access_policy_sha256,
            "RQ6-V04_POLICY_MISMATCH",
        )
        require(
            len(mapping["exact_source_slot_selectors"]) == 1 and len(self.sources) == 3,
            "RQ6-V04_UNEXPECTED_COVERAGE",
        )
        nonces = {
            mapping["bundle_seed"],
            mapping["commitment_nonce"],
            *self.used_seeds,
            *self.used_nonces,
        }
        selectors: list[Any] = []
        derived_ids = [*self.existing_ids, mapping["bundle_review_id"]]
        for number, (unit, source) in enumerate(self.sources.items(), start=1):
            require(
                (source.selector_bytes, source.output_pointer) == self.frozen_selection[number - 1],
                "RQ6-V04_FROZEN_SELECTOR_POINTER",
            )
            require(
                source.output_pointer not in {source.context_pointer, source.neutral_pointer},
                "RQ6-V04_SOURCE_POINTER_ROLE",
            )
            opening = decode_exact(source.source_link_opening_bytes)
            nonce = opening["independent_unit_nonce"]
            require(nonce not in nonces, "RQ6-V04_REUSED_UNIT_NONCE")
            nonces.add(nonce)
            selector = decode_exact(source.selector_bytes)
            selectors.append(selector)
            preimage = {key: mapping[key] for key in UNIT_ID_FIELDS if key in mapping}
            preimage.update(
                exact_source_slot_selector=mapping["exact_source_slot_selectors"][0],
                repeat_number=number,
            )
            require(
                opaque_unit_id(mapping["bundle_seed"], preimage, existing_ids=derived_ids) == unit,
                "RQ6-V04_UNIT_ID_DERIVATION",
            )
            derived_ids.append(unit)
            require(
                sha256(source.raw_artifact) == mapping["source_artifact_sha256"],
                "RQ6-V04_SOURCE_ARTIFACT",
            )
        require(
            selectors == mapping["complete_required_repeat_selectors"], "RQ6-V04_SELECTOR_ORDER"
        )

    def v05(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.core import decode_exact
        from civicgate.rq6.crypto import mapping_commitment, verify_source_link
        from civicgate.rq6.source import json_value_slice

        require(self.source_integrity_verifier() is None, "RQ6-V02_INVALID_VERIFIER_CONTRACT")
        data = artifact.data()
        require(data["reviewer_unit_id"] in self.sources, "RQ6-V05_UNKNOWN_SOURCE")
        source = self.sources[data["reviewer_unit_id"]]
        require(
            source.raw_output_slice == json_value_slice(source.raw_artifact, source.output_pointer)
            and source.context_bytes
            == json_value_slice(source.raw_artifact, source.context_pointer)
            and source.neutral_bytes
            == json_value_slice(source.raw_artifact, source.neutral_pointer),
            "RQ6-V05_RAW_SLICE_NOT_FROM_SOURCE",
        )
        opening = decode_exact(source.source_link_opening_bytes)
        require(type(opening) is dict, "RQ6-V05_OPENING_INVALID")
        require(
            data["mapping_commitment_sha256"] == mapping_commitment(self.mapping.data()),
            "RQ6-V05_MAPPING_MISMATCH",
        )
        projection = dict(data)
        projection.pop("source_link_commitment_sha256")
        required_hashes = {
            "source_artifact_sha256": sha256(source.raw_artifact),
            "raw_output_slice_sha256": sha256(source.raw_output_slice),
            "context_sha256": sha256(source.context_bytes),
            "neutral_reference_sha256": sha256(source.neutral_bytes),
            "payload_sha256": sha256(exact_json(projection)),
            "mapping_commitment_sha256": data["mapping_commitment_sha256"],
        }
        require(
            all(opening.get(key) == value for key, value in required_hashes.items()),
            "RQ6-V05_SOURCE_HASH_MISMATCH",
        )
        require(
            exact_json(opening["exact_selector"]) == source.selector_bytes,
            "RQ6-V05_SELECTOR_MISMATCH",
        )
        require(
            all(opening.get(key) == value for key, value in self.binding.items()),
            "RQ6-V05_OPENING_BINDING",
        )
        require(opening["reviewer_unit_id"] == data["reviewer_unit_id"], "RQ6-V05_OPENING_BINDING")
        require(opening.get("final_card_sha256") == artifact.sha256, "RQ6-V05_FINAL_CARD_HASH")
        verify_source_link(opening, data["source_link_commitment_sha256"], card=data)
        context = decode_exact(source.context_bytes)
        require(
            all(
                exact_json(data[key]) == exact_json(context[key])
                for key in ("user_request", "proposed_tool", "proposed_arguments")
            ),
            "RQ6-V05_CONTEXT_CHANGED",
        )
        require(
            exact_json(data["stored_output"]) == exact_json(decode_exact(source.raw_output_slice)),
            "RQ6-V05_OUTPUT_CHANGED",
        )
        require(
            exact_json(data["frozen_neutral_reference"])
            == exact_json(decode_exact(source.neutral_bytes)),
            "RQ6-V05_REFERENCE_CHANGED",
        )
        validate_literal_leakage(data, self.forbidden_literals)

    def v06(self, artifact: ArtifactSnapshot) -> None:
        data = artifact.data()
        card = self.get(data["reviewer_card_sha256"], "reviewer_card")
        form = self.get(data["human_form_sha256"], "empty_human_form")
        self.v05(card)
        self(form)
        access = self.get(data["reviewer_access_provenance_sha256"], "reviewer_access_provenance")
        self.v03(access)
        require(
            datetime.fromisoformat(access.data()["effective_timestamp"])
            <= datetime.fromisoformat(data["release_timestamp"]),
            "RQ6-V06_ACCESS_NOT_YET_EFFECTIVE",
        )
        require(
            all(
                data[key] == card.data()[key]
                for key in (
                    "reviewer_unit_id",
                    "mapping_commitment_sha256",
                    "source_link_commitment_sha256",
                )
            ),
            "RQ6-V06_RELEASE_LINK_MISMATCH",
        )
        order = list(self.sources)
        index = order.index(data["reviewer_unit_id"])
        require(
            card.data()["observation_sequence_within_bundle"] == index + 1,
            "RQ6-V06_OBSERVATION_ORDER",
        )
        require(
            (data["previous_unit_closure_sha256"] is None) == (index == 0),
            "RQ6-V06_FIRST_PREDECESSOR_RULE",
        )
        if data["previous_unit_closure_sha256"] is not None:
            previous = self.get(data["previous_unit_closure_sha256"], "unit_closure")
            self.v08(previous)
            require(
                previous.data()["reviewer_unit_id"] != data["reviewer_unit_id"],
                "RQ6-V06_SELF_PREDECESSOR",
            )
            require(
                previous.data()["reviewer_unit_id"] == order[index - 1], "RQ6-V06_PREDECESSOR_ORDER"
            )

    def v07(self, artifact: ArtifactSnapshot) -> None:
        data = artifact.data()
        fixed = self._closed_unit_receipts.get(data["reviewer_unit_id"])
        require(fixed is None or fixed == artifact.sha256, "RQ6-V07_CLOSED_UNIT_RECODING")
        release = self.get(data["release_receipt_sha256"], "unit_release_receipt")
        self.v06(release)
        fields = (
            "reviewer_card_sha256",
            "reviewer_unit_id",
            "mapping_commitment_sha256",
            "source_link_commitment_sha256",
            "reviewer_access_provenance_sha256",
        )
        require(
            all(data[key] == release.data()[key] for key in fields), "RQ6-V07_RECEIPT_LINK_MISMATCH"
        )
        access = self.get(data["reviewer_access_provenance_sha256"])
        require(data["reviewer"] == access.data()["reviewer"], "RQ6-V07_REVIEWER_MISMATCH")
        require(
            datetime.fromisoformat(data["adjudication_timestamp"])
            >= datetime.fromisoformat(release.data()["release_timestamp"]),
            "RQ6-V07_RECEIPT_PRECEDES_RELEASE",
        )

    def v08(self, artifact: ArtifactSnapshot) -> None:
        data = artifact.data()
        receipt = self.get(data["human_receipt_sha256"], "human_receipt")
        self.v07(receipt)
        require(
            all(
                data[key] == receipt.data()[key]
                for key in (
                    "reviewer_unit_id",
                    "reviewer_card_sha256",
                    "release_receipt_sha256",
                    "mapping_commitment_sha256",
                    "source_link_commitment_sha256",
                )
            ),
            "RQ6-V08_CLOSURE_LINK_MISMATCH",
        )
        fixed = self._closed_unit_receipts.get(data["reviewer_unit_id"])
        require(fixed is None or fixed == receipt.sha256, "RQ6-V08_CLOSED_UNIT_RECODING")

    def v09(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.core import decode_exact
        from civicgate.rq6.crypto import mapping_commitment, verify_source_link

        data = artifact.data()
        require(
            data["reviewer_access_policy_sha256"] == self.access_policy_sha256,
            "RQ6-V09_ACCESS_POLICY_MISMATCH",
        )
        authority = self.get(data["human_authorization_receipt_sha256"], "operation_authorization")
        self.authority(authority)
        require(authority.data()["operation"] == "bundle_unblind", "RQ6-V09_AUTHORITY_SCOPE")
        require(
            data["authorized_recipients"] == authority.data()["authorized_recipients"],
            "RQ6-V09_AUDIENCE_MISMATCH",
        )
        require(
            len(data["required_unit_closure_hashes"]) == len(self.sources),
            "RQ6-V09_INCOMPLETE_COVERAGE",
        )
        require(
            len(data["required_human_receipt_hashes"]) == len(self.sources),
            "RQ6-V09_INCOMPLETE_COVERAGE",
        )
        units: set[str] = set()
        for closure_hash, receipt_hash in zip(
            data["required_unit_closure_hashes"], data["required_human_receipt_hashes"], strict=True
        ):
            closure = self.get(closure_hash, "unit_closure")
            self.v08(closure)
            require(closure.data()["human_receipt_sha256"] == receipt_hash, "RQ6-V09_BROKEN_CHAIN")
            units.add(closure.data()["reviewer_unit_id"])
        require(units == set(self.sources), "RQ6-V09_UNIT_COVERAGE")
        mapping = self.mapping.data()
        require(
            data["alias_commitment_sha256"] == mapping_commitment(mapping), "RQ6-V09_MAPPING_HASH"
        )
        require(
            exact_json(data["current_bundle_commitment_openings"]) == exact_json(mapping),
            "RQ6-V09_MAPPING_OPENING",
        )
        require(
            data["revealed_current_bundle_mapping"] == mapping["source_identity_bindings"],
            "RQ6-V09_IDENTITY_OPENING",
        )
        openings = data["current_bundle_source_link_openings"]
        require(set(openings) == set(self.sources), "RQ6-V09_SOURCE_OPENING_COVERAGE")
        for unit, source in self.sources.items():
            expected = decode_exact(source.source_link_opening_bytes)
            require(exact_json(openings[unit]) == exact_json(expected), "RQ6-V09_SOURCE_OPENING")
            card_hash = self._unit_objects[("reviewer_card", unit)]
            card = self.get(card_hash, "reviewer_card").data()
            verify_source_link(openings[unit], card["source_link_commitment_sha256"], card=card)
        self.v11()

    def v10(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.stability import Observation, characterize, normalize_flags

        data = artifact.data()
        self.v11()
        if artifact.kind == "mechanical_comparison":
            self.get(data["unblind_receipt_sha256"], "bundle_unblind_receipt")
            require(
                data["primary_anchor_receipt_sha256"] == self.primary_anchor.sha256,
                "RQ6-V10_OTHER_PRIMARY",
            )
            primary = self.primary_anchor.data()["stored_output"]
            outputs = [primary]
            cards = [record for record in self._records.values() if record.kind == "reviewer_card"]
            cards.sort(key=lambda record: record.data()["observation_sequence_within_bundle"])
            outputs.extend(card.data()["stored_output"] for card in cards)
            require(len(outputs) == len(self.sources) + 1, "RQ6-V10_COVERAGE")
            normalized = [list(normalize_flags(item["flags"])) for item in outputs]
            require(data["normalized_flag_sets"] == normalized, "RQ6-V10_FLAG_SETS")
            require(
                data["class_changed"] == (len({item["classification"] for item in outputs}) > 1),
                "RQ6-V10_CLASS_AXIS",
            )
            require(
                data["flags_changed"] == (len({tuple(item) for item in normalized}) > 1),
                "RQ6-V10_FLAG_AXIS",
            )
            require(
                exact_json(data["confidences"])
                == exact_json([item["confidence"] for item in outputs]),
                "RQ6-V10_CONFIDENCE_CHANGED",
            )
            require(data["observation_count"] == len(outputs), "RQ6-V10_COVERAGE")
        elif artifact.kind == "rationale_variation_assessment_artifact":
            self.get(data["unblind_receipt_sha256"], "bundle_unblind_receipt")
            require(
                data["primary_anchor_receipt_sha256"] == self.primary_anchor.sha256,
                "RQ6-V10_OTHER_PRIMARY",
            )
            primary = self.primary_anchor.data()
            require(
                data["primary_stored_rationale"] == primary["stored_output"]["rationale"],
                "RQ6-V10_PRIMARY_RATIONALE_CHANGED",
            )
            require(
                data["frozen_primary_semantic_coding"] == primary["semantic_coding"],
                "RQ6-V10_PRIMARY_CODING_CHANGED",
            )
            receipts = [
                self.get(digest, "human_receipt")
                for digest in data["completed_unit_receipt_hashes"]
            ]
            require(
                {record.sha256 for record in receipts} == set(self._frozen_receipts),
                "RQ6-V10_ASSESSMENT_COVERAGE",
            )
            codes = [
                {
                    key: receipt.data()[key]
                    for key in ("primary_disposition", "rationale_propositions", "reviewer_reason")
                }
                for receipt in receipts
            ]
            rationales = [
                self.get(receipt.data()["reviewer_card_sha256"]).data()["stored_output"][
                    "rationale"
                ]
                for receipt in receipts
            ]
            require(
                data["frozen_repeat_semantic_coding"] == codes
                and data["repeat_rationales"] == rationales,
                "RQ6-V10_FROZEN_CODING_CHANGED",
            )
        elif artifact.kind == "rationale_variation_assessment_receipt":
            original = self.get(
                data["rationale_artifact_sha256"], "rationale_variation_assessment_artifact"
            ).data()
            for field in (
                "unblind_receipt_sha256",
                "primary_anchor_receipt_sha256",
                "completed_unit_receipt_hashes",
            ):
                require(data[field] == original[field], "RQ6-V10_ASSESSMENT_LINK_MISMATCH")
            sets = [original["frozen_primary_semantic_coding"]["rationale_propositions"]]
            sets.extend(
                item["rationale_propositions"] for item in original["frozen_repeat_semantic_coding"]
            )
            require(data["frozen_proposition_sets"] == sets, "RQ6-V10_PROPOSITIONS_CHANGED")
            candidate = len({frozenset(item) for item in sets}) > 1
            require(
                data["proposition_set_difference_candidate"] is candidate,
                "RQ6-V10_CANDIDATE_MISMATCH",
            )
        else:
            mechanical = self.get(data["mechanical_comparison_sha256"], "mechanical_comparison")
            self.v10(mechanical)
            receipt = self.get(
                data["rationale_variation_assessment_receipt_sha256"],
                "rationale_variation_assessment_receipt",
            )
            self.v10(receipt)
            primary = self.primary_anchor.data()["stored_output"]
            outputs = [
                self.get(self.get(digest).data()["reviewer_card_sha256"]).data()["stored_output"]
                for digest in receipt.data()["completed_unit_receipt_hashes"]
            ]
            expected = characterize(
                Observation(
                    **{key: primary[key] for key in ("classification", "flags", "confidence")}
                ),
                [
                    Observation(
                        **{key: output[key] for key in ("classification", "flags", "confidence")}
                    )
                    for output in outputs
                ],
                expected_repeat_count=len(self.sources),
                rationale_variation=receipt.data()["rationale_variation"],
                material_boundary_changed=receipt.data()["material_boundary_changed"],
            )
            require(
                data["stability_disposition"] == expected["stability_disposition"]
                and data["review_status"] == expected["review_status"],
                "RQ6-V10_CHARACTERIZATION_MISMATCH",
            )

    def v11(self) -> None:
        for digest, raw in self._frozen_receipts.items():
            require(self.get(digest).payload_bytes == raw, "RQ6-V11_HINDSIGHT_MUTATION")

    def v12(self, artifact: ArtifactSnapshot) -> None:
        from civicgate.rq6.crypto import mapping_commitment

        data = artifact.data()
        self.v11()
        require(
            data["applicable_primary_case_id"] == self.primary_case_id,
            "RQ6-V12_PRIMARY_CASE_CHANGED",
        )
        if data["stability_disposition"] == "INSUFFICIENT_REPEAT_EVIDENCE":
            require(
                data["reviewer_access_policy_sha256"] == self.access_policy_sha256
                and data["frozen_manifest_position"]
                == self.mapping.data()["private_manifest_position"]
                and data["alias_commitment_sha256"] == mapping_commitment(self.mapping.data()),
                "RQ6-V12_PARTIAL_BINDING_CHANGED",
            )
            for kind, field, embedded in (
                ("bundle_unblind_receipt", "unblind_receipt_sha256", False),
                ("mechanical_comparison", "per_model_primary_repeat_comparison", True),
                (
                    "rationale_variation_assessment_receipt",
                    "rationale_variation_assessment_receipt_sha256",
                    False,
                ),
            ):
                performed = [
                    self.get(digest, kind)
                    for digest, record in self._records.items()
                    if record.kind == kind
                ]
                require(len(performed) <= 1, "RQ6-V12_AMBIGUOUS_OPERATION_HISTORY")
                if performed:
                    require(
                        exact_json(data[field]) == performed[0].payload_bytes
                        if embedded
                        else data[field] == performed[0].sha256,
                        "RQ6-V12_PERFORMED_OPERATION_OMITTED_OR_CHANGED",
                    )
                else:
                    require(data[field] is None, "RQ6-V12_FABRICATED_UNPERFORMED_OPERATION")
            require(self.evidence_limitation is not None, "RQ6-V12_UNPINNED_FAILURE_RECORD")
            assert self.evidence_limitation is not None
            failure = self.get(self.evidence_limitation.sha256, "evidence_limitation").data()
            for field in (
                "expected_evidence",
                "available_evidence",
                "missing_evidence",
                "unusable_evidence",
                "evidence_limitation_reasons",
                "relevant_hashes_or_validation_failures",
                "stability_not_established_reason",
            ):
                require(
                    exact_json(data[field]) == exact_json(failure[field]),
                    "RQ6-V12_FAILURE_RECONSTRUCTION",
                )
            require(
                data["validation_results"] == {**failure["validation_results"], "RQ6-V12": "PASS"},
                "RQ6-V12_FAILURE_CONTROL_REWRITTEN",
            )
            require(
                self.evidence_limitation.sha256 in data["provenance_hashes"],
                "RQ6-V12_FAILURE_PROVENANCE",
            )
            require(data["missing_evidence"] or data["unusable_evidence"], "RQ6-V12_NO_LIMITATION")
            require(
                data["evidence_limitation_reasons"] and data["stability_not_established_reason"],
                "RQ6-V12_UNEXPLAINED_LIMITATION",
            )
            require(
                data["relevant_hashes_or_validation_failures"], "RQ6-V12_MISSING_FAILURE_PROVENANCE"
            )
            if data["unblind_receipt_sha256"] is None:
                require(
                    all(
                        data[field] is None
                        for field in (
                            "revealed_source_mapping",
                            "per_model_primary_repeat_comparison",
                            "frozen_rationale_variation_record",
                            "rationale_variation_assessment_receipt_sha256",
                        )
                    ),
                    "RQ6-V12_FABRICATED_UNPERFORMED_OPERATION",
                )
            else:
                unblind = self.get(data["unblind_receipt_sha256"], "bundle_unblind_receipt")
                self.v09(unblind)
                require(
                    data["revealed_source_mapping"]
                    == unblind.data()["revealed_current_bundle_mapping"]
                    and data["authorized_identity_audience"]
                    == unblind.data()["authorized_recipients"]
                    and data["unit_closure_hashes"]
                    == unblind.data()["required_unit_closure_hashes"]
                    and data["human_receipt_hashes"]
                    == unblind.data()["required_human_receipt_hashes"],
                    "RQ6-V12_PARTIAL_UNBLIND_CHANGED",
                )
                if data["per_model_primary_repeat_comparison"] is not None:
                    mechanical = [
                        self.get(digest, "mechanical_comparison")
                        for digest in data["provenance_hashes"]
                        if self.get(digest).kind == "mechanical_comparison"
                    ]
                    require(len(mechanical) == 1, "RQ6-V12_MECHANICAL_PROVENANCE")
                    self.v10(mechanical[0])
                    require(
                        mechanical[0].data()["unblind_receipt_sha256"] == unblind.sha256
                        and exact_json(data["per_model_primary_repeat_comparison"])
                        == mechanical[0].payload_bytes,
                        "RQ6-V12_PARTIAL_MECHANICAL_CHANGED",
                    )
                assessment_hash = data["rationale_variation_assessment_receipt_sha256"]
                if assessment_hash is None:
                    require(
                        data["frozen_rationale_variation_record"] is None,
                        "RQ6-V12_FABRICATED_UNPERFORMED_OPERATION",
                    )
                else:
                    require(
                        data["per_model_primary_repeat_comparison"] is not None,
                        "RQ6-V12_ASSESSMENT_BEFORE_MECHANICAL",
                    )
                    assessment = self.get(assessment_hash, "rationale_variation_assessment_receipt")
                    self.v10(assessment)
                    require(
                        assessment_hash in data["provenance_hashes"]
                        and assessment.data()["unblind_receipt_sha256"] == unblind.sha256
                        and exact_json(data["frozen_rationale_variation_record"])
                        == assessment.payload_bytes,
                        "RQ6-V12_PARTIAL_ASSESSMENT_CHANGED",
                    )
            cards = [
                self.get(digest, "reviewer_card") for digest in data["reviewer_artifact_hashes"]
            ]
            require(
                data["reviewer_unit_ids"] == [card.data()["reviewer_unit_id"] for card in cards],
                "RQ6-V12_PARTIAL_CARD_COVERAGE",
            )
            outputs: list[Any] = []
            require(
                data["primary_anchor_hashes"] in ([], [self.primary_anchor.sha256]),
                "RQ6-V12_OTHER_PRIMARY",
            )
            if data["primary_anchor_hashes"]:
                outputs.append(self.get(self.primary_anchor.sha256).data()["stored_output"])
            outputs.extend(card.data()["stored_output"] for card in cards)
            from civicgate.rq6.stability import normalize_flags

            expected_partial = {
                "stored_classifications": [item["classification"] for item in outputs],
                "stored_structured_flag_lists": [item["flags"] for item in outputs],
                "stored_confidences": [item["confidence"] for item in outputs],
                "normalized_flag_sets": [list(normalize_flags(item["flags"])) for item in outputs],
            }
            require(
                all(
                    exact_json(data[key]) == exact_json(value)
                    for key, value in expected_partial.items()
                ),
                "RQ6-V12_FABRICATED_PARTIAL_DESCRIPTIVES",
            )
            if data["confidence_descriptive_values_and_range"] is not None:
                confidences = [item["confidence"] for item in outputs]
                require(
                    exact_json(data["confidence_descriptive_values_and_range"])
                    == exact_json(
                        {
                            "interpretation": "DESCRIPTIVE_ONLY",
                            "values": confidences,
                            "range": [min(confidences), max(confidences)] if confidences else None,
                        }
                    ),
                    "RQ6-V12_FABRICATED_PARTIAL_CONFIDENCES",
                )
            known_units = {card.data()["reviewer_unit_id"] for card in cards}
            for field, kind in (
                ("human_receipt_hashes", "human_receipt"),
                ("unit_closure_hashes", "unit_closure"),
            ):
                for digest in data[field]:
                    require(
                        self.get(digest, kind).data()["reviewer_unit_id"] in known_units,
                        "RQ6-V12_PARTIAL_CHAIN_BROKEN",
                    )
            require(
                data["source_artifact_hashes"]
                in ([], [self.mapping.data()["source_artifact_sha256"]]),
                "RQ6-V12_PARTIAL_SOURCE_CHANGED",
            )
            coverage = {
                key: {exact_json(item) for item in data[key]}
                for key in (
                    "expected_evidence",
                    "available_evidence",
                    "missing_evidence",
                    "unusable_evidence",
                )
            }
            require(
                not (
                    coverage["available_evidence"]
                    & (coverage["missing_evidence"] | coverage["unusable_evidence"])
                )
                and coverage["available_evidence"]
                | coverage["missing_evidence"]
                | coverage["unusable_evidence"]
                == coverage["expected_evidence"],
                "RQ6-V12_INSUFFICIENT_COVERAGE_PARTITION",
            )
            require(
                len(coverage["available_evidence"]) == len(outputs),
                "RQ6-V12_PARTIAL_COVERAGE_COUNT",
            )
        else:
            require(
                not data["missing_evidence"] and not data["unusable_evidence"],
                "RQ6-V12_FALSE_COVERAGE",
            )
            unblind = self.get(data["unblind_receipt_sha256"], "bundle_unblind_receipt")
            self.v09(unblind)
            assessment = self.get(
                data["rationale_variation_assessment_receipt_sha256"],
                "rationale_variation_assessment_receipt",
            )
            self.v10(assessment)
            require(
                data["human_receipt_hashes"] == assessment.data()["completed_unit_receipt_hashes"],
                "RQ6-V12_RECEIPT_COVERAGE",
            )
            input_data = self.get(assessment.data()["rationale_artifact_sha256"]).data()
            receipts = [
                self.get(digest, "human_receipt")
                for digest in input_data["completed_unit_receipt_hashes"]
            ]
            cards = [
                self.get(receipt.data()["reviewer_card_sha256"], "reviewer_card")
                for receipt in receipts
            ]
            primary = self.get(self.primary_anchor.sha256, "primary_anchor")
            outputs = [
                primary.data()["stored_output"],
                *[card.data()["stored_output"] for card in cards],
            ]
            mechanical = [
                self.get(digest, "mechanical_comparison")
                for digest in data["provenance_hashes"]
                if self.get(digest).kind == "mechanical_comparison"
            ]
            require(len(mechanical) == 1, "RQ6-V12_MECHANICAL_PROVENANCE")
            self.v10(mechanical[0])
            require(assessment.sha256 in data["provenance_hashes"], "RQ6-V12_ASSESSMENT_PROVENANCE")
            from civicgate.rq6.stability import Observation, characterize, normalize_flags

            observations = [
                Observation(**{key: item[key] for key in ("classification", "flags", "confidence")})
                for item in outputs
            ]
            result = characterize(
                observations[0],
                observations[1:],
                expected_repeat_count=3,
                rationale_variation=assessment.data()["rationale_variation"],
                material_boundary_changed=assessment.data()["material_boundary_changed"],
            )
            expected = {
                "reviewer_unit_ids": [card.data()["reviewer_unit_id"] for card in cards],
                "reviewer_artifact_hashes": [card.sha256 for card in cards],
                "unit_closure_hashes": unblind.data()["required_unit_closure_hashes"],
                "alias_commitment_sha256": unblind.data()["alias_commitment_sha256"],
                "revealed_source_mapping": unblind.data()["revealed_current_bundle_mapping"],
                "source_artifact_hashes": [self.mapping.data()["source_artifact_sha256"]],
                "primary_anchor_hashes": [primary.sha256],
                "stored_classifications": [item["classification"] for item in outputs],
                "stored_structured_flag_lists": [item["flags"] for item in outputs],
                "stored_confidences": [item["confidence"] for item in outputs],
                "normalized_flag_sets": [list(normalize_flags(item["flags"])) for item in outputs],
                "per_model_primary_repeat_comparison": mechanical[0].data(),
                "frozen_rationale_variation_record": assessment.data(),
                "confidence_descriptive_values_and_range": {
                    "interpretation": "DESCRIPTIVE_ONLY",
                    "values": result["confidence_values"],
                    "range": result["confidence_range"],
                },
                "review_status": result["review_status"],
                "stability_disposition": result["stability_disposition"],
                "reviewer_access_policy_sha256": self.access_policy_sha256,
                "authorized_identity_audience": unblind.data()["authorized_recipients"],
                "frozen_manifest_position": self.mapping.data()["private_manifest_position"],
                "applicable_primary_case_id": self.primary_case_id,
            }
            require(
                all(exact_json(data[key]) == exact_json(value) for key, value in expected.items()),
                "RQ6-V12_CLOSURE_EVIDENCE_CHANGED",
            )
            require(
                len(data["expected_evidence"]) == 4
                and data["available_evidence"] == data["expected_evidence"],
                "RQ6-V12_FALSE_COVERAGE",
            )
        for field, kind in (
            ("human_receipt_hashes", "human_receipt"),
            ("unit_closure_hashes", "unit_closure"),
            ("reviewer_artifact_hashes", "reviewer_card"),
        ):
            for digest in data[field]:
                self.get(digest, kind)
