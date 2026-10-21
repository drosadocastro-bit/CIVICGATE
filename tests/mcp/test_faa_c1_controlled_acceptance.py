"""Independent wire oracle and pre-dispatch attacks for the controlled FAA slice."""

import ast
import copy
import hashlib
import inspect
import json
from dataclasses import replace

import httpx
import pytest

from civicgate.channel_b.faa_adapter_v1 import FAA_C1
from civicgate.channel_b.faa_profile_v1 import FaaScopeV1
from civicgate.governance.execution import ExecutionBoundary, ExecutionBoundaryError
from experiments.b2b_faa_002.contract_v1 import FaaScopeV1 as PreservedScope
from tests.mcp.test_faa_c1 import CONTEXT, Capture, body, issued, query


def test_original_faa_query_model_is_preserved_exactly():
    assert FaaScopeV1.model_json_schema() == PreservedScope.model_json_schema()
    assert ast.dump(ast.parse(inspect.getsource(FaaScopeV1))) == ast.dump(
        ast.parse(inspect.getsource(PreservedScope))
    )


@pytest.mark.parametrize("year", [2008, 2025, 2027])
@pytest.mark.parametrize(
    "award_type", ["A", "B", "C", "D", "02", "03", "04", "05", "06", "09", "10", "11"]
)
async def test_independent_full_wire_oracle_and_policy_scope(year, award_type):
    proposed = query() | {
        "fiscal_year": year,
        "start_date": f"{year - 1}-10-01",
        "end_date": f"{year}-09-30",
        "award_types": [award_type],
    }
    original = copy.deepcopy(proposed)
    c = Capture()
    result = await c.call(proposed)
    expected = {
        "filters": {
            "time_period": [{"start_date": f"{year - 1}-10-01", "end_date": f"{year}-09-30"}],
            "award_type_codes": [award_type],
            "agencies": [
                {
                    "type": "awarding",
                    "tier": "subtier",
                    "name": "Federal Aviation Administration",
                    "toptier_name": "Department of Transportation",
                }
            ],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Award Amount",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Funding Agency",
            "Funding Sub Agency",
            "generated_internal_id",
        ],
        "page": 1,
        "limit": 20,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    assert proposed == original
    assert result.decision == "PERMIT" and result.verification_state == "RESULT_VERIFIED"
    assert len(c.requests) == result.attempt_count == 1
    sent = c.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    assert sent.content == json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert "authorization" not in sent.headers
    policy = next(e for e in c.trace.events if e["stage"] == "policy")
    start = next(e for e in c.trace.events if e["stage"] == "execution_started")
    assert json.loads(policy["facts"]["arguments_json"]) == proposed
    assert policy["binding_issued"] and policy["policy"]["decision"] == "PERMIT"
    bound_args = json.dumps(proposed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert (
        start["execution_binding"]["arguments_sha256"]
        == hashlib.sha256(bound_args.encode()).hexdigest()
    )
    assert c.trace.events[-1]["pre_dispatch_verification"] == "PASS"
    assert set(result.result) == {"records"}  # Not a spending total.


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_version": "B2B-FAA-001-C1-v2"},
        {"agency_type": "funding"},
        {"agency_tier": "toptier"},
        {"agency_toptier_name": "Other Department"},
        {"awarding_agency": "Federal Highway Administration"},
        {"limit": 19},
        {"award_types": ["A"]},
        {"page": 2},
        {"fiscal_year": 2026, "start_date": "2025-10-01", "end_date": "2026-09-30"},
        {"response_fields": ["Award ID"]},
    ],
)
async def test_actual_gateway_rejects_scope_tamper_at_last_gate(changes):
    c = Capture()
    consume = c.gateway._execution_boundary.consume

    def substituted(envelope, **kwargs):
        kwargs["arguments"] = kwargs["arguments"] | changes
        return consume(envelope, **kwargs)

    c.gateway._execution_boundary.consume = substituted
    result = await c.call()
    policy = next(e for e in c.trace.events if e["stage"] == "policy")
    assert policy["policy"]["decision"] == "PERMIT" and policy["binding_issued"]
    assert result.decision == "DENY" and not result.tool_executed
    assert result.result is None and c.requests == []
    assert c.trace.events[-1]["pre_dispatch_verification"] == "FAIL"


def test_separate_trusted_versions_cannot_exchange_authority():
    original = ExecutionBoundary(FAA_C1.registry, contract=FAA_C1)
    other_contract = replace(FAA_C1, version="INDEPENDENT_SYNTHETIC_VERSION")
    other = ExecutionBoundary(other_contract.registry, contract=other_contract)
    envelope = issued(original).envelope
    with pytest.raises(ExecutionBoundaryError):
        other.consume(envelope, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)
    original.consume(envelope, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)
    with pytest.raises(ExecutionBoundaryError):
        original.consume(
            envelope, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"funding_agency": "Federal Aviation Administration"},
        {"keywords": ["aviation"]},
        {"agency_type": "funding"},
        {"contract_version": "B2B-FAA-001-C1-v2"},
        {"award_types": ["IDV_A"]},
        {"award_types": ["A", "A"]},
        {"start_date": "2025-01-01"},
        {"limit": 0},
        {"page": 0},
    ],
)
async def test_unsupported_scope_is_not_dropped_or_repaired(extra):
    args = query() | extra
    original = copy.deepcopy(args)
    c = Capture()
    result = await c.call(args)
    assert args == original
    assert result.decision == "DENY" and not result.tool_executed and not c.requests
    assert not next(e for e in c.trace.events if e["stage"] == "policy")["binding_issued"]


async def test_excess_rows_and_wrong_award_type_evidence_never_release_or_expand():
    for change in ["excess_rows", "unrequested_award_type"]:
        obj = body()
        if change == "excess_rows":
            obj["results"] *= 21
        else:
            obj["results"][0]["Award Type"] = "IDV_A"
        c = Capture(obj)
        result = await c.call()
        assert result.result is None and result.decision == "REVIEW_REQUIRED"
        assert result.tool_executed and result.attempt_count == len(c.requests) == 1
        assert result.verification_state == "FAILED_VALIDATION"
        assert c.trace.events[-1]["pre_dispatch_verification"] == "PASS"


@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_complete_http_rejections_keep_dispatch_without_redirect_retry_or_fallback(status):
    c = Capture(status=status)
    result = await c.call()
    assert result.result is None and result.tool_executed
    assert result.dispatch_state == "REQUEST_CONFIRMED"
    assert result.attempt_count == len(c.requests) == 1
    assert not result.errors[0].retryable


async def test_partial_response_preserves_confirmed_request_and_unknown_result():
    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"results":['
            raise httpx.ReadError("synthetic interruption after headers")

    c = Capture()
    calls = []

    def receive(req):
        calls.append(req)
        return httpx.Response(
            200, headers={"content-type": "application/json"}, stream=Interrupted()
        )

    c.adapter.transport = httpx.MockTransport(receive)
    result = await c.call()
    assert result.result is None and result.provenance is None
    assert result.tool_executed and result.dispatch_state == "REQUEST_CONFIRMED"
    assert result.verification_state == "RESULT_UNKNOWN"
    assert result.next_action == "RETRY_BLOCKED" and result.attempt_count == len(calls) == 1
