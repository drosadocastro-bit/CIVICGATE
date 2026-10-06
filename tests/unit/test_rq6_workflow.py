"""Synthetic gate tests; no sealed evidence, provider or credential operations."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from civicgate.rq6.core import ArtifactSnapshot, RQ6Error, exact_json
from civicgate.rq6.schemas import SCHEMA_VERSIONS
from civicgate.rq6.workflow import DEFERRED, BundleBinding, BundleWorkflow, CohortWorkflow

STAMP = "2026-01-01T00:00:00+00:00"
HASH = "d" * 64
PRIMARY = "e" * 64
BUNDLE = "a" * 64
UNITS = tuple(f"{number:064x}" for number in range(1, 4))
BINDING = BundleBinding(
    "CIVICGATE-JUDGE-COMPARISON-V1", "CIVICGATE-RQ6-AMENDMENT-001", "synthetic-package", BUNDLE
)


class SyntheticCustody:
    """A fixture-only persisted registry, so an arbitrary snapshot is rejected."""

    def __init__(self) -> None:
        self.bytes: dict[str, bytes] = {}

    def make(self, kind: str, payload: dict[str, Any]) -> ArtifactSnapshot:
        snapshot = ArtifactSnapshot.build(kind, payload)
        self.bytes[snapshot.sha256] = snapshot.payload_bytes
        return snapshot

    def verify(self, snapshot: ArtifactSnapshot) -> None:
        if self.bytes.get(snapshot.sha256) != snapshot.payload_bytes:
            raise RQ6Error("UNPERSISTED_SYNTHETIC_ARTIFACT")
        snapshot.data()


class SyntheticBundle:
    def __init__(self, bundle_id: str = BUNDLE) -> None:
        self.custody = SyntheticCustody()
        self.binding = BundleBinding(
            BINDING.protocol_id, BINDING.amendment_id, BINDING.package_id, bundle_id
        )
        units = () if bundle_id.startswith("RQ6_CUSTODY_FAILURE:") else UNITS
        self.flow = BundleWorkflow(self.binding, units, self.custody.verify, PRIMARY)
        self.cards: list[ArtifactSnapshot] = []
        self.receipts: list[ArtifactSnapshot] = []
        self.closures: list[ArtifactSnapshot] = []
        self.alias: ArtifactSnapshot | None = None
        self.access: ArtifactSnapshot | None = None
        self.unblind: ArtifactSnapshot | None = None
        self.mechanical: ArtifactSnapshot | None = None

    def record(self, kind: str, **payload: Any) -> ArtifactSnapshot:
        base: dict[str, Any] = {
            "protocol_id": self.binding.protocol_id,
            "amendment_id": self.binding.amendment_id,
            "package_id": self.binding.package_id,
            "bundle_review_id": self.binding.bundle_review_id,
        }
        if kind in SCHEMA_VERSIONS and SCHEMA_VERSIONS[kind] is not None:
            base["schema_version"] = SCHEMA_VERSIONS[kind]
        base.update(payload)
        return self.custody.make(kind, base)

    def authority(
        self, operation: str, unit_id: str | None = None, **updates: Any
    ) -> ArtifactSnapshot:
        fields = {
            "operation": operation,
            "reviewer_unit_id": unit_id,
            "reviewer": "Synthetic human",
            "authorized_recipients": ["Synthetic human"],
            "approved": True,
            "timestamp": STAMP,
            "private_manifest_position": 1,
        }
        fields.update(updates)
        return self.record("operation_authorization", **fields)

    def initialize(self) -> None:
        self.alias = self.record(
            "alias_commitment", mapping_commitment_sha256=HASH, reviewer_access_policy_sha256=HASH
        )
        self.access = self.record(
            "reviewer_access_provenance",
            reviewer="Synthetic human",
            access_contract="OPERATIONALLY_MAPPING_BLIND",
            approved_access_policy_sha256=HASH,
            access_mode="REVIEWER_ATTESTATION",
            reviewer_attestation="Synthetic fixture declaration",
            enforcement_evidence_hashes=[],
            effective_timestamp=STAMP,
            valid_through_bundle_semantic_freeze=True,
            immutability=True,
        )
        self.flow.fix_alias_commitment(
            self.alias, self.access, self.authority("alias_mapping_creation")
        )

    def release(
        self, index: int, **release_updates: Any
    ) -> tuple[ArtifactSnapshot, ArtifactSnapshot, ArtifactSnapshot]:
        assert self.access is not None
        card = self.record(
            "reviewer_card",
            reviewer_unit_id=UNITS[index],
            observation_sequence_within_bundle=index + 1,
            blind_alias="SIDE_1",
            user_request="Public awards for a synthetic recipient.",
            proposed_tool="find_federal_awards",
            proposed_arguments={"recipient": "Synthetic recipient"},
            frozen_neutral_reference={"classification": "IN_SCOPE", "flags": []},
            stored_output={
                "classification": "IN_SCOPE",
                "flags": [],
                "confidence": 0.9,
                "rationale": f"Synthetic rationale {index}.",
            },
            mapping_commitment_sha256=HASH,
            source_link_commitment_sha256=HASH,
        )
        form = self.custody.make(
            "empty_human_form",
            {
                "primary_disposition": None,
                "rationale_propositions": None,
                "reviewer_reason": None,
            },
        )
        fields = dict(
            reviewer_unit_id=UNITS[index],
            reviewer_card_sha256=card.sha256,
            human_form_sha256=form.sha256,
            mapping_commitment_sha256=HASH,
            source_link_commitment_sha256=HASH,
            reviewer_access_provenance_sha256=self.access.sha256,
            previous_unit_closure_sha256=self.closures[-1].sha256 if self.closures else None,
            release_timestamp=STAMP,
            validation_results={"RQ6-V07": "PASS"},
        )
        fields.update(release_updates)
        release = self.record("unit_release_receipt", **fields)
        self.flow.release_unit(card, form, release, self.authority("unit_release", UNITS[index]))
        self.cards.append(card)
        return card, form, release

    def freeze(self, index: int, release: ArtifactSnapshot) -> ArtifactSnapshot:
        assert self.access is not None
        card = self.cards[index]
        receipt = self.record(
            "human_receipt",
            reviewer_unit_id=UNITS[index],
            blind_alias="SIDE_1",
            reviewer_card_sha256=card.sha256,
            release_receipt_sha256=release.sha256,
            mapping_commitment_sha256=HASH,
            source_link_commitment_sha256=HASH,
            reviewer_access_provenance_sha256=self.access.sha256,
            reviewer="Synthetic human",
            primary_disposition="ALIGNED",
            rationale_propositions=[],
            reviewer_reason="Texto humano exacto. ",
            adjudication_timestamp=STAMP,
            adjudication_status="FIXED",
            operationally_mapping_blind_at_coding=True,
            mechanical_stability_seen=False,
            immutability=True,
        )
        self.flow.fix_human_receipt(receipt)
        self.receipts.append(receipt)
        closure = self.record(
            "unit_closure",
            reviewer_unit_id=UNITS[index],
            reviewer_card_sha256=card.sha256,
            release_receipt_sha256=release.sha256,
            human_receipt_sha256=receipt.sha256,
            mapping_commitment_sha256=HASH,
            source_link_commitment_sha256=HASH,
            closure_timestamp=STAMP,
            validation_results={"RQ6-V08": "PASS"},
            semantic_coding_frozen=True,
            unblinded=False,
            state="SEMANTICALLY_CLOSED_BLINDED",
        )
        self.flow.verify_unit_closure(closure)
        self.closures.append(closure)
        return receipt

    def complete_units(self) -> None:
        self.initialize()
        for index in range(3):
            _, _, release = self.release(index)
            self.freeze(index, release)

    def unblind_record(self, authority: ArtifactSnapshot, **updates: Any) -> ArtifactSnapshot:
        fields = dict(
            alias_commitment_sha256=HASH,
            required_human_receipt_hashes=[item.sha256 for item in self.receipts],
            required_unit_closure_hashes=[item.sha256 for item in self.closures],
            human_authorization_receipt_sha256=authority.sha256,
            reviewer_access_policy_sha256=HASH,
            authorized_recipients=["Synthetic human"],
            revealed_current_bundle_mapping={"SIDE_1": "synthetic-source"},
            current_bundle_commitment_openings={"synthetic": "opening"},
            current_bundle_source_link_openings=[{"synthetic": "opening"}],
            unblind_timestamp=STAMP,
            validation_results={"RQ6-V09": "PASS"},
            scope="Current synthetic bundle only",
        )
        fields.update(updates)
        return self.record("bundle_unblind_receipt", **fields)

    def reveal(self) -> None:
        authority = self.authority("bundle_unblind")
        self.unblind = self.unblind_record(authority)
        self.flow.reveal_mapping(self.unblind, authority)

    def compare(self) -> None:
        assert self.unblind is not None
        self.mechanical = self.record(
            "mechanical_comparison",
            unblind_receipt_sha256=self.unblind.sha256,
            primary_anchor_receipt_sha256=PRIMARY,
            observation_count=4,
            class_changed=False,
            flags_changed=False,
            confidences=[0.9] * 4,
            normalized_flag_sets=[[]] * 4,
        )
        self.flow.record_mechanical(self.mechanical, self.authority("mechanical_comparison"))

    def assess(self, *, changed_boundary: bool = False) -> ArtifactSnapshot:
        assert self.unblind is not None
        projections = [
            {
                key: item.data()[key]
                for key in ("primary_disposition", "rationale_propositions", "reviewer_reason")
            }
            for item in self.receipts
        ]
        artifact = self.record(
            "rationale_variation_assessment_artifact",
            unblind_receipt_sha256=self.unblind.sha256,
            primary_anchor_receipt_sha256=PRIMARY,
            completed_unit_receipt_hashes=[item.sha256 for item in self.receipts],
            primary_stored_rationale="Synthetic primary rationale.",
            repeat_rationales=[item.data()["stored_output"]["rationale"] for item in self.cards],
            frozen_primary_semantic_coding={
                "primary_disposition": "ALIGNED",
                "rationale_propositions": [],
                "reviewer_reason": "Synthetic primary human text.",
            },
            frozen_repeat_semantic_coding=projections,
        )
        receipt = self.record(
            "rationale_variation_assessment_receipt",
            rationale_artifact_sha256=artifact.sha256,
            unblind_receipt_sha256=self.unblind.sha256,
            primary_anchor_receipt_sha256=PRIMARY,
            completed_unit_receipt_hashes=[item.sha256 for item in self.receipts],
            reviewer="Synthetic human",
            frozen_proposition_sets=[[]] * 4,
            proposition_set_difference_candidate=False,
            rationale_variation="MATERIAL_BOUNDARY_CHANGE" if changed_boundary else "NONE",
            material_rationale_variation_confirmed=changed_boundary,
            material_boundary_changed=changed_boundary,
            human_variation_note="A synthetic boundary difference is not captured by the proposition set."
            if changed_boundary
            else None,
            reviewer_reason="Exact synthetic assessment.",
            assessment_timestamp=STAMP,
            source_identity_seen_at_assessment=True,
            independent_unit_coding_reopened=False,
            immutability=True,
        )
        self.flow.fix_rationale_assessment(artifact, receipt)
        return receipt

    def finish(self) -> ArtifactSnapshot:
        self.complete_units()
        self.reveal()
        self.compare()
        assessment = self.assess()
        assert self.mechanical is not None and self.unblind is not None
        characterization = self.record(
            "bundle_characterization",
            mechanical_comparison_sha256=self.mechanical.sha256,
            rationale_variation_assessment_receipt_sha256=assessment.sha256,
            stability_disposition="STABLE",
            review_status="REVIEW_COMPLETE",
        )
        self.flow.fix_characterization(characterization)
        closure = self.record(
            "bundle_closure",
            frozen_manifest_position=1,
            applicable_primary_case_id="synthetic-case",
            source_artifact_hashes=[HASH],
            reviewer_unit_ids=list(UNITS),
            reviewer_artifact_hashes=[item.sha256 for item in self.cards],
            alias_commitment_sha256=HASH,
            human_receipt_hashes=[item.sha256 for item in self.receipts],
            unit_closure_hashes=[item.sha256 for item in self.closures],
            unblind_receipt_sha256=self.unblind.sha256,
            revealed_source_mapping={"SIDE_1": "synthetic-source"},
            primary_anchor_hashes=[PRIMARY],
            stored_classifications=["IN_SCOPE"] * 4,
            stored_structured_flag_lists=[[]] * 4,
            stored_confidences=[0.9] * 4,
            normalized_flag_sets=[[]] * 4,
            per_model_primary_repeat_comparison={"class_changed": False, "flags_changed": False},
            confidence_descriptive_values_and_range={"values": [0.9] * 4, "range": 0},
            frozen_rationale_variation_record=assessment.data(),
            review_status="REVIEW_COMPLETE",
            stability_disposition="STABLE",
            timestamps={"closed": STAMP},
            validation_results={"RQ6-V12": "PASS"},
            provenance_hashes=[HASH],
            state="RQ6_BUNDLE_CLOSED",
            rationale_variation_assessment_receipt_sha256=assessment.sha256,
            reviewer_access_policy_sha256=HASH,
            authorized_identity_audience=["Synthetic human"],
            expected_evidence=["primary", "repeat-1", "repeat-2", "repeat-3"],
            available_evidence=["primary", "repeat-1", "repeat-2", "repeat-3"],
            missing_evidence=[],
            unusable_evidence=[],
            evidence_limitation_reasons=[],
            relevant_hashes_or_validation_failures=[],
            stability_not_established_reason=None,
        )
        self.flow.close_bundle(closure)
        return closure

    def insufficient_record(self, **updates: Any) -> ArtifactSnapshot:
        fields = dict(
            frozen_manifest_position=1,
            applicable_primary_case_id="synthetic-case",
            source_artifact_hashes=[],
            reviewer_unit_ids=list(UNITS[: len(self.cards)]),
            reviewer_artifact_hashes=[item.sha256 for item in self.cards],
            alias_commitment_sha256=HASH if self.alias is not None else None,
            human_receipt_hashes=[item.sha256 for item in self.receipts],
            unit_closure_hashes=[item.sha256 for item in self.closures],
            unblind_receipt_sha256=None,
            revealed_source_mapping=None,
            primary_anchor_hashes=[],
            stored_classifications=[],
            stored_structured_flag_lists=[],
            stored_confidences=[],
            normalized_flag_sets=[],
            per_model_primary_repeat_comparison=None,
            confidence_descriptive_values_and_range=None,
            frozen_rationale_variation_record=None,
            review_status="INSUFFICIENT_EVIDENCE_RECORDED",
            stability_disposition="INSUFFICIENT_REPEAT_EVIDENCE",
            timestamps={"closed": STAMP},
            validation_results={"RQ6-V04": "FAIL", "RQ6-V12": "PASS"},
            provenance_hashes=[],
            state="RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE",
            rationale_variation_assessment_receipt_sha256=None,
            reviewer_access_policy_sha256=HASH,
            authorized_identity_audience=["Synthetic custody actor"],
            expected_evidence=["primary", "repeat-1", "repeat-2", "repeat-3"],
            available_evidence=[],
            missing_evidence=["repeat-3"],
            unusable_evidence=[],
            evidence_limitation_reasons=["Required frozen observation unavailable"],
            relevant_hashes_or_validation_failures=[{"RQ6-V04": "FAIL"}],
            stability_not_established_reason="Required coverage unavailable; no values or receipts imputed.",
        )
        fields.update(updates)
        return self.record("bundle_closure", **fields)


def insufficient_after_operations(
    through: str,
) -> tuple[SyntheticBundle, dict[str, Any]]:
    """A late source failure must retain every already performed operation."""
    fixture = SyntheticBundle()
    fixture.complete_units()
    updates: dict[str, Any] = {
        "available_evidence": ["repeat-1", "repeat-2", "repeat-3"],
        "missing_evidence": [],
        "unusable_evidence": ["primary"],
        "stored_classifications": ["IN_SCOPE"] * 3,
        "stored_structured_flag_lists": [[]] * 3,
        "stored_confidences": [0.9] * 3,
        "normalized_flag_sets": [[]] * 3,
        "confidence_descriptive_values_and_range": {"values": [0.9] * 3, "range": 0},
        "provenance_hashes": [],
    }
    if through == "units":
        return fixture, updates
    fixture.reveal()
    assert fixture.unblind is not None
    updates.update(
        unblind_receipt_sha256=fixture.unblind.sha256,
        revealed_source_mapping=fixture.unblind.data()["revealed_current_bundle_mapping"],
        authorized_identity_audience=fixture.unblind.data()["authorized_recipients"],
    )
    if through == "unblind":
        return fixture, updates
    fixture.compare()
    assert fixture.mechanical is not None
    updates["per_model_primary_repeat_comparison"] = fixture.mechanical.data()
    updates["provenance_hashes"].append(fixture.mechanical.sha256)
    if through == "mechanical":
        return fixture, updates
    assert through == "assessment"
    assessment = fixture.assess()
    updates.update(
        rationale_variation_assessment_receipt_sha256=assessment.sha256,
        frozen_rationale_variation_record=assessment.data(),
    )
    updates["provenance_hashes"].append(assessment.sha256)
    return fixture, updates


def test_unit_sequence_preserves_exact_human_receipt_and_previous_closure_link() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    _, _, release = fixture.release(0)
    receipt = fixture.freeze(0, release)
    assert receipt.data()["reviewer_reason"] == "Texto humano exacto. "
    _, _, next_release = fixture.release(1)
    assert next_release.data()["previous_unit_closure_sha256"] == fixture.closures[0].sha256


def test_next_unit_release_before_previous_receipt_and_closure_is_rejected() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    fixture.release(0)
    with pytest.raises(RQ6Error, match="PREMATURE_UNIT_RELEASE"):
        fixture.release(1)


def test_second_unit_cannot_erase_previous_closure_hash() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    _, _, release = fixture.release(0)
    fixture.freeze(0, release)
    with pytest.raises(RQ6Error, match="RELEASE_LINK_MISMATCH"):
        fixture.release(1, previous_unit_closure_sha256=None)


def test_unblind_before_all_scheduled_units_close_is_rejected() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    _, _, release = fixture.release(0)
    fixture.freeze(0, release)
    authority = fixture.authority("bundle_unblind")
    with pytest.raises(RQ6Error, match="PREMATURE_UNBLIND"):
        fixture.flow.reveal_mapping(fixture.unblind_record(authority), authority)


def test_cross_bundle_access_artifact_is_rejected() -> None:
    fixture = SyntheticBundle()
    other = SyntheticBundle("b" * 64)
    other.initialize()
    assert other.alias is not None and other.access is not None
    fixture.custody.bytes.update(other.custody.bytes)
    with pytest.raises(RQ6Error, match="CROSS_BUNDLE_BINDING"):
        fixture.flow.fix_alias_commitment(
            other.alias, other.access, other.authority("alias_mapping_creation")
        )


def test_alias_mapping_cannot_be_reassigned_after_fix() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    assert fixture.alias is not None and fixture.access is not None
    with pytest.raises(RQ6Error, match="REMAPPING_PROHIBITED"):
        fixture.flow.fix_alias_commitment(
            fixture.alias, fixture.access, fixture.authority("alias_mapping_creation")
        )


def test_receipt_byte_mutation_with_retained_hash_is_detected() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    _, _, release = fixture.release(0)
    receipt = fixture.freeze(0, release)
    altered = receipt.data()
    altered["reviewer_reason"] = "Changed after coding"
    corrupt = replace(receipt, payload_bytes=exact_json(altered))
    with pytest.raises(RQ6Error, match="ARTIFACT_HASH_MISMATCH"):
        corrupt.data()
    assert fixture.flow.human_receipt_hashes == (receipt.sha256,)


def test_already_fixed_human_receipt_cannot_be_replaced() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    _, _, release = fixture.release(0)
    receipt = fixture.freeze(0, release)
    altered = receipt.data()
    altered["reviewer_reason"] = "Newly asserted semantics"
    replacement = fixture.custody.make("human_receipt", altered)
    with pytest.raises(RQ6Error, match="HUMAN_RECEIPT_OUT_OF_SEQUENCE"):
        fixture.flow.fix_human_receipt(replacement)


def test_unblind_human_receipt_list_must_match_all_fixed_hashes() -> None:
    fixture = SyntheticBundle()
    fixture.complete_units()
    authority = fixture.authority("bundle_unblind")
    receipt = fixture.unblind_record(
        authority, required_human_receipt_hashes=[f"{number:064x}" for number in range(50, 53)]
    )
    with pytest.raises(RQ6Error, match="UNBLIND_RECEIPT_COVERAGE_MISMATCH"):
        fixture.flow.reveal_mapping(receipt, authority)


def test_unblind_requires_external_approved_operation_authority() -> None:
    fixture = SyntheticBundle()
    fixture.complete_units()
    authority = fixture.authority("bundle_unblind", approved=False)
    with pytest.raises(RQ6Error, match="OPERATION_NOT_AUTHORIZED"):
        fixture.flow.reveal_mapping(fixture.unblind_record(authority), authority)


def test_mechanical_comparison_cannot_precede_local_unblind() -> None:
    fixture = SyntheticBundle()
    fixture.complete_units()
    comparison = fixture.record("mechanical_comparison", unblind_receipt_sha256=HASH)
    with pytest.raises(RQ6Error, match="PREMATURE_MECHANICAL_COMPARISON"):
        fixture.flow.record_mechanical(comparison, fixture.authority("mechanical_comparison"))


def test_rationale_assessment_cannot_precede_mechanical_comparison() -> None:
    fixture = SyntheticBundle()
    fixture.complete_units()
    fixture.reveal()
    artifact = fixture.record("rationale_variation_assessment_artifact")
    receipt = fixture.record("rationale_variation_assessment_receipt")
    with pytest.raises(RQ6Error, match="PREMATURE_RATIONALE_ASSESSMENT"):
        fixture.flow.fix_rationale_assessment(artifact, receipt)


def test_rationale_only_material_boundary_change_is_procedural_deferral() -> None:
    fixture = SyntheticBundle()
    fixture.complete_units()
    frozen_hashes = fixture.flow.human_receipt_hashes
    fixture.reveal()
    fixture.compare()
    assessment = fixture.assess(changed_boundary=True)
    assert fixture.mechanical is not None
    characterization = fixture.record(
        "bundle_characterization",
        mechanical_comparison_sha256=fixture.mechanical.sha256,
        rationale_variation_assessment_receipt_sha256=assessment.sha256,
        stability_disposition=None,
        review_status=DEFERRED,
    )
    fixture.flow.fix_characterization(characterization)
    assert fixture.flow.state == DEFERRED
    assert fixture.flow.human_receipt_hashes == frozen_hashes
    with pytest.raises(RQ6Error, match="PREMATURE_BUNDLE_CLOSURE"):
        fixture.flow.close_bundle(fixture.record("bundle_closure"))


def test_unpersisted_artifact_is_not_accepted_as_verified() -> None:
    fixture = SyntheticBundle()
    authority = fixture.authority("alias_mapping_creation")
    alias = ArtifactSnapshot.build(
        "alias_commitment",
        {
            **authority.data(),
            "mapping_commitment_sha256": HASH,
            "reviewer_access_policy_sha256": HASH,
        },
    )
    access = fixture.record("reviewer_access_provenance")
    with pytest.raises(RQ6Error, match="UNPERSISTED_SYNTHETIC_ARTIFACT"):
        fixture.flow.fix_alias_commitment(alias, access, authority)


def test_callback_cannot_substitute_boolean_pass_for_artifact_validation() -> None:
    fixture = SyntheticBundle()
    workflow = BundleWorkflow(BINDING, UNITS, lambda _: True, PRIMARY)  # type: ignore[arg-type,return-value]
    authority = fixture.authority("alias_mapping_creation")
    with pytest.raises(RQ6Error, match="INVALID_VERIFIER_CONTRACT"):
        workflow.fix_alias_commitment(
            fixture.record("alias_commitment"),
            fixture.record("reviewer_access_provenance"),
            authority,
        )


def test_next_bundle_cannot_open_before_current_terminal_closure() -> None:
    first = SyntheticBundle()
    second = SyntheticBundle("b" * 64)
    cohort = CohortWorkflow((1, 2, 3, 4, 5, 6), first.custody.verify)
    cohort.open_bundle(first.flow, first.authority("bundle_open"))
    with pytest.raises(RQ6Error, match="CURRENT_BUNDLE_NOT_TERMINAL"):
        cohort.open_bundle(second.flow, second.authority("bundle_open"))
    assert second.flow.state == "FROZEN"


def test_aggregate_gate_requires_six_validated_terminal_closures() -> None:
    fixture = SyntheticBundle()
    cohort = CohortWorkflow((1, 2, 3, 4, 5, 6), fixture.custody.verify)
    with pytest.raises(RQ6Error, match="AGGREGATE_BEFORE_SIX_TERMINAL_CLOSURES"):
        cohort.require_aggregate_authority(fixture.authority("aggregate_analysis"))


def test_judge_gate_requires_aggregate_completion_and_human_review() -> None:
    fixture = SyntheticBundle()
    cohort = CohortWorkflow((1, 2, 3, 4, 5, 6), fixture.custody.verify)
    with pytest.raises(RQ6Error, match="JUDGE_BEFORE_AGGREGATE_HUMAN_REVIEW"):
        cohort.require_judge_authority(fixture.authority("judge_selection"))


def test_complete_local_lifecycle_has_immutable_terminal_closure() -> None:
    fixture = SyntheticBundle()
    closure = fixture.finish()
    assert fixture.flow.state == "RQ6_BUNDLE_CLOSED"
    assert fixture.flow.closure is closure
    fixture.flow.verify_frozen()
    with pytest.raises(RQ6Error, match="PREMATURE_UNIT_RELEASE"):
        fixture.release(0)


def test_insufficient_closure_before_mapping_uses_custody_id_without_entropy() -> None:
    fixture = SyntheticBundle(f"RQ6_CUSTODY_FAILURE:{HASH}:1")
    fixture.flow = BundleWorkflow.pre_mapping_failure(
        protocol_id=fixture.binding.protocol_id,
        amendment_id=fixture.binding.amendment_id,
        package_id=fixture.binding.package_id,
        frozen_manifest_sha256=HASH,
        private_manifest_position=1,
        verifier=fixture.custody.verify,
    )
    closure = fixture.insufficient_record()
    fixture.flow.close_insufficient(closure)
    assert fixture.flow.state == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"
    assert fixture.alias is None
    assert fixture.flow.required_unit_ids == ()
    assert fixture.flow.custody_only is True
    assert closure.data()["alias_commitment_sha256"] is None
    assert closure.data()["validation_results"]["RQ6-V04"] == "FAIL"


def test_empty_units_are_forbidden_for_an_initialized_opaque_bundle() -> None:
    fixture = SyntheticBundle()
    with pytest.raises(RQ6Error, match="UNEXPECTED_SCHEDULED_COVERAGE"):
        BundleWorkflow(BINDING, (), fixture.custody.verify, PRIMARY)


def test_custody_failure_id_cannot_be_combined_with_reviewer_units() -> None:
    fixture = SyntheticBundle(f"RQ6_CUSTODY_FAILURE:{HASH}:1")
    with pytest.raises(RQ6Error, match="PRE_MAPPING_FAILURE_HAS_REVIEWER_UNITS"):
        BundleWorkflow(fixture.binding, UNITS, fixture.custody.verify, PRIMARY)


@pytest.mark.parametrize("position", [0, -1, True, 1.0])
def test_pre_mapping_failure_factory_rejects_invalid_manifest_position(position: Any) -> None:
    fixture = SyntheticBundle()
    with pytest.raises(RQ6Error, match="INVALID_PRIVATE_MANIFEST_POSITION"):
        BundleWorkflow.pre_mapping_failure(
            protocol_id=BINDING.protocol_id,
            amendment_id=BINDING.amendment_id,
            package_id=BINDING.package_id,
            frozen_manifest_sha256=HASH,
            private_manifest_position=position,
            verifier=fixture.custody.verify,
        )


def test_custody_failure_cannot_initialize_aliases_or_inspect_release_artifacts() -> None:
    fixture = SyntheticBundle(f"RQ6_CUSTODY_FAILURE:{HASH}:1")
    unexpected = ArtifactSnapshot.build("deliberately_invalid_unopened_artifact", {})
    with pytest.raises(RQ6Error, match="PRE_MAPPING_FAILURE_IS_CUSTODY_ONLY"):
        fixture.flow.fix_alias_commitment(unexpected, unexpected, unexpected)
    with pytest.raises(RQ6Error, match="PRE_MAPPING_FAILURE_IS_CUSTODY_ONLY"):
        fixture.flow.release_unit(unexpected, unexpected, unexpected, unexpected)
    assert fixture.custody.bytes == {}
    assert fixture.flow.state == "FROZEN"


def test_insufficient_closure_does_not_bypass_unblind_gate() -> None:
    fixture = SyntheticBundle()
    fixture.initialize()
    _, _, release = fixture.release(0)
    fixture.freeze(0, release)
    closure = fixture.insufficient_record(available_evidence=["repeat-1"])
    fixture.flow.close_insufficient(closure)
    authority = fixture.authority("bundle_unblind")
    with pytest.raises(RQ6Error, match="PREMATURE_UNBLIND"):
        fixture.flow.reveal_mapping(fixture.unblind_record(authority), authority)


@pytest.mark.parametrize("through", ["units", "unblind", "mechanical", "assessment"])
def test_late_insufficient_closure_preserves_performed_history_and_source_failure(
    through: str,
) -> None:
    fixture, fields = insufficient_after_operations(through)
    fixed_receipts = fixture.flow.human_receipt_hashes
    closure = fixture.insufficient_record(**fields)
    fixture.flow.close_insufficient(closure)
    assert fixture.flow.state == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"
    assert fixture.flow.closure is closure
    assert fixture.flow.human_receipt_hashes == fixed_receipts
    assert closure.data()["validation_results"]["RQ6-V04"] == "FAIL"
    assert closure.data()["confidence_descriptive_values_and_range"] is not None
    fixture.flow.verify_frozen()


@pytest.mark.parametrize(
    ("through", "field", "replacement", "error"),
    [
        ("unblind", "unblind_receipt_sha256", None, "INSUFFICIENT_UNBLIND_HISTORY_CHANGED"),
        ("unblind", "revealed_source_mapping", None, "INSUFFICIENT_UNBLIND_HISTORY_CHANGED"),
        (
            "unblind",
            "authorized_identity_audience",
            ["Different audience"],
            "INSUFFICIENT_UNBLIND_HISTORY_CHANGED",
        ),
        (
            "unblind",
            "revealed_source_mapping",
            {"SIDE_1": "substituted-source"},
            "INSUFFICIENT_UNBLIND_HISTORY_CHANGED",
        ),
        (
            "mechanical",
            "per_model_primary_repeat_comparison",
            None,
            "INSUFFICIENT_MECHANICAL_HISTORY_CHANGED",
        ),
        (
            "mechanical",
            "per_model_primary_repeat_comparison",
            {"class_changed": True},
            "INSUFFICIENT_MECHANICAL_HISTORY_CHANGED",
        ),
        ("mechanical", "provenance_hashes", [], "INSUFFICIENT_MECHANICAL_HISTORY_CHANGED"),
        (
            "assessment",
            "rationale_variation_assessment_receipt_sha256",
            None,
            "INSUFFICIENT_ASSESSMENT_HISTORY_CHANGED",
        ),
        (
            "assessment",
            "frozen_rationale_variation_record",
            None,
            "INSUFFICIENT_ASSESSMENT_HISTORY_CHANGED",
        ),
        (
            "assessment",
            "frozen_rationale_variation_record",
            {"reviewer_reason": "Substituted assessment"},
            "INSUFFICIENT_ASSESSMENT_HISTORY_CHANGED",
        ),
    ],
)
def test_insufficient_closure_cannot_omit_or_substitute_performed_operations(
    through: str, field: str, replacement: Any, error: str
) -> None:
    fixture, fields = insufficient_after_operations(through)
    previous_state = fixture.flow.state
    fields[field] = replacement
    with pytest.raises(RQ6Error, match=error):
        fixture.flow.close_insufficient(fixture.insufficient_record(**fields))
    assert fixture.flow.state == previous_state
    assert fixture.flow.closure is None


def test_insufficient_closure_requires_performed_assessment_in_provenance() -> None:
    fixture, fields = insufficient_after_operations("assessment")
    assert fixture.mechanical is not None
    fields["provenance_hashes"] = [fixture.mechanical.sha256]
    with pytest.raises(RQ6Error, match="INSUFFICIENT_ASSESSMENT_HISTORY_CHANGED"):
        fixture.flow.close_insufficient(fixture.insufficient_record(**fields))
    assert fixture.flow.state == "RATIONALE_ASSESSMENT_FIXED"


@pytest.mark.parametrize(
    ("through", "field", "fabricated", "error"),
    [
        ("units", "unblind_receipt_sha256", HASH, "INSUFFICIENT_PREMATURE_UNBLIND"),
        (
            "unblind",
            "per_model_primary_repeat_comparison",
            {"class_changed": False},
            "INSUFFICIENT_IMPUTED_MECHANICAL",
        ),
        (
            "mechanical",
            "rationale_variation_assessment_receipt_sha256",
            HASH,
            "INSUFFICIENT_IMPUTED_ASSESSMENT",
        ),
        (
            "mechanical",
            "frozen_rationale_variation_record",
            {"reviewer_reason": "Unperformed assessment"},
            "INSUFFICIENT_IMPUTED_ASSESSMENT",
        ),
    ],
)
def test_insufficient_closure_keeps_unperformed_operations_null(
    through: str, field: str, fabricated: Any, error: str
) -> None:
    fixture, fields = insufficient_after_operations(through)
    previous_state = fixture.flow.state
    fields[field] = fabricated
    with pytest.raises(RQ6Error, match=error):
        fixture.flow.close_insufficient(fixture.insufficient_record(**fields))
    assert fixture.flow.state == previous_state
    assert fixture.flow.closure is None


def test_cohort_frozen_order_uses_private_positions_without_future_aliases() -> None:
    first = SyntheticBundle()
    cohort = CohortWorkflow((1, 2, 3, 4, 5, 6), first.custody.verify)
    with pytest.raises(RQ6Error, match="BUNDLE_ORDER_VIOLATION"):
        cohort.open_bundle(first.flow, first.authority("bundle_open", private_manifest_position=2))
    assert first.flow.state == "FROZEN"
