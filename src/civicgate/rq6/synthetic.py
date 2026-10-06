"""Synthetic end-to-end harness. No real package paths, entropy or source discovery.

Run with ``python -m civicgate.rq6.synthetic``. The fixture's authority allowlist,
human decisions, seeds and outputs are explicitly synthetic, never research data.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from civicgate.rq6.artifacts import ArtifactStore, EventLedger, build_artifact
from civicgate.rq6.core import ArtifactSnapshot, decode_exact, exact_json, require, sha256
from civicgate.rq6.crypto import (
    ALGORITHM_VERSION,
    ENCODING_VERSION,
    build_card,
    mapping_commitment,
    opaque_bundle_id,
    opaque_unit_id,
    ordered_aliases,
)
from civicgate.rq6.schemas import SCHEMA_VERSIONS
from civicgate.rq6.stability import Observation, characterize, normalize_flags
from civicgate.rq6.validators import FrozenSource, ValidatorSuite
from civicgate.rq6.workflow import BundleBinding, BundleWorkflow

STAMP = "2026-01-01T00:00:00+00:00"
REVIEWER = "Synthetic test human (fixture only)"
POLICY = sha256(b"synthetic approved audience policy")


class SyntheticScenario:
    """Fully linked fixtures for exercising implementation, not operational authority."""

    def __init__(
        self,
        root: Path,
        *,
        variation: str = "NONE",
        repeat_outputs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.root = root
        self.variation = variation
        self.common = {
            "canonical_encoding_version": ENCODING_VERSION,
            "protocol_id": "CIVICGATE-JUDGE-COMPARISON-V1",
            "amendment_id": "CIVICGATE-RQ6-AMENDMENT-001",
            "package_id": "synthetic-rq6-package",
        }
        self.seed = "11" * 32  # Fixed synthetic bytes, never an entropy call.
        self.slot = {"synthetic_slot": "one"}
        self.selectors = [{"synthetic_slot": "one", "repeat_number": n} for n in range(1, 4)]
        bundle_metadata = {
            **self.common,
            "frozen_manifest_sha256": sha256(b"synthetic manifest"),
            "private_manifest_position": 1,
        }
        bundle = opaque_bundle_id(self.seed, bundle_metadata)
        self.binding = BundleBinding(
            self.common["protocol_id"],
            self.common["amendment_id"],
            self.common["package_id"],
            bundle,
        )
        self.base = asdict(self.binding)
        self.unit_ids = tuple(
            opaque_unit_id(
                self.seed,
                {
                    **self.common,
                    "bundle_review_id": bundle,
                    "exact_source_slot_selector": self.slot,
                    "repeat_number": n,
                },
            )
            for n in range(1, 4)
        )
        primary_output = {
            "classification": "IN_SCOPE",
            "flags": [],
            "confidence": Decimal("0.90"),
            "rationale": "Synthetic public lookup. Exact text. ",
        }
        self.outputs = repeat_outputs or [dict(primary_output) for _ in range(3)]
        require(len(self.outputs) == 3, "SYNTHETIC_FIXTURE_COVERAGE")
        context = {
            "user_request": "Synthetic public awards.  ",
            "proposed_tool": "find_federal_awards",
            "proposed_arguments": {"recipient": "Synthetic entity", "note": "é\n exact "},
        }
        neutral = {"classification": "IN_SCOPE", "flags": []}
        source_raw = exact_json(
            {"context": context, "neutral": neutral, "observations": self.outputs}
        )
        assignment = {
            **bundle_metadata,
            "algorithm_version": ALGORITHM_VERSION,
            "source_slot_selector": self.slot,
        }
        self.mapping_data = {
            **bundle_metadata,
            "algorithm_version": ALGORITHM_VERSION,
            "source_artifact_sha256": sha256(source_raw),
            "exact_source_slot_selectors": [self.slot],
            "complete_required_repeat_selectors": self.selectors,
            "bundle_review_id": bundle,
            "bundle_seed": self.seed,
            "commitment_nonce": "22" * 32,
            "aliases": ordered_aliases(self.seed, [assignment]),
            "source_identity_bindings": {"SIDE_1": "synthetic-source-identity"},
            "reviewer_access_policy_sha256": POLICY,
        }
        mapping = ArtifactSnapshot.build("private_mapping", self.mapping_data)
        self.commitment = mapping_commitment(self.mapping_data)
        self.cards: list[ArtifactSnapshot] = []
        self.sidecars: list[dict[str, Any]] = []
        sources: dict[str, FrozenSource] = {}
        for index, unit in enumerate(self.unit_ids):
            opening = {
                **self.common,
                "bundle_review_id": bundle,
                "reviewer_unit_id": unit,
                "source_artifact_sha256": sha256(source_raw),
                "raw_output_slice_sha256": sha256(exact_json(self.outputs[index])),
                "exact_selector": self.selectors[index],
                "context_sha256": sha256(exact_json(context)),
                "neutral_reference_sha256": sha256(exact_json(neutral)),
                "mapping_commitment_sha256": self.commitment,
                "independent_unit_nonce": f"{index + 51:064x}",
            }
            payload = {
                **self.base,
                "schema_version": SCHEMA_VERSIONS["reviewer_card"],
                "reviewer_unit_id": unit,
                "observation_sequence_within_bundle": index + 1,
                "blind_alias": "SIDE_1",
                **context,
                "frozen_neutral_reference": neutral,
                "stored_output": self.outputs[index],
                "mapping_commitment_sha256": self.commitment,
            }
            card, sidecar = build_card(payload, opening)
            opening = sidecar
            self.sidecars.append(sidecar)
            self.cards.append(build_artifact("reviewer_card", card))
            sources[unit] = FrozenSource(
                source_raw,
                exact_json(self.outputs[index]),
                exact_json(context),
                exact_json(neutral),
                exact_json(self.selectors[index]),
                exact_json(opening),
                ("observations", index),
                ("context",),
                ("neutral",),
            )
        self.primary = ArtifactSnapshot.build(
            "primary_anchor",
            {
                **self.base,
                "stored_output": primary_output,
                "semantic_coding": {
                    "primary_disposition": "ALIGNED",
                    "rationale_propositions": [],
                    "reviewer_reason": "Synthetic primary fixed decision.",
                },
            },
        )
        self.authorities: dict[tuple[str, str | None], ArtifactSnapshot] = {}
        for operation, authority_unit in [
            ("alias_mapping_creation", None),
            ("bundle_unblind", None),
            ("mechanical_comparison", None),
            *[("unit_release", unit) for unit in self.unit_ids],
        ]:
            self.authorities[(operation, authority_unit)] = ArtifactSnapshot.build(
                "operation_authorization",
                {
                    **self.base,
                    "operation": operation,
                    "reviewer_unit_id": authority_unit,
                    "reviewer": REVIEWER,
                    "authorized_recipients": [REVIEWER],
                    "approved": True,
                    "timestamp": STAMP,
                },
            )

        def raw_source_integrity() -> None:
            parsed = decode_exact(source_raw)
            for number, source in enumerate(sources.values()):
                require(
                    source.raw_artifact == source_raw
                    and source.raw_output_slice == exact_json(parsed["observations"][number])
                    and source.context_bytes == exact_json(parsed["context"])
                    and source.neutral_bytes == exact_json(parsed["neutral"])
                    and source.selector_bytes == exact_json(self.selectors[number]),
                    "SYNTHETIC_RAW_SOURCE_CHANGED",
                )

        self.suite = ValidatorSuite(
            self.base,
            mapping=mapping,
            sources=sources,
            primary_anchor=self.primary,
            access_policy_sha256=POLICY,
            approved_authority_hashes=frozenset(
                record.sha256 for record in self.authorities.values()
            ),
            forbidden_literals=("synthetic-source-identity",),
            source_integrity_verifier=raw_source_integrity,
            custody_resolver=lambda digest: self.store.read_raw(digest),
            frozen_selection=tuple(
                (exact_json(self.selectors[index]), ("observations", index)) for index in range(3)
            ),
            primary_case_id="synthetic-primary",
        )
        self.store = ArtifactStore(root / "custody", self.suite)
        self.flow = BundleWorkflow(
            self.binding, self.unit_ids, self.verify_persisted, self.primary.sha256
        )
        self.ledger = EventLedger(root / "ledger", self.base, self.suite)
        self.receipts: list[ArtifactSnapshot] = []
        self.closures: list[ArtifactSnapshot] = []
        self.persist(self.primary)
        for record in self.authorities.values():
            self.persist(record)
        self.form = self.persist(
            build_artifact(
                "empty_human_form",
                {
                    "primary_disposition": None,
                    "rationale_propositions": None,
                    "reviewer_reason": None,
                },
            )
        )

    def verify_persisted(self, artifact: ArtifactSnapshot) -> None:
        require(self.store.get(artifact.sha256) == artifact, "PERSISTED_ARTIFACT_CHANGED")

    def persist(self, artifact: ArtifactSnapshot) -> ArtifactSnapshot:
        persisted = self.store.persist(artifact)
        self.suite.register(persisted)
        return persisted

    def record(self, kind: str, **fields: Any) -> ArtifactSnapshot:
        body = {**self.base, **fields}
        if kind in SCHEMA_VERSIONS:
            body["schema_version"] = SCHEMA_VERSIONS[kind]
            return self.persist(build_artifact(kind, body))
        return self.persist(ArtifactSnapshot.build(kind, body))

    def event(self, event_type: str, artifact: ArtifactSnapshot) -> None:
        events = self.ledger.verify()
        self.ledger.append(
            {
                **self.base,
                "schema_version": SCHEMA_VERSIONS["bundle_event_ledger"],
                "event_sequence": len(events) + 1,
                "event_type": event_type,
                "artifact_sha256": artifact.sha256,
                "previous_event_sha256": events[-1].sha256 if events else None,
                "audience_policy_sha256": POLICY,
                "timestamp": STAMP,
            }
        )

    def initialize(self) -> None:
        self.alias = self.record(
            "alias_commitment",
            mapping_commitment_sha256=self.commitment,
            reviewer_access_policy_sha256=POLICY,
            algorithm_version=ALGORITHM_VERSION,
            commitment_timestamp=STAMP,
        )
        self.access = self.record(
            "reviewer_access_provenance",
            reviewer=REVIEWER,
            access_contract="OPERATIONALLY_MAPPING_BLIND",
            approved_access_policy_sha256=POLICY,
            access_mode="REVIEWER_ATTESTATION",
            reviewer_attestation="Synthetic fixture attestation.",
            enforcement_evidence_hashes=[],
            effective_timestamp=STAMP,
            valid_through_bundle_semantic_freeze=True,
            immutability=True,
        )
        self.flow.fix_alias_commitment(
            self.alias, self.access, self.authorities[("alias_mapping_creation", None)]
        )
        self.event("ALIAS_COMMITMENT_FIXED", self.alias)

    def complete_units(self) -> None:
        self.initialize()
        for index, card in enumerate(self.cards):
            self.persist(card)
            data = card.data()
            release = self.record(
                "unit_release_receipt",
                reviewer_unit_id=self.unit_ids[index],
                reviewer_card_sha256=card.sha256,
                human_form_sha256=self.form.sha256,
                mapping_commitment_sha256=self.commitment,
                source_link_commitment_sha256=data["source_link_commitment_sha256"],
                reviewer_access_provenance_sha256=self.access.sha256,
                previous_unit_closure_sha256=self.closures[-1].sha256 if self.closures else None,
                release_timestamp=STAMP,
                validation_results={"RQ6-V05": "PASS", "RQ6-V06": "PASS"},
            )
            self.flow.release_unit(
                card, self.form, release, self.authorities[("unit_release", self.unit_ids[index])]
            )
            self.event("UNIT_RELEASED", release)
            receipt = self.record(
                "human_receipt",
                reviewer_unit_id=self.unit_ids[index],
                blind_alias="SIDE_1",
                reviewer_card_sha256=card.sha256,
                release_receipt_sha256=release.sha256,
                mapping_commitment_sha256=self.commitment,
                source_link_commitment_sha256=data["source_link_commitment_sha256"],
                reviewer_access_provenance_sha256=self.access.sha256,
                reviewer=REVIEWER,
                primary_disposition="ALIGNED",
                rationale_propositions=[],
                reviewer_reason="Synthetic fixed human text.  ",
                adjudication_timestamp=STAMP,
                adjudication_status="FIXED",
                operationally_mapping_blind_at_coding=True,
                mechanical_stability_seen=False,
                immutability=True,
            )
            self.flow.fix_human_receipt(receipt)
            self.event("HUMAN_RECEIPT_FIXED", receipt)
            self.receipts.append(receipt)
            closure = self.record(
                "unit_closure",
                reviewer_unit_id=self.unit_ids[index],
                reviewer_card_sha256=card.sha256,
                release_receipt_sha256=release.sha256,
                human_receipt_sha256=receipt.sha256,
                mapping_commitment_sha256=self.commitment,
                source_link_commitment_sha256=data["source_link_commitment_sha256"],
                closure_timestamp=STAMP,
                validation_results={"RQ6-V08": "PASS"},
                semantic_coding_frozen=True,
                unblinded=False,
                state="SEMANTICALLY_CLOSED_BLINDED",
            )
            self.flow.verify_unit_closure(closure)
            self.event("UNIT_CLOSURE_VERIFIED", closure)
            self.closures.append(closure)

    def finish(self) -> ArtifactSnapshot:
        authority = self.authorities[("bundle_unblind", None)]
        unblind = self.record(
            "bundle_unblind_receipt",
            alias_commitment_sha256=self.commitment,
            required_human_receipt_hashes=list(self.flow.human_receipt_hashes),
            required_unit_closure_hashes=list(self.flow.unit_closure_hashes),
            human_authorization_receipt_sha256=authority.sha256,
            reviewer_access_policy_sha256=POLICY,
            authorized_recipients=[REVIEWER],
            revealed_current_bundle_mapping=self.mapping_data["source_identity_bindings"],
            current_bundle_commitment_openings=self.mapping_data,
            current_bundle_source_link_openings={
                unit: decode_exact(source.source_link_opening_bytes)
                for unit, source in self.suite.sources.items()
            },
            unblind_timestamp=STAMP,
            validation_results={"RQ6-V09": "PASS"},
            scope="Current synthetic bundle only",
        )
        self.flow.reveal_mapping(unblind, authority)
        self.event("BUNDLE_MAPPING_REVEALED", unblind)
        outputs = [self.primary.data()["stored_output"], *self.outputs]
        normalized = [list(normalize_flags(output["flags"])) for output in outputs]
        mechanical = self.record(
            "mechanical_comparison",
            unblind_receipt_sha256=unblind.sha256,
            primary_anchor_receipt_sha256=self.primary.sha256,
            observation_count=4,
            class_changed=len({item["classification"] for item in outputs}) > 1,
            flags_changed=len({tuple(item) for item in normalized}) > 1,
            confidences=[item["confidence"] for item in outputs],
            normalized_flag_sets=normalized,
        )
        self.flow.record_mechanical(mechanical, self.authorities[("mechanical_comparison", None)])
        self.event("MECHANICAL_COMPARISON_RECORDED", mechanical)
        primary = self.primary.data()
        projections = [
            {
                key: record.data()[key]
                for key in ("primary_disposition", "rationale_propositions", "reviewer_reason")
            }
            for record in self.receipts
        ]
        assessment_input = self.record(
            "rationale_variation_assessment_artifact",
            unblind_receipt_sha256=unblind.sha256,
            primary_anchor_receipt_sha256=self.primary.sha256,
            completed_unit_receipt_hashes=list(self.flow.human_receipt_hashes),
            primary_stored_rationale=primary["stored_output"]["rationale"],
            repeat_rationales=[item["rationale"] for item in self.outputs],
            frozen_primary_semantic_coding=primary["semantic_coding"],
            frozen_repeat_semantic_coding=projections,
        )
        boundary = {
            "NONE": False,
            "MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE": False,
            "MATERIAL_BOUNDARY_CHANGE": True,
            "UNRESOLVED": None,
        }[self.variation]
        assessment = self.record(
            "rationale_variation_assessment_receipt",
            rationale_artifact_sha256=assessment_input.sha256,
            unblind_receipt_sha256=unblind.sha256,
            primary_anchor_receipt_sha256=self.primary.sha256,
            completed_unit_receipt_hashes=list(self.flow.human_receipt_hashes),
            reviewer=REVIEWER,
            frozen_proposition_sets=[[]] * 4,
            proposition_set_difference_candidate=False,
            rationale_variation=self.variation,
            material_rationale_variation_confirmed=None
            if boundary is None
            else self.variation != "NONE",
            material_boundary_changed=boundary,
            human_variation_note="Synthetic human confirms variation."
            if self.variation != "NONE"
            else None,
            reviewer_reason="Synthetic assessment, no recoding.",
            assessment_timestamp=STAMP,
            source_identity_seen_at_assessment=True,
            independent_unit_coding_reopened=False,
            immutability=True,
        )
        self.flow.fix_rationale_assessment(assessment_input, assessment)
        self.event("RATIONALE_ASSESSMENT_FIXED", assessment)
        observations = [
            Observation(**{key: output[key] for key in ("classification", "flags", "confidence")})
            for output in outputs
        ]
        result = characterize(
            observations[0],
            observations[1:],
            expected_repeat_count=3,
            rationale_variation=self.variation,
            material_boundary_changed=boundary,
        )
        characterization = self.record(
            "bundle_characterization",
            mechanical_comparison_sha256=mechanical.sha256,
            rationale_variation_assessment_receipt_sha256=assessment.sha256,
            stability_disposition=result["stability_disposition"],
            review_status=result["review_status"],
        )
        self.flow.fix_characterization(characterization)
        if result["stability_disposition"] is None:
            return characterization  # Procedural deferral is not a terminal seventh enum.
        self.event("BUNDLE_CHARACTERIZATION_FIXED", characterization)
        closure = self.record(
            "bundle_closure",
            frozen_manifest_position=1,
            applicable_primary_case_id="synthetic-primary",
            source_artifact_hashes=[self.mapping_data["source_artifact_sha256"]],
            reviewer_unit_ids=list(self.unit_ids),
            reviewer_artifact_hashes=[card.sha256 for card in self.cards],
            alias_commitment_sha256=self.commitment,
            human_receipt_hashes=list(self.flow.human_receipt_hashes),
            unit_closure_hashes=list(self.flow.unit_closure_hashes),
            unblind_receipt_sha256=unblind.sha256,
            revealed_source_mapping=self.mapping_data["source_identity_bindings"],
            primary_anchor_hashes=[self.primary.sha256],
            stored_classifications=[item["classification"] for item in outputs],
            stored_structured_flag_lists=[item["flags"] for item in outputs],
            stored_confidences=[item["confidence"] for item in outputs],
            normalized_flag_sets=normalized,
            per_model_primary_repeat_comparison=mechanical.data(),
            confidence_descriptive_values_and_range={
                "interpretation": "DESCRIPTIVE_ONLY",
                "values": result["confidence_values"],
                "range": result["confidence_range"],
            },
            frozen_rationale_variation_record=assessment.data(),
            review_status=result["review_status"],
            stability_disposition=result["stability_disposition"],
            timestamps={"closure": STAMP},
            validation_results={"RQ6-V12": "PASS"},
            provenance_hashes=[assessment.sha256, mechanical.sha256],
            state="RQ6_BUNDLE_CLOSED",
            rationale_variation_assessment_receipt_sha256=assessment.sha256,
            reviewer_access_policy_sha256=POLICY,
            authorized_identity_audience=[REVIEWER],
            expected_evidence=["primary", "repeat1", "repeat2", "repeat3"],
            available_evidence=["primary", "repeat1", "repeat2", "repeat3"],
            missing_evidence=[],
            unusable_evidence=[],
            evidence_limitation_reasons=[],
            relevant_hashes_or_validation_failures=[],
            stability_not_established_reason=None,
        )
        self.flow.close_bundle(closure)
        self.event("BUNDLE_CLOSURE_VERIFIED", closure)
        return closure


def run_synthetic(root: Path) -> dict[str, Any]:
    scenario = SyntheticScenario(root)
    scenario.complete_units()
    closure = scenario.finish()
    return {
        "synthetic_only": True,
        "terminal_state": scenario.flow.state,
        "closure_sha256": closure.sha256,
        "event_count": len(scenario.ledger.verify()),
        "real_repeat_files_read": 0,
        "real_model_calls": 0,
        "real_gateway_executions": 0,
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="civicgate-rq6-synthetic-") as directory:
        print(json.dumps(run_synthetic(Path(directory)), indent=2))
