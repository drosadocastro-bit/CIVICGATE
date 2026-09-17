"""Opt-in read-only adapter contract check against the public government API."""

import asyncio
import json
from pathlib import Path

from civicgate.adapters.usaspending import AdapterError, USAspending
from civicgate.models.provenance import utcnow
from civicgate.models.requests import Award, Recipient, Search


async def main() -> None:
    adapter = USAspending()
    evidence = {
        "checked_at": utcnow().isoformat(),
        "mode": "LIVE_PUBLIC_API_CONTRACT_CHECK",
        "checks": [],
    }
    query = Search(start_date="2024-10-01", end_date="2025-09-30", state_code="PR", limit=2)
    try:
        batch = await adapter.search(query)
        evidence["checks"].append(
            {"operation": "search", "status": "OK", "data": batch.model_dump(mode="json")}
        )
        if batch.records:
            details = await adapter.detail(
                Award(award_id=batch.records[0]["generated_internal_id"])
            )
            evidence["checks"].append(
                {"operation": "detail", "status": "OK", "data": details.model_dump(mode="json")}
            )
    except AdapterError as exc:
        evidence["checks"].append(
            {"operation": "search_or_detail", "status": "ERROR", "code": exc.code}
        )
    try:
        batch = await adapter.recipients(Recipient(recipient_name="Acme", limit=2))
        evidence["checks"].append(
            {"operation": "recipient", "status": "OK", "data": batch.model_dump(mode="json")}
        )
    except AdapterError as exc:
        evidence["checks"].append({"operation": "recipient", "status": "ERROR", "code": exc.code})
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/live-smoke.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


asyncio.run(main())
