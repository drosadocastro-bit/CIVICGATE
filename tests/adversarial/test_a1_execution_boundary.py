"""Independent Channel A1 attacks, using synthetic public-read transports only.

Private hooks exercise corruption/TOCTOU detection at the composition boundary;
they do not claim to sandbox an attacker with arbitrary trusted-process access.
"""

import asyncio
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from typing import Any

import httpx
import pytest

import civicgate.adapters.usaspending as adapter_module
from civicgate.adapters.usaspending import AdapterCall, USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.governance.execution import (
    MAX_OUTSTANDING_ENVELOPES,
    ExecutionBoundary,
    ExecutionBoundaryError,
)
from civicgate.governance.policy import PolicyFacts
from civicgate.llm.base import UnavailableProvider
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search

CONTEXT = (True, True, 0.85, 0)
GOOD = JudgeSignal(classification="IN_SCOPE", confidence=1, available=True, provider="synthetic-a1")


class SyntheticJudge:
    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        return GOOD.model_copy(deep=True)


class CountingAdapter(USAspending):
    def __init__(self) -> None:
        super().__init__(transport=fixture_transport(), fixture=True)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, request: Search) -> AdapterCall:
        self.calls.append(("search", request.model_dump(mode="json")))
        return await super().search(request)

    async def detail(self, request: Award) -> AdapterCall:
        self.calls.append(("detail", request.model_dump(mode="json")))
        return await super().detail(request)

    async def recipients(self, request: Recipient) -> AdapterCall:
        self.calls.append(("recipients", request.model_dump(mode="json")))
        return await super().recipients(request)


def _proposal(search_args: dict[str, object]) -> Proposal:
    return Proposal(tool="find_federal_awards", arguments=deepcopy(search_args))


def _evaluation(
    boundary: ExecutionBoundary,
    search_args: dict[str, object],
    *,
    facts: PolicyFacts | None = None,
    judge: JudgeSignal | None = None,
    request_id: str = "synthetic-request-1",
):
    return boundary.evaluate(
        request_id=request_id,
        facts=facts or PolicyFacts(tool="find_federal_awards", text="public awards"),
        judge=judge or GOOD.model_copy(deep=True),
        agent_k=KSignal(),
        threshold=0.85,
        arguments=Search.model_validate(search_args).model_dump(mode="json"),
        policy_context=CONTEXT,
    )


def _consume(
    boundary: ExecutionBoundary, envelope: Any, search_args: dict[str, object], **changes: Any
):
    supplied = {
        "request_id": "synthetic-request-1",
        "tool": "find_federal_awards",
        "arguments": Search.model_validate(search_args).model_dump(mode="json"),
        "policy_context": CONTEXT,
    }
    supplied.update(changes)
    return boundary.consume(envelope, **supplied)


async def test_discovery_is_metadata_and_never_dispatches(search_args: dict[str, object]) -> None:
    adapter = CountingAdapter()
    gateway = Gateway(adapter, UnavailableProvider(), Trace())
    server = create_server(gateway)
    discovered = await server.list_tools()
    assert {tool.name for tool in discovered} == set(TOOLS)
    assert all(tool.annotations.readOnlyHint for tool in discovered)
    assert adapter.calls == []
    result = await gateway.call("public awards", _proposal(search_args))
    assert result.decision == "REVIEW_REQUIRED"
    assert not result.tool_executed
    assert adapter.calls == []


