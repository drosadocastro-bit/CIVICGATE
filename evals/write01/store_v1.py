"""Synthetic-only SQLite review overlay; never a policy or binding issuer.

The trusted WRITE Gateway owns this backend. Its methods are not MCP tools.
OPEN is durable before adapter entry. Mutation and its evidence are one SQLite
transaction; custody ACK is separate. No method retries, refunds or clears OPEN.
This is local SQLite evidence, not certification for power loss or hostile hosts.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

DATASET_SHA256 = "7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d"
STORE_VERSION = "WRITE01_REVIEW_STORE_V1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE review_state (
  award_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('UNREVIEWED','PENDING_REVIEW')),
  version INTEGER NOT NULL CHECK(version IN (0,1))
);
CREATE TABLE intents (
  operation_id TEXT PRIMARY KEY,
  award_id TEXT NOT NULL REFERENCES review_state(award_id),
  idempotency_key TEXT NOT NULL UNIQUE,
  operation_json TEXT NOT NULL,
  operation_sha256 TEXT NOT NULL,
  binding_sha256 TEXT NOT NULL,
  custody TEXT NOT NULL CHECK(custody IN ('OPEN','CLOSED')),
  attempt_started INTEGER NOT NULL CHECK(attempt_started IN (0,1)),
  receipt_json TEXT,
  receipt_sha256 TEXT
);
CREATE UNIQUE INDEX one_open_per_target ON intents(award_id) WHERE custody='OPEN';
CREATE TABLE notes (
  operation_id TEXT PRIMARY KEY REFERENCES intents(operation_id),
  award_id TEXT NOT NULL REFERENCES review_state(award_id),
  version INTEGER NOT NULL CHECK(version=1),
  note TEXT NOT NULL
);
"""


class StoreError(RuntimeError):
    """Safe code only; sqlite/file paths never enter agent-visible errors."""

    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if type(value) is not dict:
        raise StoreError("STORE_EVIDENCE_INVALID")
    return value


def _safe_path(path: Path) -> Path:
    if not isinstance(path, Path) or any(p.is_symlink() for p in (path, *path.parents)):
        raise StoreError("STORE_PATH_INVALID")
    return path.resolve()


def _dataset(path: Path) -> tuple[str, ...]:
    try:
        raw = _safe_path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != DATASET_SHA256:
            raise StoreError("DATASET_IDENTITY_MISMATCH")
        value = json.loads(raw)
        records = value["records"]
        ids = tuple(r["award_id"] for r in records)
        if (
            len(ids) != 40
            or len(set(ids)) != 40
            or value["classification"] != "SYNTHETIC"
            or any(r["review_status"] != "UNREVIEWED" for r in records)
        ):
            raise StoreError("DATASET_CONTRACT_INVALID")
        return ids
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StoreError("DATASET_UNAVAILABLE_OR_INVALID") from exc


