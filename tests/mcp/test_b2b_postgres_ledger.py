"""Local/synthetic ledger protocol checks; no real PostgreSQL validation.

The immutable Gateway and ExecutionBoundary run with existing synthetic HTTP
adapter fixtures. Database statements are handled by an in-memory protocol model.
Passing these tests does not certify SQL execution, driver, WAL, storage, engine
locks, isolation, privileges, process-crash durability or distributed deployment.
"""

import asyncio
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from time import time

import httpx
import pytest

from civicgate.adapters.usaspending import USAspending
from civicgate.audit import postgres_journal as module
from civicgate.audit.postgres_journal import PostgresDispatchJournal, provision_postgres_domain
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp import tools
from civicgate.mcp.http_identity import (
    InvocationContext,
    LocalHold,
    TrustDomain,
    invocation_context,
)
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Proposal
from tests.mcp.b2b_synthetic_postgres import (
    REQUIRED_SETTINGS,
    SyntheticDatabaseError,
    SyntheticPostgres,
)

ROOT = Path(__file__).resolve().parents[2]
REVISION = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
DOMAIN = TrustDomain(
    "https://b2b-synthetic.invalid",
    "http://127.0.0.1:12345/mcp",
    "synthetic-caller",
    "synthetic-service",
    "synthetic-instance",
)
AWARD = Proposal(tool="get_federal_award", arguments={"award_id": "1"})


@pytest.fixture(autouse=True)
def authenticated_context():
    token = invocation_context.set(
        InvocationContext(
            DOMAIN.principal,
            DOMAIN.issuer,
            DOMAIN.audience,
            "session",
            "request",
            int(time()) + 240,
        )
    )
    try:
        yield
    finally:
        invocation_context.reset(token)


@pytest.fixture
def store():
    database = SyntheticPostgres()
    provision_postgres_domain(database.connect, DOMAIN, REVISION)
    return database


class Harness:
    def __init__(self, store, *, transport=None, domain=DOMAIN):
        self.store = store
        self.journal = PostgresDispatchJournal(store.connect, domain, REVISION)
        self.calls = []
        underlying = transport or fixture_transport()

        async def respond(request):
            self.calls.append(request.url.path)
            committed = store.records(self.journal.domain_key)
            assert committed[-1]["kind"] == "intent"
            return await underlying.handle_async_request(request)

        self.gateway = Gateway(
            USAspending(httpx.MockTransport(respond), True, max_attempts=1),
            MockProvider(),
            Trace(),
            dispatch_journal=self.journal,
        )


def assert_recovery_hold(store, *, domain=DOMAIN):
    """Two independent replacement sessions cannot alter unresolved evidence."""
    before = store.snapshot()
    for _ in range(2):
        with pytest.raises(LocalHold):
            PostgresDispatchJournal(store.connect, domain, REVISION)
        assert store.snapshot() == before


def test_sql_contract_requires_bound_full_owner_fence_and_complete_ordered_history():
    assert module.SQL_SETTINGS == REQUIRED_SETTINGS
    assert module.SQL_STATE.endswith("WHERE domain_key=%s FOR UPDATE")
    assert module.SQL_HISTORY.endswith("WHERE domain_key=%s ORDER BY sequence LIMIT %s")
    assert module.SQL_HISTORY.count("%s") == 2
    assert module.SQL_UPDATE.count("%s") == 15
    fence = module.SQL_UPDATE.split(" WHERE ", 1)[1]
    for clause in (
        "domain_key=%s",
        "epoch=%s",
        "owner_id IS NOT DISTINCT FROM %s",
        "owner_active=%s",
        "sequence=%s",
        "digest=%s",
        "source_revision=%s",
        "source_sha256=%s",
    ):
        assert clause in fence


