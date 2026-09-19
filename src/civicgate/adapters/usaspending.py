import asyncio
import json
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from math import isfinite
from time import monotonic
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from civicgate.models.provenance import Provenance, fingerprint, utcnow
from civicgate.models.requests import Award, Recipient, Search, StrictModel

BASE_URL = "https://api.usaspending.gov"
MAX_BYTES = 2_000_000
MAX_ATTEMPTS = 3
ATTEMPT_TIMEOUT_SECONDS = 20.0
RETRY_BACKOFF_SECONDS = (0.2, 0.4)
DEFAULT_RETRY_BUDGET_SECONDS = MAX_ATTEMPTS * ATTEMPT_TIMEOUT_SECONDS + sum(RETRY_BACKOFF_SECONDS)


DispatchState = Literal["DISPATCH_ATTEMPTED", "REQUEST_CONFIRMED", "DISPATCH_UNKNOWN"]
ResponseState = Literal["NO_RESPONSE", "RESPONSE_RECEIVED", "TRANSPORT_ERROR"]
RetryDecision = Literal["NONE", "RETRY_ALLOWED", "RETRY_BLOCKED"]


@dataclass(frozen=True)
class AttemptRecord:
    attempt: int
    max_attempts: int
    elapsed_ms: float
    dispatch_state: DispatchState
    response_state: ResponseState
    exception_type: str | None
    status_code: int | None
    response_received: bool
    retry_after_seconds: float | None
    retry_decision: RetryDecision
    retry_reason: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "elapsed_ms": self.elapsed_ms,
            "dispatch_state": self.dispatch_state,
            "response_state": self.response_state,
            "exception_type": self.exception_type,
            "status_code": self.status_code,
            "response_received": self.response_received,
            "retry_after_seconds": self.retry_after_seconds,
            "retry_decision": self.retry_decision,
            "retry_reason": self.retry_reason,
        }


@dataclass(frozen=True)
class RequestOutcome:
    raw: Any
    query_fingerprint: str
    attempts: tuple[AttemptRecord, ...]
    retry_class: str = "CONDITIONALLY_SAFE"


