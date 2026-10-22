import asyncio
import json

import httpx

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.demo import fixture_transport
from civicgate.llm.mock import MockProvider
from civicgate.mcp.server import create_server
from civicgate.mcp.tools import Gateway
from civicgate.models.requests import TOOLS, Proposal


async def main():
    schemas = {name: model.model_json_schema() for name, model in TOOLS.items()}
    q = {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"}
    cases = [
        ("Show public federal data", "find_federal_awards", q),
        ("Show public federal data", "summarize_federal_spending", q),
        ("Show public federal data", "get_federal_award", {"award_id": "1"}),
        ("Show public federal data", "resolve_federal_recipient", {"recipient_name": "Acme"}),
        ("Deny benefits to this applicant.", "find_federal_awards", q),
        ("Deny this award to the vendor.", "find_federal_awards", q),
        (
            'Get public awards for agency "Other Agency".',
            "find_federal_awards",
            q | {"awarding_agency": "Example Office"},
        ),
        (
            'Get public awards for agency "Example Office".',
            "find_federal_awards",
            q | {"awarding_agency": "Example Office"},
        ),
        ("Show public federal data", "find_federal_awards", q | {"agency_tier": "subtier"}),
        ("Show public federal data", "hidden_tool", q),
    ]
    results = []
    for request, tool, args in cases:
        wire = []
        underlying = fixture_transport()

        async def capture(req, wire=wire, underlying=underlying):
            wire.append(
                {
                    "method": req.method,
                    "url": str(req.url),
                    "body": json.loads(req.content) if req.content else None,
                }
            )
            return await underlying.handle_async_request(req)

        trace = Trace()
        gateway = Gateway(
            USAspending(httpx.MockTransport(capture), fixture=True), MockProvider(), trace
        )
        server = create_server(gateway)
        discovery = [t.model_dump(mode="json") for t in await server.list_tools()]
        result = await gateway.call(request, Proposal(tool=tool, arguments=args))
        data = result.model_dump(mode="json")
        data.pop("request_id")
        if data["provenance"]:
            data["provenance"].pop("retrieved_at")
        policy = next(e for e in trace.events if e["stage"] == "policy")
        results.append(
            {
                "input": [request, tool, args],
                "output": data,
                "wire": wire,
                "initial_policy": policy["policy"],
                "facts": policy["facts"],
                "binding_issued": policy["binding_issued"],
                "verification": trace.events[-1]["pre_dispatch_verification"],
            }
        )
    print(
        json.dumps({"schemas": schemas, "discovery": discovery, "cases": results}, sort_keys=True)
    )


asyncio.run(main())