async def test_valid_gateway_commit_precedes_original_binding_consume_and_dispatch(
    store, monkeypatch
):
    h = Harness(store)
    boundary = h.gateway._execution_boundary
    original_consume = boundary.consume
    consumed = []

    def consume(authority, *args, **kwargs):
        records = store.records(h.journal.domain_key)
        intent = records[-1]
        assert intent["kind"] == "intent"
        assert intent["request_id"] == authority.binding.request_id
        assert intent["authority"]["binding"]["binding_sha256"] == authority.binding.binding_sha256
        assert intent["authority"]["decision"] == "PERMIT"
        assert intent["dispatch_state"] == "NOT_DISPATCHED"
        assert id(authority) in boundary._issued
        consumed.append(authority)
        return original_consume(authority, *args, **kwargs)

    monkeypatch.setattr(boundary, "consume", consume)
    result = await h.gateway.call("Show public federal award", AWARD)
    assert result.decision == "PERMIT" and result.tool_executed
    assert len(consumed) == len(h.calls) == 1
    assert id(consumed[0]) not in boundary._issued
    finish = store.records(h.journal.domain_key)[-1]
    assert finish["kind"] == "finish" and finish["binding_consumption"] == "VERIFIED"
    assert finish["pre_dispatch_verification"] == "PASS"
    h.journal.close()
    successor = PostgresDispatchJournal(
        store.connect, replace(DOMAIN, instance="replacement-instance"), REVISION
    )
    assert successor.epoch == h.journal.epoch + 1
    assert not successor.held and successor.denials == 0
    successor.close()
    assert len(h.calls) == 1


async def test_deny_and_pre_dispatch_review_commit_no_intent_or_consume(store, monkeypatch):
    h = Harness(store)

    def forbidden(*args, **kwargs):
        pytest.fail("DENY/pre-dispatch REVIEW reached binding consumption")

    monkeypatch.setattr(h.gateway._execution_boundary, "consume", forbidden)
    deny = await h.gateway.call("blacklist this contractor", AWARD)
    assert deny.decision == "DENY" and not deny.tool_executed
    h.gateway._judge = UnavailableProvider()
    review = await h.gateway.call("Show public federal award", AWARD)
    assert review.decision == "REVIEW_REQUIRED" and not review.tool_executed
    records = store.records(h.journal.domain_key)
    policies = [event for event in records if event["kind"] == "policy"]
    assert [event["initial_decision"] for event in policies] == ["DENY", "REVIEW_REQUIRED"]
    assert all(not event["binding_issued"] for event in policies)
    assert not [event for event in records if event["kind"] == "intent"]
    assert not h.calls
    h.journal.close()


@pytest.mark.parametrize("phase", ["before_persist", "after_persist"])
async def test_uncertain_intent_commit_never_consumes_or_dispatches(store, monkeypatch, phase):
    h = Harness(store)

    def forbidden(*args, **kwargs):
        pytest.fail("Unacknowledged intent reached binding consumption")

    monkeypatch.setattr(h.gateway._execution_boundary, "consume", forbidden)
    store.fault(kind="intent", phase=phase)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert h.journal.held and not h.calls
    intents = [event for event in store.records(h.journal.domain_key) if event["kind"] == "intent"]
    assert len(intents) == (phase == "after_persist")
    connections_before = len(store.connections)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert len(store.connections) == connections_before
    h.journal.close()
    assert_recovery_hold(store)
    assert not h.calls


@pytest.mark.parametrize("point", ["begin", "intent", "finish"])
@pytest.mark.parametrize("error", [SyntheticDatabaseError, ValueError, TypeError])
async def test_database_statement_failures_are_wrapped_and_withhold_result(store, point, error):
    h = Harness(store)
    store.fault(statement=module.SQL_EVENT, kind=point, error=error)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert h.journal.held
    assert len(h.calls) == (point == "finish")
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    h.journal.close()
    assert_recovery_hold(store)
    assert len(h.calls) == (point == "finish")


@pytest.mark.parametrize("point", ["begin", "intent", "finish"])
async def test_terminated_connection_never_reconnects_or_releases_result(store, point):
    h = Harness(store)
    store.fault(statement=module.SQL_EVENT, kind=point, phase="disconnect")
    connection_count = len(store.connections)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert h.journal.held and len(h.calls) == (point == "finish")
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert len(store.connections) == connection_count
    h.journal.close()
    assert_recovery_hold(store)
    assert len(h.calls) == (point == "finish")


@pytest.mark.parametrize("phase", ["before_persist", "after_persist"])
async def test_finish_commit_ack_loss_withholds_result_after_one_dispatch(store, phase):
    h = Harness(store)
    store.fault(kind="finish", phase=phase)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert h.journal.held and len(h.calls) == 1
    h.journal.close()
    assert_recovery_hold(store)
    assert len(h.calls) == 1


