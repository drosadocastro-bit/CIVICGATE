"""Execution-state receipts (Milestone 3, first slice).

Every assertion here is about something CivicGate can observe from its own transport
boundary. Hidden fixture facts — e.g. whether a retried read returned a different
snapshot than an attempt whose body was never received — are deliberately never asserted.
"""

import httpx

from civicgate.adapters.usaspending import DataBatch, USAspending
from civicgate.audit.trace import Trace
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway
from civicgate.models.provenance import fingerprint
from civicgate.models.requests import Proposal, Search
from tests.fixture_transports import build_transport

ROW = {
    "internal_id": 1,
    "generated_internal_id": "ONE",
    "Award ID": "1",
    "Recipient Name": "X",
    "Award Amount": 10,
    "Awarding Agency": "A",
}
ROW_BODY = {"results": [ROW], "page_metadata": {"hasNext": False}}


def _proposal(search_args: dict[str, object]) -> Proposal:
    return Proposal(tool="find_federal_awards", arguments=search_args)


def _attempts(gateway: Gateway) -> list[dict[str, object]]:
    completed = gateway.trace.events[-1]
    assert completed["stage"] == "completed"
    return completed["attempts"]


async def test_five_hundred_then_success_receipt(search_args: dict[str, object]) -> None:
    adapter = USAspending(build_transport("five_hundred_then_success"), fixture=True)
    gateway = Gateway(adapter, MockProvider(), Trace())
    result = await gateway.call("public awards", _proposal(search_args))
    assert result.decision == "PERMIT" and result.status == "OK" and result.tool_executed
    assert result.attempt_metadata_available and result.attempt_count == 2
    assert result.retry_class == "CONDITIONALLY_SAFE"
    assert result.dispatch_state == "REQUEST_CONFIRMED"
    assert result.response_state == "RESPONSE_RECEIVED"
    assert result.verification_state == "RESULT_VERIFIED"
    assert result.next_action == "NONE"
    attempts = _attempts(gateway)
    assert [a["status_code"] for a in attempts] == [500, 200]
    assert [a["retry_decision"] for a in attempts] == ["RETRY_ALLOWED", "NONE"]
    assert gateway.trace.events[-1]["attempt_metadata_available"] is True


async def test_timeout_then_retry_records_observable_trajectory_only(
    search_args: dict[str, object],
) -> None:
    adapter = USAspending(build_transport("timeout_then_changed_snapshot"), fixture=True)
    gateway = Gateway(adapter, MockProvider(), Trace())
    result = await gateway.call("public awards", _proposal(search_args))
    assert result.decision == "PERMIT" and result.status == "OK"
    assert result.attempt_count == 2 and result.verification_state == "RESULT_VERIFIED"
    first, second = _attempts(gateway)
    # Headers arrived before the body stream failed, so dispatch was confirmed.
    assert first["dispatch_state"] == "REQUEST_CONFIRMED"
    assert first["response_state"] == "TRANSPORT_ERROR"
    assert first["exception_type"] == "ReadTimeout"
    assert first["retry_decision"] == "RETRY_ALLOWED"
    assert second["status_code"] == 200 and second["retry_decision"] == "NONE"
    # Only the retry's body was ever observed; that is the data released.
    assert result.result["records"][0]["generated_internal_id"] == "CHANGED_AWARD_SNAPSHOT"


