"""Phase 1.3 cooperative receiver experiment; no production composition.

Caller identity and epoch provenance are deliberately outside this experiment.
An authorized-looking wire message is NOT an authenticated AuthorityEnvelope.
Only the trusted synthetic harness supplies messages and publishes authority.
F2 protects a database-local effect relative to serialized durable publication,
not physical session loss, an arbitrary HTTP effect, or current real-world truth.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from civicgate.audit.postgres_journal import ConnectionFactory, PostgresConnection

Mode = Literal["U", "F1", "F2"]
Hook = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class Request:
    scope: str
    owner: str
    epoch: int
    request_id: str
    payload_sha256: str

    @classmethod
    def parse(cls, raw: bytes) -> "Request":
        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("DUPLICATE_FIELD")
                value[key] = item
            return value

        if len(raw) > 4096:
            raise ValueError("REQUEST_TOO_LARGE")
        obj = json.loads(raw, object_pairs_hook=unique)
        if type(obj) is not dict or set(obj) != {
            "scope",
            "owner",
            "epoch",
            "request_id",
            "payload_sha256",
        }:
            raise ValueError("INVALID_FIELDS")
        if any(
            type(obj[k]) is not str or not 1 <= len(obj[k]) <= 128
            for k in ("scope", "owner", "request_id")
        ):
            raise ValueError("INVALID_IDENTIFIER")
        if type(obj["epoch"]) is not int or not 1 <= obj["epoch"] < 2**63:
            raise ValueError("INVALID_EPOCH")
        digest = obj["payload_sha256"]
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("INVALID_PAYLOAD_DIGEST")
        return cls(**obj)

    def fingerprint(self) -> str:
        value = [self.scope, self.owner, self.epoch, self.request_id, self.payload_sha256]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Outcome:
    status: str
    effect: str  # APPLIED / REFUSED / ALREADY_COMMITTED / UNKNOWN
    reason: str


def check_authority(request: Request, row: tuple[Any, ...] | None) -> str | None:
    """Validate the locked row itself; never accept absent/ill-typed authority."""
    if row is None or len(row) != 3:
        return "AUTHORITY_UNKNOWN"
    epoch, owner, revoked = row
    if (
        type(epoch) is not int
        or epoch < 1
        or type(owner) is not str
        or not owner
        or type(revoked) is not bool
    ):
        return "AUTHORITY_UNKNOWN"
    if revoked:
        return "REVOKED"
    if epoch != request.epoch or owner != request.owner:
        return "STALE_OR_UNKNOWN_OWNER"
    return None


class PostgresReceiver:
    """Fresh direct connection per request; no retries, caches or takeover.

    F1 serializes highest-seen update, dedup and effect under a receiver-scope row.
    F2 additionally locks the authoritative row FOR SHARE until effect commit.
    All authority publishers must UPDATE that same row on the same primary.
    The effect and receipt are in the very same transaction/database. Ambiguous
    COMMIT is UNKNOWN, even when a later independent inspection sees an effect.
    The hook is a trusted test cutpoint, never a client-supplied callback.
    """

    def __init__(self, mode: Mode, connect: ConnectionFactory, hook: Hook | None = None):
        if mode not in ("U", "F1", "F2"):
            raise ValueError("UNSUPPORTED_RECEIVER")
        self.mode = mode
        self.connect = connect
        self.hook = hook or (lambda _event, _data: None)

    def receive(self, raw: bytes) -> Outcome:
        try:
            request = Request.parse(raw)
        except (ValueError, TypeError, UnicodeError):
            return Outcome("REJECTED", "REFUSED", "INVALID_REQUEST")
        connection: PostgresConnection | None = None
        try:
            connection = self.connect()
            if connection.autocommit is not False:
                raise ValueError("TRANSACTION_REQUIRED")
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cursor.execute("SET LOCAL synchronous_commit = 'on'")
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute("SHOW fsync")
                if cursor.fetchone() != ("on",):
                    raise ValueError("DURABILITY_UNAVAILABLE")
                cursor.execute("SELECT pg_backend_pid()")
                self.hook("receiver_transaction_started", {"backend_pid": cursor.fetchone()[0]})  # type: ignore[index]
                cursor.execute(
                    "SELECT highest_epoch FROM b2b_receiver.scopes WHERE mode=%s AND scope=%s FOR UPDATE",
                    (self.mode, request.scope),
                )
                row = cursor.fetchone()
                if row is None or type(row[0]) is not int or row[0] < 0:
                    return Outcome("REJECTED", "REFUSED", "SCOPE_UNKNOWN")
                self.hook("receiver_scope_locked", {"mode": self.mode, "highest_epoch": row[0]})
                if self.mode == "F1":
                    if request.epoch < row[0]:
                        return Outcome("REJECTED", "REFUSED", "LOWER_THAN_HIGHEST_SEEN")
                    cursor.execute(
                        "UPDATE b2b_receiver.scopes SET highest_epoch=%s WHERE mode=%s AND scope=%s",
                        (request.epoch, self.mode, request.scope),
                    )
                elif self.mode == "F2":
                    cursor.execute(
                        "SELECT epoch,owner,revoked FROM b2b_receiver.authority WHERE scope=%s FOR SHARE",
                        (request.scope,),
                    )
                    authority = cursor.fetchone()
                    reason = check_authority(request, authority)
                    self.hook(
                        "authority_locked_and_checked", {"authority": authority, "reason": reason}
                    )
                    if reason is not None:
                        return Outcome("REJECTED", "REFUSED", reason)
                if self.mode != "U":
                    cursor.execute(
                        "SELECT fingerprint FROM b2b_receiver.receipts WHERE mode=%s AND scope=%s AND request_id=%s",
                        (self.mode, request.scope, request.request_id),
                    )
                    prior = cursor.fetchone()
                    if prior is not None:
                        if prior != (request.fingerprint(),):
                            return Outcome("REJECTED", "REFUSED", "REQUEST_ID_CONFLICT")
                        return Outcome("DUPLICATE", "ALREADY_COMMITTED", "NO_NEW_EFFECT")
                    cursor.execute(
                        "INSERT INTO b2b_receiver.receipts(mode,scope,request_id,fingerprint) VALUES(%s,%s,%s,%s)",
                        (self.mode, request.scope, request.request_id, request.fingerprint()),
                    )
                self.hook("before_effect", {"mode": self.mode, "epoch": request.epoch})
                cursor.execute(
                    "INSERT INTO b2b_receiver.effects(effect_id,mode,scope,request_id,epoch,payload_sha256) VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        uuid4().hex,
                        self.mode,
                        request.scope,
                        request.request_id,
                        request.epoch,
                        request.payload_sha256,
                    ),
                )
                self.hook("effect_inserted_uncommitted", {"mode": self.mode})
                connection.commit()
                self.hook("effect_commit_acknowledged", {"mode": self.mode})
                return Outcome("ACCEPTED", "APPLIED", "COMMIT_ACKNOWLEDGED")
            finally:
                cursor.close()
        except Exception as error:
            self.hook("receiver_uncertain", {"error_type": type(error).__name__})
            return Outcome("UNKNOWN", "UNKNOWN", "STORE_OR_COMMIT_UNCONFIRMED")
        finally:
            if connection is not None:
                # Read/rejection paths roll back. Never retry an ambiguous write.
                try:
                    connection.rollback()
                except Exception:
                    pass
                try:
                    connection.close()
                except Exception:
                    pass