async def test_conditional_owner_projection_update_failure_rolls_back_intent(store, monkeypatch):
    h = Harness(store)
    original_intent = h.journal.intent

    def fail_projection(authority):
        store.fault(statement=module.SQL_UPDATE, phase="rowcount_zero")
        original_intent(authority)

    monkeypatch.setattr(h.journal, "intent", fail_projection)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert h.journal.held and not h.calls
    assert not [event for event in store.records(h.journal.domain_key) if event["kind"] == "intent"]
    h.journal.close()
    assert_recovery_hold(store)


async def test_synthetic_connection_crash_after_intent_never_replays(store, monkeypatch):
    h = Harness(store)

    class SyntheticCrash(BaseException):
        pass

    def crash_before_consume(*args, **kwargs):
        assert store.records(h.journal.domain_key)[-1]["kind"] == "intent"
        store.connections[-1].close()
        raise SyntheticCrash()

    monkeypatch.setattr(h.gateway._execution_boundary, "consume", crash_before_consume)
    with pytest.raises(SyntheticCrash):
        await h.gateway.call("Show public federal award", AWARD)
    assert not h.calls
    assert store.records(h.journal.domain_key)[-1]["kind"] == "intent"
    h.journal.close()
    assert_recovery_hold(store)
    assert not h.calls


def test_two_instances_contend_for_one_stable_domain_and_clean_close_releases_owner(store):
    first = PostgresDispatchJournal(store.connect, DOMAIN, REVISION)
    second_domain = replace(DOMAIN, instance="second-process-instance")
    assert module.domain_identity(second_domain) == first.domain_key
    before = store.snapshot()
    with pytest.raises(LocalHold):
        PostgresDispatchJournal(store.connect, second_domain, REVISION)
    assert store.snapshot() == before
    assert len(store.advisory_locks) == 1
    first.close()
    second = PostgresDispatchJournal(store.connect, second_domain, REVISION)
    assert second.epoch == first.epoch + 1
    second.close()
    assert not store.advisory_locks
    for connection in store.connections:
        locks = [
            sql
            for identity, sql, _ in store.log
            if identity == connection.identity and sql == module.SQL_LOCK
        ]
        assert len(locks) <= 1


@pytest.mark.parametrize("field,value", [(3, 99), (4, "foreign-owner"), (5, False)])
def test_stale_owner_is_fenced_before_admission_or_new_evidence(store, field, value):
    journal = PostgresDispatchJournal(store.connect, DOMAIN, REVISION)
    store.states[journal.domain_key][field] = value
    before = store.snapshot()
    with pytest.raises(LocalHold):
        journal.admit()
    assert journal.held
    with pytest.raises(LocalHold):
        journal.begin("must-not-open")
    assert store.snapshot() == before
    journal.close()


async def test_duplicate_request_identifier_is_rejected_without_second_dispatch(store, monkeypatch):
    h = Harness(store)
    monkeypatch.setattr(tools, "uuid4", lambda: "synthetic-fixed-request")
    first = await h.gateway.call("Show public federal award", AWARD)
    assert first.tool_executed
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    assert len(h.calls) == 1 and h.journal.held
    records = store.records(h.journal.domain_key)
    assert len([event for event in records if event["kind"] == "begin"]) == 1
    assert len([event for event in records if event["kind"] == "intent"]) == 1
    h.journal.close()
    assert_recovery_hold(store)


async def test_denial_containment_restores_across_clean_instance_restart(store):
    h = Harness(store)
    for _ in range(2):
        result = await h.gateway.call("blacklist this contractor", AWARD)
        assert result.decision == "DENY" and not result.tool_executed
    assert h.journal.denials == 2
    h.journal.close()
    successor = Harness(store, domain=replace(DOMAIN, instance="fresh-instance"))
    assert successor.journal.denials == 2
    result = await successor.gateway.call("Show public federal award", AWARD)
    assert result.decision == "DENY" and not result.tool_executed
    assert "SESSION_CONTAINMENT_ACTIVE" in result.governance.policy_reasons
    assert "Restart and reconnect do not clear" in result.clarification
    assert not h.calls and not successor.calls
    successor.journal.close()


@pytest.mark.parametrize("field", ["issuer", "audience", "principal", "service_identity"])
def test_other_domain_never_gets_an_implicit_clear_store(store, field):
    changed = replace(DOMAIN, **{field: "different-synthetic-value"})
    before = store.snapshot()
    with pytest.raises(LocalHold):
        PostgresDispatchJournal(store.connect, changed, REVISION)
    assert store.snapshot() == before


