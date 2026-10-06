"""Synthetic linkage, persistence and closure adversaries; never real repeat data."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from civicgate.rq6.artifacts import EventLedger
from civicgate.rq6.core import ArtifactSnapshot, RQ6Error, decode_exact, exact_json
from civicgate.rq6.schemas import SCHEMA_VERSIONS
from civicgate.rq6.stability import normalize_flags
from civicgate.rq6.synthetic import POLICY, REVIEWER, STAMP, SyntheticScenario, run_synthetic


def output(
    *,
    classification: str = "IN_SCOPE",
    flags: list[str] | None = None,
    confidence: Any = Decimal("0.90"),
) -> dict[str, Any]:
    return {
        "classification": classification,
        "flags": flags or [],
        "confidence": confidence,
        "rationale": "Synthetic exact rationale.  ",
    }


@pytest.mark.parametrize(
    ("classification", "flags", "variation", "expected"),
    [
        ("IN_SCOPE", [], "NONE", "STABLE"),
        (
            "IN_SCOPE",
            [],
            "MATERIAL_VARIATION_WITHOUT_BOUNDARY_CHANGE",
            "STABLE_WITH_RATIONALE_VARIATION",
        ),
        ("AMBIGUOUS", [], "NONE", "CLASSIFICATION_VARIABLE"),
        ("IN_SCOPE", ["PROVENANCE_RISK"], "NONE", "STRUCTURED_SIGNAL_VARIABLE"),
        ("AMBIGUOUS", ["PROVENANCE_RISK"], "NONE", "MULTI_AXIS_VARIABLE"),
    ],
)
def test_complete_linked_synthetic_dispositions(
    tmp_path: Path, classification: str, flags: list[str], variation: str, expected: str
) -> None:
    scenario = SyntheticScenario(
        tmp_path,
        variation=variation,
        repeat_outputs=[output(classification=classification, flags=flags), output(), output()],
    )
    scenario.complete_units()
    before = tuple(record.payload_bytes for record in scenario.receipts)
    closure = scenario.finish()
    assert closure.data()["stability_disposition"] == expected
    assert scenario.flow.state == "RQ6_BUNDLE_CLOSED"
    assert tuple(record.payload_bytes for record in scenario.receipts) == before
    assert len(scenario.ledger.verify()) == 15


@pytest.mark.parametrize("variation", ["MATERIAL_BOUNDARY_CHANGE", "UNRESOLVED"])
def test_human_rationale_deferral_cannot_close(tmp_path: Path, variation: str) -> None:
    scenario = SyntheticScenario(tmp_path, variation=variation)
    scenario.complete_units()
    characterization = scenario.finish()
    assert characterization.data()["stability_disposition"] is None
    assert scenario.flow.state == "RQ6_REVIEW_DEFERRED_PENDING_HUMAN_RESOLUTION"
    assert scenario.flow.closure is None


def test_confidence_and_raw_sentinel_are_representation_only(tmp_path: Path) -> None:
    source_number = decode_exact(b"9e-1")
    scenario = SyntheticScenario(
        tmp_path,
        repeat_outputs=[
            output(confidence=source_number),
            output(flags=["NONE"], confidence=Decimal("0.700")),
            output(confidence=1),
        ],
    )
    scenario.complete_units()
    closure = scenario.finish().data()
    assert closure["stability_disposition"] == "STABLE"
    assert closure["normalized_flag_sets"] == [[], [], [], []]
    assert closure["stored_structured_flag_lists"][2] == ["NONE"]
    assert b'"confidence":9e-1' in scenario.cards[0].payload_bytes
    assert b'"confidence":0.700' in scenario.cards[1].payload_bytes


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("stored_classifications", ["OUT_OF_SCOPE"] * 4),
        ("stored_structured_flag_lists", [["NONE"]] * 4),
        ("stored_confidences", [Decimal("0.1")] * 4),
        ("source_artifact_hashes", ["f" * 64]),
        ("primary_anchor_hashes", ["f" * 64]),
        ("per_model_primary_repeat_comparison", {"fabricated": True}),
        ("confidence_descriptive_values_and_range", {"fabricated": True}),
        ("revealed_source_mapping", {"SIDE_1": "counterfeit"}),
        ("authorized_identity_audience", ["counterfeit reviewer"]),
        ("reviewer_access_policy_sha256", "f" * 64),
        ("applicable_primary_case_id", "another-primary"),
    ],
)
def test_v12_rejects_self_consistent_but_fabricated_closure(
    tmp_path: Path, field: str, replacement: Any
) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.complete_units()
    closure = scenario.finish().data()
    closure[field] = replacement
    counterfeit = ArtifactSnapshot.build("bundle_closure", closure)
    with pytest.raises(RQ6Error):
        scenario.suite(counterfeit)


def test_v11_detects_physical_receipt_mutation(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.complete_units()
    digest = scenario.receipts[0].sha256
    path = tmp_path / "custody" / "objects" / f"{digest}.json"
    path.write_bytes(path.read_bytes() + b"\n")  # Synthetic adversary, never historical evidence.
    with pytest.raises(RQ6Error, match="PERSISTED_ARTIFACT_MUTATION"):
        scenario.suite.v11()


def test_v07_rejects_recode_after_independent_closure(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.complete_units()
    data = scenario.receipts[0].data()
    data["primary_disposition"] = "UNDERCALL"
    data["reviewer_reason"] = "Counterfeit later recoding."
    with pytest.raises(RQ6Error, match="CLOSED_UNIT_RECODING"):
        scenario.suite(ArtifactSnapshot.build("human_receipt", data))


def test_authority_self_assertion_cannot_grant_release(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    data = next(iter(scenario.authorities.values())).data()
    data["reviewer"] = "unapproved operator"
    with pytest.raises(RQ6Error, match="UNAPPROVED_AUTHORITY"):
        scenario.suite(ArtifactSnapshot.build("operation_authorization", data))


def test_v04_public_alias_record_rejects_private_metadata(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.initialize()
    data = scenario.alias.data()
    data["bundle_seed"] = scenario.seed
    with pytest.raises(RQ6Error, match="HELPER_UNDECLARED"):
        scenario.suite(ArtifactSnapshot.build("alias_commitment", data))


def test_v05_literal_identity_is_withheld_without_redaction(tmp_path: Path) -> None:
    outputs = [output(), output(), output()]
    outputs[0]["rationale"] = "Literal identity gpt-6-luna in synthetic source."
    scenario = SyntheticScenario(tmp_path, repeat_outputs=outputs)
    with pytest.raises(RQ6Error, match="LITERAL_IDENTITY_LEAK"):
        scenario.complete_units()
    assert scenario.flow.state == "ALIAS_COMMITMENT_FIXED"
    assert scenario.cards[0].data()["stored_output"]["rationale"] == outputs[0]["rationale"]


def test_v05_slice_not_from_source_is_rejected(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    unit = scenario.unit_ids[0]
    source = scenario.suite.sources[unit]
    scenario.suite.sources[unit] = replace(
        source, raw_output_slice=exact_json(output(classification="AMBIGUOUS"))
    )
    with pytest.raises(RQ6Error, match="RAW_SLICE_NOT_FROM_SOURCE"):
        scenario.suite(scenario.cards[0])


@pytest.mark.parametrize("stage", ["primary", "alias", "card"])
def test_source_integrity_verifier_false_is_not_success(tmp_path: Path, stage: str) -> None:
    scenario = SyntheticScenario(tmp_path)
    if stage == "alias":
        scenario.initialize()

    def rejected() -> Any:
        return False

    scenario.suite.source_integrity_verifier = rejected
    artifact = (
        scenario.primary
        if stage == "primary"
        else scenario.alias
        if stage == "alias"
        else scenario.cards[0]
    )
    with pytest.raises(RQ6Error, match="INVALID_VERIFIER_CONTRACT"):
        scenario.suite(artifact)


def test_v04_selector_pointer_bijection_rejects_duplicate_output(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    unit = scenario.unit_ids[1]
    scenario.suite.sources[unit] = replace(
        scenario.suite.sources[unit], output_pointer=("observations", 0)
    )
    with pytest.raises(RQ6Error, match="FROZEN_SELECTOR_POINTER"):
        scenario.initialize()


@pytest.mark.parametrize("truncate", [True, False])
def test_pinned_ledger_rejects_truncation_and_rewrite(tmp_path: Path, truncate: bool) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.complete_units()
    events = scenario.ledger.verify()
    last = tmp_path / "ledger" / f"{len(events):06d}.json"
    if truncate:
        last.unlink()
    else:
        data = events[-1].data()
        data["timestamp"] = "2026-01-02T00:00:00+00:00"
        last.write_bytes(exact_json(data))
    with pytest.raises(RQ6Error, match="LEDGER_TRUNCATION_OR_REWRITE"):
        scenario.ledger.verify()


def test_ledger_reopening_requires_trusted_tip(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.initialize()
    events = scenario.ledger.verify()
    reopened = EventLedger(
        tmp_path / "ledger",
        scenario.base,
        scenario.suite,
        expected_count=len(events),
        expected_tip=events[-1].sha256,
    )
    assert reopened.verify() == events
    with pytest.raises(RQ6Error, match="LEDGER_TRUNCATION_OR_REWRITE"):
        EventLedger(tmp_path / "ledger", scenario.base, scenario.suite).verify()


def test_synthetic_harness_has_no_real_calls_or_repeat_reads(tmp_path: Path) -> None:
    report = run_synthetic(tmp_path)
    assert report["synthetic_only"] is True
    assert report["event_count"] == 15
    assert (
        report["real_repeat_files_read"]
        == report["real_model_calls"]
        == report["real_gateway_executions"]
        == 0
    )


def test_v03_enforcement_cannot_be_claimed_without_evidence(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.initialize()
    data = scenario.access.data()
    data.update(
        access_mode="ENFORCED_REVIEWER_RELEASE_ONLY",
        reviewer_attestation=None,
        enforcement_evidence_hashes=["f" * 64],
    )
    with pytest.raises(RQ6Error, match="ENFORCEMENT_NOT_ESTABLISHED"):
        scenario.suite(ArtifactSnapshot.build("reviewer_access_provenance", data))


def test_v09_unblind_policy_cannot_change_after_semantic_freeze(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.complete_units()
    closure = scenario.finish().data()
    data = scenario.suite.get(closure["unblind_receipt_sha256"]).data()
    data["reviewer_access_policy_sha256"] = "f" * 64
    with pytest.raises(RQ6Error, match="ACCESS_POLICY_MISMATCH"):
        scenario.suite(ArtifactSnapshot.build("bundle_unblind_receipt", data))


def test_v10_helper_boolean_cannot_be_numeric(tmp_path: Path) -> None:
    scenario = SyntheticScenario(tmp_path)
    scenario.complete_units()
    closure = scenario.finish().data()
    data = closure["per_model_primary_repeat_comparison"]
    data["flags_changed"] = 0
    with pytest.raises(RQ6Error, match="HELPER_BOOLEAN_TYPE"):
        scenario.suite(ArtifactSnapshot.build("mechanical_comparison", data))


def mapped_insufficient_payload(
    scenario: SyntheticScenario, *, after_unblind: bool, performed_stage: str | None = None
) -> dict[str, Any]:
    """Pin an original synthetic failure; never invent absent independent reviews."""
    unblind: ArtifactSnapshot | None = None
    mechanical: ArtifactSnapshot | None = None
    assessment: ArtifactSnapshot | None = None
    if after_unblind:
        scenario.complete_units()
        authority = scenario.authorities[("bundle_unblind", None)]
        unblind = scenario.record(
            "bundle_unblind_receipt",
            alias_commitment_sha256=scenario.commitment,
            required_human_receipt_hashes=list(scenario.flow.human_receipt_hashes),
            required_unit_closure_hashes=list(scenario.flow.unit_closure_hashes),
            human_authorization_receipt_sha256=authority.sha256,
            reviewer_access_policy_sha256=POLICY,
            authorized_recipients=[REVIEWER],
            revealed_current_bundle_mapping=scenario.mapping_data["source_identity_bindings"],
            current_bundle_commitment_openings=scenario.mapping_data,
            current_bundle_source_link_openings={
                unit: decode_exact(source.source_link_opening_bytes)
                for unit, source in scenario.suite.sources.items()
            },
            unblind_timestamp=STAMP,
            validation_results={"RQ6-V09": "PASS"},
            scope="Current synthetic bundle only",
        )
        scenario.flow.reveal_mapping(unblind, authority)
        scenario.event("BUNDLE_MAPPING_REVEALED", unblind)
        if performed_stage is not None:
            mechanical, assessment = performed_synthetic_review_stages(
                scenario, unblind, include_assessment=performed_stage == "assessment"
            )
        outputs = [card.data()["stored_output"] for card in scenario.cards]
        available = ["repeat1", "repeat2", "repeat3"]
        missing: list[str] = []
        unusable = ["primary"]
        cards = scenario.cards
        primary_hashes: list[str] = []
    else:
        scenario.initialize()
        outputs = [scenario.primary.data()["stored_output"]]
        available = ["primary"]
        missing = ["repeat1", "repeat2", "repeat3"]
        unusable = []
        cards = []
        primary_hashes = [scenario.primary.sha256]
    failure_fields: dict[str, Any] = {
        "expected_evidence": ["primary", "repeat1", "repeat2", "repeat3"],
        "available_evidence": available,
        "missing_evidence": missing,
        "unusable_evidence": unusable,
        "evidence_limitation_reasons": ["Original synthetic evidence validation failure."],
        "relevant_hashes_or_validation_failures": [
            {"control": "RQ6-V10", "result": "FAIL", "synthetic_only": True}
        ],
        "stability_not_established_reason": "Synthetic required evidence was not usable.",
        "validation_results": {"RQ6-V10": "FAIL"},
    }
    limitation = ArtifactSnapshot.build("evidence_limitation", {**scenario.base, **failure_fields})
    scenario.suite.evidence_limitation = limitation
    scenario.persist(limitation)
    return {
        **scenario.base,
        "schema_version": SCHEMA_VERSIONS["bundle_closure"],
        "frozen_manifest_position": 1,
        "applicable_primary_case_id": "synthetic-primary",
        "source_artifact_hashes": [scenario.mapping_data["source_artifact_sha256"]],
        "reviewer_unit_ids": [card.data()["reviewer_unit_id"] for card in cards],
        "reviewer_artifact_hashes": [card.sha256 for card in cards],
        "alias_commitment_sha256": scenario.commitment,
        "human_receipt_hashes": list(scenario.flow.human_receipt_hashes),
        "unit_closure_hashes": list(scenario.flow.unit_closure_hashes),
        "unblind_receipt_sha256": unblind.sha256 if unblind is not None else None,
        "revealed_source_mapping": (
            scenario.mapping_data["source_identity_bindings"] if unblind is not None else None
        ),
        "primary_anchor_hashes": primary_hashes,
        "stored_classifications": [item["classification"] for item in outputs],
        "stored_structured_flag_lists": [item["flags"] for item in outputs],
        "stored_confidences": [item["confidence"] for item in outputs],
        "normalized_flag_sets": [list(normalize_flags(item["flags"])) for item in outputs],
        "per_model_primary_repeat_comparison": (
            mechanical.data() if mechanical is not None else None
        ),
        "confidence_descriptive_values_and_range": None,
        "frozen_rationale_variation_record": assessment.data() if assessment is not None else None,
        "rationale_variation_assessment_receipt_sha256": (
            assessment.sha256 if assessment is not None else None
        ),
        "review_status": "INSUFFICIENT_REPEAT_EVIDENCE",
        "stability_disposition": "INSUFFICIENT_REPEAT_EVIDENCE",
        "timestamps": {"closure": STAMP},
        "provenance_hashes": [
            limitation.sha256,
            *([mechanical.sha256] if mechanical is not None else []),
            *([assessment.sha256] if assessment is not None else []),
        ],
        "state": "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE",
        "reviewer_access_policy_sha256": POLICY,
        "authorized_identity_audience": [REVIEWER],
        **failure_fields,
        "validation_results": {**failure_fields["validation_results"], "RQ6-V12": "PASS"},
    }


def performed_synthetic_review_stages(
    scenario: SyntheticScenario,
    unblind: ArtifactSnapshot,
    *,
    include_assessment: bool,
) -> tuple[ArtifactSnapshot, ArtifactSnapshot | None]:
    """Perform genuine fixture stages before recording a later evidence limitation."""
    primary = scenario.primary.data()
    outputs = [primary["stored_output"], *scenario.outputs]
    normalized = [list(normalize_flags(item["flags"])) for item in outputs]
    mechanical = scenario.record(
        "mechanical_comparison",
        unblind_receipt_sha256=unblind.sha256,
        primary_anchor_receipt_sha256=scenario.primary.sha256,
        observation_count=len(outputs),
        class_changed=len({item["classification"] for item in outputs}) > 1,
        flags_changed=len({tuple(item) for item in normalized}) > 1,
        confidences=[item["confidence"] for item in outputs],
        normalized_flag_sets=normalized,
    )
    scenario.flow.record_mechanical(
        mechanical, scenario.authorities[("mechanical_comparison", None)]
    )
    scenario.event("MECHANICAL_COMPARISON_RECORDED", mechanical)
    if not include_assessment:
        return mechanical, None
    assessment_input = scenario.record(
        "rationale_variation_assessment_artifact",
        unblind_receipt_sha256=unblind.sha256,
        primary_anchor_receipt_sha256=scenario.primary.sha256,
        completed_unit_receipt_hashes=list(scenario.flow.human_receipt_hashes),
        primary_stored_rationale=primary["stored_output"]["rationale"],
        repeat_rationales=[item["rationale"] for item in scenario.outputs],
        frozen_primary_semantic_coding=primary["semantic_coding"],
        frozen_repeat_semantic_coding=[
            {
                key: receipt.data()[key]
                for key in ("primary_disposition", "rationale_propositions", "reviewer_reason")
            }
            for receipt in scenario.receipts
        ],
    )
    assessment = scenario.record(
        "rationale_variation_assessment_receipt",
        rationale_artifact_sha256=assessment_input.sha256,
        unblind_receipt_sha256=unblind.sha256,
        primary_anchor_receipt_sha256=scenario.primary.sha256,
        completed_unit_receipt_hashes=list(scenario.flow.human_receipt_hashes),
        reviewer=REVIEWER,
        frozen_proposition_sets=[[]] * len(outputs),
        proposition_set_difference_candidate=False,
        rationale_variation="NONE",
        material_rationale_variation_confirmed=False,
        material_boundary_changed=False,
        human_variation_note=None,
        reviewer_reason="Synthetic frozen assessment before a late evidence failure.",
        assessment_timestamp=STAMP,
        source_identity_seen_at_assessment=True,
        independent_unit_coding_reopened=False,
        immutability=True,
    )
    scenario.flow.fix_rationale_assessment(assessment_input, assessment)
    scenario.event("RATIONALE_ASSESSMENT_FIXED", assessment)
    return mechanical, assessment


@pytest.mark.parametrize("after_unblind", [False, True])
def test_mapped_insufficient_closure_preserves_original_failure(
    tmp_path: Path, after_unblind: bool
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(scenario, after_unblind=after_unblind)
    closure = scenario.persist(ArtifactSnapshot.build("bundle_closure", payload))
    scenario.flow.close_insufficient(closure)
    assert scenario.flow.state == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"
    assert closure.data()["validation_results"] == {"RQ6-V10": "FAIL", "RQ6-V12": "PASS"}
    assert len(closure.data()["human_receipt_hashes"]) == (3 if after_unblind else 0)
    assert (closure.data()["unblind_receipt_sha256"] is not None) is after_unblind
    assert closure.data()["per_model_primary_repeat_comparison"] is None


@pytest.mark.parametrize("after_unblind", [False, True])
@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("reviewer_access_policy_sha256", "f" * 64),
        ("frozen_manifest_position", 2),
        ("alias_commitment_sha256", "f" * 64),
        ("revealed_source_mapping", {"SIDE_1": "counterfeit"}),
        ("unblind_receipt_sha256", "f" * 64),
        ("per_model_primary_repeat_comparison", {"fabricated": True}),
        ("confidence_descriptive_values_and_range", {"fabricated": True}),
        ("frozen_rationale_variation_record", {"fabricated": True}),
        ("rationale_variation_assessment_receipt_sha256", "f" * 64),
    ],
)
def test_v12_insufficient_closure_rejects_forged_links_and_optional_records(
    tmp_path: Path, after_unblind: bool, field: str, replacement: Any
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(scenario, after_unblind=after_unblind)
    scenario.suite(ArtifactSnapshot.build("bundle_closure", payload))
    payload[field] = replacement
    with pytest.raises(RQ6Error):
        scenario.suite(ArtifactSnapshot.build("bundle_closure", payload))


@pytest.mark.parametrize("after_unblind", [False, True])
def test_v12_insufficient_closure_cannot_annul_pinned_failure(
    tmp_path: Path, after_unblind: bool
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(scenario, after_unblind=after_unblind)
    payload["validation_results"] = {"RQ6-V10": "PASS", "RQ6-V12": "PASS"}
    with pytest.raises(RQ6Error, match="FAILURE_CONTROL_REWRITTEN"):
        scenario.suite(ArtifactSnapshot.build("bundle_closure", payload))


def test_v12_insufficient_post_unblind_audience_matches_authorized_reveal(
    tmp_path: Path,
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(scenario, after_unblind=True)
    payload["authorized_identity_audience"] = ["counterfeit reviewer"]
    with pytest.raises(RQ6Error, match="PARTIAL_UNBLIND_CHANGED"):
        scenario.suite(ArtifactSnapshot.build("bundle_closure", payload))


@pytest.mark.parametrize("after_unblind", [False, True])
def test_mapped_insufficient_confidence_remains_exact_custody_descriptives(
    tmp_path: Path, after_unblind: bool
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(scenario, after_unblind=after_unblind)
    values = payload["stored_confidences"]
    payload["confidence_descriptive_values_and_range"] = {
        "interpretation": "DESCRIPTIVE_ONLY",
        "values": values,
        "range": [min(values), max(values)],
    }
    closure = scenario.persist(ArtifactSnapshot.build("bundle_closure", payload))
    scenario.flow.close_insufficient(closure)
    assert closure.data()["stability_disposition"] == "INSUFFICIENT_REPEAT_EVIDENCE"
    assert closure.data()["validation_results"]["RQ6-V10"] == "FAIL"


def test_late_primary_failure_preserves_all_performed_stages_in_insufficient_closure(
    tmp_path: Path,
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(
        scenario, after_unblind=True, performed_stage="assessment"
    )
    closure = scenario.persist(ArtifactSnapshot.build("bundle_closure", payload))
    scenario.flow.close_insufficient(closure)
    assert closure.data()["validation_results"] == {"RQ6-V10": "FAIL", "RQ6-V12": "PASS"}
    assert closure.data()["unusable_evidence"] == ["primary"]
    assert closure.data()["unblind_receipt_sha256"] is not None
    assert closure.data()["per_model_primary_repeat_comparison"] is not None
    assert closure.data()["rationale_variation_assessment_receipt_sha256"] is not None
    assert closure.data()["frozen_rationale_variation_record"] is not None
    assert scenario.flow.state == "RQ6_BUNDLE_CLOSED_INSUFFICIENT_REPEAT_EVIDENCE"


@pytest.mark.parametrize(
    ("performed_stage", "omitted_fields"),
    [
        (None, ("unblind_receipt_sha256", "revealed_source_mapping")),
        ("mechanical", ("per_model_primary_repeat_comparison",)),
        (
            "assessment",
            ("rationale_variation_assessment_receipt_sha256", "frozen_rationale_variation_record"),
        ),
        (
            "assessment",
            (
                "unblind_receipt_sha256",
                "revealed_source_mapping",
                "per_model_primary_repeat_comparison",
                "rationale_variation_assessment_receipt_sha256",
                "frozen_rationale_variation_record",
            ),
        ),
    ],
    ids=["unblind", "comparison", "assessment", "all-performed-stages"],
)
def test_v12_insufficient_closure_cannot_omit_performed_operations(
    tmp_path: Path, performed_stage: str | None, omitted_fields: tuple[str, ...]
) -> None:
    scenario = SyntheticScenario(tmp_path)
    payload = mapped_insufficient_payload(
        scenario, after_unblind=True, performed_stage=performed_stage
    )
    scenario.suite(ArtifactSnapshot.build("bundle_closure", payload))
    for field in omitted_fields:
        payload[field] = None
    with pytest.raises(RQ6Error):
        scenario.suite(ArtifactSnapshot.build("bundle_closure", payload))
