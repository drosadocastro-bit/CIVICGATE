"""New contract-disposition overlay; original v1 labels/tests remain intact."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evals.tests.test_data01_fullpath_v1 import CASES
from evals.tests.test_data01_fullpath_v1 import test_data01_existing_fullpath as _observe_v1

ROOT = Path.cwd()
OVERLAY = json.loads((ROOT / "evals/data01/benchmark_dispositions_r021_v1.json").read_bytes())


def revised_cases():
    result = copy.deepcopy(CASES)
    assert len(OVERLAY["changes"]) == 1
    change = OVERLAY["changes"][0]
    assert change["case_id"] == "DATA01-026"
    for item in result:
        if item["case_id"] == change["case_id"]:
            assert item["user_request"] == change["exact_request"]
            assert item["expected_initial_policy"] == change["original_initial_policy"]
            assert item["expected_final_policy"] == change["original_final_policy"]
            assert item["expected_dispatch"] == change["expected_dispatch"] is False
            item["expected_initial_policy"] = change["contract_derived_initial_policy"]
            item["expected_final_policy"] = change["contract_derived_final_policy"]
            item["expectation_provenance"] = "R021_CONTRACT_DISPOSITION_OVERLAY_V1_NOT_HUMAN_GOLDEN"
    return result


@pytest.mark.parametrize("case", revised_cases(), ids=[c["case_id"] for c in CASES])
def test_r021_contract_disposition_benchmark(case, monkeypatch):
    for name, key in (
        ("benchmark_v1.json", "base_benchmark_sha256"),
        ("reference_answers_v1.json", "base_reference_sha256"),
    ):
        assert (
            hashlib.sha256((ROOT / "evals/data01" / name).read_bytes()).hexdigest() == OVERLAY[key]
        )
    for name, expected in OVERLAY["changes"][0]["source_identities"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    # Reuse the unchanged complete observation, assertions and primary writer.
    # This selection has explicit new provenance; it never relabels the v1 run.
    _observe_v1(case, monkeypatch)
    if case["case_id"] == "DATA01-026":
        observed = json.loads(
            (ROOT.parent / "execution/cases/DATA01-026/measurement.json").read_bytes()
        )
        assert observed["policy_reasons"] == [OVERLAY["changes"][0]["expected_reason"]]
