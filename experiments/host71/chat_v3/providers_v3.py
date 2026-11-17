"""Existing provider parsers behind durable one-send offline boundaries.

No genuine HTTP transport is constructed in this candidate. The same actual
Granite/NVIDIA/Luna serialization and parsing paths are exercised with mocks.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, TypedDict

import httpx
from demo_models_v1.contract import (
    ENDPOINTS,
    JUDGE,
    MODE,
    PLANNERS,
    DemoError,
    canonical,
    digest,
    require_offline,
)
from pydantic import BaseModel, SecretStr

from civicgate.llm.live import (
    LiveJudgeProvider,
    ProviderError,
    _BoundedClient,
)
from civicgate.models.requests import TOOLS, Proposal
from civicgate.runtime_config import SecretProvider
from evals.harness.live_attempt_budget_v1 import BudgetError, LiveAttemptBudget

from .chat_custody_v1 import ChatCustody
from .granite_contract_v2 import ScopedGranitePlanner
from .nvidia_contract_v2 import (
    NVIDIAPlannerConfigV1,
    NVIDIAPlannerError,
    NVIDIAPlannerProvider,
    _Attempt,
)
from .transport_profile_v1 import LiveAdmission

SCHEMA_SHA = digest(canonical({name: model.model_json_schema() for name, model in TOOLS.items()}))
MOCK_WIRE = "http://127.0.0.1:1"  # Documentary fixture marker; no socket is opened.


class RequestContext(TypedDict):
    observation_id: str
    role: str
    request_sha256: str
    schema_sha256: str
    logical_origin: str
    wire_fixture_origin: str
    effective_invocation_sha256: str | None


class Exchange:
    """Consumes one existing SQLite lease before a single MockTransport entry."""

    def __init__(
        self,
        budget: LiveAttemptBudget | ChatCustody,
        observation: str,
        provider: str,
        fixture: httpx.MockTransport | None,
        *,
        mode: str = MODE,
        seconds: float | None = None,
        effective_sha: str | None = None,
        admission: LiveAdmission | None = None,
    ) -> None:
        if provider not in ENDPOINTS:
            raise DemoError("HOST_PROVIDER_REQUIRED")
        self.mode, self.admission = mode, admission
        if mode == "LIVE":
            if fixture is not None or admission is None or type(budget) is not ChatCustody:
                raise DemoError("LIVE_CUSTODY_APPROVAL_AND_GENUINE_TRANSPORT_REQUIRED")
            admission.check()
            budget.verify_profile()
            if budget.mode != "LIVE" or budget.profile != admission.profile:
                raise DemoError("LIVE_PROFILE_CUSTODY_MISMATCH")
            if provider not in {budget.profile.planner, "judge"}:
                raise DemoError("UNAPPROVED_PROVIDER")
        else:
            require_offline(mode)
            if type(fixture) is not httpx.MockTransport or admission is not None:
                raise DemoError("EXPLICIT_OFFLINE_TRANSPORT_REQUIRED")
        self.schema_sha = SCHEMA_SHA
        self.budget, self.observation, self.provider = budget, observation, provider
        self.fixture = fixture
        self.seconds = (
            seconds
            if seconds is not None
            else (90.0 if provider == "granite" else 30.0 if provider == "judge" else 60.0)
        )
        self.effective_sha = effective_sha
        self.used = False
        self._wire_entered = False
        self.deadline: float | None = None
        self.facts: dict[str, Any] = {
            "mode": mode,
            "provider": provider,
            "reservation": None,
            "lease_consumed": False,
            "delegate_entries": 0,
            "response_observed": False,
            "custody_ack": False,
            "error": None,
            "stop_ack": False,
        }

    def stop(self, code: str) -> None:
        self.facts["error"] = code
        try:
            self.budget.stop(code)
            self.facts["stop_ack"] = True
        except BudgetError:
            self.facts["stop_ack"] = False

    def accept_typed(self) -> None:
        if self.deadline is None or time.monotonic() >= self.deadline:
            self.stop("LATE_TYPED_ACCEPTANCE")
            raise DemoError("LATE_TYPED_ACCEPTANCE")
        self.facts["typed_accepted"] = True

    async def post(self, payload: dict[str, Any], headers: dict[str, str]) -> tuple[bytes, int]:
        if self.used:
            raise DemoError("SEND_ALREADY_USED")
        self.used = True
        if self.admission is not None:
            self.admission.check()
        started = time.monotonic()
        deadline = started + self.seconds
        self.deadline = deadline
        role = "judge" if self.provider == "judge" else "planner"
        model = JUDGE if role == "judge" else PLANNERS[self.provider]
        if (
            payload.get("model") != model
            or payload.get("max_completion_tokens", payload.get("max_tokens")) != 512
        ):
            self.stop("REQUEST_IDENTITY_REJECTED")
            raise DemoError("REQUEST_IDENTITY_REJECTED")
        request = httpx.Request("POST", ENDPOINTS[self.provider], headers=headers, json=payload)
        if len(request.content) > 32_768:
            self.stop("REQUEST_SIZE_REJECTED")
            raise DemoError("REQUEST_SIZE_REJECTED")
        request_sha = digest(request.content)
        origin = (
            str(request.url.copy_with(path=""))[:-1]
            if str(request.url.copy_with(path="")).endswith("/")
            else str(request.url.copy_with(path=""))
        )
        kwargs: RequestContext = {
            "observation_id": self.observation,
            "role": role,
            "request_sha256": request_sha,
            "schema_sha256": self.schema_sha,
            "logical_origin": origin,
            "wire_fixture_origin": origin if self.mode == "LIVE" else MOCK_WIRE,
            "effective_invocation_sha256": self.effective_sha,
        }
        reservation = None
        try:
            self.budget.bind_request_context(**kwargs)
            reservation = self.budget.reserve(
                self.observation,
                role,
                model,
                request_sha,
                digest(canonical(payload["messages"])),
                self.schema_sha,
            )
            self.facts["reservation"] = reservation.attempt_id
            self.budget.start(reservation)
            receipt = self.budget.consume_send_lease(**kwargs)
            self.facts["lease_consumed"] = True
            self.facts["lease_id"] = receipt.lease_id
            if time.monotonic() >= deadline:
                raise TimeoutError
            async with asyncio.timeout_at(deadline):
                self.facts["delegate_entries"] += 1
                response = await self._send(request)
                # Mock transport may synchronously block; recheck absolute deadline.
                if time.monotonic() >= deadline:
                    raise TimeoutError
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 65_536:
                        raise DemoError("RESPONSE_SIZE_REJECTED")
                    raw.extend(chunk)
                await response.aclose()
                if time.monotonic() >= deadline:
                    raise TimeoutError
            self.facts.update(response_observed=True, http_status=response.status_code)
            self.budget.finish(
                reservation,
                "RESPONSE_OBSERVED",
                {
                    "provider": self.provider,
                    "http_status": response.status_code,
                    "delegate_entered": True,
                    "elapsed_ms": (time.monotonic() - started) * 1000,
                    "acceptance_state": "BODY_OBSERVED_NOT_YET_TYPED",
                },
            )
            self.facts["custody_ack"] = True
            if time.monotonic() >= deadline:
                self.stop("LATE_CUSTODY_ACK")
                raise DemoError("LATE_CUSTODY_ACK")
            self.facts["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
            return bytes(raw), response.status_code
        except BaseException as error:
            code = (
                "CANCELLED_DELIVERY_UNKNOWN"
                if isinstance(error, asyncio.CancelledError)
                else "DELIVERY_UNKNOWN"
                if isinstance(error, (TimeoutError, httpx.TransportError))
                else "CUSTODY_OR_RESPONSE_FAILURE"
            )
            if reservation is not None and not self.facts["custody_ack"]:
                try:
                    self.budget.finish(
                        reservation,
                        "COMPLETION_UNKNOWN",
                        {
                            "error_code": code,
                            "delegate_entered": self.facts["delegate_entries"] > 0,
                        },
                    )
                    self.facts["custody_ack"] = True
                except (BudgetError, ValueError):
                    pass
            self.stop(code)
            if isinstance(error, asyncio.CancelledError):
                raise asyncio.CancelledError() from None
            raise DemoError(code) from None

    async def _send(self, request: httpx.Request) -> httpx.Response:
        if self._wire_entered or not self.facts["lease_consumed"]:
            raise DemoError("WIRE_ATTEMPT_ALREADY_USED_OR_UNRESERVED")
        if self.mode != "LIVE":
            if type(self.fixture) is not httpx.MockTransport:
                raise DemoError("OFFLINE_TRANSPORT_REQUIRED")
            self._wire_entered = True
            return await self.fixture.handle_async_request(request)
        if self.admission is None or type(self.budget) is not ChatCustody:
            raise DemoError("LIVE_ADMISSION_REQUIRED")
        self.admission.check()
        self.budget.verify_profile()
        if not self.facts["lease_consumed"] or str(request.url) != ENDPOINTS[self.provider]:
            raise DemoError("LEASE_OR_ENDPOINT_MISMATCH")
        # No SDK, proxy inheritance, redirects, mounts, fallback or HTTP/2.
        # One client attempt is not a network-level exactly-once guarantee.
        self._wire_entered = True
        transport = httpx.AsyncHTTPTransport(
            retries=0,
            trust_env=False,
            http2=False,
            verify=True,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        request.extensions["timeout"] = {
            name: self.seconds for name in ("connect", "read", "write", "pool")
        }
        try:
            response = await transport.handle_async_request(request)
            raw = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 65536:
                        raise DemoError("RESPONSE_SIZE_REJECTED")
                    raw.extend(chunk)
            finally:
                await response.aclose()
            return httpx.Response(response.status_code, content=bytes(raw))
        finally:
            await transport.aclose()


class OneSendClient(_BoundedClient):
    """Injected at the existing client seam; never calls _BoundedClient retry loop."""

    def __init__(self, exchange: Exchange) -> None:
        self.exchange = exchange
        self.base_url = ENDPOINTS[exchange.provider].removesuffix("/chat/completions")
        self.max_attempts = 1

    async def post(
        self, path: str, *, headers: dict[str, str], payload: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if path != "/chat/completions":
            raise ProviderError("REQUEST_REJECTED", "Request rejected")
        raw, status = await self.exchange.post(payload, headers)
        if status != 200:
            raise ProviderError("PROVIDER_HTTP_ERROR", "Provider rejected request")
        try:
            body = json.loads(raw)
            model = JUDGE if self.exchange.provider == "judge" else PLANNERS[self.exchange.provider]
            if not isinstance(body, dict) or body.get("model") != model:
                raise ValueError
            choices = body.get("choices")
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            if (
                choice.get("finish_reason") != "stop"
                or choice["message"].get("tool_calls")
                or choice["message"].get("refusal")
            ):
                raise ValueError
            usage = body.get("usage")
            return body, usage if isinstance(usage, dict) else {}
        except (ValueError, KeyError, TypeError, AttributeError):
            self.exchange.stop("PROVIDER_RESPONSE_REJECTED")
            raise ProviderError(
                "MALFORMED_PROVIDER_RESPONSE", "Provider response rejected"
            ) from None


class CustodiedNvidia(NVIDIAPlannerProvider):
    def __init__(
        self, exchange: Exchange, secrets: SecretProvider, registry: Mapping[str, type[BaseModel]]
    ) -> None:
        super().__init__(
            NVIDIAPlannerConfigV1(provider="nvidia_cloud"),
            secret_provider=secrets,
            registry=registry,
        )
        self.exchange = exchange

    async def _exchange(
        self, payload: dict[str, Any], key: SecretStr, state: _Attempt
    ) -> bytes | None:
        state.attempts = 1
        state.delivery_state = "SEND_STARTED"
        raw, status = await self.exchange.post(
            payload, {"Authorization": "Bearer " + key.get_secret_value()}
        )
        state.http_status = status
        state.delivery_state = "BODY_OBSERVED"
        return raw if status == 200 else None


class Planner:
    def __init__(
        self,
        provider: str,
        exchange: Exchange,
        secrets: SecretProvider,
        *,
        registry: Mapping[str, type[BaseModel]],
    ) -> None:
        self.exchange = exchange
        self.registry = MappingProxyType(dict(registry))
        exchange.schema_sha = digest(
            canonical({name: model.model_json_schema() for name, model in self.registry.items()})
        )
        self.accepted: Proposal | None = None
        self.error: str | None = None
        self.inner: Any
        if provider == "granite":
            self.inner = ScopedGranitePlanner(
                "http://127.0.0.1:1234/v1", PLANNERS[provider], timeout=90, registry=self.registry
            )
            self.inner.client = OneSendClient(exchange)
        elif provider == "nemotron":
            self.inner = CustodiedNvidia(exchange, secrets, self.registry)
        else:
            raise DemoError("HOST_PLANNER_REQUIRED")

    async def propose(self, request: str) -> Proposal:
        try:
            proposal = await self.inner.propose(request)
            checked = Proposal.model_validate_json(proposal.model_dump_json(), strict=True)
            if checked.tool not in self.registry:
                raise ValueError
            self.registry[checked.tool].model_validate_json(
                json.dumps(checked.arguments), strict=True
            )
            self.exchange.accept_typed()
            self.accepted = checked.model_copy(deep=True)
            return checked
        except NVIDIAPlannerError as error:
            if error.delivery_unknown or error.code == "NVIDIA_MODEL_MISMATCH":
                self.exchange.stop("PLANNER_IDENTITY_OR_DELIVERY_UNCERTAIN")
            self.error = error.code
            raise DemoError(self.error) from None
        except Exception:
            self.error = "PLANNER_REJECTED"
            raise DemoError(self.error) from None


class Luna:
    """Called by Gateway.assess only after its genuine deterministic preflight."""

    def __init__(
        self,
        budget: LiveAttemptBudget | ChatCustody,
        observation: str,
        fixture: httpx.MockTransport | None,
        secrets: SecretProvider,
        *,
        admission: LiveAdmission | None = None,
        registry: Mapping[str, type[BaseModel]] = TOOLS,
    ) -> None:
        self.budget, self.observation, self.fixture, self.secrets = (
            budget,
            observation,
            fixture,
            secrets,
        )
        self.admission = admission
        self.registry = MappingProxyType(dict(registry))
        self.exchange: Exchange | None = None
        self.signal: dict[str, Any] | None = None
        self.raw_signal: dict[str, Any] | None = None
        self.flag_normalization: dict[str, Any] | None = None
        self.error: str | None = None

    async def assess(self, request: str, proposal: Proposal) -> Any:
        if self.exchange is not None:
            raise DemoError("JUDGE_ALREADY_CALLED")
        self.exchange = Exchange(
            self.budget,
            self.observation,
            "judge",
            self.fixture,
            mode="LIVE" if self.admission else MODE,
            admission=self.admission,
            effective_sha=digest(canonical(proposal.model_dump(mode="json"))),
        )
        self.exchange.schema_sha = digest(
            canonical({name: model.model_json_schema() for name, model in self.registry.items()})
        )
        key = self.secrets.get_secret("CIVICGATE_OPENAI_JUDGE_API_KEY")
        if not key:
            self.error = "JUDGE_CREDENTIAL_MISSING"
            raise DemoError(self.error)
        provider = LiveJudgeProvider(
            "https://api.openai.com/v1",
            JUDGE,
            key,
            openai_profile_id="j2-luna",
            provider_name="openai_luna",
        )
        provider.client = OneSendClient(self.exchange)
        try:
            signal = await provider.assess(request, proposal)
            # Mock fixture values are safe. Reject any literal credential echo.
            if key in signal.model_dump_json():
                raise ValueError
            from .judge_flags_v1 import VERSION, canonical_signal

            self.raw_signal = signal.model_dump(mode="json")
            signal = canonical_signal(signal)
            self.flag_normalization = {
                "version": VERSION,
                "applied": self.raw_signal["flags"] == ["NONE"],
                "raw_flags": list(self.raw_signal["flags"]),
                "canonical_flags": list(signal.flags),
            }
            self.exchange.accept_typed()
            self.signal = signal.model_dump(mode="json")
            return signal
        except Exception:
            self.error = "JUDGE_REJECTED"
            raise DemoError(self.error) from None
        finally:
            provider.api_key = ""