@pytest.mark.parametrize(
    "tool,query",
    [
        (
            "find_federal_awards",
            {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"},
        ),
        ("get_federal_award", {"award_id": "1"}),
        ("resolve_federal_recipient", {"recipient_name": "EXAMPLE RECIPIENT"}),
        (
            "summarize_federal_spending",
            {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"},
        ),
    ],
)
async def test_every_direct_mcp_tool_is_denied_before_backend(tool, query) -> None:
    adapter = CountingAdapter()
    trace = Trace()
    server = create_server(Gateway(adapter, SyntheticJudge(), trace))
    _, result = await server.call_tool(
        tool, {"user_request": "blacklist this contractor", "query": query}
    )
    assert result["decision"] == "DENY"
    assert result["tool_executed"] is False
    assert result["dispatch_state"] == "NOT_DISPATCHED"
    assert adapter.calls == []
    assert not any(event["stage"] == "execution_started" for event in trace.events)


async def test_internal_direct_call_still_applies_deterministic_gate(search_args) -> None:
    adapter = CountingAdapter()
    result = await Gateway(adapter, SyntheticJudge(), Trace())._call(
        "execute payment", _proposal(search_args), False
    )
    assert result.decision == "DENY" and not result.tool_executed
    assert adapter.calls == []


@pytest.mark.parametrize("claim", ["PERMIT", "APPROVED", {"decision": "PERMIT"}])
async def test_planner_supplied_approval_is_not_authority(search_args, claim) -> None:
    adapter = CountingAdapter()
    proposal = _proposal(search_args)
    proposal.arguments["authority"] = claim
    result = await Gateway(adapter, SyntheticJudge(), Trace()).call("public awards", proposal)
    assert result.decision == "DENY" and not result.tool_executed
    assert adapter.calls == []


@pytest.mark.parametrize("held", ["DENY", "REVIEW_REQUIRED"])
async def test_nonpermit_cannot_enter_backend_and_audit_reports_hold(search_args, held) -> None:
    adapter = CountingAdapter()
    trace = Trace()
    gateway = Gateway(adapter, UnavailableProvider(), trace)
    text = "execute payment" if held == "DENY" else "public awards"
    result = await gateway.call(text, _proposal(search_args))
    assert result.decision == held and not result.tool_executed
    assert adapter.calls == []
    assert [event["stage"] for event in trace.events] == ["proposal", "policy", "completed"]
    assert trace.events[1]["policy"]["decision"] == held
    assert trace.events[-1]["response"]["decision"] == held
    assert trace.events[-1]["response"]["dispatch_state"] == "NOT_DISPATCHED"


async def test_one_permit_dispatches_exact_synthetic_read_and_audits_verification(
    search_args,
) -> None:
    adapter = CountingAdapter()
    trace = Trace()
    result = await Gateway(adapter, SyntheticJudge(), trace).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "PERMIT" and result.tool_executed
    assert result.status == "OK" and result.verification_state == "RESULT_VERIFIED"
    assert adapter.calls == [("search", Search.model_validate(search_args).model_dump(mode="json"))]
    assert result.provenance.source_type == "SYNTHETIC_TEST_FIXTURE"
    assert [event["stage"] for event in trace.events] == [
        "proposal",
        "policy",
        "execution_started",
        "completed",
    ]
    assert trace.events[1]["policy"]["decision"] == "PERMIT"
    assert trace.events[-1]["pre_dispatch_verification"] == "PASS"
    assert trace.events[-1]["response"]["verification_state"] == "RESULT_VERIFIED"


@pytest.mark.parametrize("mutate", ["caller_proposal", "judge_proposal"])
async def test_async_judge_cannot_change_authorized_proposal(search_args, mutate) -> None:
    adapter = CountingAdapter()
    original = _proposal(search_args)
    expected = Search.model_validate(search_args).model_dump(mode="json")

    class MutatingJudge:
        async def assess(self, request, proposal):
            target = original if mutate == "caller_proposal" else proposal
            target.tool = "get_federal_award"
            target.arguments.clear()
            target.arguments.update({"award_id": "1"})
            return GOOD.model_copy(deep=True)

    result = await Gateway(adapter, MutatingJudge(), Trace()).call("public awards", original)
    assert result.tool == "find_federal_awards"
    assert result.decision == "PERMIT" and result.tool_executed
    assert adapter.calls == [("search", expected)]


async def test_queued_call_snapshots_before_waiting_for_gateway_lock(search_args) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    judge_calls = 0

    class WaitingJudge:
        async def assess(self, request, proposal):
            nonlocal judge_calls
            judge_calls += 1
            if judge_calls == 1:
                entered.set()
                await release.wait()
            return GOOD.model_copy(deep=True)

    adapter = CountingAdapter()
    gateway = Gateway(adapter, WaitingJudge(), Trace())
    first = asyncio.create_task(gateway.call("public awards", _proposal(search_args)))
    await entered.wait()
    pending_proposal = _proposal(search_args)
    second = asyncio.create_task(gateway.call("public awards", pending_proposal))
    await asyncio.sleep(0)
    pending_proposal.tool = "summarize_federal_spending"
    pending_proposal.arguments["state_code"] = "CA"
    release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result.decision == second_result.decision == "PERMIT"
    assert second_result.tool == "find_federal_awards"
    expected = Search.model_validate(search_args).model_dump(mode="json")
    assert adapter.calls == [("search", expected), ("search", expected)]


async def test_post_result_review_does_not_rewrite_predispatch_authority() -> None:
    adapter = CountingAdapter()
    trace = Trace()
    result = await Gateway(adapter, SyntheticJudge(), trace).call(
        "find public recipient candidates",
        Proposal(tool="resolve_federal_recipient", arguments={"recipient_name": "Acme"}),
    )
    assert result.decision == "REVIEW_REQUIRED" and result.tool_executed
    assert len(adapter.calls) == 1
    assert trace.events[1]["policy"]["decision"] == "PERMIT"
    assert trace.events[-1]["response"]["decision"] == "REVIEW_REQUIRED"


async def test_preexecution_audit_failure_blocks_dispatch(tmp_path, search_args) -> None:
    adapter = CountingAdapter()
    with pytest.raises(OSError):
        await Gateway(adapter, SyntheticJudge(), Trace(tmp_path)).call(
            "public awards", _proposal(search_args)
        )
    assert adapter.calls == []


async def test_result_validation_failure_is_after_authorized_dispatch(search_args) -> None:
    adapter = CountingAdapter()
    adapter.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    trace = Trace()
    result = await Gateway(adapter, SyntheticJudge(), trace).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "PERMIT" and result.tool_executed
    assert len(adapter.calls) == 1
    assert result.status == "ERROR" and result.verification_state == "FAILED_VALIDATION"
    assert trace.events[1]["policy"]["decision"] == "PERMIT"
    assert trace.events[-1]["response"]["verification_state"] == "FAILED_VALIDATION"


def test_boundary_cannot_consume_missing_authority(search_args) -> None:
    with pytest.raises(ExecutionBoundaryError):
        _consume(ExecutionBoundary(), None, search_args)


@pytest.mark.parametrize("decision", ["DENY", "REVIEW_REQUIRED"])
def test_boundary_only_issues_for_its_own_permit_evaluation(search_args, decision) -> None:
    facts = PolicyFacts(
        tool="find_federal_awards",
        text="execute payment" if decision == "DENY" else "public awards",
        bounded=decision != "REVIEW_REQUIRED",
    )
    result = _evaluation(ExecutionBoundary(), search_args, facts=facts)
    assert result.policy.decision == decision
    assert result.envelope is None


def test_issued_binding_is_single_use(search_args) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    assert result.policy.decision == "PERMIT" and result.envelope is not None
    binding = _consume(boundary, result.envelope, search_args)
    assert binding is not None
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args)


def test_equal_reconstructed_envelope_is_not_trusted_provenance(search_args) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    forged = replace(result.envelope)
    assert forged == result.envelope and forged is not result.envelope
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, forged, search_args)


