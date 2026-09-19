import httpx

from civicgate.adapters.usaspending import DataBatch, USAspending
from civicgate.audit.trace import Trace
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway
from civicgate.models.provenance import fingerprint
from civicgate.models.requests import Proposal, Search
from scripts.evaluate import assert_observed_receipt
from tests.fixture_transports import (
    build_transport,
    five_hundred_then_success,
    timeout_then_changed_snapshot,
)


def _proposal(search_args: dict[str, object]) -> Proposal:
    return Proposal(tool="find_federal_awards", arguments=search_args)


async def test_five_hundred_then_success_records_attempt_history(
    search_args: dict[str, object],
) -> None:
    trace = Trace()
    result = await Gateway(
        USAspending(five_hundred_then_success(), fixture=True), MockProvider(), trace
    ).call("Show public awards", _proposal(search_args))

    assert result.decision == "PERMIT"
    assert result.status == "OK"
    assert result.attempt_count == 2
    assert result.retry_class == "CONDITIONALLY_SAFE"
    assert result.attempt_metadata_available is True
    assert result.dispatch_state == "REQUEST_CONFIRMED"
    assert result.response_state == "RESPONSE_RECEIVED"
    attempts = trace.events[-1]["attempts"]
    assert attempts[0]["status_code"] == 500
    assert attempts[0]["retry_decision"] == "RETRY_ALLOWED"
    assert attempts[1]["status_code"] == 200
    assert attempts[1]["retry_decision"] == "NONE"


async def test_timeout_then_changed_snapshot_keeps_observable_receipt(
    search_args: dict[str, object],
) -> None:
    trace = Trace()
    result = await Gateway(
        USAspending(timeout_then_changed_snapshot(), fixture=True), MockProvider(), trace
    ).call("Show public awards", _proposal(search_args))

    assert result.status == "OK"
    assert result.verification_state == "RESULT_VERIFIED"
    assert result.attempt_count == 2
    attempts = trace.events[-1]["attempts"]
    assert attempts[0]["dispatch_state"] == "REQUEST_CONFIRMED"
    assert attempts[0]["response_state"] == "TRANSPORT_ERROR"
    assert attempts[0]["response_received"] is True
    assert attempts[1]["response_state"] == "RESPONSE_RECEIVED"
    assert_observed_receipt(
        {
            "attempt_count": 2,
            "verification_state": "RESULT_VERIFIED",
            "attempts": [
                {"response_state": "TRANSPORT_ERROR"},
                {"response_state": "RESPONSE_RECEIVED"},
            ],
        },
        result,
        trace,
    )


async def test_lane_b_malformed_response_is_execution_failure(
    search_args: dict[str, object],
) -> None:
    adapter = USAspending(
        httpx.MockTransport(lambda request: httpx.Response(200, json={})), fixture=True
    )
    result = await Gateway(adapter, MockProvider(), Trace()).call(
        "Show public awards", _proposal(search_args)
    )

    assert result.decision == "PERMIT"
    assert result.status == "ERROR"
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.validation_lane == "LANE_B_EXECUTION"
    assert result.validation_reason == "MALFORMED_RESPONSE"
    assert result.next_action == "STOP"


async def test_exhausted_timeout_reports_unknown_and_retry_blocked(
    search_args: dict[str, object],
) -> None:
    adapter = USAspending(
        httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("test"))),
        fixture=True,
    )
    trace = Trace()
    result = await Gateway(adapter, MockProvider(), trace).call(
        "Show public awards", _proposal(search_args)
    )

    assert result.status == "ERROR"
    assert result.verification_state == "RESULT_UNKNOWN"
    assert result.next_action == "RETRY_BLOCKED"
    assert result.attempt_count == 3
    assert result.errors[0].retryable is False
    assert trace.events[-1]["attempts"][-1]["retry_decision"] == "RETRY_BLOCKED"


async def test_lane_a_provenance_failure_requires_review(search_args: dict[str, object]) -> None:
    row = {
        "internal_id": 1,
        "generated_internal_id": "ONE",
        "Award ID": "1",
        "Recipient Name": "X",
        "Award Amount": 10,
        "Awarding Agency": "A",
    }
    adapter = USAspending(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "results": [row, row | {"Award Amount": 20}],
                    "page_metadata": {"hasNext": False},
                },
            )
        ),
        fixture=True,
    )
    result = await Gateway(adapter, MockProvider(), Trace()).call(
        "Show public awards", _proposal(search_args)
    )

    assert result.decision == "REVIEW_REQUIRED"
    assert result.status == "ERROR"
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.validation_lane == "LANE_A_RESOLVABILITY"
    assert result.validation_reason == "PROVENANCE_UNAVAILABLE"
    assert result.next_action == "HUMAN_REVIEW_REQUIRED"
    assert result.attempt_count == 1
    assert result.attempt_metadata_available is True


async def test_lane_a_gateway_revalidation_failure(search_args: dict[str, object]) -> None:
    class BrokenAdapter(USAspending):
        async def search(self, request: Search) -> DataBatch:
            return DataBatch.model_construct(records=[], provenance=None)

    result = await Gateway(BrokenAdapter(), MockProvider(), Trace()).call(
        "Show public awards", _proposal(search_args)
    )

    assert result.status == "ERROR"
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.validation_lane == "LANE_A_RESOLVABILITY"
    assert result.validation_reason == "ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"
    assert result.next_action == "HUMAN_REVIEW_REQUIRED"


async def test_legacy_adapter_has_explicit_unknown_attempt_metadata(
    search_args: dict[str, object],
) -> None:
    class LegacyAdapter(USAspending):
        async def search(self, request: Search) -> DataBatch:
            return DataBatch(
                records=[],
                provenance=self._batch("/legacy", fingerprint({}), {}, [], False).provenance,
            )

    result = await Gateway(LegacyAdapter(), MockProvider(), Trace()).call(
        "Show public awards", _proposal(search_args)
    )
    assert result.status == "OK"
    assert result.attempt_metadata_available is False
    assert result.retry_class == "UNKNOWN"
    assert result.dispatch_state == "DISPATCH_UNKNOWN"


def test_fixture_registry_has_both_stateful_factories() -> None:
    assert isinstance(build_transport("five_hundred_then_success"), httpx.MockTransport)
    assert isinstance(build_transport("timeout_then_changed_snapshot"), httpx.MockTransport)
