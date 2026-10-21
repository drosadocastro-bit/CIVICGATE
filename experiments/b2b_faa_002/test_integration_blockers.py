"""Tests of existing integration BLOCKERS, not a working FAA Gateway integration."""

import copy
import json
from types import MappingProxyType
from typing import Any

import pytest
from mcp.server.fastmcp.tools.base import Tool as RegisteredTool
from pydantic import ValidationError

from civicgate.audit.trace import Trace
from civicgate.governance.execution import ExecutionBoundary
from civicgate.governance.policy import PolicyFacts
from civicgate.mcp.discovery import BoundedToolDiscovery
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import TOOLS, Search
from experiments.b2b_faa_001.test_contract_characterization import (
    CONTEXT,
    OTHER,
    Capture,
    SyntheticJudge,
    arguments,
    response,
)
from experiments.b2b_faa_002.contract_v1 import (
    FAA,
    CandidateValidationError,
    FaaScopeV1,
    canonical,
    validate_synthetic_page,
)
from experiments.b2b_faa_002.test_contract_v1 import scope


def test_legacy_schema_does_not_represent_candidate_scope() -> None:
    with pytest.raises(ValidationError):
        Search.model_validate(scope().model_dump(mode="json"))
    assert set(TOOLS) == {
        "find_federal_awards",
        "get_federal_award",
        "resolve_federal_recipient",
        "summarize_federal_spending",
    }
    assert TOOLS["find_federal_awards"] is Search


async def test_actual_gateway_denies_full_candidate_before_dispatch() -> None:
    capture = Capture(response())
    result, trace = await capture.gateway(scope().model_dump(mode="json"))
    assert result.decision == "DENY" and "INVALID_INPUT" in result.governance.policy_reasons
    assert not result.tool_executed and capture.payloads == []
    event = next(e for e in trace.events if e["stage"] == "policy")
    assert event["binding_issued"] is False


def test_per_instance_boundary_registry_does_not_fix_global_r1_schema() -> None:
    snapshot = dict(TOOLS)
    local_registry = MappingProxyType(dict(TOOLS) | {"find_federal_awards": FaaScopeV1})
    boundary = ExecutionBoundary(local_registry)
    query = scope()
    request = f'Get public awards for agency "{FAA}".'
    evaluation = boundary.evaluate(
        request_id="SYNTHETIC-FAA-002-BLOCKER",
        facts=PolicyFacts(
            tool="find_federal_awards",
            text=request,
            request_text=request,
            arguments_json=query.effective_scope_json(),
        ),
        judge=JudgeSignal(
            available=True, classification="IN_SCOPE", confidence=1, provider="synthetic"
        ),
        agent_k=KSignal(),
        threshold=0.85,
        arguments=query.model_dump(mode="json"),
        policy_context=CONTEXT,
    )
    assert evaluation.policy.decision == "REVIEW_REQUIRED"
    assert "NAME_LITERAL_PROPOSAL_UNAVAILABLE" in evaluation.policy.reasons
    assert evaluation.envelope is None
    assert dict(TOOLS) == snapshot


def test_discovery_rejects_different_schema_without_global_mutation() -> None:
    capture = Capture(response())
    server = create_server(Gateway(capture.adapter, SyntheticJudge(), Trace()))
    registrations = list(server._tool_manager.list_tools())
    before = [r.parameters for r in registrations]

    def candidate_query(user_request: str, query: FaaScopeV1) -> dict[str, Any]:
        raise AssertionError("No dispatch is authorized or invoked by schema inspection")

    replaced = [
        RegisteredTool.from_function(candidate_query, name=r.name)
        if r.name == "find_federal_awards"
        else r
        for r in registrations
    ]
    with pytest.raises(ValueError, match="query schema mismatch"):
        BoundedToolDiscovery(replaced)
    assert [r.parameters for r in registrations] == before
    assert len(BoundedToolDiscovery(registrations).list_tools(registrations)) == 4
    assert capture.payloads == []


async def test_validation_failure_preserves_actual_legacy_authorized_read_history() -> None:
    # This is the OLD generic top-tier request, not FAA candidate integration.
    raw_body = response(OTHER, FAA) | {"spending_level": "awards", "limit": 20}
    capture = Capture(raw_body)
    result, trace = await capture.gateway(arguments())
    assert result.decision == "PERMIT" and result.tool_executed
    assert result.provenance is not None
    policy = next(e for e in trace.events if e["stage"] == "policy")
    assert policy["binding_issued"] is True
    assert trace.events[-1]["pre_dispatch_verification"] == "PASS"
    original = copy.deepcopy(trace.events)
    with pytest.raises(CandidateValidationError):
        validate_synthetic_page(
            scope(),
            canonical(raw_body).encode(),
            result.provenance,
            status_code=200,
            content_type="application/json",
        )
    assert trace.events == original and result.tool_executed
    assert len(capture.payloads) == 1
    assert capture.payloads[0]["filters"]["agencies"][0]["tier"] == "toptier"
    assert json.loads(policy["facts"]["arguments_json"]) == Search.model_validate(
        arguments()
    ).model_dump(mode="json")