def test_different_policy_issuer_cannot_authorize_gateway_context(search_args) -> None:
    foreign = _evaluation(ExecutionBoundary(), search_args)
    with pytest.raises(ExecutionBoundaryError):
        _consume(ExecutionBoundary(), foreign.envelope, search_args)


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "synthetic-other-request"},
        {"tool": "summarize_federal_spending"},
        {"tool": "get_federal_award", "arguments": {"award_id": "1"}},
        {"policy_context": (False, True, 0.85, 0)},
        {"policy_context": (True, False, 0.85, 0)},
        {"policy_context": (True, True, 0.5, 0)},
        {"policy_context": (True, True, 0.85, 2)},
    ],
)
def test_exact_invocation_and_policy_context_substitution_fails(search_args, change) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args, **change)


@pytest.mark.parametrize(
    "field,value", [("state_code", "CA"), ("limit", 1), ("award_types", ["A"])]
)
def test_argument_tampering_fails(search_args, field, value) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    arguments = Search.model_validate(search_args).model_dump(mode="json")
    arguments[field] = value
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args, arguments=arguments)


def test_invalid_current_arguments_cannot_use_prior_schema_valid_receipt(search_args) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args, arguments={"authority": "PERMIT"})


def test_registry_schema_replacement_invalidates_prior_envelope(monkeypatch, search_args) -> None:
    registry = dict(TOOLS)
    boundary = ExecutionBoundary(registry)
    result = _evaluation(boundary, search_args)

    class ChangedSearch(Search):
        new_scope: str = "different-schema"

    monkeypatch.setitem(registry, "find_federal_awards", ChangedSearch)
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args)


