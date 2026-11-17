"""Dormant host release: existing runner/worker seams, gated before runtime access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from civicgate.audit.trace import Trace
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import Proposal
from evals.harness.governance_observer_v3 import ReadOnlyGovernanceObserver

from .common import MODE, canonical, load, save, sha
from .providers_v3 import Luna
from .registry_v1 import owner_registry


def run(path: Path) -> None:
    from .host_gate71 import require_release

    require_release()
    config = load(path)
    if config["mode"] not in {MODE, "LIVE"}:
        raise ValueError("LIVE_COMPOSITION_NOT_ADMITTED")
    output = path.parent
    from .host_runtime71 import open_runtime

    budget, admission, secrets = open_runtime(
        load(Path(config["root"]) / "session.json"),
        worker_observation=(config["observation"], config["fence"]),
    )
    from .public_backend_v12 import require_proposal, require_scope

    public_backend = require_scope(budget, config["question"], config["owner"])
    if not public_backend or config["owner"] != "PUBLIC_API_READ" or admission is None:
        raise ValueError("PUBLIC_READ_ONLY")
    public_adapter = None
    counts = {"adapter_entries": 0, "backend_attempts": 0}
    luna = Luna(
        budget,
        config["observation"],
        None,
        secrets,
        admission=admission,
        registry=owner_registry(config["owner"]),
    )
    observer = ReadOnlyGovernanceObserver(output, config["observation"])

    class ReceiptMixin(Gateway):
        async def call(
            self, request: str, proposal: Proposal, planning_failed: bool = False
        ) -> Any:
            if request != config["question"] or planning_failed:
                raise ValueError("REQUEST_CORRELATION_FAILED")
            if public_backend:
                require_proposal(request, proposal)
            identity = sha(canonical(proposal.model_dump(mode="json")))
            budget.admit_mcp(config["observation"], identity)
            envelope = await super().call(request, proposal)
            observer.close()
            events = [json.loads(line) for line in observer.path.read_text().splitlines()]
            save(
                output / "server-receipt.json",
                {
                    "owner": config["owner"],
                    "observation": config["observation"],
                    "request_sha256": sha(request.encode()),
                    "proposal_sha256": identity,
                    "response": envelope.model_dump(mode="json"),
                    "binding_issued": sum(e.get("status") == "ISSUED" for e in events),
                    "binding_consumed": sum(e.get("status") == "VERIFIED_CONSUMED" for e in events),
                    **counts,
                    **(
                        {
                            "adapter_entries": public_adapter.entries,
                            "backend_attempts": len(public_adapter.observations),
                            "public_http_attempts": public_adapter.observations,
                        }
                        if public_adapter is not None
                        else {}
                    ),
                    "judge_called": luna.exchange is not None,
                    "judge_signal": luna.signal,
                    "judge_raw_signal": luna.raw_signal,
                    "judge_flag_normalization": luna.flag_normalization,
                    "judge_error": luna.error,
                    "judge_attempt": luna.exchange.facts if luna.exchange else None,
                    "governance_sha256": sha(observer.path.read_bytes()),
                },
            )
            return envelope

    with observer:
        from .public_capture71 import CapturedPublicRead71

        public_adapter = CapturedPublicRead71(
            live_authorized=True,
            admission=admission,
            capture_root=Path(config["root"]) / "captured-wires" / "public_read",
        )
        save(
            output / "owner-selection.json",
            {
                "owner": config["owner"],
                "phase": "HOST_BOUND_BEFORE_DISCOVERY",
                "backend": "PUBLIC_API",
            },
        )
        create_server(ReceiptMixin(public_adapter, luna, Trace(output / "audit.jsonl"))).run(
            transport="stdio"
        )
