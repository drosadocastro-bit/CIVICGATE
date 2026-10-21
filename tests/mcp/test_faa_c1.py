"""FAA-C1 real Gateway and policy tests with synthetic MockTransport only."""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from typing import Any

import httpx
import pytest

from civicgate.audit.trace import Trace
from civicgate.channel_b.faa_adapter_v1 import FAA_C1, FaaFixtureAdapter
from civicgate.channel_b.faa_profile_v1 import DOT, ENDPOINT, FAA, FIELDS, FaaScopeV1
from civicgate.governance.execution import ExecutionBoundary, ExecutionBoundaryError
from civicgate.governance.policy import PolicyFacts
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import TOOLS, Proposal, Search

REQUEST = f'Get public awards for agency "{FAA}".'
CONTEXT = (True, True, 0.85, 0)


def query() -> dict[str, Any]:
    return {
        "contract_version": "B2B-FAA-001-C1-v1",
        "method": "POST",
        "endpoint": ENDPOINT,
        "awarding_agency": FAA,
        "agency_type": "awarding",
        "agency_tier": "subtier",
        "agency_toptier_name": DOT,
        "fiscal_year": 2025,
        "start_date": "2024-10-01",
        "end_date": "2025-09-30",
        "date_semantics": "AWARD_SEARCH_DEFAULT_OVERLAP",
        "award_types": ["A", "B", "C", "D"],
        "page": 1,
        "limit": 20,
        "subawards": False,
        "response_fields": list(FIELDS),
        "sort": "Award Amount",
        "order": "desc",
    }


def body() -> dict[str, Any]:
    return {
        "spending_level": "awards",
        "limit": 20,
        "results": [
            {
                "internal_id": 1,
                "generated_internal_id": "SYNTHETIC-FAA-C1",
                "Award ID": "SYNTHETIC-1",
                "Recipient Name": "Synthetic Recipient",
                "Award Amount": "123.45",
                "Awarding Agency": DOT,
                "Awarding Sub Agency": FAA,
                "Funding Agency": DOT,
                "Funding Sub Agency": "Federal Highway Administration",
            }
        ],
        "page_metadata": {"page": 1, "hasNext": False},
    }


class Judge:
    def __init__(self, signal: JudgeSignal | None = None):
        self.signal = signal or JudgeSignal(
            available=True, classification="IN_SCOPE", confidence=1, provider="synthetic"
        )

    async def assess(self, request, proposal):
        return self.signal.model_copy(deep=True)


class Capture:
    def __init__(self, obj=None, signal=None, raw=None, error=None, status=200):
        self.requests = []

        def receive(req):
            self.requests.append(req)
            if error:
                raise error
            return (
                httpx.Response(status, content=raw, headers={"content-type": "application/json"})
                if raw is not None
                else httpx.Response(status, json=body() if obj is None else obj)
            )

        self.adapter = FaaFixtureAdapter(httpx.MockTransport(receive))
        self.trace = Trace()
        self.gateway = Gateway(self.adapter, Judge(signal), self.trace, contract=FAA_C1)

    async def call(self, args=None, request=REQUEST, tool="find_federal_awards"):
        return await self.gateway.call(
            request, Proposal(tool=tool, arguments=query() if args is None else args)
        )


def issued(boundary, args=None):
    args = query() if args is None else args
    return boundary.evaluate(
        request_id="synthetic-faa-boundary",
        facts=PolicyFacts(
            tool="find_federal_awards",
            text=REQUEST,
            request_text=REQUEST,
            arguments_json=json.dumps(args),
        ),
        judge=Judge().signal,
        agent_k=KSignal(),
        threshold=0.85,
        arguments=args,
        policy_context=CONTEXT,
    )


