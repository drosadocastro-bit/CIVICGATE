"""EVAL-002A-R4 evaluation-only SQLite custody and write-ahead admission.

This ledger counts attempts; it never authorizes tools or model execution. The
trusted operator fixes one database and run identity. SQLite transactions provide
cross-process exclusion on the tested local filesystem, not network exactly-once
execution, an exhaustive registry, or a power-loss/WORM guarantee.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

ROLES = frozenset({"planner", "judge"})
OUTCOMES = frozenset(
    {
        "RESERVATION_NO_SEND",
        "RESPONSE_OBSERVED",
        "COMPLETION_UNKNOWN",
        "MODEL_IDENTITY_REJECTED",
        "RESPONSE_REJECTED",
    }
)
STOP_OUTCOMES = OUTCOMES - {"RESERVATION_NO_SEND", "RESPONSE_OBSERVED"}
METADATA_FIELDS = frozenset(
    {
        "provider",
        "returned_model",
        "returned_model_sha256",
        "http_status",
        "started_at_utc",
        "completed_at_utc",
        "elapsed_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "usage_state",
        "cancellation_state",
        "deadline_disposition",
        "provider_correlation_id",
        "error_code",
        "delegate_entered",
        "response_arrived_at_utc",
        "response_arrival_elapsed_ms",
        "response_read_completed_at_utc",
        "acceptance_state",
    }
)
INTEGER_METADATA = frozenset({"http_status", "prompt_tokens", "completion_tokens", "total_tokens"})
MCP_METADATA_FIELDS = frozenset(
    {
        "initial_policy_decision",
        "final_policy_disposition",
        "binding_issued",
        "binding_consumed",
        "adapter_entries",
        "synthetic_http_attempts",
        "client_receipt_state",
        "backend_dispatch_state",
        "error_code",
        "mcp_call_id",
        "correlation_id",
    }
)
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9_.:/-]{1,160}")


class BudgetError(RuntimeError):
    """Fixed-message evaluation-custody rejection, never a retry signal."""


class BudgetUnavailable(BudgetError):
    pass


class BudgetExceeded(BudgetError):
    pass


class BudgetStopped(BudgetError):
    pass


class RecoveryBlocked(BudgetError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _identity(value: str, label: str) -> None:
    if type(value) is not str or IDENTITY_PATTERN.fullmatch(value) is None:
        raise ValueError(label)


def _hash(value: str) -> None:
    if type(value) is not str or HASH_PATTERN.fullmatch(value) is None:
        raise ValueError("INVALID_DOCUMENTARY_HASH")


def _metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if type(value) is not dict or not set(value) <= METADATA_FIELDS:
        raise ValueError("UNSUPPORTED_ATTEMPT_METADATA")
    result = dict(value)
    for key, item in result.items():
        if key == "delegate_entered":
            if type(item) is not bool:
                raise ValueError("INVALID_ATTEMPT_DELEGATE_OBSERVATION")
            continue
        if item is None:
            continue
        if key in INTEGER_METADATA:
            if type(item) is not int or item < 0:
                raise ValueError("INVALID_ATTEMPT_INTEGER_METADATA")
            if key == "http_status" and not 100 <= item <= 599:
                raise ValueError("INVALID_HTTP_STATUS")
        elif key in {"elapsed_ms", "response_arrival_elapsed_ms"}:
            if type(item) not in {int, float} or not math.isfinite(item) or item < 0:
                raise ValueError("INVALID_ATTEMPT_ELAPSED_METADATA")
        elif key == "returned_model_sha256":
            _hash(item)
        elif (
            type(item) is not str
            or not item
            or len(item) > 200
            or any(ord(char) < 32 for char in item)
        ):
            raise ValueError("INVALID_ATTEMPT_TEXT_METADATA")
    return result


def _mcp_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if type(value) is not dict or not set(value) <= MCP_METADATA_FIELDS:
        raise ValueError("UNSUPPORTED_MCP_METADATA")
    for key, item in value.items():
        if item is None:
            continue
        if key in {"binding_issued", "binding_consumed"}:
            if type(item) is not bool:
                raise ValueError("INVALID_MCP_BOOLEAN_METADATA")
        elif key in {"adapter_entries", "synthetic_http_attempts"}:
            if type(item) is not int or item < 0:
                raise ValueError("INVALID_MCP_COUNT_METADATA")
        elif type(item) is not str or not item or len(item) > 200 or any(ord(c) < 32 for c in item):
            raise ValueError("INVALID_MCP_TEXT_METADATA")
    return dict(value)


@dataclass(frozen=True)
class AttemptReservation:
    attempt_id: str
    correlation_id: str
    run_id: str
    observation_id: str
    role: str
    requested_model: str
    request_sha256: str
    prompt_sha256: str
    schema_sha256: str
    retry_count: int
    retry_reason: str | None
    reserved_at_utc: str


class AttemptBudget:
    """Attach to one existing run. Only create() can initialize a new store."""

    def __init__(self, path: Path, run_id: str) -> None:
        _identity(run_id, "INVALID_RUN_ID")
        original = Path(path)
        if str(original).startswith("\\\\") or original.is_symlink():
            raise BudgetUnavailable("LOCAL_REGULAR_BUDGET_FILE_REQUIRED")
        self.path = original.resolve()
        self.run_id = run_id
        # This capability admits only the current bounded observation. Reopening
        # the file never recreates it and never clears a durable fence.
        self._active_observation: tuple[str, str] | None = None
        with self._connection() as connection:
            settings = self._settings(connection)
        self.role_caps: dict[str, int] = settings["role_caps"]
        self.max_observations: int = settings["max_observations"]

    @classmethod
    def create(
        cls,
        path: Path,
        run_id: str,
        *,
        role_caps: dict[str, int] | None = None,
        max_observations: int = 6,
    ) -> AttemptBudget:
        _identity(run_id, "INVALID_RUN_ID")
        caps = {"planner": 12, "judge": 12} if role_caps is None else dict(role_caps)
        cls._validate_limits(caps, max_observations)
        target = Path(path)
        if not target.is_absolute() or str(target).startswith("\\\\") or target.is_symlink():
            raise BudgetUnavailable("LOCAL_ABSOLUTE_BUDGET_PATH_REQUIRED")
        # Exclusive initialization: a damaged or earlier file is never replaced.
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(target, isolation_level=None, timeout=1)) as connection:
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, "
                    "run_id TEXT NOT NULL, role_caps TEXT NOT NULL, max_observations INTEGER NOT NULL, "
                    "stopped INTEGER NOT NULL CHECK(stopped IN (0,1)), stop_reason TEXT)"
                )
                connection.execute(
                    "INSERT INTO meta VALUES (1,2,?,?,?,0,NULL)",
                    (run_id, json.dumps(caps, sort_keys=True), max_observations),
                )
                connection.execute(
                    "CREATE TABLE observations (observation_id TEXT PRIMARY KEY, reserved_at_utc TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE mcp_calls (observation_id TEXT PRIMARY KEY, reservation_id TEXT UNIQUE NOT NULL, "
                    "proposal_sha256 TEXT NOT NULL, state TEXT NOT NULL, reserved_at_utc TEXT NOT NULL, "
                    "admitted_at_utc TEXT, completed_at_utc TEXT, outcome TEXT, metadata_json TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, correlation_id TEXT UNIQUE NOT NULL, "
                    "reservation_json TEXT NOT NULL, observation_id TEXT NOT NULL, role TEXT NOT NULL, "
                    "retry_count INTEGER NOT NULL, state TEXT NOT NULL, started_at_utc TEXT, "
                    "completed_at_utc TEXT, outcome TEXT, metadata_json TEXT NOT NULL, "
                    "UNIQUE(observation_id,role,retry_count))"
                )
                connection.execute(
                    "CREATE TABLE observation_fences (observation_id TEXT PRIMARY KEY, "
                    "fence_id TEXT UNIQUE NOT NULL, state TEXT NOT NULL CHECK(state IN ('OPEN','CLOSED')), "
                    "opened_at_utc TEXT NOT NULL, closed_at_utc TEXT, summary_sha256 TEXT)"
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise BudgetUnavailable("BUDGET_INITIALIZATION_FAILED_PRESERVED") from exc
        return cls(target, run_id)

    @staticmethod
    def _validate_limits(caps: dict[str, int], max_observations: int) -> None:
        if (
            type(caps) is not dict
            or set(caps) != ROLES
            or any(type(v) is not int or not 0 <= v <= 12 for v in caps.values())
        ):
            raise ValueError("INVALID_ROLE_CAPS")
        if type(max_observations) is not int or not 1 <= max_observations <= 6:
            raise ValueError("INVALID_OBSERVATION_CAP")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file() or self.path.is_symlink():
            raise BudgetUnavailable("BUDGET_STORE_UNAVAILABLE")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=1
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise BudgetUnavailable("BUDGET_STORE_UNAVAILABLE") from exc
        try:
            yield connection
        except sqlite3.Error as exc:
            raise BudgetUnavailable("BUDGET_STORE_OPERATION_FAILED") from exc
        finally:
            connection.close()

    def _settings(self, connection: sqlite3.Connection) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM meta WHERE id=1").fetchone()
        if row is None or row["version"] != 2 or row["run_id"] != self.run_id:
            raise BudgetUnavailable("BUDGET_CONTRACT_MISMATCH")
        try:
            caps = json.loads(row["role_caps"])
            self._validate_limits(caps, row["max_observations"])
        except (ValueError, TypeError) as exc:
            raise BudgetUnavailable("BUDGET_CONTRACT_MISMATCH") from exc
        if hasattr(self, "role_caps") and (
            caps != self.role_caps or row["max_observations"] != self.max_observations
        ):
            raise BudgetUnavailable("BUDGET_CONTRACT_CHANGED")
        return {
            "role_caps": caps,
            "max_observations": row["max_observations"],
            "stopped": bool(row["stopped"]),
            "stop_reason": row["stop_reason"],
        }

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._settings(connection)
                yield connection
                connection.commit()
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise

    @staticmethod
    def _halt(connection: sqlite3.Connection, reason: str) -> None:
        connection.execute(
            "UPDATE meta SET stopped=1, stop_reason=COALESCE(stop_reason,?) WHERE id=1", (reason,)
        )

    def _reserve_observation(
        self, connection: sqlite3.Connection, observation_id: str, settings: dict[str, Any]
    ) -> None:
        existing = connection.execute(
            "SELECT 1 FROM observations WHERE observation_id=?", (observation_id,)
        ).fetchone()
        if existing is not None:
            return
        count = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        if count >= settings["max_observations"]:
            self._halt(connection, "OBSERVATION_BUDGET_EXHAUSTED")
            connection.commit()
            raise BudgetExceeded("OBSERVATION_BUDGET_EXHAUSTED")
        connection.execute("INSERT INTO observations VALUES (?,?)", (observation_id, _now()))

    def _assert_fence_access(self, connection: sqlite3.Connection, observation_id: str) -> None:
        """Reject bypass by a newly attached or different observation controller."""
        opened = connection.execute(
            "SELECT observation_id,fence_id FROM observation_fences WHERE state='OPEN'"
        ).fetchall()
        for row in opened:
            if self._active_observation != (row["observation_id"], row["fence_id"]):
                raise RecoveryBlocked("UNRESOLVED_OBSERVATION_FENCE")
            if observation_id != row["observation_id"]:
                raise RecoveryBlocked("OTHER_OBSERVATION_FENCE_ACTIVE")

    def assert_active_observation(self, observation_id: str | None = None) -> None:
        """Read-only validation of a previously acknowledged admission capability."""
        if observation_id is None:
            if self._active_observation is None:
                raise RecoveryBlocked("ACKNOWLEDGED_OBSERVATION_FENCE_REQUIRED")
            observation_id = self._active_observation[0]
        with self._connection() as connection:
            if self._settings(connection)["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            self._assert_fence_access(connection, observation_id)
            row = connection.execute(
                "SELECT * FROM observation_fences WHERE observation_id=?", (observation_id,)
            ).fetchone()
            if (
                row is None
                or row["state"] != "OPEN"
                or self._active_observation != (observation_id, row["fence_id"])
            ):
                raise RecoveryBlocked("ACKNOWLEDGED_OBSERVATION_FENCE_REQUIRED")

    def begin_observation(self, observation_id: str) -> str:
        """Commit OPEN before dispatch; never adopt a prior process's fence.

        If this write has no ACK, callers must dispatch nothing. If no write
        ever succeeds, this API cannot promise persistence across a restart.
        """
        _identity(observation_id, "INVALID_OBSERVATION_ID")
        if self._active_observation is not None:
            if self._active_observation[0] != observation_id:
                raise RecoveryBlocked("OTHER_OBSERVATION_FENCE_ACTIVE")
            self.assert_active_observation(observation_id)
            return self._active_observation[1]
        fence_id = uuid4().hex
        with self._transaction() as connection:
            settings = self._settings(connection)
            if settings["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            self._assert_fence_access(connection, observation_id)
            if (
                connection.execute(
                    "SELECT 1 FROM attempts WHERE state IN ('RESERVED','IN_FLIGHT') "
                    "UNION ALL SELECT 1 FROM mcp_calls WHERE state IN ('RESERVED','ADMITTED') LIMIT 1"
                ).fetchone()
                is not None
            ):
                raise RecoveryBlocked("UNRESOLVED_PENDING_ATTEMPT")
            if (
                connection.execute(
                    "SELECT 1 FROM observation_fences WHERE observation_id=?", (observation_id,)
                ).fetchone()
                is not None
            ):
                raise BudgetError("OBSERVATION_FENCE_ALREADY_EXISTS")
            self._reserve_observation(connection, observation_id, settings)
            connection.execute(
                "INSERT INTO observation_fences VALUES (?,?,'OPEN',?,NULL,NULL)",
                (observation_id, fence_id, _now()),
            )
        # Never grant the local capability before transaction commit returns.
        self._active_observation = (observation_id, fence_id)
        return fence_id

    def join_observation(self, observation_id: str, fence_id: str) -> None:
        """Join only a supplied current-run child capability; no restart recovery."""
        _identity(observation_id, "INVALID_OBSERVATION_ID")
        _identity(fence_id, "INVALID_FENCE_ID")
        if self._active_observation is not None:
            raise BudgetError("OBSERVATION_CAPABILITY_ALREADY_SET")
        with self._connection() as connection:
            if self._settings(connection)["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            row = connection.execute(
                "SELECT * FROM observation_fences WHERE observation_id=?", (observation_id,)
            ).fetchone()
            if row is None or row["state"] != "OPEN" or row["fence_id"] != fence_id:
                raise RecoveryBlocked("CURRENT_OBSERVATION_CAPABILITY_REQUIRED")
        self._active_observation = (observation_id, fence_id)

    def close_safe_observation(self, observation_id: str, summary_sha256: str) -> None:
        """Close a current successful observation after its summary is fsynced.

        No STOP, uncertain terminal result or pending reservation is clearable.
        This is successful current-completion only, never a STOP recovery API.
        A lost commit ACK is UNKNOWN: callers must not invent a new STOP solely
        because the already-safe closure acknowledgement was lost.
        """
        _hash(summary_sha256)
        with self._transaction() as connection:
            if self._settings(connection)["stopped"]:
                raise BudgetStopped("STOP_CLEARANCE_NOT_AUTHORIZED")
            self._assert_fence_access(connection, observation_id)
            row = connection.execute(
                "SELECT * FROM observation_fences WHERE observation_id=?", (observation_id,)
            ).fetchone()
            if (
                row is None
                or row["state"] != "OPEN"
                or self._active_observation != (observation_id, row["fence_id"])
            ):
                raise RecoveryBlocked("CURRENT_OBSERVATION_CAPABILITY_REQUIRED")
            unsafe = connection.execute(
                "SELECT 1 FROM attempts WHERE state!='TERMINAL' "
                "OR outcome NOT IN ('RESPONSE_OBSERVED','RESERVATION_NO_SEND') "
                "UNION ALL SELECT 1 FROM mcp_calls WHERE state!='TERMINAL' "
                "OR outcome!='CLIENT_RESPONSE_OBSERVED' LIMIT 1"
            ).fetchone()
            if unsafe is not None:
                raise RecoveryBlocked("UNRESOLVED_CUSTODY_CANNOT_CLOSE_FENCE")
            connection.execute(
                "UPDATE observation_fences SET state='CLOSED',closed_at_utc=?,summary_sha256=? "
                "WHERE observation_id=? AND state='OPEN'",
                (_now(), summary_sha256, observation_id),
            )
        self._active_observation = None

    def reserve(
        self,
        observation_id: str,
        role: str,
        requested_model: str,
        request_sha256: str,
        prompt_sha256: str,
        schema_sha256: str,
        retry_count: int = 0,
        retry_reason: str | None = None,
    ) -> AttemptReservation:
        _identity(observation_id, "INVALID_OBSERVATION_ID")
        _identity(requested_model, "INVALID_REQUESTED_MODEL")
        if role not in ROLES or type(retry_count) is not int or retry_count not in {0, 1}:
            raise ValueError("INVALID_ROLE_OR_RETRY_INDEX")
        for digest in (request_sha256, prompt_sha256, schema_sha256):
            _hash(digest)
        if retry_reason is not None:
            _identity(retry_reason, "INVALID_RETRY_REASON")
        if (retry_count == 0) != (retry_reason is None):
            raise ValueError("RETRY_REASON_BINDING_REQUIRED")
        with self._transaction() as connection:
            settings = self._settings(connection)
            if settings["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            self._assert_fence_access(connection, observation_id)
            prior = connection.execute(
                "SELECT * FROM attempts WHERE observation_id=? AND role=? ORDER BY retry_count",
                (observation_id, role),
            ).fetchall()
            if any(row["retry_count"] == retry_count for row in prior):
                raise BudgetError("DUPLICATE_ATTEMPT_RESERVATION")
            if retry_count:
                if len(prior) != 1 or prior[0]["outcome"] not in {
                    "RESPONSE_OBSERVED",
                    "RESERVATION_NO_SEND",
                }:
                    raise BudgetError("RETRY_WITHOUT_KNOWN_PRIOR_COMPLETION")
                original = json.loads(prior[0]["reservation_json"])
                if (
                    original["requested_model"],
                    original["request_sha256"],
                    original["prompt_sha256"],
                    original["schema_sha256"],
                ) != (requested_model, request_sha256, prompt_sha256, schema_sha256):
                    raise BudgetError("RETRY_IDENTITY_MISMATCH")
            role_count = connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE role=?", (role,)
            ).fetchone()[0]
            if role_count >= settings["role_caps"][role]:
                self._halt(connection, "ROLE_BUDGET_EXHAUSTED")
                connection.commit()
                raise BudgetExceeded("ROLE_BUDGET_EXHAUSTED")
            self._reserve_observation(connection, observation_id, settings)
            reservation = AttemptReservation(
                uuid4().hex,
                uuid4().hex,
                self.run_id,
                observation_id,
                role,
                requested_model,
                request_sha256,
                prompt_sha256,
                schema_sha256,
                retry_count,
                retry_reason,
                _now(),
            )
            connection.execute(
                "INSERT INTO attempts VALUES (?,?,?,?,?,?,'RESERVED',NULL,NULL,NULL,'{}')",
                (
                    reservation.attempt_id,
                    reservation.correlation_id,
                    json.dumps(asdict(reservation), sort_keys=True),
                    observation_id,
                    role,
                    retry_count,
                ),
            )
        return reservation

    @staticmethod
    def _row(connection: sqlite3.Connection, reservation: AttemptReservation) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM attempts WHERE attempt_id=?", (reservation.attempt_id,)
        ).fetchone()
        if row is None or json.loads(row["reservation_json"]) != asdict(reservation):
            raise BudgetError("RESERVATION_BINDING_MISMATCH")
        return cast(sqlite3.Row, row)

    def start(self, reservation: AttemptReservation) -> None:
        with self._transaction() as connection:
            if self._settings(connection)["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            self._assert_fence_access(connection, reservation.observation_id)
            row = self._row(connection, reservation)
            if row["state"] != "RESERVED":
                raise BudgetError("ATTEMPT_ALREADY_STARTED_OR_COMPLETED")
            connection.execute(
                "UPDATE attempts SET state='IN_FLIGHT', started_at_utc=? WHERE attempt_id=?",
                (_now(), reservation.attempt_id),
            )

    def finish(
        self, reservation: AttemptReservation, outcome: str, metadata: dict[str, Any] | None = None
    ) -> None:
        if outcome not in OUTCOMES:
            raise ValueError("UNSUPPORTED_ATTEMPT_OUTCOME")
        safe = _metadata(metadata)
        with self._transaction() as connection:
            row = self._row(connection, reservation)
            if row["state"] not in {"RESERVED", "IN_FLIGHT"}:
                raise BudgetError("ATTEMPT_ALREADY_COMPLETED")
            if outcome == "RESERVATION_NO_SEND" and row["state"] != "RESERVED":
                raise BudgetError("CANNOT_CLAIM_NO_SEND_AFTER_START")
            if outcome == "RESPONSE_OBSERVED" and row["state"] != "IN_FLIGHT":
                raise BudgetError("RESPONSE_REQUIRES_STARTED_ATTEMPT")
            connection.execute(
                "UPDATE attempts SET state='TERMINAL', completed_at_utc=?, outcome=?, metadata_json=? "
                "WHERE attempt_id=?",
                (
                    _now(),
                    outcome,
                    json.dumps(safe, sort_keys=True, allow_nan=False),
                    reservation.attempt_id,
                ),
            )
            if outcome in STOP_OUTCOMES:
                self._halt(connection, outcome)

    def stop(self, reason: str) -> None:
        _identity(reason, "INVALID_STOP_REASON")
        with self._transaction() as connection:
            self._halt(connection, reason)

    def reserve_mcp(self, observation_id: str, proposal_sha256: str) -> str:
        """Reserve one logical MCP call; this does not grant execution authority."""
        _identity(observation_id, "INVALID_OBSERVATION_ID")
        _hash(proposal_sha256)
        with self._transaction() as connection:
            settings = self._settings(connection)
            if settings["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            self._assert_fence_access(connection, observation_id)
            if (
                connection.execute(
                    "SELECT 1 FROM mcp_calls WHERE observation_id=?", (observation_id,)
                ).fetchone()
                is not None
            ):
                raise BudgetError("DUPLICATE_MCP_RESERVATION")
            self._reserve_observation(connection, observation_id, settings)
            reservation_id = uuid4().hex
            connection.execute(
                "INSERT INTO mcp_calls VALUES (?,?,?,'RESERVED',?,NULL,NULL,NULL,'{}')",
                (observation_id, reservation_id, proposal_sha256, _now()),
            )
        return reservation_id

    def admit_mcp(self, observation_id: str, proposal_sha256: str) -> None:
        """Consume a parent reservation at the evaluation receiver, exactly once."""
        _identity(observation_id, "INVALID_OBSERVATION_ID")
        _hash(proposal_sha256)
        with self._transaction() as connection:
            if self._settings(connection)["stopped"]:
                raise BudgetStopped("RUN_STOPPED")
            self._assert_fence_access(connection, observation_id)
            row = connection.execute(
                "SELECT * FROM mcp_calls WHERE observation_id=?", (observation_id,)
            ).fetchone()
            if row is None:
                raise BudgetError("MCP_RESERVATION_MISSING")
            if row["proposal_sha256"] != proposal_sha256:
                raise BudgetError("MCP_PROPOSAL_BINDING_MISMATCH")
            if row["state"] != "RESERVED":
                raise BudgetError("MCP_RESERVATION_ALREADY_ADMITTED_OR_COMPLETED")
            connection.execute(
                "UPDATE mcp_calls SET state='ADMITTED', admitted_at_utc=? WHERE observation_id=?",
                (_now(), observation_id),
            )

    def finish_mcp(
        self, observation_id: str, outcome: str, metadata: dict[str, Any] | None = None
    ) -> None:
        if outcome not in {"CLIENT_RESPONSE_OBSERVED", "CLIENT_RECEIPT_UNKNOWN"}:
            raise ValueError("UNSUPPORTED_MCP_OUTCOME")
        safe = _mcp_metadata(metadata)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM mcp_calls WHERE observation_id=?", (observation_id,)
            ).fetchone()
            if row is None or row["state"] not in {"RESERVED", "ADMITTED"}:
                raise BudgetError("MCP_RESERVATION_MISSING_OR_COMPLETED")
            connection.execute(
                "UPDATE mcp_calls SET state='TERMINAL', completed_at_utc=?, outcome=?, metadata_json=? "
                "WHERE observation_id=?",
                (
                    _now(),
                    outcome,
                    json.dumps(safe, sort_keys=True, allow_nan=False),
                    observation_id,
                ),
            )
            if outcome == "CLIENT_RECEIPT_UNKNOWN":
                self._halt(connection, outcome)

    def ensure_recoverable(self) -> None:
        """Explicit restart gate; pending custody is unknown, never safe to resend."""
        with self._transaction() as connection:
            settings = self._settings(connection)
            active_id = self._active_observation[0] if self._active_observation else ""
            self._assert_fence_access(connection, active_id)
            pending = connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE state IN ('RESERVED','IN_FLIGHT')"
            ).fetchone()[0]
            pending += connection.execute(
                "SELECT COUNT(*) FROM mcp_calls WHERE state IN ('RESERVED','ADMITTED')"
            ).fetchone()[0]
            if pending:
                self._halt(connection, "UNRESOLVED_PENDING_ATTEMPT")
                connection.commit()
                raise RecoveryBlocked("UNRESOLVED_PENDING_ATTEMPT")
            if settings["stopped"]:
                raise BudgetStopped("RUN_STOPPED")

    def snapshot(self) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            settings = self._settings(connection)
            rows = connection.execute("SELECT * FROM attempts ORDER BY rowid").fetchall()
            mcp_rows = connection.execute("SELECT * FROM mcp_calls ORDER BY rowid").fetchall()
            attempts = []
            for row in rows:
                entry = json.loads(row["reservation_json"])
                entry.update(
                    state=row["state"],
                    started_at_utc=row["started_at_utc"],
                    completed_at_utc=row["completed_at_utc"],
                    outcome=row["outcome"],
                    metadata=json.loads(row["metadata_json"]),
                )
                attempts.append(entry)
            return {
                "run_id": self.run_id,
                **settings,
                "counts": {
                    role: sum(row["role"] == role for row in rows) for role in sorted(ROLES)
                },
                "observation_count": connection.execute(
                    "SELECT COUNT(*) FROM observations"
                ).fetchone()[0],
                "attempts": attempts,
                "mcp_count": len(mcp_rows),
                "mcp_calls": [
                    {**dict(row), "metadata": json.loads(row["metadata_json"])} for row in mcp_rows
                ],
                "observation_fences": [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM observation_fences ORDER BY rowid"
                    ).fetchall()
                ],
                "admission_blocked": settings["stopped"]
                or bool(
                    connection.execute(
                        "SELECT 1 FROM observation_fences WHERE state='OPEN' LIMIT 1"
                    ).fetchone()
                ),
            }
