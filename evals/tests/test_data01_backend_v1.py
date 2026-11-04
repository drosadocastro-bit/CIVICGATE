"""Independent protocol and boundary controls for the fictional DATA-01 source."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from decimal import Decimal

import httpx
import pytest
from mcp import StdioServerParameters

from evals.data01 import backend_v1 as backend
from evals.data01.bridge_v1 import ORIGINAL_MODULE, WORKER_MODULE, worker_parameters
from evals.data01.generator import DOT, FAA, load_dataset


def payload():
    return {
        "filters": {
            "time_period": [{"start_date": "2025-10-01", "end_date": "2026-09-30"}],
            "award_type_codes": ["A", "B", "C", "D"],
            "agencies": [{"type": "awarding", "tier": "toptier", "name": DOT}],
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
        },
        "fields": backend.SEARCH_FIELDS,
        "limit": 100,
        "page": 1,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }


def request(
    method="POST", path=backend.SEARCH_PATH, body=None, origin="https://api.usaspending.gov"
):
    async def call():
        async with httpx.AsyncClient(transport=backend.fixture_transport()) as client:
            return await client.request(
                method, origin + path, json=payload() if body is None else body
            )

    return asyncio.run(call())


def test_toptier_is_not_subtier_or_funding():
    response = request()
    assert response.status_code == 200
    result = response.json()
    rows = load_dataset()["records"]
    by_id = {row["award_id"]: row for row in rows}
    delivered = [by_id[row["generated_internal_id"]] for row in result["results"]]
    assert any(row["awarding_subagency"] != FAA for row in delivered)
    assert all(row["awarding_agency"] == DOT for row in delivered)
    assert all(
        row["place_of_performance_state"] == "PR" and row["fiscal_year"] == 2026
        for row in delivered
    )
    assert not any(row["award_id"] == "SYN-NASA-PR-020" for row in delivered)
    assert not result["page_metadata"]["hasNext"]


def test_faa_as_toptier_cannot_create_synthetic_faa_scope():
    body = payload()
    body["filters"]["agencies"][0]["name"] = FAA
    response = request(body=body)
    assert response.status_code == 200
    assert response.json() == {"results": [], "page_metadata": {"hasNext": False}}


def test_pagination_amount_order_and_exact_decimal_strings():
    body = payload()
    body["limit"] = 5
    response = request(body=body).json()
    assert len(response["results"]) == 5 and response["page_metadata"]["hasNext"]
    amounts = [row["Award Amount"] for row in response["results"]]
    assert all(type(amount) is str for amount in amounts)
    assert list(map(Decimal, amounts)) == sorted(map(Decimal, amounts), reverse=True)
    # DOT's higher-valued non-FAA records must remain visible in this broad query.
    assert response["results"][0]["generated_internal_id"] == "SYN-DOT-PR-016"


def test_inclusive_fy_boundaries_and_contract_types():
    response = request().json()
    ids = {row["generated_internal_id"] for row in response["results"]}
    assert {"SYN-FAA-PR-001", "SYN-FAA-PR-002"} <= ids
    assert not {"SYN-FAA-PR-007", "SYN-FAA-PR-008", "SYN-FAA-PR-023", "SYN-FAA-PR-024"} & ids


def test_find_to_get_generated_identity():
    award = request().json()["results"][0]
    response = request(method="GET", path=f"/api/v2/awards/{award['generated_internal_id']}/")
    assert response.status_code == 200
    assert response.json()["generated_unique_award_id"] == award["generated_internal_id"]
    assert response.json()["total_obligation"] == award["Award Amount"]


def test_unknown_award_has_explicit_404():
    assert request(method="GET", path="/api/v2/awards/SYN-MISSING/").status_code == 404


def test_numeric_detail_identity_is_preserved():
    response = request(method="GET", path="/api/v2/awards/26/")
    assert response.status_code == 200
    assert response.json()["id"] == 26
    assert response.json()["generated_unique_award_id"] == "SYN-FAA-PR-026"


def test_bridge_rejects_overlapping_fixture_selection():
    from evals.data01 import bridge_v1 as bridge

    assert bridge._COMPOSITION_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="DATA01_CONCURRENT_COMPOSITION_NOT_SUPPORTED"):
            asyncio.run(bridge.run_observation(None, "synthetic", "synthetic", None, None))
    finally:
        bridge._COMPOSITION_LOCK.release()


def test_recipient_candidates_and_ambiguity_are_not_resolved_by_source():
    body = {
        "keyword": "Fictional",
        "limit": 2,
        "page": 1,
        "sort": "name",
        "order": "asc",
        "award_type": "all",
    }
    response = request(path=backend.RECIPIENT_PATH, body=body)
    assert response.status_code == 200
    result = response.json()
    assert len(result["results"]) == 2 and result["page_metadata"]["hasNext"]
    assert all(row["uei"] is None and row["id"].startswith("SYN-REC-") for row in result["results"])


def test_empty_result_does_not_fallback():
    body = payload()
    body["filters"]["recipient_search_text"] = ["Fictional Unknown"]
    assert request(body=body).json() == {"results": [], "page_metadata": {"hasNext": False}}


@pytest.mark.parametrize(
    "change",
    [
        {"page": 2},
        {"page": True},
        {"limit": True},
        {"limit": 101},
        {"limit": 0},
        {"subawards": True},
        {"sort": "Obligations"},
        {"order": "asc"},
        {"fields": ["private_data"]},
        {"extra": "unapproved"},
    ],
)
def test_unsupported_search_payload_rejected(change):
    body = payload() | change
    assert request(body=body).status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        {"agencies": [{"type": "funding", "tier": "toptier", "name": DOT}]},
        {"agencies": [{"type": "awarding", "tier": "subtier", "name": FAA}]},
        {"date_type": "new_awards_only"},
        {"time_period": [{"start_date": "2026-09-30", "end_date": "2025-10-01"}]},
        {"award_type_codes": ["UNSUPPORTED"]},
        {"recipient_search_text": ["a", "b"]},
    ],
)
def test_no_contract_extension_hidden_in_fixture(change):
    body = payload()
    body["filters"] |= change
    assert request(body=body).status_code == 400


@pytest.mark.parametrize("origin", ["https://other.invalid", "http://api.usaspending.gov"])
def test_logical_origin_rejected_without_network(origin):
    assert request(origin=origin).status_code == 400


def test_duplicate_json_key_rejected():
    async def call():
        async with httpx.AsyncClient(transport=backend.fixture_transport()) as client:
            return await client.post(
                "https://api.usaspending.gov" + backend.SEARCH_PATH,
                content=b'{"limit":1,"limit":2}',
            )

    assert asyncio.run(call()).status_code == 400


def test_source_tamper_cannot_be_admitted_against_manifest(tmp_path, monkeypatch):
    for name in ("awards_v1.json", "dataset_manifest_v1.json"):
        (tmp_path / name).write_bytes((backend.HERE / name).read_bytes())
    data = json.loads((tmp_path / "awards_v1.json").read_bytes())
    data["records"][0]["award_amount"] = "1.00"
    (tmp_path / "awards_v1.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(backend, "HERE", tmp_path)
    with pytest.raises(ValueError, match="DATA01_DATASET_IDENTITY_MISMATCH"):
        backend.fixture_transport()


def test_only_exact_worker_module_is_replaced():
    command = [
        "-B",
        "-m",
        ORIGINAL_MODULE,
        "--synthetic-worker-config",
        "synthetic-http-worker-config.json",
    ]
    actual = worker_parameters(StdioServerParameters, command=sys.executable, args=command)
    assert actual.args == ["-B", "-m", WORKER_MODULE, *command[3:]]
    assert command[2] == ORIGINAL_MODULE


@pytest.mark.parametrize(
    "index,value", [(0, "-s"), (1, "-c"), (2, "other"), (3, "--live"), (4, "different.json")]
)
def test_unexpected_worker_parameters_fail_closed(index, value):
    command = [
        "-B",
        "-m",
        ORIGINAL_MODULE,
        "--synthetic-worker-config",
        "synthetic-http-worker-config.json",
    ]
    command[index] = value
    with pytest.raises(ValueError, match="DATA01_EXACT_SYNTHETIC_WORKER_REQUIRED"):
        worker_parameters(StdioServerParameters, command=sys.executable, args=command)


def test_backend_does_not_mutate_source_or_inputs():
    original = (backend.HERE / "awards_v1.json").read_bytes()
    records = load_dataset()["records"]
    copy_of_records = copy.deepcopy(records)
    body = payload()
    copy_of_payload = copy.deepcopy(body)
    backend.select_search(records, body)
    assert records == copy_of_records and body == copy_of_payload
    assert (backend.HERE / "awards_v1.json").read_bytes() == original
