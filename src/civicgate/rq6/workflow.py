"""Artifact-driven RQ6 sequencing. Construction and imports perform no I/O.

The mandatory verifier supplies persisted-custody, cryptographic and externally
approved authority checks. These gates are additional to, not substitutes for,
the local linkage and sequencing checks here. No transition accepts a caller's
``verified=True`` declaration.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from civicgate.rq6.core import ArtifactSnapshot, exact_json, require
from civicgate.rq6.schemas import FIELDS, validate_artifact

Verifier = Callable[[ArtifactSnapshot], None]
DEFERRED = "RQ6_REVIEW_DEFERRED_PENDING_HUMAN_RESOLUTION"
TERMINAL_STATES = frozenset({"RQ6_BUNDLE_CLOSED", "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"})
_FAILURE_IDENTIFIER = re.compile(r"RQ6_CUSTODY_FAILURE:([0-9a-f]{64}):([1-9][0-9]*)\Z")


@dataclass(frozen=True)
class BundleBinding:
    protocol_id: str
    amendment_id: str
    package_id: str
    bundle_review_id: str

    def check(self, payload: dict[str, Any]) -> None:
        for name in ("protocol_id", "amendment_id", "package_id", "bundle_review_id"):
            require(payload.get(name) == getattr(self, name), "CROSS_BUNDLE_BINDING")


class BundleWorkflow:
    """One frozen bundle, with one explicitly authorized unit released at a time."""

    def __init__(
        self,
        binding: BundleBinding,
        required_unit_ids: tuple[str, ...],
        verifier: Verifier,
        primary_anchor_receipt_sha256: str,
    ) -> None:
        require(type(required_unit_ids) is tuple, "INVALID_UNIT_ID_SEQUENCE")
        require(type(binding.bundle_review_id) is str, "INVALID_BUNDLE_ID")
        failure = _FAILURE_IDENTIFIER.fullmatch(binding.bundle_review_id)
        if failure is not None:
            require(not required_unit_ids, "PRE_MAPPING_FAILURE_HAS_REVIEWER_UNITS")
        else:
            require(len(required_unit_ids) == 3, "UNEXPECTED_SCHEDULED_COVERAGE")
            require(len(set(required_unit_ids)) == 3, "DUPLICATE_UNIT_ID")
            require(
                all(type(value) is str and value for value in required_unit_ids), "INVALID_UNIT_ID"
            )
        self.binding = binding
        self._pre_mapping_failure = failure is not None
        self.required_unit_ids = tuple(required_unit_ids)
        self.primary_anchor_receipt_sha256 = primary_anchor_receipt_sha256
        self._verify = verifier
        self._state = "FROZEN"
        self._fixed: dict[str, ArtifactSnapshot] = {}
        self._fixed_hashes: dict[str, str] = {}
        self._cards: list[ArtifactSnapshot] = []
        self._releases: list[ArtifactSnapshot] = []
        self._human_receipts: list[ArtifactSnapshot] = []
        self._unit_closures: list[ArtifactSnapshot] = []
        self._assessment_history: list[ArtifactSnapshot] = []
        self._alias: ArtifactSnapshot | None = None
        self._access: ArtifactSnapshot | None = None
        self._unblind: ArtifactSnapshot | None = None
        self._mechanical: ArtifactSnapshot | None = None
        self._assessment_input: ArtifactSnapshot | None = None
        self._assessment: ArtifactSnapshot | None = None
        self._characterization: ArtifactSnapshot | None = None
        self._closure: ArtifactSnapshot | None = None

    @classmethod
    def pre_mapping_failure(
        cls,
        *,
        protocol_id: str,
        amendment_id: str,
        package_id: str,
        frozen_manifest_sha256: str,
        private_manifest_position: int,
        verifier: Verifier,
        primary_anchor_receipt_sha256: str = "",
    ) -> BundleWorkflow:
        """Create custody-only failure state, requiring no seed, alias or unit IDs.

        An absent primary receipt remains absent; the optional empty anchor here
        is never used for an unblind or a mechanical comparison in this branch.
        Evidence-limitation validation still runs when the closure is supplied.
        """
        require(
            type(frozen_manifest_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", frozen_manifest_sha256) is not None,
            "INVALID_FROZEN_MANIFEST_HASH",
        )
        require(
            type(private_manifest_position) is int and private_manifest_position > 0,
            "INVALID_PRIVATE_MANIFEST_POSITION",
        )
        binding = BundleBinding(
            protocol_id,
            amendment_id,
            package_id,
            f"RQ6_CUSTODY_FAILURE:{frozen_manifest_sha256}:{private_manifest_position}",
        )
        return cls(binding, (), verifier, primary_anchor_receipt_sha256)

    @property
    def custody_only(self) -> bool:
        return self._pre_mapping_failure

    @property
    def state(self) -> str:
        return self._state

    @property
    def closure(self) -> ArtifactSnapshot | None:
        return self._closure

    @property
    def human_receipt_hashes(self) -> tuple[str, ...]:
        return tuple(item.sha256 for item in self._human_receipts)

    @property
    def unit_closure_hashes(self) -> tuple[str, ...]:
        return tuple(item.sha256 for item in self._unit_closures)

    def verify_frozen(self) -> None:
        """Recheck original immutable bytes, including before/after local reveal."""
        for key, snapshot in self._fixed.items():
            require(snapshot.sha256 == self._fixed_hashes[key], "FROZEN_ARTIFACT_CHANGED")
            snapshot.data()
            require(self._verify(snapshot) is None, "INVALID_VERIFIER_CONTRACT")

    def _validate(self, snapshot: ArtifactSnapshot, kind: str) -> dict[str, Any]:
        require(snapshot.kind == kind, "WRONG_ARTIFACT_KIND")
        payload = snapshot.data()
        if kind in FIELDS:
            validate_artifact(kind, payload)
        if kind != "empty_human_form":
            self.binding.check(payload)
        require(self._verify(snapshot) is None, "INVALID_VERIFIER_CONTRACT")
        return payload

    def _remember(self, key: str, snapshot: ArtifactSnapshot) -> None:
        require(key not in self._fixed, "IMMUTABLE_ARTIFACT_ALREADY_FIXED")
        self._fixed[key] = snapshot
        self._fixed_hashes[key] = snapshot.sha256

    def _authorize(
        self, authority: ArtifactSnapshot, operation: str, unit_id: str | None = None
    ) -> dict[str, Any]:
        payload = self._validate(authority, "operation_authorization")
        require(payload.get("approved") is True, "OPERATION_NOT_AUTHORIZED")
        require(payload.get("operation") == operation, "WRONG_OPERATION_AUTHORITY")
        require(payload.get("reviewer_unit_id") == unit_id, "WRONG_UNIT_AUTHORITY")
        require(bool(payload.get("reviewer")), "AUTHORITY_REVIEWER_MISSING")
        return payload

    def _check_current_unit(self, payload: dict[str, Any], index: int) -> None:
        require(index < len(self.required_unit_ids), "NO_UNRELEASED_UNIT")
        require(
            payload.get("reviewer_unit_id") == self.required_unit_ids[index], "UNIT_ORDER_VIOLATION"
        )

    def _mapping_commitment(self) -> str:
        require(self._alias is not None, "ALIAS_COMMITMENT_NOT_FIXED")
        assert self._alias is not None
        return str(self._alias.data()["mapping_commitment_sha256"])

    def fix_alias_commitment(
        self,
        commitment: ArtifactSnapshot,
        access_provenance: ArtifactSnapshot,
        authority: ArtifactSnapshot,
    ) -> None:
        require(not self._pre_mapping_failure, "PRE_MAPPING_FAILURE_IS_CUSTODY_ONLY")
        require(self._state == "FROZEN", "REMAPPING_PROHIBITED")
        self.verify_frozen()
        alias = self._validate(commitment, "alias_commitment")
        access = self._validate(access_provenance, "reviewer_access_provenance")
        authorization = self._authorize(authority, "alias_mapping_creation")
        require(
            alias.get("reviewer_access_policy_sha256") == access["approved_access_policy_sha256"],
            "ACCESS_POLICY_LINK_MISMATCH",
        )
        require(authorization["reviewer"] == access["reviewer"], "REVIEWER_ACCESS_MISMATCH")
        self._remember("alias", commitment)
        self._remember("access", access_provenance)
        self._remember("alias_authority", authority)
        self._alias, self._access = commitment, access_provenance
        self._state = "ALIAS_COMMITMENT_FIXED"

    def release_unit(
        self,
        card: ArtifactSnapshot,
        empty_form: ArtifactSnapshot,
        release_receipt: ArtifactSnapshot,
        authority: ArtifactSnapshot,
    ) -> None:
        require(not self._pre_mapping_failure, "PRE_MAPPING_FAILURE_IS_CUSTODY_ONLY")
        require(
            self._state in {"ALIAS_COMMITMENT_FIXED", "UNIT_CLOSURE_VERIFIED"},
            "PREMATURE_UNIT_RELEASE",
        )
        self.verify_frozen()
        index = len(self._cards)
        evidence = self._validate(card, "reviewer_card")
        self._check_current_unit(evidence, index)
        form = self._validate(empty_form, "empty_human_form")
        release = self._validate(release_receipt, "unit_release_receipt")
        self._check_current_unit(release, index)
        authorization = self._authorize(authority, "unit_release", self.required_unit_ids[index])
        assert self._access is not None
        require(
            authorization["reviewer"] == self._access.data()["reviewer"], "REVIEWER_ACCESS_MISMATCH"
        )
        require(
            evidence["observation_sequence_within_bundle"] == index + 1,
            "OBSERVATION_ORDER_VIOLATION",
        )
        require(evidence["blind_alias"] == "SIDE_1", "UNEXPECTED_SOURCE_TOPOLOGY")
        require(all(value in (None, "", []) for value in form.values()), "PREPOPULATED_HUMAN_FORM")
        require(
            evidence["mapping_commitment_sha256"] == self._mapping_commitment(),
            "REMAPPING_PROHIBITED",
        )
        links = {
            "reviewer_card_sha256": card.sha256,
            "human_form_sha256": empty_form.sha256,
            "mapping_commitment_sha256": evidence["mapping_commitment_sha256"],
            "source_link_commitment_sha256": evidence["source_link_commitment_sha256"],
            "reviewer_access_provenance_sha256": self._access.sha256,
            "previous_unit_closure_sha256": self._unit_closures[-1].sha256 if index else None,
        }
        require(
            all(release.get(key) == value for key, value in links.items()), "RELEASE_LINK_MISMATCH"
        )
        require(len(self._unit_closures) == index, "PREVIOUS_UNIT_NOT_CLOSED")
        self._remember(f"card:{index}", card)
        self._remember(f"form:{index}", empty_form)
        self._remember(f"release:{index}", release_receipt)
        self._remember(f"release_authority:{index}", authority)
        self._cards.append(card)
        self._releases.append(release_receipt)
        self._state = "UNIT_RELEASED"

    def fix_human_receipt(self, receipt: ArtifactSnapshot) -> None:
        require(self._state == "UNIT_RELEASED", "HUMAN_RECEIPT_OUT_OF_SEQUENCE")
        self.verify_frozen()
        index = len(self._human_receipts)
        human = self._validate(receipt, "human_receipt")
        self._check_current_unit(human, index)
        evidence = self._cards[index].data()
        assert self._access is not None
        links = {
            "reviewer_card_sha256": self._cards[index].sha256,
            "release_receipt_sha256": self._releases[index].sha256,
            "mapping_commitment_sha256": self._mapping_commitment(),
            "source_link_commitment_sha256": evidence["source_link_commitment_sha256"],
            "reviewer_access_provenance_sha256": self._access.sha256,
            "blind_alias": evidence["blind_alias"],
            "reviewer": self._access.data()["reviewer"],
        }
        require(
            all(human.get(key) == value for key, value in links.items()),
            "HUMAN_RECEIPT_LINK_MISMATCH",
        )
        require(human["operationally_mapping_blind_at_coding"] is True, "CODING_NOT_MAPPING_BLIND")
        require(human["mechanical_stability_seen"] is False, "MECHANICAL_HINDSIGHT")
        self._remember(f"human:{index}", receipt)
        self._human_receipts.append(receipt)
        self._state = "HUMAN_RECEIPT_FIXED"

    def verify_unit_closure(self, closure: ArtifactSnapshot) -> None:
        require(self._state == "HUMAN_RECEIPT_FIXED", "UNIT_CLOSURE_OUT_OF_SEQUENCE")
        self.verify_frozen()
        index = len(self._unit_closures)
        payload = self._validate(closure, "unit_closure")
        self._check_current_unit(payload, index)
        evidence = self._cards[index].data()
        links = {
            "reviewer_card_sha256": self._cards[index].sha256,
            "release_receipt_sha256": self._releases[index].sha256,
            "human_receipt_sha256": self._human_receipts[index].sha256,
            "mapping_commitment_sha256": self._mapping_commitment(),
            "source_link_commitment_sha256": evidence["source_link_commitment_sha256"],
        }
        require(
            all(payload.get(key) == value for key, value in links.items()),
            "UNIT_CLOSURE_LINK_MISMATCH",
        )
        require(
            payload["semantic_coding_frozen"] is True and payload["unblinded"] is False,
            "INVALID_UNIT_FREEZE",
        )
        require(payload["state"] == "SEMANTICALLY_CLOSED_BLINDED", "INVALID_UNIT_STATE")
        self._remember(f"unit_closure:{index}", closure)
        self._unit_closures.append(closure)
        self._state = "UNIT_CLOSURE_VERIFIED"

    def reveal_mapping(self, receipt: ArtifactSnapshot, authority: ArtifactSnapshot) -> None:
        require(self._state == "UNIT_CLOSURE_VERIFIED", "PREMATURE_UNBLIND")
        require(len(self._unit_closures) == len(self.required_unit_ids), "PREMATURE_UNBLIND")
        self.verify_frozen()
        unblind = self._validate(receipt, "bundle_unblind_receipt")
        authorization = self._authorize(authority, "bundle_unblind")
        assert self._alias is not None
        require(
            unblind["alias_commitment_sha256"] == self._mapping_commitment(),
            "UNBLIND_COMMITMENT_MISMATCH",
        )
        require(
            unblind["required_human_receipt_hashes"] == list(self.human_receipt_hashes),
            "UNBLIND_RECEIPT_COVERAGE_MISMATCH",
        )
        require(
            unblind["required_unit_closure_hashes"] == list(self.unit_closure_hashes),
            "UNBLIND_CLOSURE_COVERAGE_MISMATCH",
        )
        require(
            unblind["human_authorization_receipt_sha256"] == authority.sha256,
            "UNBLIND_AUTHORITY_LINK_MISMATCH",
        )
        require(
            unblind["authorized_recipients"] == authorization.get("authorized_recipients"),
            "UNBLIND_AUDIENCE_MISMATCH",
        )
        require(bool(unblind["authorized_recipients"]), "EMPTY_UNBLIND_AUDIENCE")
        require(
            unblind["reviewer_access_policy_sha256"]
            == self._alias.data()["reviewer_access_policy_sha256"],
            "UNBLIND_ACCESS_POLICY_MISMATCH",
        )
        self._remember("unblind", receipt)
        self._remember("unblind_authority", authority)
        self._unblind = receipt
        self._state = "BUNDLE_MAPPING_REVEALED"
        self.verify_frozen()

    def record_mechanical(self, comparison: ArtifactSnapshot, authority: ArtifactSnapshot) -> None:
        require(self._state == "BUNDLE_MAPPING_REVEALED", "PREMATURE_MECHANICAL_COMPARISON")
        self.verify_frozen()
        payload = self._validate(comparison, "mechanical_comparison")
        self._authorize(authority, "mechanical_comparison")
        assert self._unblind is not None
        require(
            payload.get("unblind_receipt_sha256") == self._unblind.sha256,
            "MECHANICAL_UNBLIND_LINK_MISMATCH",
        )
        require(
            payload.get("primary_anchor_receipt_sha256") == self.primary_anchor_receipt_sha256,
            "WRONG_PRIMARY_ANCHOR",
        )
        require(payload.get("observation_count") == 4, "INCOMPLETE_MECHANICAL_COVERAGE")
        self._remember("mechanical", comparison)
        self._remember("mechanical_authority", authority)
        self._mechanical = comparison
        self._state = "MECHANICAL_COMPARISON_RECORDED"

    def fix_rationale_assessment(
        self, artifact: ArtifactSnapshot, receipt: ArtifactSnapshot
    ) -> None:
        require(self._state == "MECHANICAL_COMPARISON_RECORDED", "PREMATURE_RATIONALE_ASSESSMENT")
        self.verify_frozen()
        source = self._validate(artifact, "rationale_variation_assessment_artifact")
        human = self._validate(receipt, "rationale_variation_assessment_receipt")
        assert self._unblind is not None
        for payload in (source, human):
            require(
                payload["unblind_receipt_sha256"] == self._unblind.sha256,
                "ASSESSMENT_UNBLIND_LINK_MISMATCH",
            )
            require(
                payload["primary_anchor_receipt_sha256"] == self.primary_anchor_receipt_sha256,
                "WRONG_PRIMARY_ANCHOR",
            )
            require(
                payload["completed_unit_receipt_hashes"] == list(self.human_receipt_hashes),
                "ASSESSMENT_RECEIPT_COVERAGE_MISMATCH",
            )
        require(
            human["rationale_artifact_sha256"] == artifact.sha256, "ASSESSMENT_INPUT_LINK_MISMATCH"
        )
        require(
            source["repeat_rationales"]
            == [item.data()["stored_output"]["rationale"] for item in self._cards],
            "FROZEN_RATIONALE_CHANGED",
        )
        projections = [
            {
                key: item.data()[key]
                for key in ("primary_disposition", "rationale_propositions", "reviewer_reason")
            }
            for item in self._human_receipts
        ]
        require(
            source["frozen_repeat_semantic_coding"] == projections, "FROZEN_SEMANTIC_CODING_CHANGED"
        )
        self._remember("assessment_input", artifact)
        self._remember("assessment", receipt)
        self._assessment_history.append(receipt)
        self._assessment_input, self._assessment = artifact, receipt
        self._state = "RATIONALE_ASSESSMENT_FIXED"

    def fix_characterization(self, characterization: ArtifactSnapshot) -> None:
        require(self._state == "RATIONALE_ASSESSMENT_FIXED", "CHARACTERIZATION_OUT_OF_SEQUENCE")
        self.verify_frozen()
        payload = self._validate(characterization, "bundle_characterization")
        assert self._mechanical is not None and self._assessment is not None
        require(
            payload.get("mechanical_comparison_sha256") == self._mechanical.sha256,
            "CHARACTERIZATION_MECHANICAL_LINK_MISMATCH",
        )
        require(
            payload.get("rationale_variation_assessment_receipt_sha256") == self._assessment.sha256,
            "CHARACTERIZATION_ASSESSMENT_LINK_MISMATCH",
        )
        assessment = self._assessment.data()
        mechanical = self._mechanical.data()
        stable_axes = (
            mechanical.get("class_changed") is False and mechanical.get("flags_changed") is False
        )
        deferred = assessment["rationale_variation"] == "UNRESOLVED" or (
            stable_axes and assessment["material_boundary_changed"] is True
        )
        if deferred:
            require(
                payload.get("review_status") == DEFERRED
                and payload.get("stability_disposition") is None,
                "DEFERRED_NOT_TERMINAL",
            )
        else:
            require(
                payload.get("review_status") != DEFERRED
                and payload.get("stability_disposition") is not None,
                "MISSING_FINAL_CHARACTERIZATION",
            )
        self._remember("characterization", characterization)
        self._characterization = characterization
        self._state = DEFERRED if deferred else "BUNDLE_CHARACTERIZATION_FIXED"

    def close_bundle(self, closure: ArtifactSnapshot) -> None:
        require(self._state == "BUNDLE_CHARACTERIZATION_FIXED", "PREMATURE_BUNDLE_CLOSURE")
        self.verify_frozen()
        payload = self._validate(closure, "bundle_closure")
        assert (
            self._characterization is not None
            and self._unblind is not None
            and self._assessment is not None
        )
        require(payload["state"] == "RQ6_BUNDLE_CLOSED", "WRONG_TERMINAL_BRANCH")
        require(
            payload["stability_disposition"]
            == self._characterization.data()["stability_disposition"],
            "CLOSURE_CHARACTERIZATION_MISMATCH",
        )
        require(
            payload["review_status"] == self._characterization.data()["review_status"],
            "CLOSURE_REVIEW_STATUS_MISMATCH",
        )
        require(
            payload["unblind_receipt_sha256"] == self._unblind.sha256,
            "CLOSURE_UNBLIND_LINK_MISMATCH",
        )
        require(
            payload["rationale_variation_assessment_receipt_sha256"] == self._assessment.sha256,
            "CLOSURE_ASSESSMENT_LINK_MISMATCH",
        )
        self._close_common(closure, payload, complete=True)

    def close_insufficient(self, closure: ArtifactSnapshot) -> None:
        require(
            self._state not in TERMINAL_STATES and self._state != DEFERRED,
            "INVALID_INSUFFICIENT_TRANSITION",
        )
        self.verify_frozen()
        payload = self._validate(closure, "bundle_closure")
        require(
            payload["state"] == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE",
            "WRONG_TERMINAL_BRANCH",
        )
        require(
            payload["stability_disposition"] == "INSUFFICIENT_REPEAT_EVIDENCE",
            "INVALID_INSUFFICIENT_DISPOSITION",
        )
        require(
            bool(payload["missing_evidence"] or payload["unusable_evidence"]),
            "UNDOCUMENTED_INSUFFICIENCY",
        )
        require(
            bool(
                payload["evidence_limitation_reasons"]
                and payload["stability_not_established_reason"]
            ),
            "UNDOCUMENTED_INSUFFICIENCY",
        )
        if self._unblind is None:
            require(
                payload["unblind_receipt_sha256"] is None
                and payload["revealed_source_mapping"] is None,
                "INSUFFICIENT_PREMATURE_UNBLIND",
            )
        else:
            require(
                payload["unblind_receipt_sha256"] == self._unblind.sha256
                and payload["revealed_source_mapping"]
                == self._unblind.data()["revealed_current_bundle_mapping"]
                and payload["authorized_identity_audience"]
                == self._unblind.data()["authorized_recipients"],
                "INSUFFICIENT_UNBLIND_HISTORY_CHANGED",
            )
        if self._mechanical is None:
            require(
                payload["per_model_primary_repeat_comparison"] is None,
                "INSUFFICIENT_IMPUTED_MECHANICAL",
            )
        else:
            require(
                exact_json(payload["per_model_primary_repeat_comparison"])
                == self._mechanical.payload_bytes
                and self._mechanical.sha256 in payload["provenance_hashes"],
                "INSUFFICIENT_MECHANICAL_HISTORY_CHANGED",
            )
        if self._assessment is None:
            require(
                payload["rationale_variation_assessment_receipt_sha256"] is None
                and payload["frozen_rationale_variation_record"] is None,
                "INSUFFICIENT_IMPUTED_ASSESSMENT",
            )
        else:
            require(
                payload["rationale_variation_assessment_receipt_sha256"] == self._assessment.sha256
                and exact_json(payload["frozen_rationale_variation_record"])
                == self._assessment.payload_bytes
                and self._assessment.sha256 in payload["provenance_hashes"],
                "INSUFFICIENT_ASSESSMENT_HISTORY_CHANGED",
            )
        self._close_common(closure, payload, complete=False)

    def _close_common(
        self, closure: ArtifactSnapshot, payload: dict[str, Any], *, complete: bool
    ) -> None:
        require(
            payload["reviewer_unit_ids"] == list(self.required_unit_ids[: len(self._cards)]),
            "CLOSURE_UNIT_COVERAGE_MISMATCH",
        )
        require(
            payload["human_receipt_hashes"] == list(self.human_receipt_hashes),
            "CLOSURE_RECEIPT_COVERAGE_MISMATCH",
        )
        require(
            payload["unit_closure_hashes"] == list(self.unit_closure_hashes),
            "CLOSURE_UNIT_CLOSURE_MISMATCH",
        )
        require(
            payload["alias_commitment_sha256"]
            == (self._mapping_commitment() if self._alias else None),
            "CLOSURE_ALIAS_LINK_MISMATCH",
        )
        if complete:
            require(
                len(self._unit_closures) == len(self.required_unit_ids),
                "INCOMPLETE_TERMINAL_COVERAGE",
            )
        self._remember("bundle_closure", closure)
        self._closure = closure
        self._state = str(payload["state"])
        self.verify_frozen()


class CohortWorkflow:
    """Prerequisite gates only; no aggregate denominator or selection policy."""

    def __init__(self, bundle_order: tuple[int, ...], verifier: Verifier) -> None:
        require(
            bundle_order == (1, 2, 3, 4, 5, 6)
            and all(type(position) is int for position in bundle_order),
            "INVALID_FROZEN_BUNDLE_COHORT",
        )
        self._order = tuple(bundle_order)
        self._verify = verifier
        self._current: BundleWorkflow | None = None
        self._closed: list[ArtifactSnapshot] = []
        self._aggregate: ArtifactSnapshot | None = None
        self._aggregate_review: ArtifactSnapshot | None = None

    def _authority(self, authority: ArtifactSnapshot, operation: str) -> dict[str, Any]:
        require(authority.kind == "operation_authorization", "WRONG_ARTIFACT_KIND")
        payload = authority.data()
        require(self._verify(authority) is None, "INVALID_VERIFIER_CONTRACT")
        require(
            payload.get("approved") is True and payload.get("operation") == operation,
            "OPERATION_NOT_AUTHORIZED",
        )
        return payload

    def open_bundle(self, workflow: BundleWorkflow, authority: ArtifactSnapshot) -> None:
        require(self._current is None, "CURRENT_BUNDLE_NOT_TERMINAL")
        require(len(self._closed) < len(self._order), "NO_UNOPENED_BUNDLE")
        require(workflow.state == "FROZEN", "BUNDLE_ALREADY_INITIALIZED")
        payload = self._authority(authority, "bundle_open")
        workflow.binding.check(payload)
        require(
            type(payload.get("private_manifest_position")) is int
            and payload.get("private_manifest_position") == self._order[len(self._closed)],
            "BUNDLE_ORDER_VIOLATION",
        )
        for closure in self._closed:
            closure.data()
            require(self._verify(closure) is None, "INVALID_VERIFIER_CONTRACT")
        self._current = workflow

    def record_terminal(self, workflow: BundleWorkflow) -> None:
        require(workflow is self._current, "CROSS_BUNDLE_CLOSURE")
        require(
            workflow.state in TERMINAL_STATES and workflow.closure is not None,
            "CURRENT_BUNDLE_NOT_TERMINAL",
        )
        workflow.verify_frozen()
        assert workflow.closure is not None
        require(self._verify(workflow.closure) is None, "INVALID_VERIFIER_CONTRACT")
        require(
            workflow.closure.data()["frozen_manifest_position"] == self._order[len(self._closed)],
            "BUNDLE_ORDER_VIOLATION",
        )
        self._closed.append(workflow.closure)
        self._current = None

    def require_aggregate_authority(self, authority: ArtifactSnapshot) -> None:
        require(
            len(self._closed) == 6 and self._current is None,
            "AGGREGATE_BEFORE_SIX_TERMINAL_CLOSURES",
        )
        self._authority(authority, "aggregate_analysis")
        for closure in self._closed:
            closure.data()
            require(self._verify(closure) is None, "INVALID_VERIFIER_CONTRACT")

    def record_aggregate_completion(
        self, artifact: ArtifactSnapshot, authority: ArtifactSnapshot
    ) -> None:
        self.require_aggregate_authority(authority)
        require(self._aggregate is None, "AGGREGATE_ALREADY_FIXED")
        require(artifact.kind == "aggregate_completion", "WRONG_ARTIFACT_KIND")
        payload = artifact.data()
        require(self._verify(artifact) is None, "INVALID_VERIFIER_CONTRACT")
        require(
            payload.get("terminal_bundle_closure_hashes") == [item.sha256 for item in self._closed],
            "AGGREGATE_CLOSURE_LINK_MISMATCH",
        )
        self._aggregate = artifact

    def record_aggregate_review(self, receipt: ArtifactSnapshot) -> None:
        require(self._aggregate is not None, "REVIEW_BEFORE_AGGREGATE_COMPLETION")
        require(self._aggregate_review is None, "AGGREGATE_REVIEW_ALREADY_FIXED")
        require(receipt.kind == "aggregate_human_review", "WRONG_ARTIFACT_KIND")
        payload = receipt.data()
        require(self._verify(receipt) is None, "INVALID_VERIFIER_CONTRACT")
        assert self._aggregate is not None
        require(
            payload.get("aggregate_artifact_sha256") == self._aggregate.sha256,
            "AGGREGATE_REVIEW_LINK_MISMATCH",
        )
        require(
            payload.get("approved") is True and bool(payload.get("reviewer")),
            "AGGREGATE_REVIEW_NOT_APPROVED",
        )
        self._aggregate_review = receipt

    def require_judge_authority(self, authority: ArtifactSnapshot) -> None:
        require(
            self._aggregate is not None and self._aggregate_review is not None,
            "JUDGE_BEFORE_AGGREGATE_HUMAN_REVIEW",
        )
        assert self._aggregate is not None and self._aggregate_review is not None
        self._aggregate.data()
        self._aggregate_review.data()
        require(self._verify(self._aggregate) is None, "INVALID_VERIFIER_CONTRACT")
        require(self._verify(self._aggregate_review) is None, "INVALID_VERIFIER_CONTRACT")
        self._authority(authority, "judge_selection")