def test_selected_model_schema_drift_invalidates_prior_envelope(monkeypatch, search_args) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    original_schema = Search.model_json_schema()
    altered_schema = deepcopy(original_schema)
    altered_schema["description"] = "A different applicable schema identity"
    monkeypatch.setattr(Search, "model_json_schema", classmethod(lambda cls: altered_schema))
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args)


async def test_transport_failure_preserves_permit_dispatch_and_unknown_result(
    monkeypatch, search_args
) -> None:
    monkeypatch.setattr(adapter_module, "MAX_ATTEMPTS", 1)
    adapter = CountingAdapter()

    def failed_read(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic transport timeout")

    adapter.transport = httpx.MockTransport(failed_read)
    trace = Trace()
    result = await Gateway(adapter, SyntheticJudge(), trace).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "PERMIT" and result.tool_executed
    assert len(adapter.calls) == 1 and result.attempt_count == 1
    assert result.dispatch_state == "DISPATCH_UNKNOWN"
    assert result.verification_state == "RESULT_UNKNOWN"
    assert result.result is None and result.status == "ERROR"
    assert trace.events[1]["policy"]["decision"] == "PERMIT"
    assert trace.events[-1]["pre_dispatch_verification"] == "PASS"
    assert trace.events[-1]["response"]["verification_state"] == "RESULT_UNKNOWN"


@pytest.mark.parametrize("elapsed", [30.0, 31.0, -1.0, float("nan"), float("inf")])
def test_expired_or_invalid_clock_cannot_authorize_dispatch(search_args, elapsed) -> None:
    now = [100.0]
    boundary = ExecutionBoundary(clock=lambda: now[0], max_age_seconds=30)
    result = _evaluation(boundary, search_args)
    now[0] += elapsed
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, result.envelope, search_args)


@pytest.mark.parametrize(
    "binding_patch",
    [
        {"operation_scope": "ADMINISTRATIVE_WRITE"},
        {"policy_decision": "DENY"},
        {"schema_sha256": "0" * 64},
        {"arguments_sha256": "0" * 64},
        {"policy_sha256": "0" * 64},
        {"policy_facts_sha256": "0" * 64},
    ],
)
def test_self_rehashed_forged_binding_does_not_authenticate_provenance(
    search_args, binding_patch
) -> None:
    boundary = ExecutionBoundary()
    result = _evaluation(boundary, search_args)
    substituted = replace(result.envelope.binding, **binding_patch)
    forged = replace(result.envelope, binding=substituted)
    # The replacement exposes a coherently recalculated digest, not trusted issuance.
    assert forged.binding.binding_sha256 != result.envelope.binding.binding_sha256
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, forged, search_args)


def test_envelope_and_binding_are_immutable(search_args) -> None:
    result = _evaluation(ExecutionBoundary(), search_args)
    with pytest.raises(FrozenInstanceError):
        result.envelope.decision = "DENY"
    with pytest.raises(FrozenInstanceError):
        result.envelope.binding.tool = "get_federal_award"