def test_wrong_source_identity_and_revision_do_not_change_evidence(store, monkeypatch):
    before = store.snapshot()
    with pytest.raises(LocalHold):
        PostgresDispatchJournal(store.connect, DOMAIN, "0" * 40)
    assert store.snapshot() == before
    monkeypatch.setattr(module, "read_source_identity", lambda revision: "f" * 64)
    with pytest.raises(LocalHold):
        PostgresDispatchJournal(store.connect, DOMAIN, REVISION)
    assert store.snapshot() == before


@pytest.mark.parametrize("damage", ["empty", "gap", "digest", "json", "noncanonical", "projection"])
def test_invalid_or_missing_history_fails_closed_without_repair(store, damage):
    key = module.domain_identity(DOMAIN)
    rows = store.events[key]
    if damage == "empty":
        rows.clear()
    elif damage == "projection":
        store.states[key][8] += 1
    else:
        row = list(rows[0])
        if damage == "gap":
            row[0] = 2
        elif damage == "digest":
            row[5] = "f" * 64
        elif damage == "json":
            row[3] = "{"
        else:
            row[3] = json.dumps(json.loads(row[3]), indent=2)
        rows[0] = tuple(row)
    before = store.snapshot()
    with pytest.raises(LocalHold):
        PostgresDispatchJournal(store.connect, DOMAIN, REVISION)
    assert store.snapshot() == before


@pytest.mark.parametrize("missing", ["schema", "domain", "fsync"])
def test_unavailable_store_never_runs_automatic_provisioning_or_migration(missing):
    store = SyntheticPostgres()
    if missing == "schema":
        store.version = None
    elif missing == "fsync":
        store.fsync = "off"
    with pytest.raises(LocalHold):
        PostgresDispatchJournal(store.connect, DOMAIN, REVISION)
    assert not store.states and not store.events
    assert not [sql for _, sql, _ in store.log if sql == module.SQL_PROVISION]
    assert all(not sql.lstrip().upper().startswith("CREATE ") for _, sql, _ in store.log)


def test_autocommit_session_is_rejected_before_sql_or_domain_mutation(store):
    before = store.snapshot()

    def invalid_connection():
        connection = store.connect()
        connection.autocommit = True
        return connection

    with pytest.raises(LocalHold, match="POSTGRES_TRANSACTION_REQUIRED"):
        PostgresDispatchJournal(invalid_connection, DOMAIN, REVISION)
    assert store.snapshot() == before
    assert store.connections[-1].closed
    assert not [
        sql
        for identity, sql, _ in store.log
        if identity == store.connections[-1].identity and sql != "CLOSE_CONNECTION"
    ]


async def test_post_dispatch_review_preserves_initial_permit_and_consumed_read(store):
    h = Harness(store)
    proposal = Proposal(tool="resolve_federal_recipient", arguments={"recipient_name": "Acme"})
    result = await h.gateway.call("Show public federal data", proposal)
    assert result.decision == "REVIEW_REQUIRED" and result.tool_executed
    assert len(h.calls) == 1
    records = store.records(h.journal.domain_key)
    policy = next(event for event in records if event["kind"] == "policy")
    intent = next(event for event in records if event["kind"] == "intent")
    finish = records[-1]
    assert policy["initial_decision"] == "PERMIT" and policy["binding_issued"]
    assert intent["authority"]["decision"] == "PERMIT"
    assert finish["final_decision"] == "REVIEW_REQUIRED"
    assert finish["phase"] == "post_dispatch" and finish["binding_consumption"] == "VERIFIED"
    assert not h.journal.held
    h.journal.close()


@pytest.mark.parametrize("attack", ["expiry", "tamper", "foreign", "replay"])
async def test_committed_intent_does_not_replace_execution_boundary_checks(
    store, monkeypatch, attack
):
    h = Harness(store)
    original_intent = h.journal.intent
    boundary = h.gateway._execution_boundary

    def altered(authority):
        original_intent(authority)
        assert store.records(h.journal.domain_key)[-1]["kind"] == "intent"
        if attack == "expiry":
            monkeypatch.setattr(boundary, "_clock", lambda: authority.expires_at + 1)
        elif attack == "tamper":
            object.__setattr__(authority.binding, "arguments_sha256", "0" * 64)
        elif attack == "foreign":
            h.gateway._execution_boundary = Gateway(
                USAspending(fixture_transport(), True, max_attempts=1), MockProvider(), Trace()
            )._execution_boundary
        else:
            boundary.consume(
                authority,
                authority.binding.request_id,
                authority.binding.tool,
                json.loads(authority.binding.arguments_json),
                h.gateway._policy_context(),
            )

    monkeypatch.setattr(h.journal, "intent", altered)
    result = await h.gateway.call("Show public federal award", AWARD)
    assert result.decision == "DENY" and not result.tool_executed
    assert result.errors and not h.calls
    records = store.records(h.journal.domain_key)
    assert len([event for event in records if event["kind"] == "intent"]) == 1
    h.journal.close()


