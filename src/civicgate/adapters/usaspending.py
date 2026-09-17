import asyncio
import json
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from civicgate.models.provenance import Provenance, fingerprint, utcnow
from civicgate.models.requests import Award, Recipient, Search, StrictModel

BASE_URL = "https://api.usaspending.gov"
MAX_BYTES = 2_000_000


class AdapterError(Exception):
    def __init__(self, code: str, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


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


class USAspending:
    """Fixed public origin; never accepts URLs, credentials, or arbitrary REST paths."""

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, fixture: bool = False
    ) -> None:
        self.transport = transport
        self.fixture = fixture

    async def _request(self, path: str, payload: dict[str, Any] | None) -> tuple[Any, str]:
        method = "GET" if payload is None else "POST"
        query_hash = fingerprint({"method": method, "url": BASE_URL + path, "body": payload})
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(15, connect=5),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for attempt in range(3):
                try:
                    async with asyncio.timeout(20):
                        async with client.stream(
                            method,
                            BASE_URL + path,
                            json=payload,
                            headers={"Accept": "application/json"},
                        ) as response:
                            if response.status_code == 404:
                                raise AdapterError("NOT_FOUND")
                            if response.status_code == 429 or response.status_code >= 500:
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
                                return json.loads(body), query_hash
                            except (ValueError, UnicodeError) as exc:
                                raise AdapterError("MALFORMED_RESPONSE") from exc
                except (httpx.TimeoutException, TimeoutError) as exc:
                    error = AdapterError("TIMEOUT", True)
                    if attempt == 2:
                        raise error from exc
                except httpx.RequestError as exc:
                    error = AdapterError("NETWORK_ERROR", True)
                    if attempt == 2:
                        raise error from exc
                except AdapterError as exc:
                    if not exc.retryable or attempt == 2:
                        raise
                await asyncio.sleep(0.2 * (2**attempt))
        raise AdapterError("UPSTREAM_UNAVAILABLE", True)

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

    async def search(self, request: Search) -> DataBatch:
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
        raw, query_hash = await self._request(path, payload)
        try:
            data = SearchResponse.model_validate(raw)
            if len(data.results) > request.limit:
                raise ValueError("Upstream exceeded requested limit")
        except (ValidationError, ValueError) as exc:
            raise AdapterError("MALFORMED_RESPONSE") from exc
        records = [row.model_dump(mode="json") for row in data.results]
        if len({r["generated_internal_id"] for r in records}) != len(records):
            raise AdapterError("CONFLICTING_SOURCE_RESULTS")
        return self._batch(path, query_hash, raw, records, data.page_metadata.hasNext)

    async def recipients(self, request: Recipient) -> DataBatch:
        path = "/api/v2/recipient/"
        raw, query_hash = await self._request(
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
            data = RecipientResponse.model_validate(raw)
            if len(data.results) > request.limit:
                raise ValueError("Upstream exceeded requested limit")
        except (ValidationError, ValueError) as exc:
            raise AdapterError("MALFORMED_RESPONSE") from exc
        return self._batch(
            path,
            query_hash,
            raw,
            [r.model_dump(mode="json") for r in data.results],
            data.page_metadata.hasNext,
        )

    async def detail(self, request: Award) -> DataBatch:
        path = f"/api/v2/awards/{request.award_id}/"
        raw, query_hash = await self._request(path, None)
        try:
            data = DetailResponse.model_validate(raw)
            if request.award_id not in (str(data.id), data.generated_unique_award_id):
                raise ValueError("Award identifier mismatch")
        except (ValidationError, ValueError) as exc:
            raise AdapterError("MALFORMED_RESPONSE") from exc
        return self._batch(path, query_hash, raw, [data.model_dump(mode="json")], False)
