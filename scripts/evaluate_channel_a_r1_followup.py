"""Offline follow-up measurements. These outputs are never authority."""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path

from civicgate.models.requests import Proposal
from scripts.evaluate_channel_a_remediation_r1 import R1_MODES, measure_case

ROOT = Path(__file__).parents[1]
FIXTURES = {
    "channel_a_r1_followup_independent_v1.json": "fbbe488ba9bce516b91860ee0097208e3e6352f4bf031a97cccf811bd278236c",
    "channel_a_r1_literal_controls_v1.json": "f825cf05be073060ad6904bc6e947f81c9baf77367a99ba507e2161920850a57",
}


def cases():
    result = []
    for name, expected in FIXTURES.items():
        raw = (ROOT / "tests/fixtures" / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Independent specification identity differs: " + name)
        for item in json.loads(raw)["cases"]:
            benign = (
                item.get("expected_safety") == "BENIGN"
                or item.get("expecteddecisionifpermissive") == "PERMIT"
            )
            result.append(
                {
                    **item,
                    "case_id": item["id"],
                    "language": item.get("language", "mixed"),
                    "request_intent": "BENIGN_PUBLIC_RESEARCH" if benign else "UNRESOLVED",
                    "corpus": name,
                }
            )
    return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proposal = Proposal(tool="get_federal_award", arguments={"award_id": "1"})
    rows = [await measure_case(case, proposal, mode) for case in cases() for mode in R1_MODES]
    summary = {}
    for group in ("BEN_", "SCOPE_", "LITERAL_POS_", "LITERAL_NEG_"):
        summary[group] = {
            mode: dict(
                Counter(
                    row["actual_gateway_final_decision"]
                    for row in rows
                    if row["case_id"].startswith(group) and row["mode"] == mode
                )
            )
            for mode in R1_MODES
        }
    result = {
        "contract": "channel-a-r1-name-literal-followup-v1",
        "limits": "Independent author specifications, visible to developers. Fixed read-only proposal isolates policy admission, not task-answer correctness. No real Judge accuracy, population accuracy, authenticated intent or complete semantic understanding is established.",
        "fixture_sha256": FIXTURES,
        "risk_code_sha256": hashlib.sha256(
            (ROOT / "src/civicgate/governance/request_risk.py").read_bytes()
        ).hexdigest(),
        "summary": summary,
        "measurements": rows,
        "real_model_calls": 0,
        "live_api_calls": 0,
    }
    args.output.open("x", encoding="utf-8").write(json.dumps(result, indent=2, ensure_ascii=False))
    print(
        json.dumps({key: value for key, value in result.items() if key != "measurements"}, indent=2)
    )


if __name__ == "__main__":
    asyncio.run(main())
