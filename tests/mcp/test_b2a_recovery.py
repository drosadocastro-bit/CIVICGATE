import asyncio
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from time import time

import httpx
import pytest

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.local_journal import LocalDispatchJournal, provision_local_store
from civicgate.audit.trace import Trace
from civicgate.llm.mock import MockProvider
from civicgate.mcp.http_identity import (
    InvocationContext,
    LocalHold,
    TrustDomain,
    invocation_context,
)
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Proposal

REVISION = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
DOMAIN = TrustDomain(
    "https://synthetic.invalid", "http://127.0.0.1:12345/mcp", "caller", "service", "instance"
)
WORKER = Path(__file__).with_name("b2a_crash_worker.py")


@pytest.mark.parametrize("point", ["begin", "intent", "dispatch", "before_finish"])
def test_real_process_crash_recovers_hold_without_replay(tmp_path, point):
    path = tmp_path / "state.sqlite"
    provision_local_store(path, DOMAIN)
    process = subprocess.run(
        [sys.executable, str(WORKER), str(path), json.dumps(asdict(DOMAIN)), point],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 73, process.stderr
    assert path.with_suffix(".dispatch").exists() == (point in {"dispatch", "before_finish"})
    before = path.read_bytes()
    for _ in range(2):
        with pytest.raises(LocalHold, match="RECOVERY_HOLD"):
            LocalDispatchJournal(path, DOMAIN, REVISION)
    assert path.read_bytes() == before


def test_cross_process_ownership_is_exclusive(tmp_path):
    path = tmp_path / "state.sqlite"
    provision_local_store(path, DOMAIN)
    process = subprocess.Popen(
        [sys.executable, str(WORKER), str(path), json.dumps(asdict(DOMAIN)), "lock"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "LOCKED"
        with pytest.raises(OSError):
            LocalDispatchJournal(path, DOMAIN, REVISION)
        process.communicate(input="close\n", timeout=15)
        assert process.returncode == 0
        journal = LocalDispatchJournal(path, DOMAIN, REVISION)
        journal.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize("damage", ["truncate", "delete", "hash", "empty"])
def test_unreadable_or_missing_recovery_never_creates_clear_store(tmp_path, damage):
    path = tmp_path / "state.sqlite"
    provision_local_store(path, DOMAIN)
    journal = LocalDispatchJournal(path, DOMAIN, REVISION)
    journal.close()
    if damage == "truncate":
        path.write_bytes(path.read_bytes()[:100])
    elif damage == "delete":
        path.unlink()
    elif damage == "empty":
        path.write_bytes(b"")
    else:
        # Corruption by a privileged local writer is outside isolation claims,
        # but an inconsistent chain still must fail closed.
        with sqlite3.connect(path) as db:
            db.execute("DROP TRIGGER no_update")
            db.execute("UPDATE events SET digest='tampered' WHERE seq=2")
    with pytest.raises((LocalHold, sqlite3.Error, OSError)):
        LocalDispatchJournal(path, DOMAIN, REVISION)


async def test_cancellation_after_intent_holds_and_does_not_retry(tmp_path):
    path = tmp_path / "state.sqlite"
    provision_local_store(path, DOMAIN)
    journal = LocalDispatchJournal(path, DOMAIN, REVISION)
    entered = asyncio.Event()
    attempts = 0

    async def respond(request):
        nonlocal attempts
        attempts += 1
        entered.set()
        await asyncio.Future()

    gateway = Gateway(
        USAspending(httpx.MockTransport(respond), True, max_attempts=1),
        MockProvider(),
        Trace(),
        dispatch_journal=journal,
    )
    context = invocation_context.set(
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
        proposal = Proposal(tool="get_federal_award", arguments={"award_id": "1"})
        task = asyncio.create_task(gateway.call("Show public award", proposal))
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(LocalHold, match="DURABLE_HOLD"):
            await gateway.call("Show public award", proposal)
    finally:
        invocation_context.reset(context)
        journal.close()
    assert attempts == 1
    with pytest.raises(LocalHold, match="RECOVERY_HOLD"):
        LocalDispatchJournal(path, DOMAIN, REVISION)
