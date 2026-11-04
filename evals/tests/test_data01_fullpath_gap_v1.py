"""Independent additive scope probe; not one of the original 26 cases."""

import asyncio
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from evals.data01.bridge_v1 import run_observation
from evals.demos.observability_v1 import install_a2_capture, verify_a2_capture
from evals.harness.evidence import write_new
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_composition_v3 import OfflineScenario
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy


def test_matching_faa_literal_requires_subtier_review(monkeypatch):
    directory = Path.cwd().parent / "execution" / "agency-probe"
    directory.mkdir(exist_ok=False)
    database = directory / "coordinator.sqlite"
    run_id = "DATA01_SCOPE_" + uuid4().hex
    observation_id = "DATA01_SCOPE_OBS_" + uuid4().hex
    scenario = OfflineScenario(
        request='Find public awards for agency "Federal Aviation Administration".',
        proposal_arguments_json=json.dumps(
            {
                "start_date": "2025-10-01",
                "end_date": "2026-09-30",
                "state_code": "PR",
                "awarding_agency": "Federal Aviation Administration",
            }
        ),
    )
    install_a2_capture(monkeypatch, directory)
    LiveAttemptBudget.create(database, run_id, liability_policy=SyntheticLiabilityPolicy(24))
    returned = asyncio.run(
        run_observation(database, run_id, observation_id, directory / "evidence", scenario)
    )
    write_new(directory / "returned.json", returned)
    audit = [json.loads(x) for x in (directory / "evidence/audit.jsonl").read_bytes().splitlines()]
    graph = verify_a2_capture(directory, scenario, audit, returned)
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        db.row_factory = sqlite3.Row
        fence = [dict(x) for x in db.execute("SELECT * FROM observation_fences")]
    write_new(
        directory / "observed-versus-required.json",
        {
            "probe": "FAA_LITERAL_TOP_TIER_CONTRACT_GAP",
            "expected": "REVIEW_REQUIRED",
            "observed_decision": returned["decision"],
            "bindings_issued": returned["binding_issuances"],
            "bindings_consumed": returned["binding_consumptions"],
            "adapter_entries": returned["adapter_entries"],
            "mock_backend_attempts": returned["mock_backend_attempts"],
            "observed_envelope": returned["observed_envelope"],
            "primary_projection_verified": returned["primary_projection_verified"],
            "fence_close": returned["fence_close"],
            "sqlite_fence": fence,
            "graph_nodes": graph["nodes"],
            "intended_faa_fy2026_pr_contract_reference_count": 16,
            "no_policy_or_schema_modification": True,
            "operational_authorization": "HOLD",
        },
    )
    assert returned["primary_projection_verified"]
    assert returned["decision"] == "REVIEW_REQUIRED", (
        "FAA_SUBTIER_SCOPE_CANNOT_BE_AUTHORIZED_AS_TOP_TIER"
    )
    assert returned["binding_consumptions"] == 0 and returned["adapter_entries"] == 0
