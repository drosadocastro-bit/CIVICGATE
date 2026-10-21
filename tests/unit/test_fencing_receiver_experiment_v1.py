"""Pure synthetic contract checks; SQL atomicity requires the real PG suite."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from civicgate.audit.fencing_receiver_experiment_v1 import (
    PostgresReceiver,
    Request,
    check_authority,
)


def message(**changes):
    value = dict(
        scope="synthetic",
        owner="owner-one",
        epoch=1,
        request_id="read-one",
        payload_sha256="a" * 64,
    )
    value.update(changes)
    return json.dumps(value).encode()


@pytest.mark.parametrize(
    "change",
    [
        {"epoch": True},
        {"epoch": 0},
        {"epoch": -1},
        {"epoch": 2**63},
        {"epoch": 1.0},
        {"epoch": "1"},
        {"scope": ""},
        {"scope": None},
        {"scope": "x" * 129},
        {"owner": 1},
        {"request_id": []},
        {"payload_sha256": "g" * 64},
        {"payload_sha256": "a" * 63},
        {"payload_sha256": None},
        {"extra": "PERMIT"},
    ],
)
def test_rejects_malformed_wire_claims_without_connecting(change):
    def forbidden():
        raise AssertionError("Malformed request reached database")

    result = PostgresReceiver("F2", forbidden).receive(message(**change))
    assert (result.status, result.effect, result.reason) == (
        "REJECTED",
        "REFUSED",
        "INVALID_REQUEST",
    )


@pytest.mark.parametrize(
    "raw", [b"{}", b"[]", b"null", b"bad", b"\xff", b" " * 4097, b'{"epoch":1,"epoch":2}']
)
def test_invalid_documents(raw):
    with pytest.raises((ValueError, TypeError, UnicodeError)):
        Request.parse(raw)


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (None, "AUTHORITY_UNKNOWN"),
        ((1,), "AUTHORITY_UNKNOWN"),
        ((True, "owner-one", False), "AUTHORITY_UNKNOWN"),
        ((1, "owner-one", "false"), "AUTHORITY_UNKNOWN"),
        ((1, "", False), "AUTHORITY_UNKNOWN"),
        ((1, "owner-one", True), "REVOKED"),
        ((2, "owner-one", False), "STALE_OR_UNKNOWN_OWNER"),
        ((1, "owner-two", False), "STALE_OR_UNKNOWN_OWNER"),
        ((1, "owner-one", False), None),
    ],
)
def test_authority_requires_exact_typed_state(row, reason):
    assert check_authority(Request.parse(message()), row) == reason


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "other"),
        ("owner", "other"),
        ("epoch", 2),
        ("request_id", "other"),
        ("payload_sha256", "b" * 64),
    ],
)
def test_request_fingerprint_covers_all_fields(field, value):
    assert (
        Request.parse(message()).fingerprint()
        != Request.parse(message(**{field: value})).fingerprint()
    )


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
def test_unavailable_store_never_claims_no_effect_or_retries(mode):
    calls = []

    def unavailable():
        calls.append("connect")
        raise ConnectionError("synthetic outage")

    result = PostgresReceiver(mode, unavailable).receive(message())
    assert calls == ["connect"]
    assert result.status == result.effect == "UNKNOWN"


def test_no_unsupported_mode():
    with pytest.raises(ValueError, match="UNSUPPORTED_RECEIVER"):
        PostgresReceiver("unknown", lambda: None)


class SQLiteSimulation:
    """Explicit SQL translation surrogate, NOT proof of PostgreSQL behavior.

    SQLite serializes the WHOLE database with BEGIN IMMEDIATE here. PostgreSQL
    uses narrower row locks; only tests/postgres17 can establish that behavior.
    """

    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE authority(scope text PRIMARY KEY,epoch integer,owner text,revoked integer);
                CREATE TABLE scopes(mode text,scope text,highest_epoch integer,PRIMARY KEY(mode,scope));
                CREATE TABLE receipts(mode text,scope text,request_id text,fingerprint text,PRIMARY KEY(mode,scope,request_id));
                CREATE TABLE effects(effect_id text PRIMARY KEY,mode text,scope text,request_id text,epoch integer,payload_sha256 text);
                INSERT INTO authority VALUES('synthetic',1,'owner-one',0);
                INSERT INTO scopes VALUES('U','synthetic',0),('F1','synthetic',0),('F2','synthetic',0);
            """)

    def connect(self):
        return SQLiteConnection(self.path)

    def publish(self, epoch=1, owner="owner-one", revoked=False):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE authority SET epoch=?,owner=?,revoked=?", (epoch, owner, revoked))

    def count(self, mode):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT count(*) FROM effects WHERE mode=?", (mode,)).fetchone()[0]