async def test_intent_commit_delay_does_not_extend_authenticated_context_validity(
    store, monkeypatch
):
    h = Harness(store)

    def delayed_time():
        records = store.records(h.journal.domain_key)
        return time() + (1000 if records[-1]["kind"] == "intent" else 0)

    monkeypatch.setattr(module, "time", delayed_time)

    def forbidden(*args, **kwargs):
        pytest.fail("Expired authenticated context reached binding consumption")

    monkeypatch.setattr(h.gateway._execution_boundary, "consume", forbidden)
    with pytest.raises(LocalHold, match="AUTH_CONTEXT_INVALID_OR_EXPIRED"):
        await h.gateway.call("Show public federal award", AWARD)
    assert h.journal.held and not h.calls
    assert store.records(h.journal.domain_key)[-1]["kind"] == "intent"
    h.journal.close()
    assert_recovery_hold(store)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError])
async def test_unknown_dispatch_holds_and_recovery_cannot_replay(store, failure):
    attempts = []

    def uncertain(request):
        attempts.append(request)
        raise failure("synthetic transport uncertainty")

    h = Harness(store, transport=httpx.MockTransport(uncertain))
    result = await h.gateway.call("Show public federal award", AWARD)
    assert result.decision == "PERMIT" and result.tool_executed
    assert result.result is None and result.provenance is None
    assert result.dispatch_state == "DISPATCH_UNKNOWN"
    assert result.next_action == "HUMAN_REVIEW_REQUIRED"
    assert all(not error.retryable for error in result.errors)
    assert h.journal.held and len(attempts) == 1
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    h.journal.close()
    assert_recovery_hold(store)
    assert len(attempts) == 1


async def test_cancellation_after_dispatch_has_one_attempt_and_durable_hold(store):
    entered = asyncio.Event()
    attempts = []

    async def never_complete(request):
        attempts.append(request)
        entered.set()
        await asyncio.Future()

    h = Harness(store, transport=httpx.MockTransport(never_complete))
    task = asyncio.create_task(h.gateway.call("Show public federal award", AWARD))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled() and h.journal.held
    records = store.records(h.journal.domain_key)
    assert records[-1]["kind"] == "hold"
    assert not [event for event in records if event["kind"] == "finish"]
    assert len(attempts) == 1
    h.journal.close()
    assert_recovery_hold(store)
    assert len(attempts) == 1


async def test_failed_after_completed_call_is_a_durable_hold_and_redacts_diagnostics(store):
    h = Harness(store)
    result = await h.gateway.call("Show public federal award", AWARD)
    assert result.tool_executed and h.journal.active is None
    secret_marker = "synthetic-secret-must-not-enter-ledger"
    h.journal.failed(ValueError(secret_marker))
    assert h.journal.held
    assert secret_marker not in repr(store.events)
    with pytest.raises(LocalHold):
        await h.gateway.call("Show public federal award", AWARD)
    h.journal.close()
    assert_recovery_hold(store)


async def test_every_write_transaction_is_bounded_synchronous_and_fenced(store):
    h = Harness(store)
    await h.gateway.call("Show public federal award", AWARD)
    h.journal.close()
    append_transactions = 0
    for connection in store.connections:
        for statements in connection.transactions:
            if module.SQL_EVENT not in statements:
                continue
            append_transactions += 1
            setting_positions = [statements.index(setting) for setting in module.SQL_SETTINGS]
            assert setting_positions == sorted(setting_positions)
            assert setting_positions[-1] < statements.index(module.SQL_EVENT)
            assert module.SQL_UPDATE in statements
            assert statements.index(module.SQL_EVENT) < statements.index(module.SQL_UPDATE)
            if module.SQL_PROVISION not in statements:
                assert statements.index(module.SQL_STATE) < statements.index(module.SQL_EVENT)
    assert append_transactions >= 7  # provision, boot, begin, policy, intent, finish, close
