"""Abrupt process-exit fixture, invoked only by local synthetic tests."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from time import time

import httpx

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.local_journal import LocalDispatchJournal
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.llm.mock import MockProvider
from civicgate.mcp.http_identity import (
    InvocationContext,
    LocalHold,
    TrustDomain,
    invocation_context,
)
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Proposal


async def main() -> None:
    path = Path(sys.argv[1])
    domain = TrustDomain(**json.loads(sys.argv[2]))
    point = sys.argv[3]
    try:
        journal = LocalDispatchJournal(
            path, domain, subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        )
    except LocalHold as exc:
        if point == "recover_hold" and str(exc) == "RECOVERY_HOLD":
            print("RECOVERY_HOLD: no Gateway or authority constructed", flush=True)
            return
        raise
    if point == "recover_hold":
        journal.close()
        raise AssertionError("Uncertain store unexpectedly admitted a new generation")
    if point == "lock":
        print("LOCKED", flush=True)
        sys.stdin.readline()
        journal.close()
        return
    original = journal._append

    def append(kind, **evidence):
        if point == "before_finish" and kind == "finish":
            os._exit(73)
        original(kind, **evidence)
        if point == kind:
            os._exit(73)

    journal._append = append
    fixture = fixture_transport()

    async def respond(request):
        with path.with_suffix(".dispatch").open("xb") as file:
            file.write(b"synthetic-dispatch-observed")
            file.flush()
            os.fsync(file.fileno())
        if point == "dispatch":
            os._exit(73)
        return await fixture.handle_async_request(request)

    gateway = Gateway(
        USAspending(httpx.MockTransport(respond), True, max_attempts=1),
        MockProvider(),
        Trace(),
        dispatch_journal=journal,
    )
    invocation_context.set(
        InvocationContext(
            domain.principal,
            domain.issuer,
            domain.audience,
            "synthetic-session",
            "synthetic-request",
            int(time()) + 240,
        )
    )
    await gateway.call(
        "Show public awards", Proposal(tool="get_federal_award", arguments={"award_id": "1"})
    )
    raise AssertionError("Crash fixture did not exit")


if __name__ == "__main__":
    asyncio.run(main())
