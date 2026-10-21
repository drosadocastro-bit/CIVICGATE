"""Synthetic guard checks; these do not verify PostgreSQL engine properties.

The existing strict ledger model handles all ledger statements unchanged. This
test-local extension models only session identity and current-session advisory
lock inspection. Its pg_locks answers are inputs, not evidence about a server.
No network, driver, credentials or live model is used.
"""

import asyncio
from dataclasses import replace
from typing import Any

import httpx
import pytest

from civicgate.adapters.usaspending import AdapterError, USAspending
from civicgate.audit import postgres_journal as ledger
from civicgate.audit import postgres_transport_guard_v1 as module
from civicgate.audit.postgres_journal import PostgresDispatchJournal, provision_postgres_domain
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.governance.execution import ExecutionBoundary
from civicgate.governance.policy import PolicyFacts
from civicgate.llm.mock import MockProvider
from civicgate.mcp.http_identity import (
    InvocationContext,
    LocalHold,
    TrustDomain,
    invocation_context,
)
from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal, KSignal
from civicgate.models.requests import Award, Proposal
from tests.mcp.b2b_synthetic_postgres import (
    SyntheticConnection,
    SyntheticCursor,
    SyntheticPostgres,
)

REVISION = "a" * 40
SOURCE = "b" * 64
DOMAIN = TrustDomain(
    "https://guard-unit.invalid",
    "http://127.0.0.1:12345/mcp",
    "guard-unit-caller",
    "guard-unit-service",
    "guard-unit-instance",
)
DEFAULT = object()


class GuardDatabase(SyntheticPostgres):
    """A narrow extension; all original statements use the original model."""

    def connect(self):
        connection = GuardConnection(self, len(self.connections) + 1)
        self.connections.append(connection)
        return connection


class GuardConnection(SyntheticConnection):
    def __init__(self, store, identity):
        super().__init__(store, identity)
        self.session_row: Any = (identity, 16384, "synthetic", "synthetic_runtime", "start-1")
        self.lock_row: Any = DEFAULT
        self.after_commit = None
        self.cursors = []

    def cursor(self):
        self._check()
        cursor = GuardCursor(self)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        super().commit()
        hook, self.after_commit = self.after_commit, None
        if hook is not None:
            hook()


class GuardCursor(SyntheticCursor):
    def execute(self, statement, parameters=()):
        if statement not in {module.SQL_SESSION, module.SQL_OWNED_LOCK}:
            return super().execute(statement, parameters)
        connection = self.connection
        store = connection.store
        connection._check()
        assert not self.closed
        assert type(parameters) is tuple
        connection._begin()
        store.log.append((connection.identity, statement, parameters))
        fault = store.take_fault(statement, None, "disconnect")
        if fault:
            connection.close()
            raise fault.error("synthetic guard query disconnected")
        fault = store.take_fault(statement, None, "execute")
        if fault:
            raise fault.error("synthetic guard query failed")
        connection._statements.append(statement)
        self.rowcount = -1
        if statement == module.SQL_SESSION:
            assert not parameters
            self.rows = [connection.session_row]
            return None
        assert len(parameters) == 3
        if connection.lock_row is not DEFAULT:
            self.rows = [connection.lock_row]
            return None
        database, high, low = parameters
        unsigned = (high << 32) | low
        signed = unsigned if unsigned < 2**63 else unsigned - 2**64
        owned = (
            database == connection.session_row[1]
            and store.advisory_locks.get((signed,)) == connection.identity
        )
        self.rows = [(owned,)]
        return None


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, *, failure=None, cleanup_failure=None):
        self.calls = []
        self.closes = 0
        self.failure = failure
        self.cleanup_failure = cleanup_failure

    async def handle_async_request(self, request):
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        return httpx.Response(200, json={"synthetic": True})

    async def aclose(self):
        self.closes += 1
        if self.cleanup_failure is not None:
            raise self.cleanup_failure


@pytest.fixture(autouse=True)
def synthetic_identity(monkeypatch):
    # Unit fixtures do not claim to establish a repository source identity.
    monkeypatch.setattr(ledger, "read_source_identity", lambda revision: SOURCE)
    clock = [1000]
    monkeypatch.setattr(ledger, "time", lambda: clock[0])
    token = invocation_context.set(
        InvocationContext(
            DOMAIN.principal, DOMAIN.issuer, DOMAIN.audience, "session", "request", 1100
        )
    )
    try:
        yield clock
    finally:
        invocation_context.reset(token)


