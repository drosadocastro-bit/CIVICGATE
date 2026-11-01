"""Evaluation-only end-to-end deadline candidate v3.

The offline factory accepts exact MockTransport delegates only. The generic
transport is an inspectable future composition seam, not live authorization.
Existing production prompts, parsing, policy and 30-second timeouts are reused.
An observed HTTP response is not an accepted typed result. SQLite records that
observation with acceptance pending; only a final in-memory role boundary can
confirm that the preceding synchronous custody ACK, parse, telemetry, client
lease teardown and snapshot finished before both absolute deadlines. No finite
write/ACK protocol can durably certify the timeliness of its own final ACK.
The last monotonic sample guards the program's return boundary; this is neither
OS preemption nor a hard real-time guarantee against descheduling after sampling.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from civicgate.llm.judge_profiles import select_openai_profile
from civicgate.llm.live import (
    JUDGE_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    GranitePlanner,
    LiveJudgeProvider,
    _JudgeSignalWire,
)
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from evals.harness.attempt_budget_v2 import AttemptBudget, AttemptReservation

Role = Literal["planner", "judge"]


class BoundedProviderError(RuntimeError):
    """Fixed, non-sensitive failure; never a retryable HTTP transport error."""


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DeadlinePlan:
    """Extra evaluation guards; production timeout values remain unchanged."""

    attempt_seconds: float = 1.0
    role_seconds: float = 2.0
    mcp_seconds: float = 4.0
    observation_seconds: float = 12.0

    def __post_init__(self) -> None:
        values = (
            self.attempt_seconds,
            self.role_seconds,
            self.mcp_seconds,
            self.observation_seconds,
        )
        if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("FINITE_POSITIVE_EVALUATION_DEADLINES_REQUIRED")
        if not all(a < b for a, b in zip(values, values[1:], strict=False)):
            raise ValueError("EVALUATION_DEADLINES_MUST_BE_ORDERED")


class BudgetedTransport(httpx.AsyncBaseTransport):
    """One reserved attempt; response custody precedes typed role acceptance.

    The attempt deadline continues through the whole bound role, rather than
    ending at HTTP response arrival. The optional clock is an evaluation seam
    for deterministic offline tests; asyncio cancellation remains cooperative.
    """

    def __init__(
        self,
        delegate: httpx.AsyncBaseTransport,
        budget: AttemptBudget,
        *,
        observation_id: str,
        role: Role,
        requested_model: str,
        base_url: str,
        deadlines: DeadlinePlan | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if role not in {"planner", "judge"}:
            raise ValueError("UNSUPPORTED_EVALUATION_ROLE")
        if not requested_model or len(requested_model) > 120:
            raise ValueError("PINNED_MODEL_ID_REQUIRED")
        # Durable admission fence precedes provider activity, including a
        # standalone transport call outside the complete composition.
        budget.begin_observation(observation_id)
        self._delegate = delegate
        self._pinned_delegate = delegate
        self.budget = budget
        self.observation_id = observation_id
        self.role = role
        self.requested_model = requested_model
        self.endpoint = base_url.rstrip("/") + "/chat/completions"
        self.deadlines = deadlines or DeadlinePlan()
        self._monotonic = monotonic or time.monotonic
        self._armed_payload: bytes | None = None
        self._schema_sha256: str | None = None
        self._entered = False
        self._stopped = False
        self._shutdown = False
        self._attempt_deadline: float | None = None
        self._role_deadline: float | None = None
        self._response_observed = False
        self._clock_started: float | None = None
        self.events: list[dict[str, Any]] = []
        self.acceptance: Mapping[str, Any] | None = None

    def begin_role(self) -> None:
        if self._role_deadline is not None:
            self._stop("DUPLICATE_LOGICAL_PROVIDER_CALL")
            raise BoundedProviderError("DUPLICATE_LOGICAL_PROVIDER_CALL")
        self._role_deadline = self._monotonic() + self.deadlines.role_seconds

    def arm(self, payload: dict[str, Any], schema_sha256: str) -> None:
        if self._entered or self._armed_payload is not None:
            self._stop("DUPLICATE_LOGICAL_PROVIDER_CALL")
            raise BoundedProviderError("DUPLICATE_LOGICAL_PROVIDER_CALL")
        if re.fullmatch(r"[0-9a-f]{64}", schema_sha256) is None:
            raise ValueError("SCHEMA_IDENTITY_REQUIRED")
        self._armed_payload = canonical(payload)
        self._schema_sha256 = schema_sha256

    def _stop(self, reason: str) -> None:
        self._stopped = True
        self.acceptance = None
        try:
            self.budget.stop(reason)
        except Exception:
            self.events.append({"event": "STOP", "reason": reason, "stop_persistence": "UNKNOWN"})
            raise BoundedProviderError("BUDGET_CUSTODY_UNAVAILABLE") from None
        self.events.append({"event": "STOP", "reason": reason, "stop_persistence": "PERSISTED"})

    def integrity(self) -> None:
        if self._delegate is not self._pinned_delegate or self._shutdown:
            self._stop("TRANSPORT_IDENTITY_CHANGED")
            raise BoundedProviderError("TRANSPORT_IDENTITY_CHANGED")

    def _expired(self, now: float) -> str | None:
        attempt = self._attempt_deadline is not None and now >= self._attempt_deadline
        role = self._role_deadline is not None and now >= self._role_deadline
        if attempt and role:
            return "ATTEMPT_AND_ROLE"
        return "ATTEMPT" if attempt else "ROLE" if role else None

    def _guard(self, stage: str) -> float:
        now = self._monotonic()
        expired = self._expired(now)
        if expired is not None:
            self.events.append(
                {
                    "event": "DEADLINE_REJECTED",
                    "stage": stage,
                    "expired_scope": expired,
                    "observed_monotonic": now,
                    "attempt_deadline": self._attempt_deadline,
                    "role_deadline": self._role_deadline,
                    "response_observed": self._response_observed,
                    "error_code": stage + "_AFTER_DEADLINE",
                }
            )
            raise BoundedProviderError(stage + "_AFTER_DEADLINE")
        return now

    def _remaining(self) -> float:
        ends = [x for x in (self._attempt_deadline, self._role_deadline) if x is not None]
        return max(0.0, min(ends) - self._monotonic())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._clock_started = self._monotonic()
        self._attempt_deadline = self._clock_started + self.deadlines.attempt_seconds
        if self._role_deadline is None:
            self._role_deadline = self._clock_started + self.deadlines.role_seconds
        clock = time.perf_counter()
        started = _now()
        self.integrity()
        if self._stopped or self._entered:
            raise BoundedProviderError("REISSUE_OR_STOPPED_TRANSPORT")
        if request.method != "POST" or str(request.url) != self.endpoint:
            self._stop("PROVIDER_ENDPOINT_OR_METHOD_MISMATCH")
            raise BoundedProviderError("PROVIDER_ENDPOINT_OR_METHOD_MISMATCH")
        try:
            payload = json.loads(request.content)
            matched = canonical(payload) == self._armed_payload
        except (ValueError, TypeError, UnicodeError):
            matched, payload = False, {}
        if not matched or payload.get("model") != self.requested_model:
            self._stop("PROVIDER_PAYLOAD_IDENTITY_MISMATCH")
            raise BoundedProviderError("PROVIDER_PAYLOAD_IDENTITY_MISMATCH")
        assert self._schema_sha256 is not None
        metadata: dict[str, Any] = {
            "provider": "lm_studio" if self.role == "planner" else "openai_compatible",
            "started_at_utc": started,
            "usage_state": "UNAVAILABLE_OR_UNCERTAIN",
            "delegate_entered": False,
            "cancellation_state": "NOT_CANCELLED",
            "deadline_disposition": "DEADLINE_NOT_YET_CONFIRMED",
            "acceptance_state": "NOT_ACCEPTED",
        }
        reservation: AttemptReservation | None = None
        start_attempted = False
        terminal_ack = False
        finish_attempted = False
        timeout_context: asyncio.Timeout | None = None

        def completion_fields() -> None:
            metadata["completed_at_utc"] = _now()
            metadata["elapsed_ms"] = (time.perf_counter() - clock) * 1000

        def finish(outcome: str) -> None:
            nonlocal terminal_ack, finish_attempted
            assert reservation is not None
            finish_attempted = True
            self.budget.finish(reservation, outcome, metadata)
            terminal_ack = True
            self.events.append({"event": "ATTEMPT_CUSTODY_ACK", "outcome": outcome, **metadata})

        try:
            reservation = self.budget.reserve(
                self.observation_id,
                self.role,
                self.requested_model,
                hashlib.sha256(request.content).hexdigest(),
                digest(payload["messages"]),
                self._schema_sha256,
                retry_count=0,
                retry_reason=None,
            )
            try:
                self._guard("RESERVATION_ACK")
            except BoundedProviderError:
                self._entered = True
                completion_fields()
                metadata.update(
                    deadline_disposition="RESERVATION_ACK_AFTER_DEADLINE_NO_SEND",
                    error_code="RESERVATION_ACK_AFTER_DEADLINE_NO_SEND",
                )
                finish("RESERVATION_NO_SEND")
                raise
            start_attempted = True
            self.budget.start(reservation)
            self._entered = True
            try:
                self._guard("START_ACK")
            except BoundedProviderError:
                completion_fields()
                metadata.update(
                    deadline_disposition="START_ACK_AFTER_DEADLINE_NO_DELEGATE_ENTRY",
                    error_code="START_ACK_AFTER_DEADLINE_NO_DELEGATE_ENTRY",
                )
                finish("COMPLETION_UNKNOWN")
                raise
            timeout_context = asyncio.timeout(self._remaining())
            async with timeout_context:
                self.budget.assert_active_observation(self.observation_id)
                self._guard("PRE_DELEGATE")
                metadata["delegate_entered"] = True
                response = await self._delegate.handle_async_request(request)
                self._response_observed = True
                metadata["http_status"] = response.status_code
                metadata["response_arrived_at_utc"] = _now()
                metadata["response_arrival_elapsed_ms"] = max(
                    0.0, (self._monotonic() - self._clock_started) * 1000
                )
                self._guard("PROVIDER_RESPONSE")
                raw = await response.aread()
                metadata["response_read_completed_at_utc"] = _now()
                self._guard("RESPONSE_READ")
            self._guard("RESPONSE_READ")
            if not 200 <= response.status_code < 300:
                raise BoundedProviderError("HTTP_RESPONSE_REJECTED")
            if len(raw) > 200_000:
                raise BoundedProviderError("PROVIDER_RESPONSE_TOO_LARGE")
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                body = None
            returned = body.get("model") if isinstance(body, dict) else None
            if returned != self.requested_model:
                if isinstance(returned, str):
                    metadata["returned_model_sha256"] = hashlib.sha256(
                        returned.encode()
                    ).hexdigest()
                raise BoundedProviderError("RETURNED_MODEL_IDENTITY_MISMATCH_OR_MISSING")
            metadata["returned_model"] = returned
            usage = body.get("usage") if isinstance(body, dict) else None
            if isinstance(usage, dict):
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = usage.get(key)
                    if type(value) is int and value >= 0:
                        metadata[key] = value
                if "prompt_tokens" in metadata and "completion_tokens" in metadata:
                    metadata["usage_state"] = "PROVIDER_REPORTED_NOT_BILLING_VERIFIED"
            correlation = response.headers.get("x-request-id", "")
            if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", correlation):
                metadata["provider_correlation_id"] = (
                    "sha256:" + hashlib.sha256(correlation.encode()).hexdigest()
                )
            completion_fields()
            self._guard("LOCAL_RESPONSE_PROCESSING")
            # This is a truthful durable transport observation, never a claim
            # that future custody, typed parsing or final acceptance succeeded.
            metadata["deadline_disposition"] = "ACCEPTANCE_PENDING_ROLE_PARSE_AND_FINAL_GUARD"
            metadata["acceptance_state"] = "PENDING_ROLE_AND_FINAL_GUARD"
            finish("RESPONSE_OBSERVED")
            self._guard("CUSTODY_ACK")
            self._guard("TRANSPORT_RETURN")
            return response
        except BaseException as exc:
            self._stopped = True
            self.acceptance = None
            completion_fields()
            code = (
                str(exc) if isinstance(exc, BoundedProviderError) else "PROVIDER_COMPLETION_UNKNOWN"
            )
            if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
                if (
                    isinstance(exc, TimeoutError)
                    and timeout_context is not None
                    and timeout_context.expired()
                ):
                    code = (
                        "EVALUATION_ROLE_DEADLINE"
                        if self._expired(self._monotonic()) == "ROLE"
                        else "EVALUATION_ATTEMPT_DEADLINE"
                    )
                else:
                    code = "PROVIDER_TIMEOUT"
            metadata["error_code"] = code
            if code.endswith("_AFTER_DEADLINE"):
                metadata["deadline_disposition"] = code
            elif isinstance(exc, TimeoutError):
                metadata["deadline_disposition"] = code
            if isinstance(exc, asyncio.CancelledError):
                metadata["cancellation_state"] = "CANCELLED_AFTER_RESERVATION"
            if finish_attempted and not terminal_ack:
                self.events.append(
                    {
                        "event": "ATTEMPT_CUSTODY_UNACKNOWLEDGED",
                        "response_observed": self._response_observed,
                    }
                )
                self._stop("BUDGET_CUSTODY_UNAVAILABLE")
                raise BoundedProviderError("BUDGET_CUSTODY_UNAVAILABLE") from None
            if reservation is not None and not terminal_ack:
                outcome = "RESPONSE_REJECTED" if self._response_observed else "COMPLETION_UNKNOWN"
                if code == "RETURNED_MODEL_IDENTITY_MISMATCH_OR_MISSING":
                    outcome = "MODEL_IDENTITY_REJECTED"
                if not start_attempted and not metadata["delegate_entered"]:
                    outcome = "RESERVATION_NO_SEND"
                try:
                    finish(outcome)
                except Exception:
                    self.events.append(
                        {
                            "event": "ATTEMPT_CUSTODY_UNACKNOWLEDGED",
                            "outcome": outcome,
                            "response_observed": self._response_observed,
                        }
                    )
                    self._stop("BUDGET_CUSTODY_UNAVAILABLE")
                    raise BoundedProviderError("BUDGET_CUSTODY_UNAVAILABLE") from None
            # An already-acknowledged RESPONSE_OBSERVED is not overwritten or
            # refunded if its ACK or later return guard proved late.
            self._stop(code)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise BoundedProviderError(code) from None

    def accept_role(self) -> None:
        """Publish acceptance only after all required potentially blocking work.

        Caller has exited its timeout context before entering this function.
        Snapshot is the last custody read. The final guard follows local event
        preparation; no I/O, await or external callback follows that sample.
        """
        self._guard("LOCAL_TYPED_PROCESSING")
        if not self._response_observed or not self._entered:
            raise BoundedProviderError("MISSING_ACKNOWLEDGED_PROVIDER_RESPONSE")
        state = self.budget.snapshot()
        self._guard("CUSTODY_SNAPSHOT")
        if self._stopped or state["stopped"]:
            raise BoundedProviderError("RUN_STOPPED_AFTER_RESPONSE")
        accepted: dict[str, Any] = {
            "event": "ROLE_ACCEPTED",
            "role": self.role,
            "deadline_disposition": "WITHIN_EVALUATION_DEADLINE",
            "acceptance_state": "ACCEPTED_AT_FINAL_ROLE_BOUNDARY",
            "response_observed": True,
        }
        # Snapshot may block, and local work may cross the boundary after the
        # preceding checkpoint. Sample again immediately before publication.
        accepted["accepted_monotonic"] = self._guard("FINAL_ACCEPTANCE")
        self.acceptance = MappingProxyType(accepted)
        self.events.append(accepted)

    async def aclose(self) -> None:
        # Production client-lease close is deliberately nonblocking. Owned
        # delegate cleanup is a later composition operation, not role acceptance.
        return None

    async def shutdown(self) -> None:
        if not self._shutdown:
            self._shutdown = True
            await self._delegate.aclose()


def _planner_contract(request: str, model: str) -> tuple[dict[str, Any], str]:
    schemas = {tool: schema.model_json_schema() for tool, schema in TOOLS.items()}
    prompt = (
        PLANNER_SYSTEM_PROMPT + " Registered tool schemas: " + json.dumps(schemas, sort_keys=True)
    )
    payload = {
        "model": model,
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": request},
        ],
    }
    return payload, digest({"tools": schemas, "proposal": Proposal.model_json_schema()})


def _judge_contract(request: str, proposal: Proposal) -> tuple[dict[str, Any], str]:
    schema = _JudgeSignalWire.model_json_schema()
    prompt = JUDGE_SYSTEM_PROMPT + json.dumps(schema, sort_keys=True)
    content = json.dumps({"request": request, "proposal": proposal.model_dump()}, sort_keys=True)
    return select_openai_profile("j2-luna").payload("gpt-5.6-luna", prompt, content), digest(schema)


class _BoundPlanner:
    def __init__(self, provider: GranitePlanner, transport: BudgetedTransport) -> None:
        self._provider = provider
        self.transport = transport

    def integrity(self) -> None:
        _provider_integrity(self._provider, self.transport)

    async def propose(self, request: str) -> Proposal:
        self.transport.begin_role()
        try:
            self.integrity()
            payload, schema = _planner_contract(request, self.transport.requested_model)
            self.transport.arm(payload, schema)
            self.transport._guard("ROLE_PREPARATION")
            async with asyncio.timeout(self.transport._remaining()):
                proposal = await self._provider.propose(request)
            self.transport.accept_role()
            return proposal
        except BaseException as exc:
            reason = (
                str(exc)
                if isinstance(exc, BoundedProviderError)
                else "PLANNER_ROLE_FAILED_OR_CANCELLED"
            )
            if isinstance(exc, TimeoutError):
                reason = "EVALUATION_ROLE_DEADLINE"
            self.transport._stop(reason)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise BoundedProviderError(reason) from None


class _BoundJudge:
    def __init__(self, provider: LiveJudgeProvider, transport: BudgetedTransport) -> None:
        self._provider = provider
        self.transport = transport

    @property
    def provider_name(self) -> str:
        return "evaluation_j2_luna"

    def integrity(self) -> None:
        _provider_integrity(self._provider, self.transport)
        if self._provider.openai_profile.profile_id != "j2-luna":
            self.transport._stop("JUDGE_PROFILE_CHANGED")
            raise BoundedProviderError("JUDGE_PROFILE_CHANGED")

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        self.transport.begin_role()
        try:
            self.integrity()
            payload, schema = _judge_contract(request, proposal)
            self.transport.arm(payload, schema)
            self.transport._guard("ROLE_PREPARATION")
            async with asyncio.timeout(self.transport._remaining()):
                signal = await self._provider.assess(request, proposal)
                if not signal.available:
                    raise BoundedProviderError("JUDGE_ASSESSMENT_UNAVAILABLE")
            self.transport.accept_role()
            return signal
        except BaseException as exc:
            reason = (
                str(exc)
                if isinstance(exc, BoundedProviderError)
                else "JUDGE_ROLE_FAILED_OR_CANCELLED"
            )
            if isinstance(exc, TimeoutError):
                reason = "EVALUATION_ROLE_DEADLINE"
            self.transport._stop(reason)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise BoundedProviderError(reason) from None


def _provider_integrity(
    provider: GranitePlanner | LiveJudgeProvider, transport: BudgetedTransport
) -> None:
    transport.integrity()
    if (
        provider.client.transport is not transport
        or provider.model != transport.requested_model
        or provider.client.base_url + "/chat/completions" != transport.endpoint
        or provider.client.max_attempts != 2
        or provider.client.timeout != 30.0
        or provider.protocol != "openai_compatible"
    ):
        transport._stop("PROVIDER_COMPOSITION_IDENTITY_CHANGED")
        raise BoundedProviderError("PROVIDER_COMPOSITION_IDENTITY_CHANGED")


@dataclass(frozen=True)
class BoundProviders:
    planner: _BoundPlanner
    judge: _BoundJudge
    planner_transport: BudgetedTransport
    judge_transport: BudgetedTransport
    contract_identities: Mapping[str, str]

    def integrity(self) -> None:
        self.planner.integrity()
        self.judge.integrity()

    async def shutdown(self) -> None:
        await self.planner_transport.shutdown()
        await self.judge_transport.shutdown()


def build_bound_providers(
    budget: AttemptBudget,
    observation_id: str,
    planner_model: str,
    planner_delegate: httpx.AsyncBaseTransport,
    judge_delegate: httpx.AsyncBaseTransport,
    *,
    deadlines: DeadlinePlan | None = None,
    planner_base_url: str = "http://127.0.0.1:1234/v1",
    monotonic: Callable[[], float] | None = None,
) -> BoundProviders:
    """Offline factory: no credential acquisition and no real-network delegates."""
    if (
        type(planner_delegate) is not httpx.MockTransport
        or type(judge_delegate) is not httpx.MockTransport
    ):
        raise ValueError("OFFLINE_FACTORY_REQUIRES_EXACT_MOCK_TRANSPORTS")
    parsed = urlparse(planner_base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("LOCAL_PLANNER_ENDPOINT_REQUIRED")
    plan = deadlines or DeadlinePlan()
    planner_transport = BudgetedTransport(
        planner_delegate,
        budget,
        observation_id=observation_id,
        role="planner",
        requested_model=planner_model,
        base_url=planner_base_url,
        deadlines=plan,
        monotonic=monotonic,
    )
    judge_transport = BudgetedTransport(
        judge_delegate,
        budget,
        observation_id=observation_id,
        role="judge",
        requested_model="gpt-5.6-luna",
        base_url="https://api.openai.com/v1",
        deadlines=plan,
        monotonic=monotonic,
    )
    planner = GranitePlanner(planner_base_url, planner_model, transport=planner_transport)
    judge = LiveJudgeProvider(
        "https://api.openai.com/v1",
        "gpt-5.6-luna",
        "SYNTHETIC_NOT_A_CREDENTIAL",
        openai_profile_id="j2-luna",
        transport=judge_transport,
    )
    _, planner_schema = _planner_contract("", planner_model)
    _, judge_schema = _judge_contract("", Proposal(tool="find_federal_awards", arguments={}))
    return BoundProviders(
        _BoundPlanner(planner, planner_transport),
        _BoundJudge(judge, judge_transport),
        planner_transport,
        judge_transport,
        MappingProxyType(
            {"planner_schema_sha256": planner_schema, "judge_schema_sha256": judge_schema}
        ),
    )
