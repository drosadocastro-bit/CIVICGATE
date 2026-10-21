"""Experimental synchronous Channel B ledger; never an authority issuer.

The caller supplies a fresh, dedicated DB-API-style PostgreSQL session. No
driver, credentials, database creation, reconnect, takeover or retry is supplied.
"""

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from time import time
from typing import Any, NoReturn, Protocol
from uuid import uuid4

from civicgate.adapters.usaspending import AttemptRecord
from civicgate.audit.postgres_history import LedgerState, canonical, event_digest, replay
from civicgate.governance.execution import AuthorityEnvelope
from civicgate.mcp.http_identity import LocalHold, TrustDomain, invocation_context
from civicgate.models.responses import Envelope

MAX_EVENTS = 10000
SCHEMA_VERSION = 1
SQL_SETTINGS = (
    "SET LOCAL lock_timeout = '100ms'",
    "SET LOCAL statement_timeout = '5s'",
    "SET LOCAL synchronous_commit = 'on'",
)
SQL_FSYNC = "SHOW fsync"
SQL_SYNC = "SHOW synchronous_commit"
SQL_VERSION = "SELECT version FROM civicgate_dispatch.schema_version"
SQL_LOCK = "SELECT pg_try_advisory_lock(%s)"
SQL_STATE = (
    "SELECT domain_json,source_revision,source_sha256,epoch,owner_id,owner_active,"
    "denials,held,sequence,digest FROM civicgate_dispatch.domain_state "
    "WHERE domain_key=%s FOR UPDATE"
)
SQL_HISTORY = (
    "SELECT sequence,kind,request_id,payload,previous_digest,digest "
    "FROM civicgate_dispatch.events WHERE domain_key=%s ORDER BY sequence LIMIT %s"
)
SQL_PROVISION = (
    "INSERT INTO civicgate_dispatch.domain_state "
    "(domain_key,domain_json,source_revision,source_sha256,epoch,owner_id,owner_active,"
    "denials,held,sequence,digest) VALUES (%s,%s,%s,%s,0,NULL,FALSE,0,FALSE,0,'')"
)
SQL_EVENT = (
    "INSERT INTO civicgate_dispatch.events "
    "(domain_key,sequence,kind,request_id,payload,previous_digest,digest) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s)"
)
SQL_UPDATE = (
    "UPDATE civicgate_dispatch.domain_state SET epoch=%s,owner_id=%s,owner_active=%s,"
    "denials=%s,held=%s,sequence=%s,digest=%s "
    "WHERE domain_key=%s AND epoch=%s AND owner_id IS NOT DISTINCT FROM %s "
    "AND owner_active=%s AND sequence=%s AND digest=%s "
    "AND source_revision=%s AND source_sha256=%s"
)


class PostgresCursor(Protocol):
    rowcount: int

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def close(self) -> None: ...


class PostgresConnection(Protocol):
    autocommit: bool

    def cursor(self) -> PostgresCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], PostgresConnection]


def stable_domain(domain: TrustDomain) -> dict[str, str]:
    """Instance generations cannot split a principal's containment domain."""
    return {key: value for key, value in asdict(domain).items() if key != "instance"}


def domain_identity(domain: TrustDomain) -> str:
    return hashlib.sha256(canonical(stable_domain(domain)).encode("utf-8")).hexdigest()


def read_source_identity(code_revision: str) -> str:
    if (
        type(code_revision) is not str
        or len(code_revision) != 40
        or any(c not in "0123456789abcdef" for c in code_revision)
    ):
        raise LocalHold("SOURCE_REVISION_INVALID")
    root = Path(__file__).resolve().parents[3]
    try:
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
        ).strip()
        if actual != code_revision:
            raise LocalHold("SOURCE_REVISION_MISMATCH")
        paths = sorted((root / "src/civicgate").rglob("*.py")) + [
            root / "pyproject.toml",
            root / "migrations/001_postgres_dispatch_journal.sql",
        ]
        manifest = {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths
        }
        return hashlib.sha256(canonical(manifest).encode("utf-8")).hexdigest()
    except Exception:
        raise LocalHold("SOURCE_IDENTITY_UNVERIFIABLE") from None


def _prepare(cursor: PostgresCursor) -> None:
    for statement in SQL_SETTINGS:
        cursor.execute(statement)
    cursor.execute(SQL_FSYNC)
    if cursor.fetchone() != ("on",):
        raise LocalHold("POSTGRES_DURABILITY_UNAVAILABLE")
    cursor.execute(SQL_SYNC)
    if cursor.fetchone() != ("on",):
        raise LocalHold("POSTGRES_DURABILITY_UNAVAILABLE")
    cursor.execute(SQL_VERSION)
    if cursor.fetchall() != [(SCHEMA_VERSION,)]:
        raise LocalHold("POSTGRES_SCHEMA_UNSUPPORTED")


