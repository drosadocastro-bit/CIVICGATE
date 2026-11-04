"""Unit controls for measurement accounting; these are not MCP observations."""

import json

from scripts.evaluate_data01_v1 import ROOT, summarize


def fixture_rows():
    cases = json.loads((ROOT / "evals/data01/benchmark_v1.json").read_bytes())["cases"]
    return [
        {
            "case_id": c["case_id"],
            "initial_policy": c["expected_initial_policy"],
            "final_policy": c["expected_final_policy"],
            "tool_correct": True,
            "argument_evaluable": c["functional_eligible"],
            "arguments_correct": True,
            "query_result_correct": True if c["functional_eligible"] else None,
            "binding_issuances": int(c["expected_dispatch"]),
            "binding_consumptions": int(c["expected_dispatch"]),
            "adapter_entries": int(c["expected_dispatch"]),
            "mock_backend_attempts": int(c["expected_dispatch"]),
            "mcp_logical_calls": 1,
            "custody_state": "CLOSED",
            "fence_close_ack": "ACKNOWLEDGED",
            "primary_projection_verified": True,
            "unit_fixture_not_primary_evidence": True,
        }
        for c in cases
    ]


def put(root, rows):
    for index, row in enumerate(rows):
        path = root / "cases" / str(index) / "measurement.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(row), encoding="utf-8")
    return summarize(root)


def test_complete_inventory_has_separate_functional_and_policy_denominators(tmp_path):
    result = put(tmp_path, fixture_rows())
    assert result["measurement_inventory_exact"]
    assert result["query_result"] == {"correct": 14, "evaluated": 14, "ratio": 1.0}
    assert result["final_policy"]["evaluated"] == 26
    assert len(result["functional_queries_not_executed"]) == 12


def test_missing_measurement_blocks_exact_inventory(tmp_path):
    result = put(tmp_path, fixture_rows()[1:])
    assert not result["measurement_inventory_exact"]
    assert result["missing_measurements"] == ["DATA01-001"]
    assert result["eligible_functional_definitions"] == 14
    assert result["query_result"]["evaluated"] == 13


def test_duplicate_measurement_blocks_exact_inventory(tmp_path):
    rows = fixture_rows()
    result = put(tmp_path, rows + [rows[0]])
    assert not result["measurement_inventory_exact"]
    assert result["duplicate_measurements"] == ["DATA01-001"]


def test_unexpected_measurement_blocks_exact_inventory(tmp_path):
    rows = fixture_rows()
    result = put(tmp_path, rows + [dict(rows[0], case_id="UNKNOWN")])
    assert not result["measurement_inventory_exact"]
    assert result["unexpected_measurements"] == ["UNKNOWN"]


def test_functional_failure_does_not_relabel_policy(tmp_path):
    rows = fixture_rows()
    rows[0]["query_result_correct"] = False
    result = put(tmp_path, rows)
    assert result["query_result"]["correct"] == 13
    assert result["initial_policy"]["correct"] == 26


def test_fixture_quality_is_not_model_or_human_acceptance(tmp_path):
    result = put(tmp_path, fixture_rows())
    assert result["real_granite_or_luna_quality"] == "NOT_MEASURED"
    assert result["human_acceptance"] == "NOT_GRANTED_BY_THIS_REPORT"
    assert result["planner_uncertainty_handling"].startswith("NOT_MEASURED")
