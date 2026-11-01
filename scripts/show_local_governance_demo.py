"""Read genuine captured evidence. No project imports, network or new execution."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--case", choices=["all", "permit", "deny", "review"], default="all")
    a = p.parse_args()
    base = a.run.resolve()
    m = json.loads((base / "RUN_SHA256_MANIFEST.json").read_bytes())
    seen = set()
    for row in m["files"]:
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts or row["path"] in seen:
            raise SystemExit("STOP: invalid manifest path")
        seen.add(row["path"])
        raw = (base / rel).read_bytes()
        if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise SystemExit("STOP: evidence identity mismatch")
    result = json.loads((base / "run-result.json").read_bytes())
    if result["final_status"] not in {"A2_INTEGRATED_DEMO_READY", "DEMO_READY_OFFLINE_SYNTHETIC"}:
        raise SystemExit("STOP: run was not verified; inspect preserved failure")
    print("PREVIOUSLY CAPTURED LOCAL SYNTHETIC EVIDENCE - READ-ONLY PLAYBACK")
    print("Capture completed UTC:", result["completed_at_utc"])
    print(
        "Manifest verified:",
        len(m["files"]),
        "files. Playback makes no new MCP/provider/backend calls.",
    )
    for card in result["cards"]:
        if a.case != "all" and card["case"] != a.case:
            continue
        print("\n" + card["decision"] + " | " + card["tool"])
        print("Request:", card["original_request"])
        if "graph_visited_nodes" in card:
            print("Actual A2 nodes:", " -> ".join(card["graph_visited_nodes"]))
            print("Compiled LangGraph invocations:", card["compiled_graph_invocations"])
        else:
            print("A2 node history: not persisted by the original MINI07.1 capture; use MINI07.2.")
        print("Reasons:", ", ".join(card["policy_reasons"]))
        print(
            "Bindings issued/consumed:",
            card["binding_issuances"],
            "/",
            card["binding_consumptions"],
        )
        print(
            "Adapter entries/MockTransport attempts:",
            card["adapter_entries"],
            "/",
            card["mock_backend_attempts"],
        )
        print(
            "Synthetic planner/Judge HTTP receipts:",
            card["planner_http_receipts"],
            "/",
            card["judge_http_receipts"],
        )
        print(
            "Verification:",
            card["verification_state"],
            "| Custody:",
            card["custody_state"],
            "| Close ACK:",
            card["custody_close_ack"],
        )
        print(
            "Judge advice:",
            card["judge"]["classification"],
            "| available:",
            card["judge"]["available"],
        )
        if card["result"] is not None:
            print("Synthetic records:", json.dumps(card["result"], ensure_ascii=True))
    print("\nFULL FAA FY2026 CONTRACT: NOT EXECUTED; 54 definitions remain BLOCKED/SKIP.")
    print("CLOSED is evaluation custody, not human approval. Live providers/API/cloud: HOLD.")


if __name__ == "__main__":
    main()
