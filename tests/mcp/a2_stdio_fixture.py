"""Explicit synthetic subprocess composition for A2 stdio tests and demonstrations.

This entry point never constructs the configured production Gateway. All adapter
requests use the existing in-memory fixture transport, and all judge signals are
deterministic fixtures. The separate dispatch ledger is test evidence only.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from civicgate.adapters.usaspending import AdapterCall, USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.llm.base import UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Award, Recipient, Search


class SyntheticDispatchAdapter(USAspending):
    def __init__(self, ledger: Path, mode: str) -> None:
        transport = fixture_transport()
        if mode == "malformed":
            transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"bad": True}))
        super().__init__(transport=transport, fixture=True)
        self.ledger = ledger
        self.mode = mode

    def _record(self, method: str, query: Search | Award | Recipient) -> None:
        with self.ledger.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"synthetic": True, "method": method, "query": query.model_dump(mode="json")}
                )
                + "\n"
            )

    async def search(self, query: Search) -> AdapterCall:
        self._record("search", query)
        return await super().search(query)

    async def detail(self, query: Award) -> AdapterCall:
        self._record("detail", query)
        if self.mode == "slow":
            await asyncio.sleep(0.4)
        return await super().detail(query)

    async def recipients(self, query: Recipient) -> AdapterCall:
        self._record("recipients", query)
        return await super().recipients(query)


class SyntheticCompletionFailureTrace(Trace):
    """Fault injection: a response can be lost after an authorized backend call."""

    def record(self, request_id: str, stage: str, **fields: Any) -> None:
        if stage == "completed":
            raise OSError("synthetic final-audit preservation failure")
        super().record(request_id, stage, **fields)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-path", required=True, type=Path)
    parser.add_argument("--backend-path", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=("permit", "review", "slow", "malformed", "audit-failure"),
        default="permit",
    )
    options = parser.parse_args()
    trace_type = SyntheticCompletionFailureTrace if options.mode == "audit-failure" else Trace
    gateway = Gateway(
        SyntheticDispatchAdapter(options.backend_path, options.mode),
        UnavailableProvider() if options.mode == "review" else MockProvider(),
        trace_type(options.audit_path),
    )
    create_server(gateway).run(transport="stdio")


if __name__ == "__main__":
    main()
