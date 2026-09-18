"""Small local trace viewer; it never displays raw credential fields."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from civicgate.audit.trace import redact


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(redact(value))
    return events


def render_text(events: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("request_id", "unknown")), []).append(event)
    for request_id, request_events in grouped.items():
        rows.append(f"REQUEST {request_id}")
        proposal = next((e for e in request_events if e.get("stage") == "proposal"), {})
        rows.append(
            f"USER -> GRANITE proposal: {json.dumps(proposal.get('proposal', {}), ensure_ascii=False)}"
        )
        policy_event = next((e for e in request_events if e.get("stage") == "policy"), {})
        rows.append(f"JUDGE: {json.dumps(policy_event.get('judge', {}), ensure_ascii=False)}")
        rows.append(f"AGENT K: {json.dumps(policy_event.get('agent_k', {}), ensure_ascii=False)}")
        policy = policy_event.get("policy", {})
        rows.append(f"POLICY RULES -> DECISION: {json.dumps(policy, ensure_ascii=False)}")
        completion = next((e for e in request_events if e.get("stage") == "completed"), {})
        response = completion.get("response", {})
        rows.append(
            "EXECUTED? "
            + str(completion.get("tool_executed", response.get("tool_executed", False)))
            + " -> PROVENANCE: "
            + json.dumps(response.get("provenance"), ensure_ascii=False)
        )
        rows.append(f"FINAL RESPONSE: {json.dumps(response, ensure_ascii=False)}")
    return "\n".join(rows) + ("\n" if rows else "")


def render_html(events: list[dict[str, Any]]) -> str:
    text = html.escape(render_text(events))
    return (
        "<!doctype html><meta charset='utf-8'><title>CivicGate Trace</title><pre>" + text + "</pre>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a local CivicGate JSONL trace")
    parser.add_argument("path", type=Path)
    parser.add_argument("--html", type=Path, help="write a self-contained local HTML viewer")
    args = parser.parse_args()
    events = load_events(args.path)
    if args.html:
        args.html.write_text(render_html(events), encoding="utf-8")
        print(args.html)
    else:
        print(render_text(events), end="")


if __name__ == "__main__":
    main()