@pytest.fixture
def journal():
    store = GuardDatabase()
    provision_postgres_domain(store.connect, DOMAIN, REVISION)
    owner = PostgresDispatchJournal(store.connect, DOMAIN, REVISION, owner_id="guard-unit-owner")
    try:
        yield store, owner
    finally:
        owner.close()
        for connection in store.connections:
            connection.close()


def committed_intent(journal, request_id="guard-unit-request"):
    """Use original policy issuance and binding consumption for fixture intent."""
    boundary = ExecutionBoundary()
    policy_context = (False, False, 0.85, 0)
    arguments = {"award_id": "1"}
    evaluation = boundary.evaluate(
        request_id,
        PolicyFacts("get_federal_award", "Show public federal award", semantic_required=False),
        JudgeSignal(),
        KSignal(),
        0.85,
        arguments,
        policy_context,
    )
    assert evaluation.policy.decision == "PERMIT" and evaluation.envelope is not None
    journal.begin(request_id)
    journal.policy(
        request_id,
        {
            "initial_decision": evaluation.policy.decision,
            "reasons": evaluation.policy.reasons,
            "binding_issued": True,
            "binding_issuance_error": None,
        },
    )
    journal.intent(evaluation.envelope)
    boundary.consume(
        evaluation.envelope, request_id, "get_federal_award", arguments, policy_context
    )
    return request_id


def guard_for(journal, inner=None):
    inner = RecordingTransport() if inner is None else inner
    return module.GuardedPostgresTransport(journal, inner), inner


def request():
    return httpx.Request("GET", "https://unit-only.invalid/synthetic")


def assert_no_delegation(store, journal, inner, connection_count):
    assert not inner.calls
    assert journal.held
    assert journal._db is None
    assert len(store.connections) == connection_count
    assert all(cursor.closed for connection in store.connections for cursor in connection.cursors)


async def test_checkpoint_uses_existing_session_lock_and_commits_before_delegation(journal):
    store, owner = journal
    connection = owner._db

    class CheckingTransport(RecordingTransport):
        async def handle_async_request(self, request):
            assert connection.commits == previous_commits + 1
            assert owner.domain_key not in store.row_locks
            assert store.log[-1][1] == "COMMIT"
            return await super().handle_async_request(request)

    guard, inner = guard_for(owner, CheckingTransport())
    request_id = committed_intent(owner)
    checkpoint_start = len(store.log)
    previous_commits = connection.commits
    response = await guard.handle_async_request(request())
    assert response.status_code == 200 and len(inner.calls) == 1
    assert connection.commits == previous_commits + 1
    assert guard._delegated == {request_id}
    assert store.records(owner.domain_key)[-1]["kind"] == "intent"
    observed = [statement for _, statement, _ in store.log[checkpoint_start:]]
    assert ledger.SQL_LOCK not in observed
    assert observed[-1] == "COMMIT"
    assert observed.index(module.SQL_SESSION) < observed.index(module.SQL_OWNED_LOCK)
    parameters = next(
        parameters
        for _, statement, parameters in store.log[checkpoint_start:]
        if statement == module.SQL_OWNED_LOCK
    )
    key = int.from_bytes(bytes.fromhex(owner.domain_key)[:8], "big")
    assert parameters == (connection.session_row[1], key >> 32, key & 0xFFFFFFFF)


@pytest.mark.parametrize("stage", ["boot", "begin", "policy"])
async def test_direct_transport_without_committed_intent_is_held(journal, stage):
    store, owner = journal
    guard, inner = guard_for(owner)
    if stage != "boot":
        owner.begin("unready-request")
    if stage == "policy":
        owner.policy(
            "unready-request",
            {
                "initial_decision": "PERMIT",
                "reasons": ["BOUNDED_PUBLIC_RESEARCH"],
                "binding_issued": True,
                "binding_issuance_error": None,
            },
        )
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_INTENT_UNVERIFIED_OR_REUSED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"


