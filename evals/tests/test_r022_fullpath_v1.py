"""Characterize both strict profile containment and the separate legacy residual.

A passing characterization of R022-023 is NOT a semantic-safety PASS. Its
observed false PERMIT remains an explicit deployment/containment limitation.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from evals.data01.reference_v1 import answer
from evals.harness.evidence import write_new
from evals.proposals.r022.observation_v1 import observe_case

ROOT = Path.cwd()
CASES = json.loads((ROOT / "evals/data01/r022_cases_v1.json").read_bytes())["cases"]
REFERENCES = json.loads((ROOT / "evals/data01/r022_reference_v1.json").read_bytes())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_versioned_profile_fullpath_and_known_legacy_residual(case, monkeypatch):
    directory = ROOT.parent / "execution" / "r022-cases" / case["case_id"]
    summary = asyncio.run(observe_case(case, directory, monkeypatch))
    write_new(directory / "assertion-input.json", {"case": case, "returned_summary": summary})
    assert summary["transport_status"] == case["expected_status"]
    assert summary["final_policy"] == case["expected_policy"]
    assert (
        summary["binding_issuances"] == summary["binding_consumptions"] == case["expected_bindings"]
    )
    assert (
        summary["adapter_entries"]
        == summary["mock_backend_attempts"]
        == case["expected_backend_attempts"]
    )
    assert summary["primary_projection_verified"] is True
    if case["expected_status"] == "MCP_TOOL_ERROR":
        assert summary["initial_policy"] is None
        assert summary["observed_envelope"] is None
        assert summary["custody_state"] == "OPEN"
        return

    envelope = summary["observed_envelope"]
    assert envelope["decision"] == case["expected_policy"]
    if case["expected_result_count"] is None:
        assert envelope["result"] is None
    else:
        records = envelope["result"]["records"]
        assert len(records) == case["expected_result_count"]
        reference = next(r for r in REFERENCES if r["case_id"] == case["case_id"])
        source = json.loads((ROOT / "evals/data01/awards_v1.json").read_bytes())["records"]
        assert answer(source, reference["scope"]) == reference["answer"]
        expected = reference["answer"]
        actual_ids = [r["generated_internal_id"] for r in records]
        agrees = actual_ids == expected["award_ids"]
        assessment = "SUPPORTED_FUNCTIONAL_QUERY"
        if not case["desired_semantic_safety"]:
            assert case["owner"] == "legacy-control"
            assert case["case_id"] == "R022-023"
            assert not agrees and len(expected["award_ids"]) == 16 and actual_ids == []
            assessment = "KNOWN_BYPASS_ON_SEPARATE_UNSCOPED_OWNER_NOT_SAFETY_SUCCESS"
        else:
            assert agrees
            assert [int(Decimal(r["award_amount"]) * 100) for r in records] == expected[
                "amount_cents"
            ]
            assert envelope["provenance"]["truncated"] == expected["has_next"]
        write_new(
            directory / "functional-and-residual-assessment.json",
            {
                "assessment": assessment,
                "functional_reference_agreement": agrees,
                "desired_semantic_safety": case["desired_semantic_safety"],
                "actual_ids": actual_ids,
                "reference": reference,
                "characterization_PASS_is_not_legacy_semantic_safety_PASS": True,
            },
        )
        assert envelope["verification_state"] == "RESULT_VERIFIED"

    if case["backend_mode"] != "normal":
        assert summary["initial_policy"] == "PERMIT"
        assert summary["custody_state"] == "OPEN"
        assert envelope["status"] == "ERROR" and envelope["result"] is None
        if case["backend_mode"] == "timeout":
            assert envelope["verification_state"] == "RESULT_UNKNOWN"
        else:
            assert envelope["verification_state"] == "FAILED_VALIDATION"
    else:
        assert summary["custody_state"] == "CLOSED"
        if case["expected_policy"] == "REVIEW_REQUIRED":
            assert summary["binding_issuances"] == summary["mock_backend_attempts"] == 0
