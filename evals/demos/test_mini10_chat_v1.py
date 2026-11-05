"""One fresh MINI10 prompt through the genuine MINI07.2 integrated path."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from evals.demos import test_mini072_demo_v1 as integrated
from evals.demos.mini10_chat_fixtures_v1 import fixture_for_request
from evals.harness.evidence import write_new


def _strict_request(path: Path) -> dict[str, str]:
    raw = path.read_bytes()
    if not 0 < len(raw) <= 8192:
        raise ValueError("MINI10_REQUEST_RECORD_SIZE")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("MINI10_DUPLICATE_REQUEST_FIELD")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=unique)
    if type(value) is not dict or set(value) != {
        "host_owner",
        "planner_identity",
        "prompt",
        "prompt_sha256",
    }:
        raise ValueError("MINI10_REQUEST_RECORD_FIELDS")
    if (
        value["host_owner"] != "CHANNEL_A_LOCAL_READ_V1"
        or value["planner_identity"] != "SCRIPTED_SYNTHETIC_FIXTURE_NOT_GRANITE"
        or type(value["prompt"]) is not str
        or hashlib.sha256(value["prompt"].encode()).hexdigest() != value["prompt_sha256"]
    ):
        raise ValueError("MINI10_REQUEST_RECORD_MISMATCH")
    return value


def test_governed_chat_prompt(monkeypatch) -> None:
    request_path = Path(os.environ["CIVICGATE_MINI10_REQUEST_PATH"]).resolve(strict=True)
    case_root = Path(os.environ["CIVICGATE_MINI10_CASE_ROOT"]).resolve(strict=True)
    request = _strict_request(request_path)
    fixture = fixture_for_request(request["prompt"])
    case = (
        "permit"
        if fixture.expected_decision == "PERMIT"
        else "deny"
        if fixture.expected_decision == "DENY"
        else "chat-review"
    )
    integrated.CASE_ROOT = case_root
    integrated.SCENARIOS[case] = fixture.scenario
    integrated.EXPECTED[case] = fixture.expected_decision
    integrated.test_local_synthetic_demo(case, monkeypatch)
    directory = case_root / case
    write_new(
        directory / "mini10-chat-binding.json",
        {
            "case_id": fixture.case_id,
            "host_owner": request["host_owner"],
            "planner_identity": request["planner_identity"],
            "prompt_sha256": request["prompt_sha256"],
            "expected_decision": fixture.expected_decision,
            "intent_note": fixture.intent_note,
            "one_bounded_proposal": True,
            "write_owner_exposed": False,
            "faa_or_legacy_fallback": False,
        },
    )