async def test_permit_binds_exact_complete_scope_before_single_dispatch():
    c = Capture()
    response = await c.call()
    assert response.decision == "PERMIT" and response.tool_executed
    assert response.verification_state == "RESULT_VERIFIED"
    assert response.attempt_count == 1 and response.retry_class == "UNSAFE"
    assert len(c.requests) == 1
    scope = FaaScopeV1.model_validate(query())
    assert c.requests[0].content == scope.wire_bytes()
    policy = next(e for e in c.trace.events if e["stage"] == "policy")
    start = next(e for e in c.trace.events if e["stage"] == "execution_started")
    complete = c.trace.events[-1]
    assert policy["policy"]["decision"] == "PERMIT" and policy["binding_issued"]
    assert json.loads(policy["facts"]["arguments_json"]) == scope.model_dump(mode="json")
    import hashlib

    canonical_args = json.dumps(
        scope.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert (
        start["execution_binding"]["arguments_sha256"]
        == hashlib.sha256(canonical_args.encode()).hexdigest()
    )
    assert complete["pre_dispatch_verification"] == "PASS"
    assert response.provenance.query_fingerprint == scope.query_fingerprint()
    assert response.result["records"][0]["awarding_sub_agency"] == FAA
    assert response.result["records"][0]["funding_sub_agency"] != "Federal Aviation Administration"


@pytest.mark.parametrize("field", list(query()))
async def test_missing_effective_field_denied_before_dispatch(field):
    q = query()
    del q[field]
    c = Capture()
    result = await c.call(q)
    assert result.decision == "DENY" and not result.tool_executed and not c.requests


@pytest.mark.parametrize(
    "changes",
    [
        {"agency_type": "funding"},
        {"agency_tier": "toptier"},
        {"agency_toptier_name": "Other Department"},
        {"awarding_agency": "Other Agency"},
        {"fiscal_year": 2026},
        {"end_date": "2025-10-01"},
        {"page": 2},
        {"limit": 101},
        {"subawards": True},
        {"award_types": ["IDV_A"]},
        {"response_fields": ["Award ID"]},
        {"endpoint": "https://other.invalid"},
        {"contract": "legacy"},
        {"approval": "PERMIT"},
        {"authority_envelope": {}},
        {"sort": "Other"},
        {"order": "asc"},
    ],
)
async def test_conflicting_and_caller_authority_claims_rejected(changes):
    c = Capture()
    result = await c.call(query() | changes)
    assert result.decision == "DENY" and not result.tool_executed and not c.requests


@pytest.mark.parametrize(
    "prompt,decision",
    [
        ("Deny benefits to this applicant.", "REVIEW_REQUIRED"),
        ("Deny this award to the vendor.", "DENY"),
        ('Get public awards for agency "Other Agency".', "REVIEW_REQUIRED"),
        ('Get public awards for recipient "Synthetic Recipient".', "REVIEW_REQUIRED"),
        ("Determine which vendor should receive this contract.", "REVIEW_REQUIRED"),
    ],
)
async def test_policy_unchanged_denial_or_hold_never_dispatches(prompt, decision):
    c = Capture()
    result = await c.call(request=prompt)
    assert result.decision == decision and not result.tool_executed and not c.requests


@pytest.mark.parametrize(
    "signal",
    [
        JudgeSignal(available=False),
        JudgeSignal(available=True, classification="AMBIGUOUS", confidence=1, provider="synthetic"),
        JudgeSignal(
            available=True, classification="IN_SCOPE", confidence=0.2, provider="synthetic"
        ),
    ],
)
async def test_judge_cannot_supplement_missing_semantic_clearance(signal):
    c = Capture(signal=signal)
    result = await c.call()
    assert result.decision == "REVIEW_REQUIRED" and not result.tool_executed and not c.requests


@pytest.mark.parametrize(
    "changes",
    [
        {"Awarding Agency": "Other Department"},
        {"Awarding Sub Agency": "Federal Highway Administration", "Funding Sub Agency": FAA},
        {"Funding Agency": "Other Department", "Funding Sub Agency": FAA},
    ],
)
async def test_awarding_funding_conflict_preserves_permit_and_dispatch(changes):
    obj = body()
    obj["results"][0].update(changes)
    c = Capture(obj)
    result = await c.call()
    policy = next(e for e in c.trace.events if e["stage"] == "policy")
    assert policy["policy"]["decision"] == "PERMIT" and policy["binding_issued"]
    assert c.trace.events[-1]["pre_dispatch_verification"] == "PASS"
    assert result.tool_executed and result.attempt_count == 1 and len(c.requests) == 1
    assert result.decision == "REVIEW_REQUIRED" and result.result is None
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.errors[0].code == "CONFLICTING_SOURCE_RESULTS"
    assert not result.errors[0].retryable


@pytest.mark.parametrize(
    "field",
    [
        "Awarding Agency",
        "Awarding Sub Agency",
        "Funding Agency",
        "Funding Sub Agency",
        "Award ID",
        "Recipient Name",
    ],
)
@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_nullable_fields_hold_without_fabrication(field, missing):
    obj = body()
    if missing:
        del obj["results"][0][field]
    else:
        obj["results"][0][field] = None
    c = Capture(obj)
    result = await c.call()
    assert result.decision == "REVIEW_REQUIRED" and result.result is None and result.tool_executed
    assert len(c.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"spending_level": "subawards"},
        {"limit": 100},
        {"messages": ["Warning"]},
        {"page_metadata": {"page": 2, "hasNext": False}},
        {"page_metadata": {"page": 1, "hasNext": "false"}},
        {"results": [], "page_metadata": {"page": 1, "hasNext": True}},
        {"unrecognized_metadata": "Not silently discarded"},
    ],
)
async def test_response_compatibility_is_strict_and_fail_closed(changes):
    c = Capture(body() | changes)
    result = await c.call()
    assert result.decision == "REVIEW_REQUIRED" and result.result is None and len(c.requests) == 1


