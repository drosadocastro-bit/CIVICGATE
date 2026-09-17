import argparse
import asyncio
import json
import os
from pathlib import Path

from civicgate.agent.agent import CivicGateAgent
from civicgate.audit.trace import Trace
from civicgate.config import configured_gateway, providers
from civicgate.demo import SCENARIOS, fixture_adapter
from civicgate.llm.mock import MockProvider
from civicgate.mcp.tools import Gateway


async def run(mode: str, request: str | None) -> None:
    if mode == "demo":
        gateway = Gateway(
            fixture_adapter(),
            MockProvider(),
            Trace(Path(os.getenv("CIVICGATE_AUDIT_PATH", "audit/demo.jsonl"))),
        )
        agent = CivicGateAgent(MockProvider(), gateway)
        for text in SCENARIOS:
            result = await agent.run(text)
            print(
                json.dumps(
                    {
                        "demo_mode": "SYNTHETIC_TEST_FIXTURE",
                        "request": text,
                        "response": result.model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
    else:
        model, _ = providers()
        result = await CivicGateAgent(model, configured_gateway()).run(request or "")
        print(result.model_dump_json(indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="CivicGate sandbox public spending agent")
    parser.add_argument("mode", choices=["demo", "ask"])
    parser.add_argument("request", nargs="?")
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.request))


if __name__ == "__main__":
    main()
