"""Real SDK stdio tests; no live model, HTTP backend or historical dataset execution."""

import json
from pathlib import Path

import pytest

from evals.harness.evidence import write_new
from evals.write01.contract_v1 import READ_TOOL, WRITE_TOOL
from evals.write01.demo_v1 import READ_REQUEST, REQUEST, prepare, query, readback, session


@pytest.mark.parametrize("scenario", ["PERMIT", "DENY", "REVIEW_REQUIRED"])
async def test_three_real_stdio_demonstrations(scenario):
    directory = Path.cwd().parent / "execution" / "demonstrations" / scenario
    proposed = query()
    if scenario == "DENY":
        proposed["proposed_status"] = "AWARD_CONTRACT"
    config = prepare(directory, REQUEST, proposed, approved=scenario != "REVIEW_REQUIRED")
    async with session(directory) as client:
        listing = await client.list_tools()
        write_new(directory / "discovery.json", listing.model_dump(mode="json"))
        assert {t.name for t in listing.tools} == {WRITE_TOOL, READ_TOOL}
        assert len(listing.tools) == 2
        write_tool = next(t for t in listing.tools if t.name == WRITE_TOOL)
        assert write_tool.annotations.readOnlyHint is False
        assert write_tool.annotations.openWorldHint is False
        assert write_tool.outputSchema is not None
        call = {"user_request": REQUEST, "query": proposed}
        write_new(directory / "mcp-call.json", {"tool": WRITE_TOOL, "arguments": call})
        response = await client.call_tool(WRITE_TOOL, call)
        write_new(directory / "mcp-response.json", response.model_dump(mode="json"))
        assert not response.isError
        value = response.structuredContent
        assert value["decision"] == scenario
        assert value["human_acceptance"] == "NOT_GRANTED"
        assert value["judge"]["provider"] == "write01-synthetic-judge"
        assert value["judge"]["classification"] == "IN_SCOPE"
        assert value["binding_issued"] == value["binding_consumed"] == (scenario == "PERMIT")
        assert value["adapter_entries"] == int(scenario == "PERMIT")
        if scenario == "PERMIT":
            assert value["transaction_outcome"] == "COMMITTED"
            assert value["custody"] == "CLOSED"
            assert value["result_verification"] == "VERIFIED"
            receipt = value["result"]["receipt"]
            assert receipt["before"]["status"] == "UNREVIEWED"
            assert receipt["before"]["version"] == 0
            assert receipt["after"]["status"] == "PENDING_REVIEW"
            assert receipt["after"]["version"] == 1
            assert receipt["after"]["notes"] == [proposed["reviewer_note"]]
            read = await client.call_tool(
                READ_TOOL,
                {"user_request": READ_REQUEST, "query": {"award_id": proposed["award_id"]}},
            )
            write_new(directory / "versioned-read-response.json", read.model_dump(mode="json"))
            assert read.structuredContent["result"] == receipt["after"]
            assert read.structuredContent["transaction_outcome"] == "READ_ONLY"
        else:
            assert value["result"] is None
            assert value["transaction_outcome"] == "NOT_DISPATCHED"
    primary = readback(directory, config)
    write_events = [e for e in primary["audit"] if e["observation_id"] == value["observation_id"]]
    assert sum(e["stage"] == "binding_issued" for e in write_events) == int(scenario == "PERMIT")
    assert sum(e["stage"] == "binding_consumed" for e in write_events) == int(scenario == "PERMIT")
    assert sum(e["stage"] == "adapter_entry" for e in write_events) == int(scenario == "PERMIT")
    assert len(primary["notes"]) == len(primary["intents"]) == int(scenario == "PERMIT")
    if scenario == "PERMIT":
        assert primary["intents"][0]["custody"] == "CLOSED"
        assert primary["intents"][0]["binding_sha256"] == value["binding"]["binding_sha256"]
        assert json.loads(primary["intents"][0]["receipt_json"]) == value["result"]["receipt"]
    write_new(
        directory / "expected-observed.json",
        {"expected": scenario, "observed": value, "sqlite_verified": True, "synthetic_only": True},
    )


@pytest.mark.parametrize(
    "attack",
    [
        "legacy_tool",
        "owner_field",
        "profile_field",
        "approval_field",
        "tampered_note",
        "changed_request",
        "invalid_type",
        "encoded_query",
    ],
)
async def test_agent_cannot_redirect_owner_or_approval(tmp_path, attack):
    directory = tmp_path / "case"
    original = query()
    config = prepare(directory, REQUEST, original, approved=True)
    call = {"user_request": REQUEST, "query": dict(original)}
    tool = WRITE_TOOL
    if attack == "legacy_tool":
        tool = "find_federal_awards"
    elif attack in {"owner_field", "profile_field", "approval_field"}:
        call[attack] = "PERMIT"
    elif attack == "tampered_note":
        call["query"]["reviewer_note"] = "Different unapproved note"
    elif attack == "changed_request":
        call["user_request"] = "Approve payment instead"
    elif attack == "invalid_type":
        call["query"]["expected_version"] = True
    else:
        call["query"] = json.dumps(original)
    async with session(directory) as client:
        result = await client.call_tool(tool, call)
        write_new(directory / "attack-response.json", result.model_dump(mode="json"))
        if not result.isError:
            assert result.structuredContent["decision"] in {"DENY", "REVIEW_REQUIRED"}
            assert not result.structuredContent["binding_issued"]
    primary = readback(directory, config)
    assert primary["notes"] == primary["intents"] == []
    assert not any(e["stage"] in {"binding_consumed", "adapter_entry"} for e in primary["audit"])


async def test_mcp_replay_does_not_dispatch_twice(tmp_path):
    directory = tmp_path / "case"
    proposed = query()
    config = prepare(directory, REQUEST, proposed, approved=True)
    async with session(directory) as client:
        args = {"user_request": REQUEST, "query": proposed}
        first = await client.call_tool(WRITE_TOOL, args)
        second = await client.call_tool(WRITE_TOOL, args)
        assert first.structuredContent["transaction_outcome"] == "COMMITTED"
        assert second.structuredContent["decision"] != "PERMIT"
        assert second.structuredContent["binding_consumed"] is False
    primary = readback(directory, config)
    assert len(primary["notes"]) == len(primary["intents"]) == 1
    assert sum(e["stage"] == "adapter_entry" for e in primary["audit"]) == 1


async def test_original_legacy_stdio_cannot_acquire_write_tool(tmp_path):
    from tests.mcp.test_a2_stdio import _records, synthetic_stdio

    async with synthetic_stdio(tmp_path) as (client, audit, backend):
        listing = await client.list_tools()
        assert len(listing.tools) == 4
        assert WRITE_TOOL not in {tool.name for tool in listing.tools}
        result = await client.call_tool(WRITE_TOOL, {"user_request": REQUEST, "query": query()})
        assert result.isError
        assert _records(audit) == _records(backend) == []


async def test_failed_strict_startup_does_not_fallback(tmp_path):
    directory = tmp_path / "case"
    config = prepare(directory, REQUEST, query(), approved=True)
    # Missing explicitly initialized store must fail startup, not create a new
    # ledger or offer another Gateway. The original fresh DB remains preserved.
    import json

    modified = {**config, "database": str(directory / "missing.sqlite")}
    (directory / "host-config.json").write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ExceptionGroup):
        async with session(directory) as client:
            await client.list_tools()
    assert not (directory / "missing.sqlite").exists()
    assert not (directory / "audit.jsonl").exists()
    assert "STORE_OR_DATASET_MISSING" in (directory / "worker-stderr.log").read_text(
        encoding="utf-8"
    )