@pytest.mark.parametrize(
    "raw", [b"{", b'{"results":[],"results":[]}', b'{"x":NaN}', b"[]", b"\xff"]
)
async def test_malformed_raw_response_keeps_actual_dispatch_evidence(raw):
    c = Capture(raw=raw)
    result = await c.call()
    assert result.decision == "REVIEW_REQUIRED" and result.result is None
    assert (
        result.tool_executed
        and result.dispatch_state == "REQUEST_CONFIRMED"
        and result.attempt_count == 1
    )


@pytest.mark.parametrize("empty,truncated", [(True, False), (False, True), (False, False)])
async def test_empty_and_truncated_are_page_claims_only(empty, truncated):
    obj = body()
    if empty:
        obj["results"] = []
    obj["page_metadata"]["hasNext"] = truncated
    c = Capture(obj)
    result = await c.call()
    assert result.decision == "PERMIT" and result.provenance.truncated is truncated
    assert bool(result.result["records"]) is not empty
    assert set(result.result) == {"records"} and len(c.requests) == 1


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout("synthetic"), httpx.ConnectError("synthetic"), httpx.ReadError("synthetic")],
)
async def test_unknown_transport_never_retries(error):
    c = Capture(error=error)
    result = await c.call()
    assert result.result is None and result.verification_state == "RESULT_UNKNOWN"
    assert result.dispatch_state == "DISPATCH_UNKNOWN" and result.next_action == "RETRY_BLOCKED"
    assert result.attempt_count == 1 and len(c.requests) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"agency_type": "funding"},
        {"agency_tier": "toptier"},
        {"agency_toptier_name": "Other"},
        {"awarding_agency": "Other"},
        {"fiscal_year": 2024, "start_date": "2023-10-01", "end_date": "2024-09-30"},
        {"limit": 19},
        {"award_types": ["A"]},
        {"response_fields": ["Award ID"]},
        {"page": 2},
        {"subawards": True},
    ],
)
def test_bound_arguments_cannot_change_after_policy(changes):
    boundary = ExecutionBoundary(FAA_C1.registry, contract=FAA_C1)
    e = issued(boundary)
    assert e.envelope is not None
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(
            e.envelope, "synthetic-faa-boundary", "find_federal_awards", query() | changes, CONTEXT
        )
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(
            e.envelope, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT
        )


@pytest.mark.parametrize("other", ["legacy", "same-contract-other-instance"])
def test_cross_instance_channel_and_replay_rejected(other):
    a = ExecutionBoundary(FAA_C1.registry, contract=FAA_C1)
    b = (
        ExecutionBoundary(TOOLS)
        if other == "legacy"
        else ExecutionBoundary(FAA_C1.registry, contract=FAA_C1)
    )
    e = issued(a).envelope
    with pytest.raises(ExecutionBoundaryError):
        b.consume(e, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)
    a.consume(e, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)
    with pytest.raises(ExecutionBoundaryError):
        a.consume(e, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)


def test_wrong_tool_stale_and_forged_envelopes_rejected():
    clock = [1.0]
    boundary = ExecutionBoundary(FAA_C1.registry, contract=FAA_C1, clock=lambda: clock[0])
    e = issued(boundary).envelope
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(
            copy.deepcopy(e), "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT
        )
    clock[0] = 100
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(e, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)
    e = issued(boundary).envelope
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(
            e, "synthetic-faa-boundary", "summarize_federal_spending", query(), CONTEXT
        )


def test_immutable_contract_and_legacy_registry_unchanged():
    assert TOOLS["find_federal_awards"] is Search
    assert len(FAA_C1.registry) == 4
    with pytest.raises(FrozenInstanceError):
        FAA_C1.version = "planner-selected"
    with pytest.raises(TypeError):
        FAA_C1.registry["find_federal_awards"] = Search
    c = Capture()
    with pytest.raises(AttributeError):
        c.gateway.contract = None
    with pytest.raises(ValueError):
        ExecutionBoundary(TOOLS, contract=FAA_C1)
    with pytest.raises(ValueError):
        FaaFixtureAdapter(None)


