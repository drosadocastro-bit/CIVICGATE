"""Channel B FAA-C1 synthetic adapter and trusted startup contract.

No live backend is supported. One MockTransport attempt; no retry or fallback.
The common deterministic policy remains the only execution authority.
"""

from dataclasses import dataclass
from time import monotonic

import httpx
from pydantic import BaseModel

from civicgate.adapters.usaspending import (
    AdapterCall,
    AdapterError,
    AttemptRecord,
    DataBatch,
    RequestOutcome,
    USAspending,
)
from civicgate.channel_b.faa_money_v1 import canonical_response_bytes, response_fingerprint
from civicgate.channel_b.faa_profile_v1 import (
    ENDPOINT,
    MAX_BYTES,
    CandidateValidationError,
    FaaScopeV1,
    parse_response_bytes,
    validate_synthetic_page,
)
from civicgate.channel_b.invocation_contract_v1 import InvocationContract
from civicgate.models.provenance import Provenance, utcnow


@dataclass(frozen=True)
class FaaResponseOutcome(RequestOutcome):
    """FAA-only original bytes for Gateway revalidation, not reconstructed JSON."""

    raw_response_bytes: bytes = b""


class FaaFixtureAdapter(USAspending):
    def __init__(self, transport: httpx.MockTransport) -> None:
        if type(transport) is not httpx.MockTransport:
            raise ValueError("FAA-C1 currently supports only synthetic MockTransport")
        super().__init__(transport=transport, fixture=True, max_attempts=1)

    async def find_faa(self, request: FaaScopeV1) -> AdapterCall:
        request = FaaScopeV1.model_validate(request.model_dump(mode="json"))
        payload = request.wire_bytes()
        query_hash = request.query_fingerprint()
        started = monotonic()
        response: httpx.Response | None = None
        status: int | None = None

        def attempt(
            error: BaseException | None = None, transport_error: bool = False
        ) -> AttemptRecord:
            return AttemptRecord(
                attempt=1,
                max_attempts=1,
                elapsed_ms=(monotonic() - started) * 1000,
                dispatch_state="REQUEST_CONFIRMED" if response is not None else "DISPATCH_UNKNOWN",
                response_state="TRANSPORT_ERROR" if transport_error else "RESPONSE_RECEIVED",
                exception_type=type(error).__name__ if error is not None else None,
                status_code=status,
                response_received=response is not None,
                retry_after_seconds=None,
                retry_decision="RETRY_BLOCKED" if error else "NONE",
                retry_reason="FAA-C1 single attempt; no retry" if error else "success",
            )

        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(15, connect=5),
            ) as client:
                async with client.stream(
                    "POST",
                    ENDPOINT,
                    content=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                ) as response:
                    status = response.status_code
                    if status != 200:
                        raise ValueError("FAA non-success HTTP response")
                    if (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                        != "application/json"
                    ):
                        raise ValueError("FAA non-JSON HTTP response")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise ValueError("FAA response size exceeded")
                    obj = parse_response_bytes(bytes(raw))
            if not isinstance(obj, dict) or not isinstance(obj.get("results"), list):
                raise ValueError("FAA response shape invalid")
            provenance = Provenance(
                source_system="CIVICGATE_TEST_FIXTURE",
                source_type="SYNTHETIC_TEST_FIXTURE",
                retrieved_at=utcnow(),
                query_fingerprint=query_hash,
                response_fingerprint=response_fingerprint(obj),
                endpoint=ENDPOINT,
                records_returned=len(obj["results"]),
                truncated=obj.get("page_metadata", {}).get("hasNext", False),
            )
            validated = validate_synthetic_page(
                request, bytes(raw), provenance, status_code=200, content_type="application/json"
            )
            batch = DataBatch(
                records=[r.model_dump(mode="json", exclude_unset=True) for r in validated.records],
                provenance=provenance,
            )
            return AdapterCall(
                batch=batch,
                outcome=FaaResponseOutcome(
                    raw=obj,
                    query_fingerprint=query_hash,
                    attempts=(attempt(),),
                    retry_class="UNSAFE",
                    raw_response_bytes=bytes(raw),
                ),
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise AdapterError(
                "TIMEOUT",
                attempts=(attempt(exc, True),),
                query_fingerprint=query_hash,
                retry_class="UNSAFE",
            ) from exc
        except httpx.RequestError as exc:
            raise AdapterError(
                "NETWORK_ERROR",
                attempts=(attempt(exc, True),),
                query_fingerprint=query_hash,
                retry_class="UNSAFE",
            ) from exc
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise AdapterError(
                "CONFLICTING_SOURCE_RESULTS",
                attempts=(attempt(exc),),
                query_fingerprint=query_hash,
                retry_class="UNSAFE",
            ) from exc


async def _find(adapter: USAspending, args: BaseModel) -> AdapterCall:
    if not isinstance(adapter, FaaFixtureAdapter):
        raise ValueError("FAA requires its synthetic Channel B adapter")
    return await adapter.find_faa(FaaScopeV1.model_validate(args.model_dump(mode="json")))


def _validate(args: BaseModel, call: AdapterCall) -> None:
    """Gateway-side independent check, including adapter projection and scope."""
    try:
        query = FaaScopeV1.model_validate(args.model_dump(mode="json"))
        if type(call.outcome) is not FaaResponseOutcome:
            raise ValueError("FAA original response bytes required")
        original = parse_response_bytes(call.outcome.raw_response_bytes)
        if canonical_response_bytes(original) != canonical_response_bytes(call.outcome.raw):
            raise ValueError("FAA raw evidence projection mismatch")
        page = validate_synthetic_page(
            query,
            call.outcome.raw_response_bytes,
            call.provenance,
            status_code=200,
            content_type="application/json",
        )
        if (
            call.outcome.query_fingerprint != query.query_fingerprint()
            or call.records != [r.model_dump(mode="json", exclude_unset=True) for r in page.records]
            or len(call.outcome.attempts) != 1
            or call.outcome.attempts[0].status_code != 200
            or call.outcome.attempts[0].dispatch_state != "REQUEST_CONFIRMED"
            or call.outcome.attempts[0].response_state != "RESPONSE_RECEIVED"
            or call.outcome.attempts[0].max_attempts != 1
            or call.outcome.attempts[0].attempt != 1
        ):
            raise ValueError("FAA adapter projection or attempt mismatch")
    except (ValueError, TypeError, AttributeError, CandidateValidationError) as exc:
        raise AdapterError(
            "CONFLICTING_SOURCE_RESULTS",
            attempts=call.outcome.attempts,
            query_fingerprint=call.outcome.query_fingerprint,
            retry_class="UNSAFE",
        ) from exc


FAA_C1 = InvocationContract(
    version="CHANNEL_B_FAA_C1_V1",
    find_model=FaaScopeV1,
    find_literal_fields=("awarding_agency",),
    find_handler=_find,
    validate_find_result=_validate,
)
