"""Strict synthetic DB-API model; this is not a PostgreSQL server or driver.

It tests caller transaction ordering, rollback and lost commit acknowledgments.
Its lock, isolation and persistence rules are test inputs, not verified engine
properties. No socket, credentials, PostgreSQL executable or real DB is used.
"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from civicgate.audit import postgres_journal as journal

REQUIRED_SETTINGS = (
    "SET LOCAL lock_timeout = '100ms'",
    "SET LOCAL statement_timeout = '5s'",
    "SET LOCAL synchronous_commit = 'on'",
)


class SyntheticDatabaseError(RuntimeError):
    """A synthetic database fault with no secret-bearing diagnostic text."""


@dataclass
class Fault:
    statement: str | None = None
    kind: str | None = None
    phase: str = "execute"
    error: type[Exception] = SyntheticDatabaseError


class SyntheticPostgres:
    """Committed store shared by dedicated connection models and observers."""

    def __init__(self) -> None:
        self.version: int | None = 1
        self.fsync = "on"
        self.states: dict[str, list[Any]] = {}
        self.events: dict[str, list[tuple[Any, ...]]] = {}
        self.advisory_locks: dict[tuple[Any, ...], int] = {}
        self.row_locks: dict[str, int] = {}
        self.connections: list[SyntheticConnection] = []
        self.log: list[tuple[int, str, tuple[Any, ...]]] = []
        self.faults: list[Fault] = []

    def connect(self) -> "SyntheticConnection":
        connection = SyntheticConnection(self, len(self.connections) + 1)
        self.connections.append(connection)
        return connection

    def fault(
        self,
        *,
        statement: str | None = None,
        kind: str | None = None,
        phase: str = "execute",
        error: type[Exception] = SyntheticDatabaseError,
    ) -> None:
        self.faults.append(Fault(statement, kind, phase, error))

    def take_fault(self, statement: str, kind: str | None, phase: str) -> Fault | None:
        for index, fault in enumerate(self.faults):
            if (
                fault.phase == phase
                and (fault.statement is None or fault.statement == statement)
                and (fault.kind is None or fault.kind == kind)
            ):
                return self.faults.pop(index)
        return None

    def records(self, domain_key: str) -> list[dict[str, Any]]:
        """Independent observer sees only committed event bytes."""
        import json

        return [json.loads(row[3]) for row in self.events.get(domain_key, [])]

    def snapshot(self) -> tuple[Any, ...]:
        return deepcopy((self.states, self.events))


class SyntheticConnection:
    def __init__(self, store: SyntheticPostgres, identity: int) -> None:
        self.store = store
        self.identity = identity
        self.autocommit = False
        self.closed = False
        self._states: dict[str, list[Any]] | None = None
        self._events: dict[str, list[tuple[Any, ...]]] | None = None
        self._changed: set[str] = set()
        self._kinds: list[str] = []
        self._settings: list[str] = []
        self.transactions: list[list[str]] = []
        self._statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def _check(self) -> None:
        if self.closed:
            raise SyntheticDatabaseError("synthetic connection terminated")

    def _begin(self) -> None:
        self._check()
        assert self.autocommit is False, "synthetic model requires real transaction mode"
        if self._states is not None:
            return
        self._states = deepcopy(self.store.states)
        self._events = deepcopy(self.store.events)
        self._settings = []
        self._changed = set()
        self._kinds = []
        self._statements = []
        self.store.log.append((self.identity, "BEGIN", ()))

    def cursor(self) -> "SyntheticCursor":
        self._check()
        return SyntheticCursor(self)

    def commit(self) -> None:
        self._check()
        self.store.log.append((self.identity, "COMMIT", ()))
        kind = self._kinds[-1] if self._kinds else None
        fault = self.store.take_fault("COMMIT", kind, "before_persist")
        if fault:
            raise fault.error("synthetic commit acknowledgment unavailable")
        if self._states is not None:
            assert self._events is not None
            for key in self._changed:
                self.store.states[key] = deepcopy(self._states[key])
                self.store.events[key] = deepcopy(self._events[key])
            self.transactions.append(list(self._statements))
        self.commits += 1
        self._end_transaction()
        fault = self.store.take_fault("COMMIT", kind, "after_persist")
        if fault:
            raise fault.error("synthetic commit acknowledgment unavailable")

    def rollback(self) -> None:
        self._check()
        self.store.log.append((self.identity, "ROLLBACK", ()))
        self.rollbacks += 1
        self._end_transaction()

    def _end_transaction(self) -> None:
        for key, owner in list(self.store.row_locks.items()):
            if owner == self.identity:
                del self.store.row_locks[key]
        self._states = None
        self._events = None
        self._changed = set()
        self._kinds = []
        self._settings = []
        self._statements = []

    def close(self) -> None:
        if self.closed:
            return
        self.store.log.append((self.identity, "CLOSE_CONNECTION", ()))
        self._end_transaction()
        for key, owner in list(self.store.advisory_locks.items()):
            if owner == self.identity:
                del self.store.advisory_locks[key]
        self.closed = True


class SyntheticCursor:
    def __init__(self, connection: SyntheticConnection) -> None:
        self.connection = connection
        self.rowcount = -1
        self.rows: list[tuple[Any, ...]] = []
        self.closed = False

    def execute(self, statement: str, parameters: tuple[Any, ...] = ()) -> None:
        connection = self.connection
        store = connection.store
        connection._check()
        assert not self.closed, "closed synthetic cursor used"
        assert type(parameters) is tuple, "parameters must be bound separately"
        connection._begin()
        store.log.append((connection.identity, statement, parameters))
        kind = parameters[2] if statement == journal.SQL_EVENT else None
        fault = store.take_fault(statement, kind, "disconnect")
        if fault:
            connection.close()
            raise fault.error("synthetic connection terminated during statement")
        fault = store.take_fault(statement, kind, "execute")
        if fault:
            raise fault.error("synthetic database statement failed")
        connection._statements.append(statement)
        self.rows = []
        self.rowcount = -1
        if store.take_fault(statement, kind, "rowcount_zero"):
            assert statement == journal.SQL_UPDATE
            self.rowcount = 0
            return
        assert connection._states is not None
        assert connection._events is not None
        if statement in journal.SQL_SETTINGS:
            assert not parameters
            connection._settings.append(statement)
        elif statement == journal.SQL_FSYNC:
            self.rows = [(store.fsync,)]
        elif statement == journal.SQL_SYNC:
            self.rows = [
                ("on" if "SET LOCAL synchronous_commit = 'on'" in connection._settings else "off",)
            ]
        elif statement == journal.SQL_VERSION:
            self.rows = [] if store.version is None else [(store.version,)]
        elif statement == journal.SQL_LOCK:
            assert len(parameters) == 1
            holder = store.advisory_locks.get(parameters)
            if holder is None:
                store.advisory_locks[parameters] = connection.identity
            self.rows = [(holder in {None, connection.identity},)]
        elif statement == journal.SQL_STATE:
            assert len(parameters) == 1
            key = parameters[0]
            holder = store.row_locks.get(key)
            if holder not in {None, connection.identity}:
                raise SyntheticDatabaseError("synthetic row lock timeout")
            store.row_locks[key] = connection.identity
            # Model READ COMMITTED's locked read using latest committed state.
            if key not in connection._changed:
                if key in store.states:
                    connection._states[key] = deepcopy(store.states[key])
                    connection._events[key] = deepcopy(store.events[key])
                else:
                    connection._states.pop(key, None)
                    connection._events.pop(key, None)
            state = connection._states.get(key)
            self.rows = [] if state is None else [tuple(state)]
        elif statement == journal.SQL_HISTORY:
            assert len(parameters) == 2 and parameters[1] == 10001
            self.rows = sorted(connection._events.get(parameters[0], []))[: parameters[1]]
        elif statement == journal.SQL_PROVISION:
            assert len(parameters) == 4
            key, domain_json, revision, source_hash = parameters
            if key in connection._states:
                raise SyntheticDatabaseError("synthetic duplicate domain")
            self._check_write_settings()
            connection._states[key] = [
                domain_json,
                revision,
                source_hash,
                0,
                None,
                False,
                0,
                False,
                0,
                "",
            ]
            connection._events[key] = []
            connection._changed.add(key)
            self.rowcount = 1
        elif statement == journal.SQL_EVENT:
            assert len(parameters) == 7
            key, sequence, event_kind, request_id, payload, previous, digest = parameters
            self._check_write_settings()
            assert store.row_locks.get(key) == connection.identity or key in connection._changed
            if key not in connection._states:
                raise SyntheticDatabaseError("synthetic foreign key violation")
            rows = connection._events[key]
            if any(row[0] == sequence for row in rows):
                raise SyntheticDatabaseError("synthetic duplicate sequence")
            if event_kind == "begin" and any(
                row[1] == "begin" and row[2] == request_id for row in rows
            ):
                raise SyntheticDatabaseError("synthetic duplicate request opening")
            if not 1 <= sequence <= 10000 or len(payload.encode("utf-8")) > 16384:
                raise SyntheticDatabaseError("synthetic event bounds violated")
            rows.append((sequence, event_kind, request_id, payload, previous, digest))
            connection._kinds.append(event_kind)
            connection._changed.add(key)
            self.rowcount = 1
        elif statement == journal.SQL_UPDATE:
            assert len(parameters) == 15
            self._check_write_settings()
            key = parameters[7]
            assert store.row_locks.get(key) == connection.identity or key in connection._changed
            state = connection._states.get(key)
            self.rowcount = 0
            if (
                state is not None
                and (state[3], state[4], state[5], state[8], state[9], state[1], state[2])
                == parameters[8:]
            ):
                state[3:] = list(parameters[:7])
                self.rowcount = 1
                connection._changed.add(key)
        elif statement == "BEGIN":
            assert not parameters
        else:
            raise AssertionError(f"Unrecognized SQL in synthetic model: {statement}")

    def _check_write_settings(self) -> None:
        statements = self.connection._settings
        assert statements == list(REQUIRED_SETTINGS), "bounded synchronous transaction required"

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.rows.pop(0) if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows, self.rows = self.rows, []
        return rows

    def close(self) -> None:
        self.closed = True
