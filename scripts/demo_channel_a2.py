"""Run the five-node A2 graph through real stdio with synthetic tools only."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import timedelta
from importlib.metadata import version
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from civicgate.agent.langgraph_agent import LangGraphAgent
from civicgate.mcp.client import MCPTransport
from civicgate.models.requests import Proposal


class SyntheticPlanner:
    async def propose(self, request: str) -> Proposal:
        # Deliberately only proposes: original request independently reaches policy.
        return Proposal(tool="get_federal_award", arguments={"award_id": "1"})


async def demo(output: Path, request: str, mode: str) -> dict[str, object]:
    worktree = Path(__file__).resolve().parents[1]
    audit = output / "gateway-audit.jsonl"
    backend = output / "synthetic-dispatch.jsonl"
    env = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "TEMP", "TMP")
        if name in os.environ
    }
    env.update(
        PYTHONPATH=os.pathsep.join((str(worktree / "src"), str(worktree))),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-B",
            str(worktree / "tests" / "mcp" / "a2_stdio_fixture.py"),
            "--audit-path",
            str(audit),
            "--backend-path",
            str(backend),
            "--mode",
            mode,
        ],
        env=env,
    )
    with (output / "server-stderr.txt").open("x", encoding="utf-8") as errors:
        async with (
            stdio_client(params, errlog=errors) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as session,
        ):
            await session.initialize()
            result = await LangGraphAgent(SyntheticPlanner(), MCPTransport(session)).run(request)
    envelope = result.outcome.envelope if result.outcome else None
    return {
        "synthetic_only": True,
        "authenticated_human_intent": False,
        "mcp_version": version("mcp"),
        "langgraph_version": version("langgraph"),
        "original_request": result.context.original_request,
        "original_request_sha256": result.context.request_sha256,
        "visited_nodes": list(result.visited_nodes),
        "orchestration_status": result.status,
        "transport_status": result.outcome.status if result.outcome else None,
        "dispatch_state": result.outcome.dispatch_state if result.outcome else "NOT_ATTEMPTED",
        "error_code": result.error_code,
        "gateway_response": envelope.model_dump(mode="json") if envelope else None,
        "gateway_audit_path": str(audit),
        "synthetic_backend_ledger_path": str(backend),
        "evidence_directory": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--request", default="Get public federal award details.")
    parser.add_argument(
        "--mode", choices=("permit", "review", "malformed", "audit-failure"), default="permit"
    )
    options = parser.parse_args()
    if options.output_dir is None:
        output = Path(tempfile.mkdtemp(prefix="civicgate-a2-synthetic-"))
    else:
        output = options.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=False)
    result = asyncio.run(demo(output, options.request, options.mode))
    raw = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    with (output / "demo-result.json").open("x", encoding="utf-8") as stream:
        stream.write(raw)
    print(raw)


if __name__ == "__main__":
    main()
