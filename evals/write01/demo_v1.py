"""Trusted synthetic host fixture; agent-facing interface is only the MCP session."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from evals.harness.evidence import write_new
from evals.write01.contract_v1 import READ_TOOL, WRITE_TOOL
from evals.write01.store_v1 import ReviewStore

ROOT = Path(__file__).resolve().parents[2]
FIXED_WORKER = "evals.write01.stdio_v1"
DATASET = ROOT / "evals/data01/awards_v1.json"
REQUEST = "Mark synthetic award SYN-FAA-PR-001 as pending review and attach a reviewer note."
READ_REQUEST = "Read synthetic review state for SYN-FAA-PR-001."


def query() -> dict[str, Any]:
    return {
        "award_id": "SYN-FAA-PR-001",
        "expected_version": 0,
        "proposed_status": "PENDING_REVIEW",
        "reviewer_note": "Synthetic check requested.",
        "idempotency_key": "WRITE01-" + uuid4().hex,
    }


def prepare(
    directory: Path, request: str, proposed: dict[str, Any], *, approved: bool
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    run_id = "WRITE01_RUN_" + uuid4().hex
    store_id = "STORE_" + uuid4().hex
    store = ReviewStore.initialize(directory / "review.sqlite", DATASET, store_id)
    write_new(directory / "before.json", store.checkpoint())
    config = {
        "mode": "WRITE01_SYNTHETIC_ONLY",
        "database": str(store.path),
        "audit_path": str(directory / "audit.jsonl"),
        "owner_id": "OWNER_" + uuid4().hex,
        "store_id": store_id,
        "run_id": run_id,
        "approvals": [
            {
                "original_request": request,
                "tool": WRITE_TOOL,
                "query": proposed,
                "reference": "SYNTHETIC_HOST_APPROVAL_" + uuid4().hex,
                "approved": approved,
            },
            {
                "original_request": READ_REQUEST,
                "tool": READ_TOOL,
                "query": {"award_id": "SYN-FAA-PR-001"},
                "reference": "SYNTHETIC_READ_APPROVAL_" + uuid4().hex,
                "approved": True,
            },
        ],
    }
    write_new(directory / "host-config.json", config)
    return config


@asynccontextmanager
async def session(directory: Path) -> AsyncIterator[ClientSession]:
    """Host launches one fixed route. No agent-selected module, URL or fallback."""
    env = {
        k: os.environ[k]
        for k in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP")
        if k in os.environ
    }
    env.update(
        PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    args = ["-B", "-m", FIXED_WORKER, "--host-config", str(directory / "host-config.json")]
    write_new(
        directory / "launch.json",
        {"executable": sys.executable, "args": args, "environment": env, "legacy_route": None},
    )
    with (directory / "worker-stderr.log").open("x", encoding="utf-8") as stderr:
        async with stdio_client(
            StdioServerParameters(command=sys.executable, args=args, env=env), errlog=stderr
        ) as streams:
            async with ClientSession(*streams) as client:
                initialized = await client.initialize()
                write_new(directory / "initialize.json", initialized.model_dump(mode="json"))
                yield client


def readback(directory: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Separate read-only SQLite connection after worker exit; no inference from flags."""
    connection = sqlite3.connect(Path(config["database"]).as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result = {
            name: [dict(r) for r in connection.execute("SELECT * FROM " + name)]
            for name in ("metadata", "review_state", "notes", "intents")
        }
    finally:
        connection.close()
    result["audit"] = [
        json.loads(line)
        for line in (directory / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    write_new(directory / "independent-sqlite-readback.json", result)
    return result
