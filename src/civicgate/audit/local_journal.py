"""B2a local SQLite journal. No release API, authority reconstruction or retries.

Requires an explicitly provisioned local store and an exclusive process lock.
SQLite DELETE/EXTRA acknowledges transactions before dispatch. This assumes
a trusted local filesystem/OS honoring flushes; power loss is not certified.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from time import time
from typing import Any, BinaryIO
from uuid import uuid4

from civicgate.governance.execution import AuthorityEnvelope
from civicgate.mcp.http_identity import LocalHold, TrustDomain, invocation_context
from civicgate.models.responses import Envelope

MAX_EVENTS = 10000


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(previous: str, payload: str) -> str:
    return hashlib.sha256((previous + payload).encode()).hexdigest()


def _lock(file: BinaryIO) -> None:
    file.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=0)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=EXTRA")
    if connection.execute("PRAGMA synchronous").fetchone()[0] != 3:
        connection.close()
        raise LocalHold("DURABILITY_UNAVAILABLE")
    return connection


def provision_local_store(path: Path, domain: TrustDomain) -> None:
    """Explicit, one-time synthetic-store bootstrap. Never called by app startup.

    A replacement process MUST reopen the original path and trust domain. A new
    empty store is a human-controlled operation, never recovery clearance.
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    with path.with_suffix(path.suffix + ".owner").open("xb") as lockfile:
        lockfile.write(b"0")
        lockfile.flush()
        os.fsync(lockfile.fileno())
    connection = _connect(path)
    try:
        with connection:
            connection.execute(
                "CREATE TABLE events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, "
                "previous TEXT NOT NULL, digest TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TRIGGER no_update BEFORE UPDATE ON events "
                "BEGIN SELECT RAISE(ABORT, 'append only'); END"
            )
            connection.execute(
                "CREATE TRIGGER no_delete BEFORE DELETE ON events "
                "BEGIN SELECT RAISE(ABORT, 'append only'); END"
            )
            payload = _json({"kind": "provision", "domain": asdict(domain), "version": 1})
            connection.execute(
                "INSERT INTO events VALUES (1, ?, '', ?)", (payload, _hash("", payload))
            )
    finally:
        connection.close()


