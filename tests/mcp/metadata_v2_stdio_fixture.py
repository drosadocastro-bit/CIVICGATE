"""Test-only stdio host; explicit fixtures only, never configured live providers."""

import argparse
import json
from pathlib import Path

import anyio

from civicgate.audit.trace import Trace
from civicgate.demo import fixture_adapter
from civicgate.llm.mock import MockProvider
from civicgate.mcp.metadata_v2 import install_metadata_v2
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter
from evals.proposals.r022.faa_contract_v1 import example_query
from evals.proposals.r022.stdio_v1 import (
    CANONICAL_REQUEST,
    ScopedFaaGateway,
    TrustedFaaIntake,
    create_scoped_server,
)
from evals.write01.stdio_v1 import configured_server


def main():
    from evals.harness.eval_002b_composition_v4 import install_fixture_network_guard
    from evals.harness.live_composition_v3 import install_dataset_guard

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=["primary-stdio", "r022-faa-stdio", "write01-stdio"], required=True
    )
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    async def run_guarded() -> None:
        # AnyIO creates the Windows 3.11 Proactor self-pipe during event-loop
        # bootstrap. Install the frozen audit guards immediately afterward,
        # before constructing a server or servicing any MCP request.
        install_fixture_network_guard()
        install_dataset_guard()
        if args.profile == "write01-stdio":
            server = configured_server(args.config)
            install_metadata_v2(server)
        elif args.profile == "r022-faa-stdio":
            gateway = ScopedFaaGateway(
                FaaProfileFixtureAdapter(),
                MockProvider(),
                Trace(),
                intake=TrustedFaaIntake(CANONICAL_REQUEST, json.dumps(example_query())),
            )
            server = create_scoped_server(gateway)
            install_metadata_v2(server, gateway=gateway)
        else:
            server = create_server(Gateway(fixture_adapter(), MockProvider(), Trace()))
            install_metadata_v2(server)
        await server.run_stdio_async()

    anyio.run(run_guarded)


if __name__ == "__main__":
    main()