@pytest.mark.parametrize(
    "row",
    [
        None,
        (),
        (1, 16384, "synthetic", "runtime"),
        [1, 16384, "synthetic", "runtime", "start"],
        (True, 16384, "synthetic", "runtime", "start"),
        (1, False, "synthetic", "runtime", "start"),
        (0, 16384, "synthetic", "runtime", "start"),
        (1, -1, "synthetic", "runtime", "start"),
        (1, 16384, "", "runtime", "start"),
        (1, 16384, "synthetic", None, "start"),
        (1, 16384, "synthetic", "runtime", ""),
    ],
)
def test_constructor_rejects_malformed_session_identity(journal, row):
    store, owner = journal
    connection = owner._db
    connection.session_row = row
    before = store.snapshot()
    with pytest.raises(LocalHold, match="POSTGRES_SESSION_UNVERIFIED"):
        guard_for(owner)
    assert connection.closed and owner.held and owner._db is None
    assert store.snapshot() == before
    assert all(cursor.closed for cursor in connection.cursors)


@pytest.mark.parametrize("field", range(5))
async def test_backend_identity_change_stops_before_lock_inspection(journal, field):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    connection = owner._db
    row = list(connection.session_row)
    row[field] = row[field] + 1 if field < 2 else row[field] + "-changed"
    connection.session_row = tuple(row)
    before = store.snapshot()
    start = len(store.log)
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_BACKEND_CHANGED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.snapshot() == before
    assert module.SQL_OWNED_LOCK not in [statement for _, statement, _ in store.log[start:]]


@pytest.mark.parametrize("row", [None, (), (1,), (0,), ("t",), (True, False), [True]])
async def test_malformed_lock_observation_never_records_a_safe_logical_rejection(journal, row):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    owner._db.lock_row = row
    before = store.snapshot()
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_LOCK_UNVERIFIED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.snapshot() == before


@pytest.mark.parametrize("holder", [None, 987654])
async def test_missing_or_other_session_lock_is_not_reacquired(journal, holder):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    connection = owner._db
    key = int.from_bytes(bytes.fromhex(owner.domain_key)[:8], "big", signed=True)
    if holder is None:
        del store.advisory_locks[(key,)]
    else:
        store.advisory_locks[(key,)] = holder
    start = len(store.log)
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_LOCK_LOST"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert connection.rollbacks == 1
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"
    assert ledger.SQL_LOCK not in [statement for _, statement, _ in store.log[start:]]


@pytest.mark.parametrize(
    "field,value",
    [
        ("domain", replace(DOMAIN, instance="other-generation")),
        ("domain", replace(DOMAIN, principal="other-principal")),
        ("domain_key", "0" * 64),
        ("owner_id", "other-owner"),
        ("code_revision", "c" * 40),
        ("source_sha256", "d" * 64),
        ("autocommit", True),
        ("closed", True),
        ("epoch", 999),
    ],
)
async def test_pinned_generation_and_transaction_mode_changes_stop_without_evidence_write(
    journal, field, value
):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    before = store.snapshot()
    if field == "autocommit":
        owner._db.autocommit = value
    elif field == "epoch":
        owner._state = replace(owner._state, epoch=value)
    else:
        setattr(owner, field, value)
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_SESSION_OR_GENERATION_CHANGED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.snapshot() == before


@pytest.mark.parametrize("index,value", [(0, "{}"), (1, "e" * 40), (2, "f" * 64)])
async def test_loaded_domain_or_source_contradiction_is_not_overwritten(journal, index, value):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    store.states[owner.domain_key][index] = value
    contradicted = store.snapshot()
    with pytest.raises(LocalHold, match="POSTGRES_DOMAIN_OR_SOURCE_MISMATCH"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.snapshot() == contradicted


async def test_connection_replacement_closes_pinned_and_unverified_sessions_without_querying(
    journal,
):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    pinned = owner._db
    replacement = store.connect()
    owner._db = replacement
    before = store.snapshot()
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_SESSION_OR_GENERATION_CHANGED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 3)
    assert pinned.closed and replacement.closed
    assert not replacement.cursors
    assert store.snapshot() == before