class LocalDispatchJournal:
    def __init__(self, path: Path, domain: TrustDomain, code_revision: str) -> None:
        if len(code_revision) != 40 or any(c not in "0123456789abcdef" for c in code_revision):
            raise ValueError("Exact source revision required")
        root = Path(__file__).resolve().parents[3]
        actual_revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=5
        ).strip()
        if actual_revision != code_revision:
            raise ValueError("Configured source revision does not match local HEAD")
        # HEAD alone does not identify an edited worktree. Persist a deterministic
        # snapshot of the actual Python sources as well, including new modules.
        manifest = {
            str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted((root / "src" / "civicgate").rglob("*.py"))
        }
        manifest["pyproject.toml"] = hashlib.sha256(
            (root / "pyproject.toml").read_bytes()
        ).hexdigest()
        self.source_sha256 = hashlib.sha256(_json(manifest).encode()).hexdigest()
        self.path = path.resolve()
        self.domain = domain
        self.code_revision = code_revision
        self.generation = str(uuid4())
        self.denials = 0
        self.held = False
        self.active: str | None = None
        self.closed = False
        self._owner: BinaryIO | None = None
        self._db: sqlite3.Connection | None = None
        self._sequence = 0
        self._digest = ""
        try:
            if self.path.stat().st_size > 32 * 1024 * 1024:
                raise LocalHold("RECOVERY_STORE_TOO_LARGE")
            self._owner = self.path.with_suffix(self.path.suffix + ".owner").open("r+b")
            _lock(self._owner)
            self._db = _connect(self.path)
            if self._db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise LocalHold("RECOVERY_INVALID")
            rows = self._db.execute(
                "SELECT seq,payload,previous,digest FROM events ORDER BY seq LIMIT ?",
                (MAX_EVENTS + 1,),
            ).fetchall()
            if not rows or len(rows) >= MAX_EVENTS:
                raise LocalHold("RECOVERY_MISSING_OR_FULL")
            open_generation = False
            pending: set[str] = set()
            for seq, payload, previous, digest in rows:
                if (
                    seq != self._sequence + 1
                    or previous != self._digest
                    or digest != _hash(previous, payload)
                ):
                    raise LocalHold("RECOVERY_INVALID")
                event = json.loads(payload)
                kind = event["kind"]
                if seq == 1:
                    if event != {"kind": "provision", "domain": asdict(domain), "version": 1}:
                        raise LocalHold("TRUST_DOMAIN_MISMATCH")
                elif kind == "boot":
                    if open_generation:
                        self.held = True
                    open_generation = True
                elif kind == "close":
                    open_generation = False
                elif kind == "begin":
                    pending.add(event["request_id"])
                elif kind == "finish":
                    pending.remove(event["request_id"])
                    self.denials = max(self.denials, event["denials"])
                    self.held |= event["hold"]
                elif kind == "hold":
                    self.held = True
                elif kind not in {"policy", "intent"}:
                    raise LocalHold("RECOVERY_INVALID")
                self._sequence, self._digest = seq, digest
            if self.held or pending or open_generation:
                raise LocalHold("RECOVERY_HOLD")
            self._append("boot", code_revision=code_revision, source_sha256=self.source_sha256)
        except BaseException:
            self._release()
            raise

    def _append(self, kind: str, **evidence: Any) -> None:
        try:
            if self.closed or self._db is None or self._sequence >= MAX_EVENTS:
                raise LocalHold("JOURNAL_UNAVAILABLE")
            # Missing/replaced files cannot be mistaken for a fresh clearance.
            if not self.path.is_file():
                raise LocalHold("JOURNAL_MISSING")
            payload = _json(
                {"kind": kind, "generation": self.generation, "time": time(), **evidence}
            )
            digest = _hash(self._digest, payload)
            with self._db:
                if self._db.execute("SELECT max(seq) FROM events").fetchone()[0] != self._sequence:
                    raise LocalHold("JOURNAL_CONCURRENT_CHANGE")
                self._db.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?)",
                    (self._sequence + 1, payload, self._digest, digest),
                )
            self._sequence += 1
            self._digest = digest
        except BaseException:
            self.held = True
            raise

    def _context(self) -> dict[str, Any]:
        context = invocation_context.get()
        if context is None or (
            context.principal != self.domain.principal
            or context.issuer != self.domain.issuer
            or context.audience != self.domain.audience
            or context.expires_at <= time()
        ):
            raise LocalHold("AUTH_CONTEXT_INVALID_OR_EXPIRED")
        return context.evidence()

    def admit(self) -> int:
        if self.held or self.active or self.closed:
            raise LocalHold("DURABLE_HOLD")
        self._context()
        return self.denials

    def begin(self, request_id: str) -> None:
        self._append(
            "begin",
            request_id=request_id,
            context=self._context(),
            channel="B",
            instance=self.domain.instance,
            service_identity=self.domain.service_identity,
        )
        self.active = request_id

    def policy(self, request_id: str, evidence: dict[str, Any]) -> None:
        self._append("policy", request_id=request_id, **evidence)

    def intent(self, authority: AuthorityEnvelope | None) -> None:
        if authority is None or authority.binding.request_id != self.active:
            raise LocalHold("INTENT_BINDING_MISSING")
        self._append(
            "intent",
            request_id=self.active,
            context=self._context(),
            authority=authority.audit_record(),
            containment_denials=self.denials,
            dispatch_state="NOT_DISPATCHED",
            code_revision=self.code_revision,
            source_sha256=self.source_sha256,
        )
        # A disk delay must not extend credential validity. ExecutionBoundary
        # subsequently revalidates binding expiry and consumes it, without callbacks.
        self._context()

    def finish(self, envelope: Envelope, denials: int, evidence: dict[str, Any]) -> None:
        unknown = envelope.tool_executed and (
            not envelope.attempt_metadata_available
            or envelope.dispatch_state != "REQUEST_CONFIRMED"
            or envelope.response_state != "RESPONSE_RECEIVED"
            or any(
                a["dispatch_state"] == "DISPATCH_UNKNOWN"
                or a["response_state"] == "TRANSPORT_ERROR"
                for a in evidence["attempts"]
            )
        )
        # Execution outcome handling, not a second policy decision.
        if unknown:
            envelope.next_action = "HUMAN_REVIEW_REQUIRED"
            envelope.clarification = "DISPATCH_UNKNOWN: durable HOLD; no retry or failover."
            envelope.result = None
            for error in envelope.errors:
                error.retryable = False
        self._append(
            "finish",
            request_id=envelope.request_id,
            denials=denials,
            hold=unknown,
            final_decision=envelope.decision,
            phase="post_dispatch" if envelope.tool_executed else "pre_dispatch",
            binding_consumed=evidence["pre_dispatch_verification"] == "PASS",
            policy_reasons=envelope.governance.policy_reasons,
            tool_executed=envelope.tool_executed,
            dispatch_state=envelope.dispatch_state,
            response_state=envelope.response_state,
            next_action=envelope.next_action,
            errors=[e.model_dump() for e in envelope.errors],
            **evidence,
        )
        self.denials = denials
        self.held |= unknown
        self.active = None

    def failed(self, error: BaseException) -> None:
        self.held = True
        try:
            self._append(
                "hold",
                request_id=self.active,
                reason=str(error) if isinstance(error, LocalHold) else "INCOMPLETE_CALL",
                error_type=type(error).__name__,
                sqlite_errorname=getattr(error, "sqlite_errorname", None),
            )
        except Exception:
            # The already durable unmatched boot/begin also forces recovery HOLD.
            pass

    def _release(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
        if self._owner is not None:
            self._owner.close()
            self._owner = None

    def close(self) -> None:
        try:
            if not self.closed and not self.held and not self.active:
                self._append("close")
        finally:
            self.closed = True
            self._release()
