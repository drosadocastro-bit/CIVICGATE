"""Fail-closed completion and copy-only patch application controls."""

import json

import pytest

from evals.proposals.r021.preview_v1 import apply_to_preview, derive_policy
from scripts.run_r021_review_v2 import ROOT, observation_inventory


def observations(name):
    return [
        {"case_id": r["case_id"]}
        for r in json.loads((ROOT / "evals/data01" / name).read_bytes())["cases"]
    ]


def counts(passed=90, skipped=0):
    return dict(PASS=passed, FAIL=0, ERROR=0, SKIP=skipped)


def test_exact_baseline_and_proposal_inventories():
    base = observations("benchmark_v1.json")
    proposed = observations("agency_scope_r021_cases_v1.json")
    assert observation_inventory("baseline", base, [], counts())["verified"]
    assert observation_inventory("proposal", [], proposed, counts(24))["verified"]


def test_missing_observations_cannot_be_success():
    assert not observation_inventory("baseline", [], [], counts())["verified"]


def test_duplicate_observation_cannot_replace_missing_case():
    base = observations("benchmark_v1.json")
    base[-1] = base[0]
    gate = observation_inventory("baseline", base, [], counts())
    assert not gate["verified"] and gate["missing"] and gate["duplicates"]


def test_unexpected_observation_cannot_inflate_completion():
    base = observations("benchmark_v1.json") + [{"case_id": "UNKNOWN"}]
    assert not observation_inventory("baseline", base, [], counts())["verified"]


def test_skipped_collection_is_not_complete_execution():
    base = observations("benchmark_v1.json")
    assert not observation_inventory("baseline", base, [], counts(89, 1))["verified"]


def test_partial_collection_and_wrong_channel_are_rejected():
    base = observations("benchmark_v1.json")
    assert not observation_inventory("baseline", base, [], counts(89))["verified"]
    assert not observation_inventory("baseline", base, [{"case_id": "extra"}], counts())["verified"]


def test_preview_cannot_write_to_its_source_root():
    with pytest.raises(ValueError, match="R021_DISJOINT_SYNTHETIC_PREVIEW_REQUIRED"):
        apply_to_preview(ROOT, ROOT)


def test_unpinned_base_policy_is_never_transformed():
    with pytest.raises(ValueError, match="R021_EXACT_BASE_POLICY_REQUIRED"):
        derive_policy(b"different source bytes")