class ReviewStore:
    """Existing, explicitly initialized review store with immutable dataset pin.

    ``fault`` is trusted offline injection only, never caller-selected config.
    ``commit`` requires the Gateway's already consumed binding identity. The
    backend does not authenticate a digest or grant execution authority itself.
    """

    def __init__(
        self,
        path: Path,
        dataset_path: Path,
        store_id: str,
        *,
        fault: Callable[[str], None] | None = None,
        timeout: float = 1.0,
    ) -> None:
        if not isinstance(store_id, str) or not _ID.fullmatch(store_id):
            raise StoreError("STORE_ID_INVALID")
        if type(timeout) not in (int, float) or not 0 <= timeout <= 10:
            raise StoreError("STORE_TIMEOUT_INVALID")
        self.path = _safe_path(path)
        self.dataset_path = _safe_path(dataset_path)
        self.store_id = store_id
        self._ids = _dataset(self.dataset_path)
        self._fault = fault
        self._timeout = timeout
        connection = self._connect()
        try:
            self._validate(connection)
        finally:
            connection.close()

    @classmethod
    def initialize(cls, path: Path, dataset_path: Path, store_id: str) -> ReviewStore:
        """Create once. Failure preserves an incomplete file and fails closed."""
        ids = _dataset(dataset_path)
        if type(store_id) is not str or not _ID.fullmatch(store_id):
            raise StoreError("STORE_ID_INVALID")
        target = _safe_path(path)
        try:
            # Exclusive filesystem creation prevents overwriting a historical DB.
            with target.open("xb"):
                pass
            connection = sqlite3.connect(target.as_uri() + "?mode=rw", uri=True)
            try:
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.executescript("BEGIN IMMEDIATE;" + _SCHEMA)
                connection.executemany(
                    "INSERT INTO metadata VALUES (?,?)",
                    [
                        ("version", STORE_VERSION),
                        ("dataset_sha256", DATASET_SHA256),
                        ("store_id", store_id),
                    ],
                )
                connection.executemany(
                    "INSERT INTO review_state VALUES (?,'UNREVIEWED',0)", ((i,) for i in ids)
                )
                connection.commit()
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            raise StoreError("STORE_INITIALIZATION_FAILED") from exc
        return cls(target, dataset_path, store_id)

    def _connect(self) -> sqlite3.Connection:
        try:
            if _dataset(self.dataset_path) != self._ids or not self.path.is_file():
                raise StoreError("STORE_OR_DATASET_MISSING")
            _safe_path(self.path)
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=rw",
                uri=True,
                timeout=self._timeout,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise StoreError("STORE_UNAVAILABLE") from exc

    def _validate(self, connection: sqlite3.Connection) -> None:
        try:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise StoreError("STORE_CORRUPT")
            metadata = dict(connection.execute("SELECT key,value FROM metadata").fetchall())
            if metadata != {
                "version": STORE_VERSION,
                "dataset_sha256": DATASET_SHA256,
                "store_id": self.store_id,
            }:
                raise StoreError("STORE_IDENTITY_MISMATCH")
            rows = connection.execute("SELECT award_id,status,version FROM review_state").fetchall()
            if {r["award_id"] for r in rows} != set(self._ids) or len(rows) != 40:
                raise StoreError("STORE_TARGET_SET_INVALID")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise StoreError("STORE_REFERENCES_INVALID")
            committed: dict[str, dict[str, Any]] = {}
            for row in connection.execute("SELECT * FROM intents"):
                operation = self._operation(_object(row["operation_json"]))
                if (
                    canonical(operation) != row["operation_json"]
                    or digest(row["operation_json"]) != row["operation_sha256"]
                    or operation["query"]["award_id"] != row["award_id"]
                    or operation["query"]["idempotency_key"] != row["idempotency_key"]
                    or not _HEX.fullmatch(row["binding_sha256"])
                ):
                    raise StoreError("STORE_OPERATION_INCONSISTENT")
                receipt_raw = row["receipt_json"]
                if receipt_raw is None:
                    if row["receipt_sha256"] is not None or row["custody"] != "OPEN":
                        raise StoreError("STORE_CUSTODY_INCONSISTENT")
                    continue
                receipt = _object(receipt_raw)
                if (
                    canonical(receipt) != receipt_raw
                    or digest(receipt_raw) != row["receipt_sha256"]
                    or receipt
                    != self._receipt(row["operation_id"], operation, row["binding_sha256"])
                    or operation["query"]["expected_version"] != 0
                    or row["attempt_started"] != 1
                    or row["award_id"] in committed
                ):
                    raise StoreError("STORE_RECEIPT_INCONSISTENT")
                committed[row["award_id"]] = receipt
            note_rows = connection.execute("SELECT * FROM notes").fetchall()
            notes = {r["award_id"]: dict(r) for r in note_rows}
            if len(notes) != len(note_rows) or set(notes) != set(committed):
                raise StoreError("STORE_NOTES_INCONSISTENT")
            if connection.execute(
                "SELECT 1 FROM intents WHERE receipt_json IS NULL AND award_id IN (SELECT award_id FROM notes)"
            ).fetchone():
                raise StoreError("STORE_UNCOMMITTED_INTENT_AFTER_MUTATION")
            for row in rows:
                state_receipt = committed.get(row["award_id"])
                if state_receipt is None:
                    if row["status"] != "UNREVIEWED" or row["version"] != 0:
                        raise StoreError("STORE_STATE_WITHOUT_EVIDENCE")
                elif (
                    row["status"] != "PENDING_REVIEW"
                    or row["version"] != 1
                    or notes[row["award_id"]]
                    != {
                        "operation_id": state_receipt["operation_id"],
                        "award_id": row["award_id"],
                        "version": 1,
                        "note": state_receipt["after"]["notes"][0],
                    }
                ):
                    raise StoreError("STORE_STATE_EVIDENCE_MISMATCH")
        except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise StoreError("STORE_INVALID_OR_UNAVAILABLE") from exc

    def _operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        try:
            value = _object(canonical(operation))
            if value["dataset_sha256"] != DATASET_SHA256 or value["store_id"] != self.store_id:
                raise StoreError("OPERATION_CONTEXT_MISMATCH")
            query = value["query"]
            if type(query) is not dict or set(query) != {
                "award_id",
                "expected_version",
                "proposed_status",
                "reviewer_note",
                "idempotency_key",
            }:
                raise StoreError("OPERATION_QUERY_INVALID")
            if query["award_id"] not in self._ids:
                raise StoreError("UNKNOWN_SYNTHETIC_AWARD")
            if type(query["expected_version"]) is not int or query["expected_version"] < 0:
                raise StoreError("EXPECTED_VERSION_INVALID")
            if query["proposed_status"] != "PENDING_REVIEW":
                raise StoreError("TRANSITION_NOT_SUPPORTED")
            note = query["reviewer_note"]
            if (
                type(note) is not str
                or not 1 <= len(note) <= 1000
                or len(note.encode("utf-8")) > 4000
                or any(ord(c) < 32 and c not in "\n\t" for c in note)
            ):
                raise StoreError("NOTE_INVALID")
            if type(query["idempotency_key"]) is not str or not _ID.fullmatch(
                query["idempotency_key"]
            ):
                raise StoreError("IDEMPOTENCY_KEY_INVALID")
            for field in ("owner_id", "approval_ref", "original_request"):
                if type(value[field]) is not str or not value[field] or len(value[field]) > 4000:
                    raise StoreError("OPERATION_PROVENANCE_INVALID")
            return value
        except (ValueError, TypeError, KeyError) as exc:
            raise StoreError("OPERATION_INVALID") from exc

    def _available(self, connection: sqlite3.Connection, operation: dict[str, Any]) -> None:
        query = operation["query"]
        existing = connection.execute(
            "SELECT operation_sha256 FROM intents WHERE idempotency_key=?",
            (query["idempotency_key"],),
        ).fetchone()
        if existing is not None:
            code = (
                "IDEMPOTENCY_DUPLICATE"
                if existing[0] == digest(canonical(operation))
                else "IDEMPOTENCY_CONFLICT"
            )
            raise StoreError(code)
        if connection.execute(
            "SELECT 1 FROM intents WHERE award_id=? AND custody='OPEN'", (query["award_id"],)
        ).fetchone():
            raise StoreError("TARGET_CUSTODY_OPEN", uncertain=True)
        row = connection.execute(
            "SELECT status,version FROM review_state WHERE award_id=?", (query["award_id"],)
        ).fetchone()
        if row is None:
            raise StoreError("UNKNOWN_SYNTHETIC_AWARD")
        if row["version"] != query["expected_version"]:
            raise StoreError("EXPECTED_VERSION_CONFLICT")
        if row["status"] != "UNREVIEWED":
            raise StoreError("TRANSITION_NOT_SUPPORTED")

    def check_available(self, operation: dict[str, Any]) -> None:
        value = self._operation(operation)
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._validate(connection)
            self._available(connection, value)
        except sqlite3.Error as exc:
            raise StoreError("STORE_UNAVAILABLE") from exc
        finally:
            connection.close()

    def snapshot(self, award_id: str) -> dict[str, Any]:
        if award_id not in self._ids:
            raise StoreError("UNKNOWN_SYNTHETIC_AWARD")
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._validate(connection)
            row = connection.execute(
                "SELECT status,version FROM review_state WHERE award_id=?", (award_id,)
            ).fetchone()
            notes = [
                r[0]
                for r in connection.execute(
                    "SELECT note FROM notes WHERE award_id=? ORDER BY version", (award_id,)
                )
            ]
            return {
                "award_id": award_id,
                "dataset_sha256": DATASET_SHA256,
                "status": row["status"],
                "version": row["version"],
                "notes": notes,
            }
        except sqlite3.Error as exc:
            raise StoreError("STORE_UNAVAILABLE") from exc
        finally:
            connection.close()

    def _inject(self, stage: str) -> None:
        if self._fault is not None:
            self._fault(stage)

    def reserve(
        self, operation_id: str, operation: dict[str, Any], binding_sha256: str
    ) -> dict[str, Any]:
        if (
            type(operation_id) is not str
            or not _ID.fullmatch(operation_id)
            or type(binding_sha256) is not str
            or not _HEX.fullmatch(binding_sha256)
        ):
            raise StoreError("INTENT_IDENTITY_INVALID")
        value = self._operation(operation)
        connection = self._connect()
        commit_started = False
        try:
            self._inject("before_open")
            connection.execute("BEGIN IMMEDIATE")
            self._validate(connection)
            self._available(connection, value)
            connection.execute(
                "INSERT INTO intents VALUES (?,?,?,?,?,?,'OPEN',0,NULL,NULL)",
                (
                    operation_id,
                    value["query"]["award_id"],
                    value["query"]["idempotency_key"],
                    canonical(value),
                    digest(canonical(value)),
                    binding_sha256,
                ),
            )
            commit_started = True
            connection.commit()
            self._inject("after_open")
            return {
                "operation_id": operation_id,
                "custody": "OPEN",
                "operation_sha256": digest(canonical(value)),
                "binding_sha256": binding_sha256,
            }
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(
                "OPEN_ACK_UNKNOWN" if commit_started else "OPEN_NOT_CONFIRMED",
                uncertain=commit_started,
            ) from exc
        finally:
            connection.close()

    def _receipt(
        self, operation_id: str, operation: dict[str, Any], binding_sha256: str
    ) -> dict[str, Any]:
        query = operation["query"]
        base = {"award_id": query["award_id"], "dataset_sha256": DATASET_SHA256}
        before = {**base, "status": "UNREVIEWED", "version": 0, "notes": []}
        after = {
            **base,
            "status": "PENDING_REVIEW",
            "version": 1,
            "notes": [query["reviewer_note"]],
        }
        return {
            "contract": STORE_VERSION,
            "store_id": self.store_id,
            "operation_id": operation_id,
            "operation": operation,
            "operation_sha256": digest(canonical(operation)),
            "binding_sha256": binding_sha256,
            "before": before,
            "after": after,
            "before_sha256": digest(canonical(before)),
            "after_sha256": digest(canonical(after)),
            "transaction_outcome": "COMMITTED",
        }

    def commit(self, operation_id: str, binding_sha256: str) -> dict[str, Any]:
        """Adapter action. Gateway must have consumed this exact binding first."""
        connection = self._connect()
        committed = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate(connection)
            row = connection.execute(
                "SELECT * FROM intents WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None or row["custody"] != "OPEN" or row["binding_sha256"] != binding_sha256:
                raise StoreError("DISPATCH_INTENT_MISMATCH")
            if row["receipt_json"] is not None:
                raise StoreError("COMMITTED_OPERATION_NOT_REDISPATCHABLE", uncertain=True)
            if row["attempt_started"]:
                raise StoreError("ADAPTER_ATTEMPT_NOT_REDISPATCHABLE", uncertain=True)
            # Persist the one adapter entry before the mutation transaction. A
            # rollback, restart or failed commit cannot erase this admission.
            connection.execute(
                "UPDATE intents SET attempt_started=1 WHERE operation_id=?", (operation_id,)
            )
            connection.commit()
            self._inject("after_attempt_start")
            connection.execute("BEGIN IMMEDIATE")
            self._validate(connection)
            operation = self._operation(_object(row["operation_json"]))
            query = operation["query"]
            before = connection.execute(
                "SELECT * FROM review_state WHERE award_id=?", (query["award_id"],)
            ).fetchone()
            if before["version"] != query["expected_version"] or before["status"] != "UNREVIEWED":
                raise StoreError("TRANSACTION_STATE_CONFLICT")
            receipt = self._receipt(operation_id, operation, binding_sha256)
            raw = canonical(receipt)
            connection.execute(
                "UPDATE review_state SET status='PENDING_REVIEW',version=version+1 WHERE award_id=?",
                (query["award_id"],),
            )
            connection.execute(
                "INSERT INTO notes VALUES (?,?,1,?)",
                (operation_id, query["award_id"], query["reviewer_note"]),
            )
            connection.execute(
                "UPDATE intents SET receipt_json=?,receipt_sha256=? WHERE operation_id=?",
                (raw, digest(raw), operation_id),
            )
            self._inject("before_commit")
            connection.commit()
            committed = True
            self._inject("after_commit")
            return {"receipt": receipt, "receipt_sha256": digest(raw), "custody": "OPEN"}
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(
                "COMMIT_ACK_UNKNOWN" if committed else "TRANSACTION_NOT_CONFIRMED", uncertain=True
            ) from exc
        finally:
            connection.close()

    def acknowledge(self, operation_id: str, receipt_sha256: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate(connection)
            row = connection.execute(
                "SELECT * FROM intents WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if (
                row is None
                or row["custody"] != "OPEN"
                or row["receipt_json"] is None
                or row["receipt_sha256"] != receipt_sha256
            ):
                raise StoreError("CUSTODY_ACK_MISMATCH", uncertain=True)
            self._inject("before_ack")
            connection.execute(
                "UPDATE intents SET custody='CLOSED' WHERE operation_id=?", (operation_id,)
            )
            connection.commit()
            self._inject("after_ack")
            return {
                "operation_id": operation_id,
                "receipt_sha256": receipt_sha256,
                "custody": "CLOSED",
                "human_acceptance": "NOT_ESTABLISHED",
            }
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError("CUSTODY_ACK_UNKNOWN", uncertain=True) from exc
        finally:
            connection.close()

    def inspect(self, operation_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._validate(connection)
            row = connection.execute(
                "SELECT * FROM intents WHERE operation_id=?", (operation_id,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error as exc:
            raise StoreError("STORE_UNAVAILABLE") from exc
        finally:
            connection.close()

    def checkpoint(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            self._validate(connection)
            return {
                "version": STORE_VERSION,
                "store_id": self.store_id,
                "dataset_sha256": DATASET_SHA256,
                "states": [
                    dict(r)
                    for r in connection.execute("SELECT * FROM review_state ORDER BY award_id")
                ],
                "notes": [
                    dict(r) for r in connection.execute("SELECT * FROM notes ORDER BY operation_id")
                ],
                "intents": [
                    dict(r)
                    for r in connection.execute("SELECT * FROM intents ORDER BY operation_id")
                ],
            }
        except sqlite3.Error as exc:
            raise StoreError("STORE_UNAVAILABLE") from exc
        finally:
            connection.close()