class AdapterError(Exception):
    def __init__(
        self,
        code: str,
        retryable: bool = False,
        *,
        attempts: tuple[AttemptRecord, ...] = (),
        query_fingerprint: str | None = None,
        retry_class: str = "CONDITIONALLY_SAFE",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.attempts = attempts
        self.query_fingerprint = query_fingerprint
        self.retry_class = retry_class


class UpstreamModel(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class Page(UpstreamModel):
    hasNext: bool = Field(strict=True)


class AwardRow(UpstreamModel):
    internal_id: int = Field(strict=True)
    generated_internal_id: str = Field(min_length=1, max_length=200)
    award_id: str | None = Field(alias="Award ID")
    recipient_name: str | None = Field(alias="Recipient Name")
    award_amount: Decimal = Field(alias="Award Amount")
    awarding_agency: str | None = Field(alias="Awarding Agency")


class SearchResponse(UpstreamModel):
    results: list[AwardRow] = Field(max_length=100)
    page_metadata: Page


class RecipientRow(UpstreamModel):
    id: str = Field(min_length=1, max_length=200)
    name: str | None
    uei: str | None
    recipient_level: Literal["R", "P", "C"]


class RecipientResponse(UpstreamModel):
    results: list[RecipientRow] = Field(max_length=25)
    page_metadata: Page


class DetailResponse(UpstreamModel):
    id: int = Field(strict=True)
    generated_unique_award_id: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    total_obligation: Decimal


class DataBatch(StrictModel):
    records: list[dict[str, Any]] = Field(max_length=100)
    provenance: Provenance


@dataclass(frozen=True)
class AdapterCall:
    batch: DataBatch
    outcome: RequestOutcome

    @property
    def records(self) -> list[dict[str, Any]]:
        return self.batch.records

    @property
    def provenance(self) -> Provenance:
        return self.batch.provenance

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.batch.model_dump(*args, **kwargs)


class USAspending:
    """Fixed public origin; never accepts URLs, credentials, or arbitrary REST paths."""

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, fixture: bool = False
    ) -> None:
        self.transport = transport
        self.fixture = fixture

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            seconds = float(value)
            if isfinite(seconds):
                return max(0.0, seconds)
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None

    async def _request(self, path: str, payload: dict[str, Any] | None) -> RequestOutcome:
        method = "GET" if payload is None else "POST"
        query_hash = fingerprint({"method": method, "url": BASE_URL + path, "body": payload})
        started = monotonic()
        attempts: list[AttemptRecord] = []
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                response: httpx.Response | None = None
                retry_after: float | None = None
                remaining = DEFAULT_RETRY_BUDGET_SECONDS - (monotonic() - started)
                if remaining <= 0:
                    # Budget exhausted before this attempt entered the transport boundary.
                    # No dispatch was attempted, so no attempt record is appended; the
                    # previous attempt's pending retry is what actually got blocked.
                    if attempts:
                        attempts[-1] = dataclass_replace(
                            attempts[-1],
                            retry_decision="RETRY_BLOCKED",
                            retry_reason="retry budget exhausted",
                        )
                    raise AdapterError(
                        "UPSTREAM_UNAVAILABLE",
                        False,
                        attempts=tuple(attempts),
                        query_fingerprint=query_hash,
                    )
                try:
                    async with asyncio.timeout(min(ATTEMPT_TIMEOUT_SECONDS, remaining)):
                        async with client.stream(
                            method,
                            BASE_URL + path,
                            json=payload,
                            headers={"Accept": "application/json"},
                        ) as response:
                            if response.status_code == 404:
                                raise AdapterError("NOT_FOUND")
                            if response.status_code == 429 or response.status_code >= 500:
                                retry_after = self._retry_after(response)
                                raise AdapterError("UPSTREAM_UNAVAILABLE", True)
                            if response.status_code != 200:
                                raise AdapterError("UPSTREAM_REJECTED")
                            if "application/json" not in response.headers.get("content-type", ""):
                                raise AdapterError("MALFORMED_RESPONSE")
                            body = bytearray()
                            async for chunk in response.aiter_bytes():
                                body.extend(chunk)
                                if len(body) > MAX_BYTES:
                                    raise AdapterError("RESPONSE_TOO_LARGE")
                            try:
                                attempts.append(
                                    AttemptRecord(
                                        attempt=attempt,
                                        max_attempts=MAX_ATTEMPTS,
                                        elapsed_ms=(monotonic() - started) * 1000,
                                        dispatch_state="REQUEST_CONFIRMED",
                                        response_state="RESPONSE_RECEIVED",
                                        exception_type=None,
                                        status_code=response.status_code,
                                        response_received=True,
                                        retry_after_seconds=None,
                                        retry_decision="NONE",
                                        retry_reason="success",
                                    )
                                )
                                return RequestOutcome(
                                    raw=json.loads(body),
                                    query_fingerprint=query_hash,
                                    attempts=tuple(attempts),
                                )
                            except (ValueError, UnicodeError) as exc:
                                raise AdapterError("MALFORMED_RESPONSE") from exc
                except (httpx.TimeoutException, TimeoutError) as exc:
                    error = AdapterError("TIMEOUT", True)
                    status_code = response.status_code if response is not None else None
                    dispatch_state: DispatchState = (
                        "REQUEST_CONFIRMED" if response is not None else "DISPATCH_UNKNOWN"
                    )
                    attempts.append(
                        AttemptRecord(
                            attempt=attempt,
                            max_attempts=MAX_ATTEMPTS,
                            elapsed_ms=(monotonic() - started) * 1000,
                            dispatch_state=dispatch_state,
                            response_state="TRANSPORT_ERROR",
                            exception_type=type(exc).__name__,
                            status_code=status_code,
                            response_received=response is not None,
                            retry_after_seconds=retry_after,
                            retry_decision=(
                                "RETRY_ALLOWED" if attempt < MAX_ATTEMPTS else "RETRY_BLOCKED"
                            ),
                            retry_reason="timeout",
                        )
                    )
                    if attempt == MAX_ATTEMPTS:
                        error.retryable = False
                        error.attempts = tuple(attempts)
                        error.query_fingerprint = query_hash
                        raise error from exc
                    delay = (
                        retry_after
                        if retry_after is not None
                        else RETRY_BACKOFF_SECONDS[attempt - 1]
                    )
                    if monotonic() - started + delay >= DEFAULT_RETRY_BUDGET_SECONDS:
                        error.retryable = False
                        attempts[-1] = dataclass_replace(
                            attempts[-1],
                            retry_decision="RETRY_BLOCKED",
                            retry_reason="retry budget exhausted",
                        )
                        error.attempts = tuple(attempts)
                        error.query_fingerprint = query_hash
                        raise error from exc
                    await asyncio.sleep(delay)
                except httpx.RequestError as exc:
                    error = AdapterError("NETWORK_ERROR", True)
                    status_code = response.status_code if response is not None else None
                    attempts.append(
                        AttemptRecord(
                            attempt=attempt,
                            max_attempts=MAX_ATTEMPTS,
                            elapsed_ms=(monotonic() - started) * 1000,
                            dispatch_state=(
                                "REQUEST_CONFIRMED" if response is not None else "DISPATCH_UNKNOWN"
                            ),
                            response_state="TRANSPORT_ERROR",
                            exception_type=type(exc).__name__,
                            status_code=status_code,
                            response_received=response is not None,
                            retry_after_seconds=None,
                            retry_decision=(
                                "RETRY_ALLOWED" if attempt < MAX_ATTEMPTS else "RETRY_BLOCKED"
                            ),
                            retry_reason="network error",
                        )
                    )
                    if attempt == MAX_ATTEMPTS:
                        error.retryable = False
                        error.attempts = tuple(attempts)
                        error.query_fingerprint = query_hash
                        raise error from exc
                    delay = RETRY_BACKOFF_SECONDS[attempt - 1]
                    if monotonic() - started + delay >= DEFAULT_RETRY_BUDGET_SECONDS:
                        error.retryable = False
                        attempts[-1] = dataclass_replace(
                            attempts[-1],
                            retry_decision="RETRY_BLOCKED",
                            retry_reason="retry budget exhausted",
                        )
                        error.attempts = tuple(attempts)
                        error.query_fingerprint = query_hash
                        raise error from exc
                    await asyncio.sleep(delay)
                except AdapterError as exc:
                    if exc.code == "UPSTREAM_UNAVAILABLE" and response is not None:
                        attempts.append(
                            AttemptRecord(
                                attempt=attempt,
                                max_attempts=MAX_ATTEMPTS,
                                elapsed_ms=(monotonic() - started) * 1000,
                                dispatch_state="REQUEST_CONFIRMED",
                                response_state="RESPONSE_RECEIVED",
                                exception_type=type(exc).__name__,
                                status_code=response.status_code,
                                response_received=True,
                                retry_after_seconds=retry_after,
                                retry_decision=(
                                    "RETRY_ALLOWED" if attempt < MAX_ATTEMPTS else "RETRY_BLOCKED"
                                ),
                                retry_reason="retryable upstream status",
                            )
                        )
                    else:
                        # Every AdapterError raised inside the stream context has a bound
                        # response; a missing response here means no confirmation exists.
                        attempts.append(
                            AttemptRecord(
                                attempt=attempt,
                                max_attempts=MAX_ATTEMPTS,
                                elapsed_ms=(monotonic() - started) * 1000,
                                dispatch_state=(
                                    "REQUEST_CONFIRMED"
                                    if response is not None
                                    else "DISPATCH_UNKNOWN"
                                ),
                                response_state=(
                                    "RESPONSE_RECEIVED" if response is not None else "NO_RESPONSE"
                                ),
                                exception_type=type(exc).__name__,
                                status_code=response.status_code if response is not None else None,
                                response_received=response is not None,
                                retry_after_seconds=retry_after,
                                retry_decision="NONE",
                                retry_reason=exc.code.lower(),
                            )
                        )
                    if not exc.retryable or attempt == MAX_ATTEMPTS:
                        exc.retryable = False if attempt == MAX_ATTEMPTS else exc.retryable
                        exc.attempts = tuple(attempts)
                        exc.query_fingerprint = query_hash
                        raise exc
                    delay = (
                        retry_after
                        if retry_after is not None
                        else RETRY_BACKOFF_SECONDS[attempt - 1]
                    )
                    if monotonic() - started + delay >= DEFAULT_RETRY_BUDGET_SECONDS:
                        attempts[-1] = dataclass_replace(
                            attempts[-1],
                            retry_decision="RETRY_BLOCKED",
                            retry_reason="retry budget exhausted",
                        )
                        exc.retryable = False
                        exc.attempts = tuple(attempts)
                        exc.query_fingerprint = query_hash
                        raise exc
                    await asyncio.sleep(delay)
        raise AdapterError(
            "UPSTREAM_UNAVAILABLE",
            False,
            attempts=tuple(attempts),
            query_fingerprint=query_hash,
        )

    def _batch(
        self, path: str, query_hash: str, raw: Any, records: list[dict[str, Any]], truncated: bool
    ) -> DataBatch:
        return DataBatch(
            records=records,
            provenance=Provenance(
                source_system="CIVICGATE_TEST_FIXTURE" if self.fixture else "USAspending",
                source_type="SYNTHETIC_TEST_FIXTURE" if self.fixture else "PUBLIC_GOVERNMENT_API",
                endpoint=BASE_URL + path,
                retrieved_at=utcnow(),
                query_fingerprint=query_hash,
                response_fingerprint=fingerprint(raw),
                records_returned=len(records),
                truncated=truncated,
            ),
        )

    async def search(self, request: Search) -> AdapterCall:
        path = "/api/v2/search/spending_by_award/"
        filters: dict[str, Any] = {
            "time_period": [
                {"start_date": str(request.start_date), "end_date": str(request.end_date)}
            ],
            "award_type_codes": request.award_types,
        }
        if request.recipient_name:
            filters["recipient_search_text"] = [request.recipient_name]
        if request.awarding_agency:
            filters["agencies"] = [
                {"type": "awarding", "tier": "toptier", "name": request.awarding_agency}
            ]
        if request.state_code:
            filters["place_of_performance_locations"] = [
                {"country": "USA", "state": request.state_code}
            ]
        payload = {
            "filters": filters,
            "fields": [
                "Award ID",
                "Recipient Name",
                "Award Amount",
                "Awarding Agency",
                "generated_internal_id",
            ],
            "page": 1,
            "limit": request.limit,
            "sort": "Award Amount",
            "order": "desc",
            "subawards": False,
        }
        outcome = await self._request(path, payload)
        try:
            data = SearchResponse.model_validate(outcome.raw)
            if len(data.results) > request.limit:
                raise ValueError("Upstream exceeded requested limit")
        except (ValidationError, ValueError) as exc:
            raise AdapterError(
                "MALFORMED_RESPONSE",
                attempts=outcome.attempts,
                query_fingerprint=outcome.query_fingerprint,
                retry_class=outcome.retry_class,
            ) from exc
        records = [row.model_dump(mode="json") for row in data.results]
        if len({r["generated_internal_id"] for r in records}) != len(records):
            raise AdapterError(
                "CONFLICTING_SOURCE_RESULTS",
                attempts=outcome.attempts,
                query_fingerprint=outcome.query_fingerprint,
                retry_class=outcome.retry_class,
            )
        return AdapterCall(
            self._batch(
                path,
                outcome.query_fingerprint,
                outcome.raw,
                records,
                data.page_metadata.hasNext,
            ),
            outcome,
        )

    async def recipients(self, request: Recipient) -> AdapterCall:
        path = "/api/v2/recipient/"
        outcome = await self._request(
            path,
            {
                "keyword": request.recipient_name,
                "limit": request.limit,
                "page": 1,
                "sort": "name",
                "order": "asc",
                "award_type": "all",
            },
        )
        try:
            data = RecipientResponse.model_validate(outcome.raw)
            if len(data.results) > request.limit:
                raise ValueError("Upstream exceeded requested limit")
        except (ValidationError, ValueError) as exc:
            raise AdapterError(
                "MALFORMED_RESPONSE",
                attempts=outcome.attempts,
                query_fingerprint=outcome.query_fingerprint,
                retry_class=outcome.retry_class,
            ) from exc
        return AdapterCall(
            self._batch(
                path,
                outcome.query_fingerprint,
                outcome.raw,
                [r.model_dump(mode="json") for r in data.results],
                data.page_metadata.hasNext,
            ),
            outcome,
        )

    async def detail(self, request: Award) -> AdapterCall:
        path = f"/api/v2/awards/{request.award_id}/"
        outcome = await self._request(path, None)
        try:
            data = DetailResponse.model_validate(outcome.raw)
            if request.award_id not in (str(data.id), data.generated_unique_award_id):
                raise ValueError("Award identifier mismatch")
        except (ValidationError, ValueError) as exc:
            raise AdapterError(
                "MALFORMED_RESPONSE",
                attempts=outcome.attempts,
                query_fingerprint=outcome.query_fingerprint,
                retry_class=outcome.retry_class,
            ) from exc
        return AdapterCall(
            self._batch(
                path,
                outcome.query_fingerprint,
                outcome.raw,
                [data.model_dump(mode="json")],
                False,
            ),
            outcome,
        )