class SQLiteConnection:
    autocommit = False

    def __init__(self, path):
        self.raw = sqlite3.connect(path, timeout=5)
        self.raw.execute("BEGIN IMMEDIATE")

    def cursor(self):
        return SQLiteCursor(self.raw.cursor())

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


class SQLiteCursor:
    def __init__(self, raw):
        self.raw = raw
        self.value = None
        self.authority = False

    def execute(self, sql, args=()):
        self.value = None
        self.authority = "SELECT epoch,owner,revoked" in sql
        if sql.startswith("SET "):
            return
        if sql == "SHOW fsync":
            self.value = ("on",)
            return
        if sql == "SELECT pg_backend_pid()":
            self.value = (1,)
            return
        translated = (
            sql.replace("b2b_receiver.", "")
            .replace("%s", "?")
            .replace(" FOR UPDATE", "")
            .replace(" FOR SHARE", "")
        )
        self.raw.execute(translated, args)

    def fetchone(self):
        value = self.value if self.value is not None else self.raw.fetchone()
        if self.authority and value is not None:
            return (value[0], value[1], bool(value[2]))
        return value

    def close(self):
        self.raw.close()


@pytest.fixture
def simulation(tmp_path):
    return SQLiteSimulation(tmp_path / "explicit-synthetic-sqlite.db")


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
def test_synthetic_e0_valid_owner_transaction_commits(simulation, mode):
    result = PostgresReceiver(mode, simulation.connect).receive(message())
    assert result.status == "ACCEPTED" and simulation.count(mode) == 1


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
def test_synthetic_e4b_explicit_publication_only_f2_refuses(simulation, mode):
    simulation.publish(revoked=True)
    result = PostgresReceiver(mode, simulation.connect).receive(message())
    assert result.status == ("REJECTED" if mode == "F2" else "ACCEPTED")
    assert simulation.count(mode) == (0 if mode == "F2" else 1)


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
def test_synthetic_e3_delayed_old_epoch(simulation, mode):
    receiver = PostgresReceiver(mode, simulation.connect)
    simulation.publish(epoch=2)
    assert receiver.receive(message(epoch=2, request_id="newer")).status == "ACCEPTED"
    result = receiver.receive(message())
    assert result.status == ("ACCEPTED" if mode == "U" else "REJECTED")
    assert simulation.count(mode) == (2 if mode == "U" else 1)


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
def test_synthetic_e5_concurrent_dedup_and_restart(simulation, mode):
    barrier = Barrier(2)

    def receive():
        barrier.wait(5)
        return PostgresReceiver(mode, simulation.connect).receive(message())

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(receive) for _ in range(2)]
        outcomes = [future.result(8) for future in futures]
    assert sorted(x.status for x in outcomes) == (
        ["ACCEPTED", "ACCEPTED"] if mode == "U" else ["ACCEPTED", "DUPLICATE"]
    )
    third = PostgresReceiver(mode, simulation.connect).receive(message())
    assert third.status == ("ACCEPTED" if mode == "U" else "DUPLICATE")
    assert simulation.count(mode) == (3 if mode == "U" else 1)


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
@pytest.mark.parametrize("stage", ["before_effect", "effect_inserted_uncommitted"])
def test_synthetic_exception_before_commit_rolls_back(simulation, mode, stage):
    def hook(event, _):
        if event == stage:
            raise ConnectionError("Synthetic database fault")

    outcome = PostgresReceiver(mode, simulation.connect, hook).receive(message())
    assert outcome.status == "UNKNOWN" and simulation.count(mode) == 0


@pytest.mark.parametrize("mode", ["U", "F1", "F2"])
def test_synthetic_lost_commit_ack_is_unknown_despite_effect(simulation, mode):
    class LostAck(SQLiteConnection):
        def commit(self):
            super().commit()
            raise ConnectionError("Synthetic lost ACK; server commit actually completed")

    outcome = PostgresReceiver(mode, lambda: LostAck(simulation.path)).receive(message())
    assert outcome.status == "UNKNOWN" and simulation.count(mode) == 1


@pytest.mark.parametrize("mode", ["F1", "F2"])
def test_synthetic_conflicting_duplicate_preserves_effect_identity(simulation, mode):
    receiver = PostgresReceiver(mode, simulation.connect)
    assert receiver.receive(message()).status == "ACCEPTED"
    assert receiver.receive(message(payload_sha256="b" * 64)).reason == "REQUEST_ID_CONFLICT"
    assert simulation.count(mode) == 1