async def test_timeout_exhaustion_is_lane_b_and_blocks_retry(
    search_args: dict[str, object],
) -> None:
    """Exhaustion via attempt == MAX_ATTEMPTS, not the retry-budget check.

    This does NOT exercise the pre-loop `remaining <= 0` budget branch (fixed to no
    longer fabricate a DISPATCH_ATTEMPTED record) — see
    test_retry_budget_exhaustion_blocks_next_attempt_without_fake_record for that.
    """

    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test")

    adapter = USAspending(httpx.MockTransport(respond), fixture=True)
    gateway = Gateway(adapter, MockProvider(), Trace())
    result = await gateway.call("public awards", _proposal(search_args))
    # Transport failure never reclassifies authorization (Lane B).
    assert result.decision == "PERMIT" and result.status == "ERROR" and result.result is None
    assert result.errors[0].code == "TIMEOUT" and result.errors[0].retryable is False
    assert result.verification_state == "RESULT_UNKNOWN"
    assert result.validation_lane == "NONE"
    assert result.next_action == "RETRY_BLOCKED"
    assert result.attempt_count == 3
    assert result.dispatch_state == "DISPATCH_UNKNOWN"
    assert result.response_state == "TRANSPORT_ERROR"
    attempts = _attempts(gateway)
    assert [a["retry_decision"] for a in attempts] == [
        "RETRY_ALLOWED",
        "RETRY_ALLOWED",
        "RETRY_BLOCKED",
    ]
    assert all(a["dispatch_state"] == "DISPATCH_UNKNOWN" for a in attempts)


async def test_retry_after_header_is_recorded(search_args: dict[str, object]) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={})
        return httpx.Response(200, json=ROW_BODY)

    adapter = USAspending(httpx.MockTransport(respond), fixture=True)
    gateway = Gateway(adapter, MockProvider(), Trace())
    result = await gateway.call("public awards", _proposal(search_args))
    assert result.status == "OK" and result.attempt_count == 2
    first = _attempts(gateway)[0]
    assert first["status_code"] == 429 and first["retry_after_seconds"] == 0.0
    assert first["retry_decision"] == "RETRY_ALLOWED"


async def test_malformed_upstream_body_is_lane_b(search_args: dict[str, object]) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    adapter = USAspending(transport, fixture=True)
    result = await Gateway(adapter, MockProvider(), Trace()).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "PERMIT" and result.status == "ERROR"
    assert result.errors[0].code == "MALFORMED_RESPONSE"
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.validation_lane == "LANE_B_EXECUTION"
    assert result.validation_reason == "MALFORMED_RESPONSE"
    assert result.next_action == "STOP"
    assert result.attempt_metadata_available and result.attempt_count == 1
    assert result.dispatch_state == "REQUEST_CONFIRMED"
    assert result.response_state == "RESPONSE_RECEIVED"