def test_outstanding_issuance_capacity_fails_closed(search_args) -> None:
    boundary = ExecutionBoundary()
    issued = [
        _evaluation(boundary, search_args, request_id=f"synthetic-capacity-{index}")
        for index in range(MAX_OUTSTANDING_ENVELOPES)
    ]
    with pytest.raises(ExecutionBoundaryError) as error:
        _evaluation(boundary, search_args, request_id="synthetic-over-capacity")
    assert error.value.code == "ISSUANCE_CAPACITY_EXCEEDED"
    # Capacity pressure cannot fabricate or corrupt the already issued authority.
    assert (
        _consume(boundary, issued[0].envelope, search_args, request_id="synthetic-capacity-0")
        is not None
    )


def test_expired_issuance_is_pruned_without_making_old_envelope_reusable(search_args) -> None:
    now = [100.0]
    boundary = ExecutionBoundary(clock=lambda: now[0], max_age_seconds=30)
    historical = _evaluation(boundary, search_args)
    now[0] = 130.0
    fresh = _evaluation(boundary, search_args)
    assert fresh.envelope is not historical.envelope
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, historical.envelope, search_args)
    assert _consume(boundary, fresh.envelope, search_args) is not None


@pytest.mark.parametrize("corruption", [float("nan"), {"not-json"}])
def test_corrupted_retained_envelope_serialization_fails_with_typed_error(
    search_args, corruption
) -> None:
    boundary = ExecutionBoundary()
    evaluation = _evaluation(boundary, search_args)
    # Fault injection tests corruption detection, not hostile Python sandboxing.
    object.__setattr__(evaluation.envelope, "issued_at", corruption)
    with pytest.raises(ExecutionBoundaryError) as error:
        _consume(boundary, evaluation.envelope, search_args)
    assert error.value.code == "ENVELOPE_BINDING_MISMATCH"
    with pytest.raises(ExecutionBoundaryError):
        _consume(boundary, evaluation.envelope, search_args)


async def test_config_drift_during_judge_cannot_reuse_initial_permit(search_args) -> None:
    adapter = CountingAdapter()

    class ReconfiguringJudge:
        async def assess(self, request, proposal):
            gateway.threshold = 0.1
            return GOOD.model_copy(deep=True)

    trace = Trace()
    gateway = Gateway(adapter, ReconfiguringJudge(), trace)
    result = await gateway.call("public awards", _proposal(search_args))
    assert not result.tool_executed and adapter.calls == []
    assert result.decision == "DENY"
    assert trace.events[-1]["pre_dispatch_verification"] == "FAIL"


@pytest.mark.parametrize("fault", ["missing", "forged", "expired"])
async def test_gate_rejects_missing_forged_or_stale_authority_immediately_before_backend(
    monkeypatch, search_args, fault
) -> None:
    adapter = CountingAdapter()
    now = [100.0]
    boundary = ExecutionBoundary(clock=lambda: now[0], max_age_seconds=30)
    trace = Trace()
    gateway = Gateway(adapter, SyntheticJudge(), trace)
    gateway._execution_boundary = boundary
    original_evaluate = boundary.evaluate

    def corrupt_evaluation(*args, **kwargs):
        evaluation = original_evaluate(*args, **kwargs)
        if fault == "missing":
            return replace(evaluation, envelope=None)
        if fault == "forged":
            return replace(evaluation, envelope=replace(evaluation.envelope))
        now[0] = 131.0
        return evaluation

    monkeypatch.setattr(boundary, "evaluate", corrupt_evaluation)
    result = await gateway.call("public awards", _proposal(search_args))
    assert result.decision == "DENY" and not result.tool_executed
    assert result.dispatch_state == "NOT_DISPATCHED" and adapter.calls == []
    assert trace.events[1]["policy"]["decision"] == "PERMIT"
    assert trace.events[-1]["pre_dispatch_verification"] == "FAIL"
    assert trace.events[-1]["response"]["decision"] == "DENY"