@pytest.mark.parametrize("phase", ["before_persist", "after_persist"])
async def test_checkpoint_commit_acknowledgment_loss_preserves_intent_and_blocks_delegation(
    journal, phase
):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    before = store.snapshot()
    store.fault(statement="COMMIT", phase=phase)
    with pytest.raises(LocalHold, match="POSTGRES_TRANSACTION_UNCONFIRMED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.snapshot() == before
    assert store.records(owner.domain_key)[-1]["kind"] == "intent"
    assert not guard._delegated


@pytest.mark.parametrize("statement", [module.SQL_SESSION, module.SQL_OWNED_LOCK])
@pytest.mark.parametrize("phase", ["execute", "disconnect"])
async def test_query_failure_never_writes_hold_through_an_unverified_session(
    journal, statement, phase
):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    before = store.snapshot()
    store.fault(statement=statement, phase=phase)
    with pytest.raises(LocalHold, match="POSTGRES_TRANSACTION_UNCONFIRMED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.snapshot() == before


async def test_context_expiry_after_acknowledged_checkpoint_commit_blocks_delegation(
    journal, synthetic_identity
):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    connection = owner._db
    previous_commits = connection.commits
    connection.after_commit = lambda: synthetic_identity.__setitem__(0, 1101)
    with pytest.raises(LocalHold, match="AUTH_CONTEXT_INVALID_OR_EXPIRED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    # One acknowledged read checkpoint, then the safe logical HOLD transaction.
    assert connection.commits == previous_commits + 2
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"
    assert not guard._delegated


async def test_context_replacement_after_acknowledged_checkpoint_commit_blocks_delegation(journal):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    current = invocation_context.get()
    owner._db.after_commit = lambda: invocation_context.set(replace(current, request="changed"))
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_CONTEXT_CHANGED"):
        await guard.handle_async_request(request())
    assert_no_delegation(store, owner, inner, 2)
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"
    assert not guard._delegated


@pytest.mark.parametrize("failure_type", [RuntimeError, ValueError, asyncio.CancelledError])
async def test_single_use_mark_survives_inner_exception_and_replay_is_held(journal, failure_type):
    store, owner = journal
    failure = failure_type("synthetic primary failure")
    guard, inner = guard_for(owner, RecordingTransport(failure=failure))
    request_id = committed_intent(owner)
    with pytest.raises(failure_type) as caught:
        await guard.handle_async_request(request())
    assert caught.value is failure
    assert guard._delegated == {request_id} and len(inner.calls) == 1
    assert store.records(owner.domain_key)[-1]["kind"] == "intent"
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_INTENT_UNVERIFIED_OR_REUSED"):
        await guard.handle_async_request(request())
    assert len(inner.calls) == 1 and owner.held
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"


async def test_completed_inner_response_does_not_allow_same_intent_twice(journal):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    await guard.handle_async_request(request())
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_INTENT_UNVERIFIED_OR_REUSED"):
        await guard.handle_async_request(request())
    assert len(inner.calls) == 1 and owner.held
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"


@pytest.mark.parametrize("primary_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_type", [RuntimeError, asyncio.CancelledError])
async def test_client_cleanup_failure_preserves_primary_exception(
    journal, primary_type, cleanup_type
):
    _, owner = journal
    primary = primary_type("synthetic primary failure")
    cleanup = cleanup_type("synthetic cleanup failure")
    guard, inner = guard_for(owner, RecordingTransport(failure=primary, cleanup_failure=cleanup))
    request_id = committed_intent(owner)
    with pytest.raises(primary_type) as caught:
        async with httpx.AsyncClient(transport=guard) as client:
            await client.get("https://unit-only.invalid/synthetic")
    assert caught.value is primary
    assert guard._delegated == {request_id}
    assert inner.closes == 1 and len(inner.calls) == 1


@pytest.mark.parametrize("cleanup_type", [RuntimeError, asyncio.CancelledError])
async def test_cleanup_failure_without_primary_error_records_hold_and_withholds_response(
    journal, cleanup_type
):
    store, owner = journal
    guard, inner = guard_for(
        owner, RecordingTransport(cleanup_failure=cleanup_type("synthetic cleanup failure"))
    )
    committed_intent(owner)
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_TRANSPORT_CLEANUP_FAILED"):
        async with httpx.AsyncClient(transport=guard) as client:
            await client.get("https://unit-only.invalid/synthetic")
    assert len(inner.calls) == inner.closes == 1 and owner.held
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"


async def test_cancellation_during_inner_await_retains_mark_and_cleanup_preserves_cancellation(
    journal,
):
    _, owner = journal
    started = asyncio.Event()
    blocked = asyncio.Event()

    class BlockingTransport(RecordingTransport):
        async def handle_async_request(self, request):
            self.calls.append(request)
            started.set()
            await blocked.wait()
            pytest.fail("Cancelled synthetic inner transport completed")

    guard, inner = guard_for(
        owner, BlockingTransport(cleanup_failure=RuntimeError("synthetic cleanup failure"))
    )
    request_id = committed_intent(owner)

    async def use_client():
        async with httpx.AsyncClient(transport=guard) as client:
            await client.get("https://unit-only.invalid/synthetic")

    task = asyncio.create_task(use_client())
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert guard._delegated == {request_id}
    assert len(inner.calls) == inner.closes == 1
    with pytest.raises(LocalHold, match="POSTGRES_GUARD_INTENT_UNVERIFIED_OR_REUSED"):
        await guard.handle_async_request(request())
    assert len(inner.calls) == 1 and owner.held


async def test_healthy_cleanup_forwards_without_closing_journal_or_claiming_completion(journal):
    store, owner = journal
    guard, inner = guard_for(owner)
    committed_intent(owner)
    before = store.snapshot()
    await guard.handle_async_request(request())
    await guard.aclose()
    await guard.aclose()
    assert len(inner.calls) == 1 and inner.closes == 2
    assert not owner.held and not owner.closed and owner._db is not None
    assert store.snapshot() == before
    assert store.records(owner.domain_key)[-1]["kind"] == "intent"


async def test_original_gateway_can_reuse_guard_after_each_healthy_client_cleanup(journal):
    store, owner = journal
    fixture = fixture_transport()

    class FixtureTransport(RecordingTransport):
        async def handle_async_request(self, request):
            self.calls.append(request)
            assert store.records(owner.domain_key)[-1]["kind"] == "intent"
            assert owner.active in guard._delegated
            return await fixture.handle_async_request(request)

    guard, inner = guard_for(owner, FixtureTransport())
    gateway = Gateway(
        USAspending(guard, True, max_attempts=1),
        MockProvider(),
        Trace(),
        dispatch_journal=owner,
    )
    for _ in range(2):
        result = await gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
        assert result.decision == "PERMIT" and result.tool_executed
        assert store.records(owner.domain_key)[-1]["kind"] == "finish"
        assert not owner.held and owner.active is None
    assert len(inner.calls) == inner.closes == len(guard._delegated) == 2
    assert len(store.connections) == 2


async def test_original_gateway_cancellation_records_hold_and_preserves_cancelled_error(journal):
    store, owner = journal
    started = asyncio.Event()
    blocked = asyncio.Event()

    class BlockingTransport(RecordingTransport):
        async def handle_async_request(self, request):
            self.calls.append(request)
            assert store.records(owner.domain_key)[-1]["kind"] == "intent"
            assert owner.active in guard._delegated
            started.set()
            await blocked.wait()
            pytest.fail("Cancelled Gateway inner transport completed")

    guard, inner = guard_for(
        owner, BlockingTransport(cleanup_failure=RuntimeError("synthetic cleanup failure"))
    )
    gateway = Gateway(
        USAspending(guard, True, max_attempts=1),
        MockProvider(),
        Trace(),
        dispatch_journal=owner,
    )
    task = asyncio.create_task(
        gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
    )
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(inner.calls) == inner.closes == len(guard._delegated) == 1
    assert owner.held and owner._db is None
    assert store.records(owner.domain_key)[-1]["kind"] == "hold"
    with pytest.raises(LocalHold):
        await gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
    assert len(inner.calls) == 1 and len(store.connections) == 2


class FailingBodyStream(httpx.AsyncByteStream):
    """Headers arrive, then the body raises independently of handle()."""

    def __init__(self, failure):
        self.failure = failure
        self.reads = 0
        self.closes = 0

    async def __aiter__(self):
        self.reads += 1
        yield b'{"id":1,'
        raise self.failure

    async def aclose(self):
        self.closes += 1


def gateway_with_failing_body(store, owner, failure):
    stream = FailingBodyStream(failure)

    class BodyTransport(RecordingTransport):
        async def handle_async_request(self, request):
            self.calls.append(request)
            assert store.records(owner.domain_key)[-1]["kind"] == "intent"
            assert owner.active in guard._delegated
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=stream,
                request=request,
            )

    guard, inner = guard_for(
        owner, BodyTransport(cleanup_failure=RuntimeError("synthetic cleanup failure"))
    )
    adapter = USAspending(guard, True, max_attempts=1)
    gateway = Gateway(adapter, MockProvider(), Trace(), dispatch_journal=owner)
    return gateway, guard, inner, stream


async def test_original_adapter_body_read_timeout_survives_transport_cleanup_failure(journal):
    store, owner = journal
    gateway, guard, inner, stream = gateway_with_failing_body(
        store, owner, httpx.ReadTimeout("synthetic body timeout")
    )
    request_id = committed_intent(owner)
    with pytest.raises(AdapterError) as caught:
        await gateway._adapter.detail(Award(award_id="1"))
    error = caught.value
    assert error.code == "TIMEOUT" and not error.retryable
    assert len(error.attempts) == 1
    attempt = error.attempts[0]
    assert attempt.attempt == attempt.max_attempts == 1
    assert attempt.dispatch_state == "REQUEST_CONFIRMED"
    assert attempt.response_state == "TRANSPORT_ERROR"
    assert attempt.response_received is True and attempt.status_code == 200
    assert attempt.exception_type == "ReadTimeout" and attempt.retry_decision == "RETRY_BLOCKED"
    assert len(inner.calls) == inner.closes == stream.reads == stream.closes == 1
    assert guard._delegated == {request_id} and len(store.connections) == 2
    assert store.records(owner.domain_key)[-1]["kind"] == "intent"


async def test_original_gateway_body_timeout_reaches_legacy_finish_and_fails_closed(
    journal, monkeypatch
):
    # The unguarded original adapter has the same established legacy fit gap:
    # headers received + TRANSPORT_ERROR is rejected by postgres_history._attempts.
    # Preserve that evidence and fail closed; do not normalize it or claim a returned Envelope.
    store, owner = journal
    gateway, guard, inner, stream = gateway_with_failing_body(
        store, owner, httpx.ReadTimeout("synthetic body timeout")
    )
    original_finish = owner.finish
    observed = []

    def observe_finish(envelope, denials, evidence):
        observed.append((envelope.model_copy(deep=True), evidence))
        original_finish(envelope, denials, evidence)

    monkeypatch.setattr(owner, "finish", observe_finish)
    with pytest.raises(LocalHold, match="^HISTORY_INVALID$"):
        await gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
    assert len(observed) == 1
    envelope, evidence = observed[0]
    assert envelope.status == "ERROR" and envelope.tool_executed
    assert [error.code for error in envelope.errors] == ["TIMEOUT"]
    assert all(not error.retryable for error in envelope.errors)
    assert envelope.result is None and envelope.provenance is None
    assert envelope.attempt_count == 1 and envelope.attempt_metadata_available
    assert envelope.dispatch_state == "REQUEST_CONFIRMED"
    assert envelope.response_state == "TRANSPORT_ERROR"
    attempt = evidence["attempts"][0]
    assert attempt["attempt"] == attempt["max_attempts"] == 1
    assert attempt["response_received"] is True and attempt["status_code"] == 200
    assert attempt["response_state"] == "TRANSPORT_ERROR"
    assert attempt["retry_decision"] == "RETRY_BLOCKED"
    assert len(inner.calls) == inner.closes == stream.reads == stream.closes == 1
    assert len(guard._delegated) == 1 and len(store.connections) == 2
    assert owner.held and owner._db is None
    preserved = store.snapshot()
    assert store.records(owner.domain_key)[-1]["kind"] == "intent"
    with pytest.raises(LocalHold):
        await gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
    assert len(inner.calls) == 1 and len(store.connections) == 2
    with pytest.raises(LocalHold, match="POSTGRES_RECOVERY_HOLD"):
        PostgresDispatchJournal(store.connect, DOMAIN, REVISION)
    assert store.snapshot() == preserved and len(inner.calls) == 1


async def test_original_gateway_body_cancellation_survives_transport_cleanup_failure(journal):
    store, owner = journal
    primary = asyncio.CancelledError("synthetic body cancellation")
    gateway, guard, inner, stream = gateway_with_failing_body(store, owner, primary)
    with pytest.raises(asyncio.CancelledError) as caught:
        await gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
    assert caught.value is primary
    assert len(inner.calls) == inner.closes == stream.reads == stream.closes == 1
    assert len(guard._delegated) == 1 and len(store.connections) == 2
    assert owner.held and owner._db is None
    hold = store.records(owner.domain_key)[-1]
    assert hold["kind"] == "hold" and hold["hold"] is True
    assert hold["dispatch_state"] == "DISPATCH_UNKNOWN"
    assert hold["response_state"] == "TRANSPORT_ERROR"
    with pytest.raises(LocalHold):
        await gateway.call(
            "Show public federal award",
            Proposal(tool="get_federal_award", arguments={"award_id": "1"}),
        )
    assert len(inner.calls) == 1 and len(store.connections) == 2