async def test_conflicting_source_rows_are_lane_a(search_args: dict[str, object]) -> None:
    body = {"results": [ROW, ROW | {"Award Amount": 20}], "page_metadata": {"hasNext": False}}
    adapter = USAspending(httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    result = await Gateway(adapter, MockProvider(), Trace()).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "REVIEW_REQUIRED" and result.status == "ERROR"
    assert result.errors[0].code == "CONFLICTING_SOURCE_RESULTS"
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.validation_lane == "LANE_A_RESOLVABILITY"
    assert result.validation_reason == "PROVENANCE_UNAVAILABLE"
    assert result.next_action == "HUMAN_REVIEW_REQUIRED"
    assert result.attempt_count == 1


async def test_gateway_revalidation_failure_is_lane_a_without_attempt_metadata(
    search_args: dict[str, object],
) -> None:
    class BrokenAdapter(USAspending):
        async def search(self, request: Search) -> DataBatch:
            return DataBatch.model_construct(records=[], provenance=None)

    result = await Gateway(BrokenAdapter(), MockProvider(), Trace()).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "REVIEW_REQUIRED" and result.status == "ERROR"
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.validation_lane == "LANE_A_RESOLVABILITY"
    assert result.validation_reason == "ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"
    assert result.next_action == "HUMAN_REVIEW_REQUIRED"
    assert result.attempt_metadata_available is False and result.retry_class == "UNKNOWN"
    assert result.attempt_count == 0 and result.dispatch_state == "DISPATCH_UNKNOWN"


async def test_legacy_adapter_success_marks_metadata_unavailable(
    search_args: dict[str, object],
) -> None:
    class LegacyAdapter(USAspending):
        async def search(self, request: Search) -> DataBatch:
            raw = {"results": [], "page_metadata": {"hasNext": False}}
            return self._batch(
                "/api/v2/search/spending_by_award/", fingerprint({"legacy": True}), raw, [], False
            )

    result = await Gateway(LegacyAdapter(fixture=True), MockProvider(), Trace()).call(
        "public awards", _proposal(search_args)
    )
    assert result.decision == "PERMIT" and result.status == "OK"
    assert result.verification_state == "RESULT_VERIFIED"
    # No empty successful history is invented for an adapter without attempt metadata.
    assert result.attempt_metadata_available is False and result.retry_class == "UNKNOWN"
    assert result.attempt_count == 0 and result.dispatch_state == "DISPATCH_UNKNOWN"


async def test_held_calls_report_not_dispatched(
    gateway: Gateway, search_args: dict[str, object]
) -> None:
    denied = await gateway.call("blacklist this contractor", _proposal(search_args))
    assert denied.decision == "DENY" and denied.dispatch_state == "NOT_DISPATCHED"
    assert denied.next_action == "STOP" and denied.attempt_count == 0
    assert denied.verification_state == "UNVERIFIED"
    held = await gateway.call(
        "all federal awards",
        Proposal(
            tool="find_federal_awards",
            arguments={"start_date": "2025-01-01", "end_date": "2025-02-01"},
        ),
    )
    assert held.decision == "REVIEW_REQUIRED" and held.dispatch_state == "NOT_DISPATCHED"
    assert held.next_action == "HUMAN_REVIEW_REQUIRED"
    assert held.verification_state == "UNVERIFIED" and held.attempt_count == 0


async def test_retry_budget_exhaustion_blocks_next_attempt_without_fake_record(
    monkeypatch, search_args: dict[str, object]
) -> None:
    """Regression test for the DISPATCH_ATTEMPTED mislabeling fix.

    Forces the pre-loop `remaining <= 0` budget check to fire before a second
    attempt starts, by controlling `monotonic()` directly rather than relying on
    real wall-clock timing (which is indistinguishable, within scheduling noise,
    from the unrelated in-handler backoff-budget check that already existed and
    was never buggy). `monotonic()` is called 4 times during one failed-attempt
    cycle in the current implementation (started, pre-attempt remaining check,
    the attempt's elapsed_ms, the in-handler backoff-budget check); the 5th call
    is the pre-attempt check for the never-started second attempt, and that is the
    one this test needs to observe an exhausted budget. If `_request()`'s call
    count changes, this threshold needs updating alongside it.
    """
    import civicgate.adapters.usaspending as adapter_module

    calls = {"n": 0}

    def fake_monotonic() -> float:
        calls["n"] += 1
        return calls["n"] * 0.001 if calls["n"] <= 4 else 10_000.0

    monkeypatch.setattr(adapter_module, "monotonic", fake_monotonic)
    monkeypatch.setattr(adapter_module, "DEFAULT_RETRY_BUDGET_SECONDS", 1.0)
    monkeypatch.setattr(adapter_module, "RETRY_BACKOFF_SECONDS", (0.001, 0.001))

    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test")

    adapter = USAspending(httpx.MockTransport(respond), fixture=True)
    gateway = Gateway(adapter, MockProvider(), Trace())
    result = await gateway.call("public awards", _proposal(search_args))
    assert result.decision == "PERMIT" and result.status == "ERROR"
    assert result.next_action == "RETRY_BLOCKED"
    # Only the one real attempt happened; budget ran out before a second could start,
    # so no fabricated attempt record exists for the blocked second attempt.
    assert result.attempt_count == 1
    attempts = _attempts(gateway)
    assert len(attempts) == 1
    assert attempts[0]["dispatch_state"] == "DISPATCH_UNKNOWN"
    assert attempts[0]["retry_decision"] == "RETRY_BLOCKED"
    assert attempts[0]["retry_reason"] == "retry budget exhausted"
