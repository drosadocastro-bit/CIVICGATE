"""Additive DATA-01 injection into the existing R3.2 observation/custody path.

Only the evaluation fixture factory and exact child module are selected. The
production Gateway, schemas, policy, bindings and legacy validators are reused.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from threading import Lock
from typing import Any
from unittest.mock import patch

ORIGINAL_MODULE = "evals.harness.eval_002b_composition_v4"
WORKER_MODULE = "evals.data01.bridge_v1"
_COMPOSITION_LOCK = Lock()


def worker_parameters(original: Any, *args: Any, **kwargs: Any) -> Any:
    """Reject any unexpected worker command; replace exactly one module name."""
    params = original(*args, **kwargs)
    command = params.args
    if (
        params.command != sys.executable
        or type(command) is not list
        or len(command) != 5
        or command[:4] != ["-B", "-m", ORIGINAL_MODULE, "--synthetic-worker-config"]
        or Path(command[4]).name != "synthetic-http-worker-config.json"
    ):
        raise ValueError("DATA01_EXACT_SYNTHETIC_WORKER_REQUIRED")
    return params.model_copy(update={"args": ["-B", "-m", WORKER_MODULE, *command[3:]]})


async def run_observation(
    database: Path,
    run_id: str,
    observation_id: str,
    evidence: Path,
    scenario: Any,
) -> dict[str, Any]:
    from evals.harness import eval_002b_composition_v4 as composition

    # The evaluation fixture seam is process-local. Reject concurrent use rather
    # than letting overlapping patches select an uncertain worker composition.
    if not _COMPOSITION_LOCK.acquire(blocking=False):
        raise ValueError("DATA01_CONCURRENT_COMPOSITION_NOT_SUPPORTED")
    try:
        original = composition.StdioServerParameters

        def parameters(*args: Any, **kwargs: Any) -> Any:
            return worker_parameters(original, *args, **kwargs)

        with patch.object(composition, "StdioServerParameters", parameters):
            return await composition.run_synthetic_observation(
                database, run_id, observation_id, evidence, scenario
            )
    finally:
        _COMPOSITION_LOCK.release()


async def serve_worker(config: Path) -> None:
    from evals.data01.backend_v1 import fixture_transport
    from evals.harness import eval_002b_composition_v4 as composition
    from evals.harness import synthetic_server

    with patch.object(synthetic_server, "fixture_transport", fixture_transport):
        await composition.serve_synthetic_worker(config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-worker-config", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve_worker(args.synthetic_worker_config))


if __name__ == "__main__":
    main()