def _claim_lock(cursor: PostgresCursor, key: str) -> None:
    # Session lock, acquired exactly once. Never pooled, reconnected or unlocked
    # while the journal is usable. Hash collisions conservatively deny ownership.
    lock_key = int.from_bytes(bytes.fromhex(key)[:8], "big", signed=True)
    cursor.execute(SQL_LOCK, (lock_key,))
    if cursor.fetchone() != (True,):
        raise LocalHold("POSTGRES_OWNER_CONFLICT")


def _connection(connect: ConnectionFactory) -> PostgresConnection:
    connection = connect()
    try:
        if connection.autocommit is not False:
            raise LocalHold("POSTGRES_TRANSACTION_REQUIRED")
        return connection
    except BaseException:
        connection.close()
        raise


def _load(
    cursor: PostgresCursor, domain: TrustDomain, revision: str, source: str
) -> tuple[LedgerState, list[tuple[Any, ...]]]:
    key = domain_identity(domain)
    cursor.execute(SQL_STATE, (key,))
    row = cursor.fetchone()
    if row is None:
        raise LocalHold("POSTGRES_DOMAIN_NOT_PROVISIONED")
    if (
        len(row) != 10
        or row[0] != canonical(stable_domain(domain))
        or row[1] != revision
        or row[2] != source
    ):
        raise LocalHold("POSTGRES_DOMAIN_OR_SOURCE_MISMATCH")
    cursor.execute(SQL_HISTORY, (key, MAX_EVENTS + 1))
    rows = cursor.fetchall()
    state = replay(rows, key, stable_domain(domain), revision, source)
    expected = (
        state.epoch,
        state.owner_id,
        state.owner_active,
        state.denials,
        state.held,
        state.sequence,
        state.digest,
    )
    if tuple(row[3:]) != expected or any(
        type(row[index]) is not expected_type
        for index, expected_type in ((3, int), (5, bool), (6, int), (7, bool), (8, int))
    ):
        raise LocalHold("POSTGRES_PROJECTION_INVALID")
    return state, rows


def _append(
    cursor: PostgresCursor,
    domain: TrustDomain,
    revision: str,
    source: str,
    state: LedgerState,
    rows: list[tuple[Any, ...]],
    event: dict[str, Any],
) -> LedgerState:
    key = domain_identity(domain)
    payload = canonical(event)
    sequence = state.sequence + 1
    row = (
        sequence,
        event["kind"],
        event.get("request_id"),
        payload,
        state.digest,
        event_digest(state.digest, payload),
    )
    # Validate the prospective transition as well as the recovered history.
    # This verifies documentary consistency, not execution authority.
    after = replay([*rows, row], key, stable_domain(domain), revision, source)
    cursor.execute(SQL_EVENT, (key, *row))
    cursor.execute(
        SQL_UPDATE,
        (
            after.epoch,
            after.owner_id,
            after.owner_active,
            after.denials,
            after.held,
            after.sequence,
            after.digest,
            key,
            state.epoch,
            state.owner_id,
            state.owner_active,
            state.sequence,
            state.digest,
            revision,
            source,
        ),
    )
    if cursor.rowcount != 1:
        raise LocalHold("POSTGRES_OWNER_FENCE_REJECTED")
    return after


def provision_postgres_domain(
    connect: ConnectionFactory, domain: TrustDomain, code_revision: str
) -> None:
    """Explicit one-time domain bootstrap in an ALREADY migrated database.

    Never called by journal startup. A separate provisioner supplies INSERT on
    domain_state; runtime credentials need no provisioning privilege.
    """
    connection = None
    cursor = None
    try:
        source = read_source_identity(code_revision)
        key = domain_identity(domain)
        connection = _connection(connect)
        cursor = connection.cursor()
        _prepare(cursor)
        _claim_lock(cursor, key)
        cursor.execute(
            SQL_PROVISION, (key, canonical(stable_domain(domain)), code_revision, source)
        )
        _append(
            cursor,
            domain,
            code_revision,
            source,
            LedgerState(),
            [],
            {
                "kind": "provision",
                "domain": stable_domain(domain),
                "source_revision": code_revision,
                "source_sha256": source,
                "version": 1,
            },
        )
        cursor.close()
        cursor = None
        connection.commit()
    except BaseException:
        # A lost acknowledgment may mean the provision committed. No automatic
        # second INSERT, recreation or clean-history assumption is permitted.
        raise LocalHold("POSTGRES_PROVISION_UNCONFIRMED") from None
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


