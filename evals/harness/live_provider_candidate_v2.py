"""EVAL-002B provider seam: exclusively owned synthetic HTTP, never live admission.

Logical provider labels preserve the unchanged request/prompt interfaces. They
are never network destinations here. Routing is synthetic at construction,
never a fallback after a live attempt. All costs and effective real identities
remain unknown. R4 role/deadline/unknown-custody behavior is reused unchanged.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from types import MappingProxyType
from typing import Any

import httpx

from civicgate.llm.live import GranitePlanner, LiveJudgeProvider
from civicgate.models.requests import Proposal
from evals.harness.bounded_provider_v3 import (
    BoundedProviderError,
    BoundProviders,
    BudgetedTransport,
    DeadlinePlan,
    _BoundJudge,
    _BoundPlanner,
    _judge_contract,
    _planner_contract,
)
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_composition_v3 import effective_invocation_digest
from evals.harness.live_http_transport_v1 import LiveHTTPTransport
from evals.harness.provider_response_admission_v2 import evaluate_response
from evals.harness.synthetic_http_server_v1 import SyntheticEndpoint, require_owned_endpoint

SYNTHETIC_PLANNER_MODEL = "SYNTHETIC_GRANITE_CONTRACT_STUB"


class ResponseAdmittedDelegate(httpx.AsyncBaseTransport):
    """Lower wire gate + acknowledged response facts, not typed acceptance."""

    def __init__(
        self, budget: LiveAttemptBudget, endpoint: SyntheticEndpoint, observation_id: str, role: str
    ) -> None:
        require_owned_endpoint(endpoint)
        self.budget = budget
        self.endpoint = endpoint
        self.observation_id = observation_id
        self.role = role
        self.logical_origin = (
            "http://127.0.0.1:1234" if role == "planner" else "https://api.openai.com"
        )
        self.wire: LiveHTTPTransport | None = None
        self.facts: dict[str, Any] | None = None
        self.facts_acknowledged = False

    def configure(self, schema_sha256: str, effective: str | None) -> None:
        if self.wire is not None:
            raise BoundedProviderError("DUPLICATE_DELEGATE_CONFIGURATION")
        self.wire = LiveHTTPTransport(
            self.budget,
            self.endpoint,
            observation_id=self.observation_id,
            role=self.role,
            schema_sha256=schema_sha256,
            logical_origin=self.logical_origin,
            effective_invocation_sha256=effective,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.wire is None:
            raise BoundedProviderError("UNCONFIGURED_WIRE_DELEGATE")
        response = await self.wire.handle_async_request(request)
        raw = await response.aread()
        model = SYNTHETIC_PLANNER_MODEL if self.role == "planner" else "gpt-5.6-luna"
        self.facts = evaluate_response(
            response.status_code, raw, requested_model=model, role=self.role
        )
        self.budget.record_response_facts(
            observation_id=self.observation_id,
            role=self.role,
            request_sha256=hashlib.sha256(request.content).hexdigest(),
            facts=self.facts,
        )
        self.facts_acknowledged = True
        # Even invalid contracts return their observed raw HTTP bytes to R4.
        # R4 records arrival/rejection; the final role guard below blocks acceptance.
        return response

    async def aclose(self) -> None:
        if self.wire is not None:
            await self.wire.aclose()


class AdmittedRoleTransport(BudgetedTransport):
    def __init__(
        self, delegate: ResponseAdmittedDelegate, budget: LiveAttemptBudget, **kwargs: Any
    ):
        super().__init__(delegate, budget, **kwargs)
        self.response_delegate = delegate
        self.effective_invocation_sha256: str | None = None

    def _guard(self, stage: str) -> float:
        now = super()._guard(stage)
        if stage == "PRE_DELEGATE":
            wire = self.response_delegate.wire
            if wire is None:
                raise BoundedProviderError("UNCONFIGURED_PRE_DISPATCH_WIRE")
            # Convert remaining injected evaluation time into an independent
            # real monotonic send deadline. The wire samples again after its
            # synchronous durable lease ACK; a slow ACK cannot authorize send.
            wire.arm_send_deadline(time.monotonic() + self._remaining())
        return now

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.integrity()
        if type(self.response_delegate) is not ResponseAdmittedDelegate or (
            self._delegate is not self.response_delegate
        ):
            self._stop("UNAPPROVED_RESPONSE_DELEGATE")
            raise BoundedProviderError("UNAPPROVED_RESPONSE_DELEGATE")
        if self._schema_sha256 is None:
            raise BoundedProviderError("UNARMED_REQUEST")
        if not isinstance(self.budget, LiveAttemptBudget):
            raise BoundedProviderError("LIVE_ADMISSION_BUDGET_REQUIRED")
        try:
            self.budget.bind_request_context(
                self.observation_id,
                self.role,
                hashlib.sha256(request.content).hexdigest(),
                self._schema_sha256,
                self.response_delegate.logical_origin,
                self.response_delegate.endpoint.origin,
                self.effective_invocation_sha256,
            )
            self._guard("REQUEST_CONTEXT_ACK")
            self.response_delegate.configure(self._schema_sha256, self.effective_invocation_sha256)
            return await super().handle_async_request(request)
        except BaseException:
            self._stop("ROLE_ADMISSION_OR_RESPONSE_FAILED")
            raise

    def accept_role(self) -> None:
        facts = self.response_delegate.facts
        if (
            not self.response_delegate.facts_acknowledged
            or not facts
            or facts["contract"] != "PASS"
        ):
            self._stop("RESPONSE_CONTRACT_NOT_ADMITTED")
            raise BoundedProviderError("RESPONSE_CONTRACT_NOT_ADMITTED")
        super().accept_role()


class CorrelatedJudge(_BoundJudge):
    async def assess(self, request: str, proposal: Proposal) -> Any:
        if not isinstance(self.transport, AdmittedRoleTransport):
            raise BoundedProviderError("CORRELATED_ROLE_TRANSPORT_REQUIRED")
        self.transport.effective_invocation_sha256 = effective_invocation_digest(request, proposal)
        return await super().assess(request, proposal)


def build_synthetic_http_providers(
    budget: LiveAttemptBudget,
    observation_id: str,
    planner_endpoint: SyntheticEndpoint,
    judge_endpoint: SyntheticEndpoint,
    *,
    deadlines: DeadlinePlan | None = None,
    monotonic: Callable[[], float] | None = None,
) -> BoundProviders:
    """No arbitrary URL, client, transport, credential or real activation argument."""
    if type(budget) is not LiveAttemptBudget:
        raise ValueError("EXACT_LIVE_ATTEMPT_BUDGET_REQUIRED")
    transports: dict[str, AdmittedRoleTransport] = {}
    for role, endpoint in (("planner", planner_endpoint), ("judge", judge_endpoint)):
        delegate = ResponseAdmittedDelegate(budget, endpoint, observation_id, role)
        transports[role] = AdmittedRoleTransport(
            delegate,
            budget,
            observation_id=observation_id,
            role=role,
            requested_model=SYNTHETIC_PLANNER_MODEL if role == "planner" else "gpt-5.6-luna",
            base_url=delegate.logical_origin + "/v1",
            deadlines=deadlines,
            monotonic=monotonic,
        )
    planner = GranitePlanner(
        "http://127.0.0.1:1234/v1", SYNTHETIC_PLANNER_MODEL, transport=transports["planner"]
    )
    judge = LiveJudgeProvider(
        "https://api.openai.com/v1",
        "gpt-5.6-luna",
        "SYNTHETIC_NOT_A_CREDENTIAL",
        openai_profile_id="j2-luna",
        transport=transports["judge"],
    )
    _, planner_schema = _planner_contract("", SYNTHETIC_PLANNER_MODEL)
    _, judge_schema = _judge_contract("", Proposal(tool="find_federal_awards", arguments={}))
    return BoundProviders(
        _BoundPlanner(planner, transports["planner"]),
        CorrelatedJudge(judge, transports["judge"]),
        transports["planner"],
        transports["judge"],
        MappingProxyType(
            {
                "planner_schema_sha256": planner_schema,
                "judge_schema_sha256": judge_schema,
            }
        ),
    )
