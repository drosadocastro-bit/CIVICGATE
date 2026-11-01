"""EVAL-002B-R1 shared offline admission and persistent single-send custody.

The accepted R4 budget is inherited without editing it. Only exclusive create()
adds this schema to a NEW store; historical stores are never migrated. A lease
ACK permits one synthetic HTTP first-header operation; it is not proof that any
bytes arrived, model execution completed, or a monetary limit was verified.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit
from uuid import uuid4

from evals.harness import attempt_budget_v2 as r4
from evals.harness.monetary_admission_v1 import LiabilityPolicy, policy_document

R4_SOURCE_SHA256 = "32a2ad4d49b5ea7715c5d5e7adc34e8b46be3d9a2224a0fed7288b6104d2d31a"
AttemptReservation = r4.AttemptReservation
BudgetError = r4.BudgetError
BudgetExceeded = r4.BudgetExceeded
BudgetStopped = r4.BudgetStopped
BudgetUnavailable = r4.BudgetUnavailable
RecoveryBlocked = r4.RecoveryBlocked


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _check_origin(origin: str, *, wire: bool = False) -> None:
    if type(origin) is not str:
        raise ValueError("CANONICAL_ORIGIN_REQUIRED")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("CANONICAL_ORIGIN_REQUIRED") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or origin != f"{parsed.scheme}://{parsed.netloc}"
        or any(ord(char) <= 32 for char in origin)
    ):
        raise ValueError("CANONICAL_ORIGIN_REQUIRED")
    if wire and (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not 1 <= port <= 65535
        or origin != f"http://127.0.0.1:{port}"
    ):
        raise ValueError("SYNTHETIC_LOOPBACK_WIRE_ORIGIN_REQUIRED")


@dataclass(frozen=True)
class SendLeaseReceipt:
    lease_id: str
    attempt_id: str
    run_id: str
    observation_id: str
    role: str
    request_sha256: str
    schema_sha256: str
    logical_origin: str
    wire_fixture_origin: str
    effective_invocation_sha256: str | None
    acknowledged_at_utc: str


@dataclass(frozen=True)
class ResponseFactsReceipt:
    attempt_id: str
    run_id: str
    observation_id: str
    role: str
    request_sha256: str
    facts_sha256: str
    acknowledged_at_utc: str


def _response_facts(facts: dict[str, Any]) -> dict[str, Any]:
    enums = {
        "model_identity": {"MATCH", "MISMATCH", "MISSING", "MALFORMED"},
        "completion": {"COMPLETE", "INCOMPLETE", "UNKNOWN"},
        "refusal": {"PRESENT", "ABSENT_OR_NULL", "UNKNOWN"},
        "usage": {"KNOWN", "UNKNOWN", "INVALID"},
        "typed_schema": {"PASS", "FAIL", "NOT_PARSED"},
        "contract": {"PASS", "FAIL"},
    }
    required = set(enums) | {"http_status", "body_sha256", "body_bytes", "returned_model", "errors"}
    if type(facts) is not dict or set(facts) != required:
        raise ValueError("EXPLICIT_RESPONSE_FACTS_FIELDS_REQUIRED")
    for field, allowed in enums.items():
        if type(facts[field]) is not str or facts[field] not in allowed:
            raise ValueError("INVALID_RESPONSE_FACTS_ENUM")
    if type(facts["http_status"]) is not int or not 100 <= facts["http_status"] <= 599:
        raise ValueError("INVALID_RESPONSE_FACTS_HTTP_STATUS")
    if type(facts["body_bytes"]) is not int or facts["body_bytes"] < 0:
        raise ValueError("INVALID_RESPONSE_FACTS_BODY_BYTES")
    r4._hash(facts["body_sha256"])
    model = facts["returned_model"]
    if model is not None and (
        type(model) is not str
        or not model
        or len(model) > 200
        or any(ord(char) < 32 for char in model)
    ):
        raise ValueError("INVALID_RESPONSE_FACTS_MODEL")
    errors = facts["errors"]
    if (
        type(errors) is not list
        or len(errors) > 16
        or any(
            type(value) is not str
            or not value
            or len(value) > 160
            or any(ord(char) < 32 for char in value)
            for value in errors
        )
    ):
        raise ValueError("INVALID_RESPONSE_FACTS_ERRORS")
    # Serialize once before admission to remove external mutable aliases.
    return cast(dict[str, Any], json.loads(_canonical(facts)))


class LiveAttemptBudget(r4.AttemptBudget):
    """Atomic attempt, nonmonetary liability, context and one-use send ledger."""

    def __init__(self, path: Path, run_id: str) -> None:
        if hashlib.sha256(Path(r4.__file__).read_bytes()).hexdigest() != R4_SOURCE_SHA256:
            raise BudgetUnavailable("ACCEPTED_R4_SOURCE_PIN_MISMATCH")
        super().__init__(path, run_id)
        with self._connection() as connection:
            self._live_policy_pin = self._live_document(connection)

    @classmethod
    def create(
        cls,
        path: Path,
        run_id: str,
        *,
        role_caps: dict[str, int] | None = None,
        max_observations: int = 6,
        liability_policy: LiabilityPolicy | None = None,
    ) -> LiveAttemptBudget:
        document = policy_document(liability_policy)
        if hashlib.sha256(Path(r4.__file__).read_bytes()).hexdigest() != R4_SOURCE_SHA256:
            raise BudgetUnavailable("ACCEPTED_R4_SOURCE_PIN_MISMATCH")
        # r4.create uses O_EXCL. It cannot overwrite or upgrade an earlier file.
        base = r4.AttemptBudget.create(
            path, run_id, role_caps=role_caps, max_observations=max_observations
        )
        with base._transaction() as connection:
            connection.execute(
                "CREATE TABLE live_meta (id INTEGER PRIMARY KEY CHECK(id=1), "
                "version INTEGER NOT NULL, r4_source_sha256 TEXT NOT NULL, policy_json TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO live_meta VALUES (1,1,?,?)", (R4_SOURCE_SHA256, _canonical(document))
            )
            connection.execute(
                "CREATE TABLE request_contexts (observation_id TEXT NOT NULL, role TEXT NOT NULL, "
                "context_json TEXT NOT NULL, bound_at_utc TEXT NOT NULL, "
                "PRIMARY KEY(observation_id,role))"
            )
            connection.execute(
                "CREATE TABLE liability_reservations (attempt_id TEXT PRIMARY KEY, "
                "units INTEGER NOT NULL CHECK(units>0), reserved_at_utc TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE send_leases (attempt_id TEXT PRIMARY KEY, lease_id TEXT UNIQUE NOT NULL, "
                "binding_json TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('AVAILABLE','CONSUMED')), "
                "consumed_at_utc TEXT)"
            )
            connection.execute(
                "CREATE TABLE response_facts (attempt_id TEXT PRIMARY KEY, facts_json TEXT NOT NULL, "
                "facts_sha256 TEXT NOT NULL, acknowledged_at_utc TEXT NOT NULL)"
            )
        return cls(path, run_id)

    def _live_document(self, connection: sqlite3.Connection) -> dict[str, Any]:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            not {
                "live_meta",
                "request_contexts",
                "liability_reservations",
                "send_leases",
                "response_facts",
            }
            <= tables
        ):
            raise BudgetUnavailable("LIVE_ADMISSION_SCHEMA_REQUIRED_NO_MIGRATION")
        row = connection.execute("SELECT * FROM live_meta WHERE id=1").fetchone()
        if row is None or row["version"] != 1 or row["r4_source_sha256"] != R4_SOURCE_SHA256:
            raise BudgetUnavailable("LIVE_ADMISSION_CONTRACT_MISMATCH")
        try:
            document = json.loads(row["policy_json"])
        except (ValueError, TypeError) as exc:
            raise BudgetUnavailable("LIVE_ADMISSION_POLICY_INVALID") from exc
        if type(document) is not dict or document.get("real_provider_activation") is not False:
            raise BudgetUnavailable("LIVE_ADMISSION_POLICY_INVALID")
        if hasattr(self, "_live_policy_pin") and document != self._live_policy_pin:
            raise BudgetUnavailable("LIVE_ADMISSION_POLICY_CHANGED")
        return document

    def _settings(self, connection: sqlite3.Connection) -> dict[str, Any]:
        settings = super()._settings(connection)
        self._live_document(connection)
        return settings

    def _assert_open(self, connection: sqlite3.Connection, observation_id: str) -> None:
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

    def _assert_context(
        self, connection: sqlite3.Connection, expected: dict[str, Any]
    ) -> dict[str, Any]:
        observation_id, role = expected["observation_id"], expected["role"]
        self._assert_open(connection, observation_id)
        row = connection.execute(
            "SELECT context_json FROM request_contexts WHERE observation_id=? AND role=?",
            (observation_id, role),
        ).fetchone()
        if row is None:
            raise BudgetError("PERSISTED_ROLE_CONTEXT_REQUIRED")
        context = cast(dict[str, Any], json.loads(row["context_json"]))
        if any(context.get(key) != value for key, value in expected.items()):
            raise BudgetError("PERSISTED_ROLE_CONTEXT_MISMATCH")
        if role == "judge":
            mcp = connection.execute(
                "SELECT state,proposal_sha256 FROM mcp_calls WHERE observation_id=?",
                (observation_id,),
            ).fetchone()
            if (
                mcp is None
                or mcp["state"] != "ADMITTED"
                or not context.get("effective_invocation_sha256")
                or mcp["proposal_sha256"] != context["effective_invocation_sha256"]
            ):
                raise BudgetError("JUDGE_MATCHING_MCP_ADMISSION_REQUIRED")
        return context

    def bind_request_context(
        self,
        observation_id: str,
        role: str,
        request_sha256: str,
        schema_sha256: str,
        logical_origin: str,
        wire_fixture_origin: str,
        effective_invocation_sha256: str | None = None,
    ) -> None:
        r4._identity(observation_id, "INVALID_OBSERVATION_ID")
        if role not in r4.ROLES:
            raise ValueError("INVALID_ROLE")
        r4._hash(request_sha256)
        r4._hash(schema_sha256)
        _check_origin(logical_origin)
        _check_origin(wire_fixture_origin, wire=True)
        if effective_invocation_sha256 is not None:
            r4._hash(effective_invocation_sha256)
        if role == "planner" and effective_invocation_sha256 is not None:
            raise ValueError("PLANNER_EFFECTIVE_INVOCATION_CONTEXT_NOT_APPLICABLE")
        context = {
            "run_id": self.run_id,
            "observation_id": observation_id,
            "role": role,
            "request_sha256": request_sha256,
            "schema_sha256": schema_sha256,
            "logical_origin": logical_origin,
            "wire_fixture_origin": wire_fixture_origin,
            "effective_invocation_sha256": effective_invocation_sha256,
        }
        with self._transaction() as connection:
            self._assert_open(connection, observation_id)
            row = connection.execute(
                "SELECT context_json FROM request_contexts WHERE observation_id=? AND role=?",
                (observation_id, role),
            ).fetchone()
            if row is not None and json.loads(row["context_json"]) != context:
                raise BudgetError("ROLE_CONTEXT_ALREADY_BOUND_DIFFERENTLY")
            if row is None:
                connection.execute(
                    "INSERT INTO request_contexts VALUES (?,?,?,?)",
                    (observation_id, role, _canonical(context), r4._now()),
                )
            # Judge insertion and matching MCP verification are one transaction.
            self._assert_context(connection, context)

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
        """Reserve count, liability and lease in one BEGIN IMMEDIATE transaction."""
        r4._identity(observation_id, "INVALID_OBSERVATION_ID")
        r4._identity(requested_model, "INVALID_REQUESTED_MODEL")
        if role not in r4.ROLES or type(retry_count) is not int or retry_count not in {0, 1}:
            raise ValueError("INVALID_ROLE_OR_RETRY_INDEX")
        for value in (request_sha256, prompt_sha256, schema_sha256):
            r4._hash(value)
        if retry_reason is not None:
            r4._identity(retry_reason, "INVALID_RETRY_REASON")
        if (retry_count == 0) != (retry_reason is None):
            raise ValueError("RETRY_REASON_BINDING_REQUIRED")
        with self._transaction() as connection:
            settings = self._settings(connection)
            context = self._assert_context(
                connection,
                {
                    "observation_id": observation_id,
                    "role": role,
                    "request_sha256": request_sha256,
                    "schema_sha256": schema_sha256,
                },
            )
            policy = self._live_document(connection)
            if policy.get("mode") != "SYNTHETIC_NONMONETARY_LIABILITY_UNITS":
                raise BudgetError("MONETARY_ADMISSION_BLOCKED")
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
                if tuple(
                    original[key]
                    for key in (
                        "requested_model",
                        "request_sha256",
                        "prompt_sha256",
                        "schema_sha256",
                    )
                ) != (requested_model, request_sha256, prompt_sha256, schema_sha256):
                    raise BudgetError("RETRY_IDENTITY_MISMATCH")
            role_count = connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE role=?", (role,)
            ).fetchone()[0]
            if role_count >= settings["role_caps"][role]:
                self._halt(connection, "ROLE_BUDGET_EXHAUSTED")
                connection.commit()
                raise BudgetExceeded("ROLE_BUDGET_EXHAUSTED")
            units = policy["per_attempt_upper_bound_units"][role]
            used = connection.execute(
                "SELECT COALESCE(SUM(units),0) FROM liability_reservations"
            ).fetchone()[0]
            if used + units > policy["total_limit_units"]:
                self._halt(connection, "SYNTHETIC_LIABILITY_BUDGET_EXHAUSTED")
                connection.commit()
                raise BudgetExceeded("SYNTHETIC_LIABILITY_BUDGET_EXHAUSTED")
            # OPEN has already counted this observation. No nested base reserve.
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
                r4._now(),
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
            connection.execute(
                "INSERT INTO liability_reservations VALUES (?,?,?)",
                (reservation.attempt_id, units, reservation.reserved_at_utc),
            )
            binding = {**context, "attempt_id": reservation.attempt_id}
            connection.execute(
                "INSERT INTO send_leases VALUES (?,?,?,'AVAILABLE',NULL)",
                (reservation.attempt_id, uuid4().hex, _canonical(binding)),
            )
        return reservation

    def start(self, reservation: AttemptReservation) -> None:
        with self._transaction() as connection:
            self._assert_context(
                connection,
                {
                    "observation_id": reservation.observation_id,
                    "role": reservation.role,
                    "request_sha256": reservation.request_sha256,
                    "schema_sha256": reservation.schema_sha256,
                },
            )
            row = self._row(connection, reservation)
            if row["state"] != "RESERVED":
                raise BudgetError("ATTEMPT_ALREADY_STARTED_OR_COMPLETED")
            connection.execute(
                "UPDATE attempts SET state='IN_FLIGHT', started_at_utc=? WHERE attempt_id=?",
                (r4._now(), reservation.attempt_id),
            )

    def _admissible_lease(
        self, connection: sqlite3.Connection, expected: dict[str, Any]
    ) -> sqlite3.Row:
        context = self._assert_context(connection, expected)
        rows = connection.execute(
            "SELECT * FROM attempts WHERE observation_id=? AND role=? AND state='IN_FLIGHT'",
            (expected["observation_id"], expected["role"]),
        ).fetchall()
        if len(rows) != 1:
            raise BudgetError("EXACTLY_ONE_STARTED_ATTEMPT_REQUIRED_FOR_SEND")
        reservation = json.loads(rows[0]["reservation_json"])
        attempt_id = reservation["attempt_id"]
        if (reservation["request_sha256"], reservation["schema_sha256"]) != (
            expected["request_sha256"],
            expected["schema_sha256"],
        ):
            raise BudgetError("SEND_ATTEMPT_BINDING_MISMATCH")
        liability = connection.execute(
            "SELECT units FROM liability_reservations WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        policy = self._live_document(connection)
        if (
            policy.get("mode") != "SYNTHETIC_NONMONETARY_LIABILITY_UNITS"
            or liability is None
            or liability["units"] != policy["per_attempt_upper_bound_units"][expected["role"]]
            or connection.execute(
                "SELECT COALESCE(SUM(units),0) FROM liability_reservations"
            ).fetchone()[0]
            > policy["total_limit_units"]
        ):
            raise BudgetError("PERSISTED_LIABILITY_RESERVATION_REQUIRED")
        lease = connection.execute(
            "SELECT * FROM send_leases WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        if lease is None or json.loads(lease["binding_json"]) != {
            **context,
            "attempt_id": attempt_id,
        }:
            raise BudgetError("PERSISTED_SEND_LEASE_BINDING_REQUIRED")
        if lease["state"] != "AVAILABLE":
            raise BudgetError("HTTP_SEND_LEASE_ALREADY_CONSUMED")
        return cast(sqlite3.Row, lease)

    def assert_send_admissible(
        self,
        *,
        observation_id: str,
        role: str,
        request_sha256: str,
        schema_sha256: str,
        logical_origin: str,
        wire_fixture_origin: str,
        effective_invocation_sha256: str | None = None,
    ) -> None:
        """Nonconsuming pre-connect gate; the header gate rechecks all facts."""
        expected = {
            "run_id": self.run_id,
            "observation_id": observation_id,
            "role": role,
            "request_sha256": request_sha256,
            "schema_sha256": schema_sha256,
            "logical_origin": logical_origin,
            "wire_fixture_origin": wire_fixture_origin,
            "effective_invocation_sha256": effective_invocation_sha256,
        }
        with self._transaction() as connection:
            self._admissible_lease(connection, expected)

    def consume_send_lease(
        self,
        *,
        observation_id: str,
        role: str,
        request_sha256: str,
        schema_sha256: str,
        logical_origin: str,
        wire_fixture_origin: str,
        effective_invocation_sha256: str | None = None,
    ) -> SendLeaseReceipt:
        """ACK once immediately before owned HTTP first headers; failure sends zero."""
        expected = {
            "run_id": self.run_id,
            "observation_id": observation_id,
            "role": role,
            "request_sha256": request_sha256,
            "schema_sha256": schema_sha256,
            "logical_origin": logical_origin,
            "wire_fixture_origin": wire_fixture_origin,
            "effective_invocation_sha256": effective_invocation_sha256,
        }
        with self._transaction() as connection:
            lease = self._admissible_lease(connection, expected)
            attempt_id = lease["attempt_id"]
            acknowledged = r4._now()
            connection.execute(
                "UPDATE send_leases SET state='CONSUMED', consumed_at_utc=? "
                "WHERE attempt_id=? AND state='AVAILABLE'",
                (acknowledged, attempt_id),
            )
            receipt = SendLeaseReceipt(
                lease_id=lease["lease_id"],
                attempt_id=attempt_id,
                run_id=self.run_id,
                observation_id=observation_id,
                role=role,
                request_sha256=request_sha256,
                schema_sha256=schema_sha256,
                logical_origin=logical_origin,
                wire_fixture_origin=wire_fixture_origin,
                effective_invocation_sha256=effective_invocation_sha256,
                acknowledged_at_utc=acknowledged,
            )
        # A commit exception returns no ACK. A consumed lease is never recreated.
        return receipt

    def record_response_facts(
        self, *, observation_id: str, role: str, request_sha256: str, facts: dict[str, Any]
    ) -> ResponseFactsReceipt:
        """Persist observed response facts before delegate return, without acceptance."""
        safe = _response_facts(facts)
        r4._hash(request_sha256)
        with self._transaction() as connection:
            context = self._assert_context(
                connection,
                {
                    "observation_id": observation_id,
                    "role": role,
                    "request_sha256": request_sha256,
                },
            )
            rows = connection.execute(
                "SELECT * FROM attempts WHERE observation_id=? AND role=? AND state='IN_FLIGHT'",
                (observation_id, role),
            ).fetchall()
            if len(rows) != 1:
                raise BudgetError("EXACTLY_ONE_STARTED_ATTEMPT_REQUIRED_FOR_RESPONSE_FACTS")
            reservation = json.loads(rows[0]["reservation_json"])
            attempt_id = reservation["attempt_id"]
            if reservation["request_sha256"] != request_sha256:
                raise BudgetError("RESPONSE_FACTS_REQUEST_BINDING_MISMATCH")
            lease = connection.execute(
                "SELECT * FROM send_leases WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if (
                lease is None
                or lease["state"] != "CONSUMED"
                or json.loads(lease["binding_json"]) != {**context, "attempt_id": attempt_id}
            ):
                raise BudgetError("CONSUMED_SEND_LEASE_REQUIRED_FOR_RESPONSE_FACTS")
            if (
                connection.execute(
                    "SELECT 1 FROM response_facts WHERE attempt_id=?", (attempt_id,)
                ).fetchone()
                is not None
            ):
                raise BudgetError("RESPONSE_FACTS_ALREADY_ACKNOWLEDGED")
            document = _canonical(safe)
            digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
            acknowledged = r4._now()
            connection.execute(
                "INSERT INTO response_facts VALUES (?,?,?,?)",
                (attempt_id, document, digest, acknowledged),
            )
            receipt = ResponseFactsReceipt(
                attempt_id,
                self.run_id,
                observation_id,
                role,
                request_sha256,
                digest,
                acknowledged,
            )
        return receipt

    def snapshot(self) -> dict[str, Any]:
        # R4 field meanings are retained; every table is read in one SQLite
        # snapshot so concurrent reservations cannot split count/cost evidence.
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
            fences = [
                dict(row)
                for row in connection.execute("SELECT * FROM observation_fences ORDER BY rowid")
            ]
            result = {
                "run_id": self.run_id,
                **settings,
                "counts": {
                    role: sum(row["role"] == role for row in rows) for role in sorted(r4.ROLES)
                },
                "observation_count": connection.execute(
                    "SELECT COUNT(*) FROM observations"
                ).fetchone()[0],
                "attempts": attempts,
                "mcp_count": len(mcp_rows),
                "mcp_calls": [
                    {**dict(row), "metadata": json.loads(row["metadata_json"])} for row in mcp_rows
                ],
                "observation_fences": fences,
                "admission_blocked": settings["stopped"]
                or any(row["state"] == "OPEN" for row in fences),
                "liability_policy": self._live_document(connection),
            }
            result["liability_reservations"] = [
                dict(row)
                for row in connection.execute("SELECT * FROM liability_reservations ORDER BY rowid")
            ]
            result["reserved_liability_units"] = sum(
                row["units"] for row in result["liability_reservations"]
            )
            result["request_contexts"] = [
                {**json.loads(row["context_json"]), "bound_at_utc": row["bound_at_utc"]}
                for row in connection.execute("SELECT * FROM request_contexts ORDER BY rowid")
            ]
            result["send_leases"] = [
                {**dict(row), "binding": json.loads(row["binding_json"])}
                for row in connection.execute("SELECT * FROM send_leases ORDER BY rowid")
            ]
            result["response_facts"] = [
                {**dict(row), "facts": json.loads(row["facts_json"])}
                for row in connection.execute("SELECT * FROM response_facts ORDER BY rowid")
            ]
        return result