class PostgresDispatchJournal:
    """One stable execution domain, one dedicated session, evidence only.

    Recovery never reconnects, assumes a clean store, takes over an open owner,
    releases HOLD, reconstructs an envelope or dispatches a tool.
    """

    def __init__(
        self,
        connect: ConnectionFactory,
        domain: TrustDomain,
        code_revision: str,
        *,
        owner_id: str | None = None,
    ) -> None:
        self.domain = domain
        self.domain_key = domain_identity(domain)
        self.code_revision = code_revision
        self.source_sha256 = read_source_identity(code_revision)
        self.owner_id = str(uuid4()) if owner_id is None else owner_id
        if (
            not isinstance(self.owner_id, str)
            or not 1 <= len(self.owner_id) <= 128
            or any(not (c.isascii() and (c.isalnum() or c in "_.:-")) for c in self.owner_id)
        ):
            raise LocalHold("POSTGRES_OWNER_ID_INVALID")
        self._mutex = RLock()
        self._db: PostgresConnection | None = None
        self._state = LedgerState()
        self._poisoned = False
        self.closed = False
        cursor = None
        try:
            self._db = _connection(connect)
            cursor = self._db.cursor()
            _prepare(cursor)
            _claim_lock(cursor, self.domain_key)
            state, rows = _load(cursor, domain, code_revision, self.source_sha256)
            if state.held or state.active is not None or state.owner_active:
                raise LocalHold("POSTGRES_RECOVERY_HOLD")
            event = self._event("boot", state.epoch + 1, self.owner_id)
            after = _append(cursor, domain, code_revision, self.source_sha256, state, rows, event)
            cursor.close()
            cursor = None
            self._db.commit()
            self._state = after
        except BaseException as exc:
            self._stop(exc)
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass

    @property
    def denials(self) -> int:
        return self._state.denials

    @property
    def held(self) -> bool:
        return self._poisoned or self._state.held

    @property
    def active(self) -> str | None:
        return self._state.active

    @property
    def epoch(self) -> int:
        return self._state.epoch

    def _event(self, kind: str, epoch: int, owner: str | None, **fields: Any) -> dict[str, Any]:
        return {
            "kind": kind,
            "domain_key": self.domain_key,
            "epoch": epoch,
            "owner_id": owner,
            "instance": self.domain.instance,
            "source_revision": self.code_revision,
            "source_sha256": self.source_sha256,
            "time": time(),
            **fields,
        }

    def _release(self) -> None:
        connection, self._db = self._db, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _stop(self, error: BaseException) -> NoReturn:
        self._poisoned = True
        self._release()
        # Do not surface or persist raw driver messages/DSNs. Never leak a
        # ValueError into Gateway's adapter-response validation catch block.
        code = str(error) if isinstance(error, LocalHold) else "POSTGRES_TRANSACTION_UNCONFIRMED"
        if not 1 <= len(code) <= 128 or any(
            c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in code
        ):
            code = "POSTGRES_TRANSACTION_UNCONFIRMED"
        raise LocalHold(code) from None

    def _context(self) -> dict[str, Any]:
        context = invocation_context.get()
        if context is None or (
            context.principal != self.domain.principal
            or context.issuer != self.domain.issuer
            or context.audience != self.domain.audience
            or type(context.expires_at) is not int
            or context.expires_at <= time()
        ):
            raise LocalHold("AUTH_CONTEXT_INVALID_OR_EXPIRED")
        return context.evidence()

    def _run(self, kind: str | None = None, **fields: Any) -> None:
        with self._mutex:
            if self.closed or self.held or self._db is None:
                raise LocalHold("POSTGRES_DURABLE_HOLD")
            cursor = None
            try:
                cursor = self._db.cursor()
                _prepare(cursor)
                state, rows = _load(cursor, self.domain, self.code_revision, self.source_sha256)
                if (
                    state.epoch != self.epoch
                    or state.owner_id != self.owner_id
                    or not state.owner_active
                    or state != self._state
                ):
                    raise LocalHold("POSTGRES_OWNER_OR_HISTORY_CHANGED")
                after = state
                if kind is not None:
                    event = self._event(kind, self.epoch, self.owner_id, **fields)
                    after = _append(
                        cursor,
                        self.domain,
                        self.code_revision,
                        self.source_sha256,
                        state,
                        rows,
                        event,
                    )
                cursor.close()
                cursor = None
                self._db.commit()
                self._state = after
            except BaseException as exc:
                self._stop(exc)
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass

    def admit(self) -> int:
        try:
            if self.active is not None:
                raise LocalHold("POSTGRES_REQUEST_ACTIVE")
            self._context()
            self._run()
            self._context()
            return self.denials
        except BaseException as exc:
            self._stop(exc)

    def begin(self, request_id: str) -> None:
        try:
            self._run("begin", request_id=request_id, context=self._context())
        except BaseException as exc:
            self._stop(exc)

    def policy(self, request_id: str, evidence: dict[str, Any]) -> None:
        try:
            if set(evidence) != {
                "initial_decision",
                "reasons",
                "binding_issued",
                "binding_issuance_error",
            }:
                raise LocalHold("POSTGRES_POLICY_EVIDENCE_INVALID")
            self._run("policy", request_id=request_id, **evidence)
        except BaseException as exc:
            self._stop(exc)

    def intent(self, authority: AuthorityEnvelope | None) -> None:
        try:
            if (
                type(authority) is not AuthorityEnvelope
                or authority.binding.request_id != self.active
            ):
                raise LocalHold("POSTGRES_INTENT_BINDING_MISSING")
            self._run(
                "intent",
                request_id=self.active,
                context=self._context(),
                authority=authority.audit_record(),
                containment_denials=self.denials,
                dispatch_state="NOT_DISPATCHED",
            )
            self._context()
        except BaseException as exc:
            self._stop(exc)

    def finish(self, envelope: Envelope, denials: int, evidence: dict[str, Any]) -> None:
        try:
            if set(evidence) != {
                "pre_dispatch_verification",
                "execution_boundary_error",
                "attempts",
            }:
                raise LocalHold("POSTGRES_FINISH_EVIDENCE_INVALID")
            if type(evidence["attempts"]) is not list or any(
                type(attempt) is not dict or set(attempt) != set(AttemptRecord.__dataclass_fields__)
                for attempt in evidence["attempts"]
            ):
                raise LocalHold("POSTGRES_ATTEMPT_EVIDENCE_INVALID")
            fields = (
                "attempt",
                "max_attempts",
                "dispatch_state",
                "response_state",
                "status_code",
                "response_received",
                "retry_decision",
            )
            attempts = [{key: attempt[key] for key in fields} for attempt in evidence["attempts"]]
            unknown = envelope.tool_executed and (
                not envelope.attempt_metadata_available
                or envelope.dispatch_state != "REQUEST_CONFIRMED"
                or envelope.response_state != "RESPONSE_RECEIVED"
                or any(
                    a["dispatch_state"] == "DISPATCH_UNKNOWN"
                    or a["response_state"] == "TRANSPORT_ERROR"
                    for a in attempts
                )
            )
            if unknown:
                envelope.dispatch_state = "DISPATCH_UNKNOWN"
                envelope.next_action = "HUMAN_REVIEW_REQUIRED"
                envelope.clarification = "DISPATCH_UNKNOWN: durable HOLD; no retry or failover."
                envelope.result = None
                for error in envelope.errors:
                    error.retryable = False
            verification = evidence["pre_dispatch_verification"]
            self._run(
                "finish",
                request_id=envelope.request_id,
                denials=denials,
                hold=unknown,
                final_decision=envelope.decision,
                phase="post_dispatch" if envelope.tool_executed else "pre_dispatch",
                tool_executed=envelope.tool_executed,
                dispatch_state=envelope.dispatch_state,
                response_state=envelope.response_state,
                next_action=envelope.next_action,
                pre_dispatch_verification=verification,
                binding_consumption=(
                    "VERIFIED"
                    if verification == "PASS"
                    else "NOT_ESTABLISHED"
                    if verification == "FAIL"
                    else "NOT_REQUIRED"
                ),
                execution_boundary_error=evidence["execution_boundary_error"],
                attempt_metadata_available=envelope.attempt_metadata_available,
                attempts=attempts,
                policy_reasons=envelope.governance.policy_reasons,
                error_codes=[error.code for error in envelope.errors],
            )
        except BaseException as exc:
            self._stop(exc)

    def failed(self, error: BaseException) -> None:
        # This may follow a committed finish if later Trace recording failed.
        # Never retry a failed/unknown database transaction or mask the original error.
        try:
            if not self.held and not self.closed:
                self._run(
                    "hold",
                    request_id=self.active,
                    reason="INCOMPLETE_CALL",
                    hold=True,
                    dispatch_state="DISPATCH_UNKNOWN",
                    response_state="TRANSPORT_ERROR",
                )
        except BaseException:
            pass
        finally:
            self._poisoned = True
            self._release()

    def close(self) -> None:
        with self._mutex:
            try:
                if not self.closed and not self.held and self.active is None:
                    self._run("close")
                elif self.active is not None:
                    self._poisoned = True
            finally:
                self.closed = True
                self._release()