@pytest.mark.parametrize(
    "damage",
    ["projection", "query", "response", "raw-attribution", "source", "count", "truncation"],
)
async def test_gateway_revalidates_adapter_evidence_before_release(damage):
    c = Capture()
    original = c.adapter.find_faa

    async def corrupt(args):
        call = await original(args)
        if damage == "projection":
            call.batch.records[0]["awarding_sub_agency"] = "Other"
        elif damage == "query":
            call = replace(call, outcome=replace(call.outcome, query_fingerprint="0" * 64))
        elif damage == "response":
            call.batch.provenance.response_fingerprint = "0" * 64
        elif damage == "raw-attribution":
            call.outcome.raw["results"][0]["Awarding Sub Agency"] = "Other"
        elif damage == "source":
            call.batch.provenance.source_system = "USAspending"
        elif damage == "count":
            call.batch.provenance.records_returned = 2
        else:
            call.batch.provenance.truncated = True
        return call

    c.adapter.find_faa = corrupt
    result = await c.call()
    assert result.result is None and result.decision == "REVIEW_REQUIRED"
    assert result.tool_executed and len(c.requests) == 1


def test_schema_drift_rejected_by_boundary_and_policy():
    class Drift(FaaScopeV1):
        pass

    contract = replace(FAA_C1, find_model=Drift)
    boundary = ExecutionBoundary(contract.registry, contract=contract)
    e = issued(boundary).envelope
    Drift.model_config["title"] = "Changed after issuance"
    with pytest.raises(ExecutionBoundaryError):
        boundary.consume(e, "synthetic-faa-boundary", "find_federal_awards", query(), CONTEXT)
    assert issued(boundary).policy.decision == "DENY"


async def test_faa_profile_not_enabled_on_other_three_tools():
    for tool in set(TOOLS) - {"find_federal_awards"}:
        c = Capture()
        result = await c.call(tool=tool)
        assert result.decision == "DENY" and not c.requests


@pytest.mark.parametrize(
    "metadata",
    [
        {"agency_slug": None, "awarding_agency_id": None, "recipient_id": None},
        {
            "agency_slug": "department-of-transportation",
            "awarding_agency_id": 69,
            "recipient_id": "synthetic-recipient",
        },
    ],
)
async def test_documented_auxiliary_metadata_retained_without_authority(metadata):
    obj = body()
    obj["results"][0].update(metadata)
    obj["page_metadata"].update(last_record_unique_id=1, last_record_sort_value="123.45")
    c = Capture(obj)
    result = await c.call()
    assert result.decision == "PERMIT" and result.verification_state == "RESULT_VERIFIED"
    for key, value in metadata.items():
        assert result.result["records"][0][key] == value
    assert len(c.requests) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"agency_slug": {}},
        {"awarding_agency_id": True},
        {"recipient_id": []},
    ],
)
async def test_malformed_auxiliary_metadata_rejected(metadata):
    obj = body()
    obj["results"][0].update(metadata)
    c = Capture(obj)
    result = await c.call()
    assert result.decision == "REVIEW_REQUIRED" and result.result is None


async def test_absent_auxiliary_metadata_not_fabricated():
    c = Capture()
    result = await c.call()
    assert "agency_slug" not in result.result["records"][0]
    assert "recipient_id" not in result.result["records"][0]


async def test_concurrent_calls_have_distinct_consumed_bindings():
    import asyncio

    c = Capture()
    results = await asyncio.gather(c.call(), c.call())
    assert all(r.decision == "PERMIT" for r in results)
    assert len(c.requests) == 2
    starts = [e for e in c.trace.events if e["stage"] == "execution_started"]
    assert len({e["execution_binding"]["request_id"] for e in starts}) == 2
    assert all(
        e["pre_dispatch_verification"] == "PASS"
        for e in c.trace.events
        if e["stage"] == "completed"
    )


async def test_post_policy_argument_tampering_fails_before_real_backend():
    c = Capture()
    consume = c.gateway._execution_boundary.consume

    def corrupted_consume(*args, **kwargs):
        kwargs["arguments"] = kwargs["arguments"] | {"limit": 19}
        return consume(*args, **kwargs)

    c.gateway._execution_boundary.consume = corrupted_consume
    result = await c.call()
    policy = next(e for e in c.trace.events if e["stage"] == "policy")
    assert policy["policy"]["decision"] == "PERMIT" and policy["binding_issued"]
    assert result.decision == "DENY" and not result.tool_executed and not c.requests
    assert c.trace.events[-1]["pre_dispatch_verification"] == "FAIL"


async def test_profile_can_only_be_selected_by_trusted_composition():
    # The same full profile on an unchanged legacy Gateway is rejected, even
    # though all caller-supplied contract hashes/values are internally consistent.
    c = Capture()
    legacy = Gateway(c.adapter, Judge(), Trace())
    result = await legacy.call(REQUEST, Proposal(tool="find_federal_awards", arguments=query()))
    assert result.decision == "DENY" and not result.tool_executed and not c.requests
