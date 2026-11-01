"""EVAL001B-only composition: unchanged Gateway plus a read-only observer."""

import argparse
import json
import os
from pathlib import Path

import httpx

from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from evals.harness.evidence import write_new
from evals.harness.governance_observer_v2 import ReadOnlyGovernanceObserver
from evals.harness.synthetic_server import (
    EvidenceLedger,
    SyntheticAdapter,
    SyntheticJudge,
    SyntheticTrace,
    install_network_guard,
    load_case,
)


def match_fixture_agency(adapter: SyntheticAdapter) -> None:
    """Build matching synthetic rows before unchanged parsing/provenance hashing.

    This is fixture generation, not independent upstream attribution evidence.
    Effective requests and adapter retry semantics are never changed.
    """
    original = adapter.transport
    if type(original) is not httpx.MockTransport:
        raise ValueError("EVAL001B_REQUIRES_EXPLICIT_MOCK_TRANSPORT")

    async def respond(request: httpx.Request) -> httpx.Response:
        response = await original.handle_async_request(request)
        if request.url.path == "/api/v2/search/spending_by_award/" and response.status_code == 200:
            query = json.loads(request.content)
            agencies = query.get("filters", {}).get("agencies", [])
            body = response.json()
            if len(agencies) == 1 and isinstance(body.get("results"), list):
                for row in body["results"]:
                    row["Awarding Agency"] = agencies[0]["name"]
                return httpx.Response(200, json=body)
        return response

    adapter.transport = httpx.MockTransport(respond)


class ResponseLossTrace(SyntheticTrace):
    """Lose the MCP response only after the actual completed audit is durable.

    A test-only process failure, never an authority or a production retry path.
    """

    def __init__(
        self,
        ledger: EvidenceLedger,
        observer: ReadOnlyGovernanceObserver,
        correlation_id: str,
    ) -> None:
        super().__init__(ledger)
        self.observer = observer
        self.correlation_id = correlation_id

    def record(self, request_id: str, stage: str, **fields: object) -> None:
        super().record(request_id, stage, **fields)
        if stage == "completed" and fields.get("tool_executed") is True:
            for name in (
                "audit.jsonl",
                "dispatch.jsonl",
                "http-attempts.jsonl",
                "components.jsonl",
            ):
                with (self.ledger.directory / name).open("ab") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
            self.observer.close()
            write_new(
                self.ledger.directory / "transport-fault.json",
                {
                    "correlation_id": self.correlation_id,
                    "request_id": request_id,
                    "fault": "PROCESS_EXIT_AFTER_COMPLETED_AUDIT_BEFORE_MCP_RESPONSE",
                    "exit_code": 72,
                    "source": "EXPLICIT_SYNTHETIC_FAULT_NOT_RUNTIME_BEHAVIOR",
                },
            )
            os._exit(72)


async def serve(case_file: Path, directory: Path, correlation_id: str, drop: bool) -> None:
    case = load_case(case_file)
    if drop and case.backend.mode != "normal":
        raise ValueError("EVAL001B_UNSUPPORTED_COMBINED_TRANSPORT_BACKEND_FAULT")
    ledger = EvidenceLedger(directory)
    judge = SyntheticJudge(ledger, case.judge)
    adapter = SyntheticAdapter(ledger, case.backend.mode)
    match_fixture_agency(adapter)
    observer = ReadOnlyGovernanceObserver(directory, correlation_id)
    trace = (
        ResponseLossTrace(ledger, observer, correlation_id)
        if drop
        else SyntheticTrace(ledger, completion_failure=case.backend.mode == "audit_failure")
    )
    install_network_guard(ledger)
    server = create_server(Gateway(adapter, judge, trace))
    with observer:
        await server.run_stdio_async()


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-file", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--drop-response-after-completion", action="store_true")
    options = parser.parse_args()
    asyncio.run(
        serve(
            options.case_file,
            options.evidence_dir,
            options.correlation_id,
            options.drop_response_after_completion,
        )
    )


if __name__ == "__main__":
    main()
