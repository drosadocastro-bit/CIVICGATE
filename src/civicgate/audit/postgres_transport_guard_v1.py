"""Experimental Channel B transport checkpoint, NOT distributed fencing.

Trusted composition must keep the original Gateway/ExecutionBoundary, a dedicated
non-reconnecting PostgreSQL session and USAspending(max_attempts=1). This wrapper
does not authenticate callers or issue authority. Loss AFTER the acknowledged
checkpoint can still precede an external send; B2b remains HOLD.
"""

import json
from types import TracebackType
from typing import Any, NoReturn

import httpx

from civicgate.audit import postgres_journal as ledger
from civicgate.audit.postgres_journal import PostgresCursor, PostgresDispatchJournal
from civicgate.mcp.http_identity import LocalHold

SQL_SESSION = (
    "SELECT pg_backend_pid(),"
    "(SELECT oid::bigint FROM pg_database WHERE datname=current_database()),"
    "current_database(),current_user,"
    "(SELECT backend_start::text FROM pg_stat_activity WHERE pid=pg_backend_pid())"
)
SQL_OWNED_LOCK = (
    "SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' "
    "AND granted AND mode='ExclusiveLock' AND pid=pg_backend_pid() "
    "AND database=%s AND classid::bigint=%s AND objid::bigint=%s AND objsubid=1)"
)


def _session(cursor: PostgresCursor) -> tuple[Any, ...]:
    cursor.execute(SQL_SESSION)
    row = cursor.fetchone()
    if (
        type(row) is not tuple
        or len(row) != 5
        or any(type(row[index]) is not int or row[index] <= 0 for index in (0, 1))
        or any(type(row[index]) is not str or not row[index] for index in (2, 3, 4))
    ):
        raise LocalHold("POSTGRES_SESSION_UNVERIFIED")
    return row


class GuardedPostgresTransport(httpx.AsyncBaseTransport):
    """One checkpoint and at most one delegation per active committed intent.

    Uses pinned private journal internals to avoid changing the preserved ledger
    contract. This is an opt-in experimental composition, not a global Gateway
    enforcement mechanism. The inner transport must have no implicit retries.
    """

    def __init__(self, journal: PostgresDispatchJournal, inner: httpx.AsyncBaseTransport) -> None:
        self._journal = journal
        self._inner = inner
        self._connection = journal._db
        self._generation = self._current_generation()
        self._delegated: set[str] = set()
        self._primary_failure = False
        cursor = None
        with journal._mutex:
            try:
                self._require_connection()
                assert self._connection is not None
                cursor = self._connection.cursor()
                ledger._prepare(cursor)
                self._session = _session(cursor)
                cursor.close()
                cursor = None
                self._connection.commit()
                self._require_connection()
            except BaseException as error:
                self._stop(error)
            finally:
                self._close_cursor(cursor)

    def _current_generation(self) -> tuple[Any, ...]:
        journal = self._journal
        return (
            journal.domain,
            journal.domain_key,
            journal.owner_id,
            journal.epoch,
            journal.code_revision,
            journal.source_sha256,
        )

    def _require_connection(self) -> None:
        journal = self._journal
        if (
            journal.closed
            or journal.held
            or self._connection is None
            or journal._db is not self._connection
            or self._connection.autocommit is not False
            or self._current_generation() != self._generation
            or ledger.domain_identity(journal.domain) != journal.domain_key
        ):
            raise LocalHold("POSTGRES_GUARD_SESSION_OR_GENERATION_CHANGED")

    @staticmethod
    def _close_cursor(cursor: PostgresCursor | None) -> None:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

    def _stop(self, error: BaseException) -> NoReturn:
        # Close the pinned session too if a caller replaced journal._db. Never
        # write evidence using an unverified replacement or reconnect to one.
        if self._connection is not None and self._journal._db is not self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
        self._journal._stop(error)

    def _verify(self) -> None:
        journal = self._journal
        cursor = None
        logical_rejection_safe = False
        with journal._mutex:
            try:
                self._require_connection()
                context = journal._context()
                assert self._connection is not None
                cursor = self._connection.cursor()
                ledger._prepare(cursor)
                if _session(cursor) != self._session:
                    raise LocalHold("POSTGRES_GUARD_BACKEND_CHANGED")
                state, rows = ledger._load(
                    cursor, journal.domain, journal.code_revision, journal.source_sha256
                )
                if (
                    state != journal._state
                    or state.epoch != self._generation[3]
                    or state.owner_id != self._generation[2]
                    or not state.owner_active
                    or state.held
                ):
                    raise LocalHold("POSTGRES_GUARD_HISTORY_CHANGED")
                key = int.from_bytes(bytes.fromhex(journal.domain_key)[:8], "big")
                cursor.execute(SQL_OWNED_LOCK, (self._session[1], key >> 32, key & 0xFFFFFFFF))
                owned = cursor.fetchone()
                if owned not in ((True,), (False,)) or type(owned[0]) is not bool:
                    raise LocalHold("POSTGRES_GUARD_LOCK_UNVERIFIED")
                logical_rejection_safe = True
                if owned != (True,):
                    raise LocalHold("POSTGRES_GUARD_LOCK_LOST")
                if (
                    state.active is None
                    or state.phase != "intent"
                    or state.initial_decision != "PERMIT"
                    or not state.binding_issued
                    or state.active in self._delegated
                    or len(self._delegated) >= ledger.MAX_EVENTS
                    or json.loads(rows[-1][3])["context"] != context
                ):
                    raise LocalHold("POSTGRES_GUARD_INTENT_UNVERIFIED_OR_REUSED")
                cursor.close()
                cursor = None
                logical_rejection_safe = False
                self._connection.commit()
                self._require_connection()
                logical_rejection_safe = True
                if journal._context() != context:
                    raise LocalHold("POSTGRES_GUARD_CONTEXT_CHANGED")
                # Mark before delegation, including inner cancellation/failure.
                self._delegated.add(state.active)
            except BaseException as error:
                self._close_cursor(cursor)
                cursor = None
                if logical_rejection_safe and isinstance(error, LocalHold):
                    try:
                        self._require_connection()
                        assert self._connection is not None
                        self._connection.rollback()
                    except BaseException as rollback_error:
                        self._stop(rollback_error)
                    # Existing CAS/replay writes HOLD when still available.
                    # Query/commit/session ambiguity never reaches this path.
                    journal.failed(error)
                self._stop(error)
            finally:
                self._close_cursor(cursor)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._primary_failure = False
        try:
            self._verify()
            # No threading lock spans an await. This is the G2 exposure window:
            # a successful observation does not fence a later external send.
            return await self._inner.handle_async_request(request)
        except BaseException:
            self._primary_failure = True
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        # HTTPX forwards exceptions from response-body iteration/client scope
        # here even after handle_async_request returned successfully. Preserve
        # that primary error if the inner transport's cleanup also fails.
        self._primary_failure = self._primary_failure or exc_type is not None
        await self.aclose()

    async def aclose(self) -> None:
        # USAspending creates a client per request with the same supplied
        # transport. Forward cleanup, but do not close the journal or disable
        # healthy reuse. Inner transport lifecycle must support this contract.
        try:
            await self._inner.aclose()
        except BaseException as error:
            if not self._primary_failure:
                self._journal.failed(error)
                raise LocalHold("POSTGRES_GUARD_TRANSPORT_CLEANUP_FAILED") from None
