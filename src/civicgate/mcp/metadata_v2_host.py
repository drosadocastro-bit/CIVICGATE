"""Explicit trusted-host MCP_TOOL_METADATA_V2 STDIO launcher.

This entry point is separate from the preserved civicgate-mcp v1 command.
Neither discovery nor selecting a profile confers execution authority.
"""

import argparse
from importlib import import_module
from pathlib import Path
from typing import Sequence

import anyio

from civicgate.mcp.metadata_v2 import install_metadata_v2


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("public-read", "synthetic-write"),
        required=True,
        help="Trusted host composition, not an agent-selectable capability",
    )
    parser.add_argument(
        "--host-config",
        type=Path,
        help="Existing private, synthetic WRITE-01 host configuration",
    )
    args = parser.parse_args(argv)
    if args.profile == "synthetic-write" and args.host_config is None:
        parser.error("--host-config is required for synthetic-write")
    if args.profile == "public-read" and args.host_config is not None:
        parser.error("--host-config is forbidden for public-read")
    return args


async def _serve(args: argparse.Namespace) -> None:
    if args.profile == "synthetic-write":
        # This branch is synthetic-only and reuses the frozen WRITE-01 server.
        # Start AnyIO's Windows event loop before installing the unchanged
        # network/dataset guards; install them before opening the host config
        # or constructing a server. No external backend is configured.
        import_module(
            "evals.harness.eval_002b_composition_v4"
        ).install_fixture_network_guard()
        import_module("evals.harness.live_composition_v3").install_dataset_guard()
        owner = import_module("evals.write01.stdio_v1").configured_server(args.host_config)
    else:
        # Original public-data READ semantics remain open-world. Tool calls
        # still require the unchanged deterministic Gateway authorization.
        from civicgate.config import configured_gateway
        from civicgate.mcp.server import create_server

        owner = create_server(configured_gateway())

    install_metadata_v2(owner)
    await owner.run_stdio_async()


def main(argv: Sequence[str] | None = None) -> None:
    # Explicit opt-in, not a change to civicgate-mcp or the frozen v1 host.
    anyio.run(_serve, _parse_args(argv))


if __name__ == "__main__":
    main()
