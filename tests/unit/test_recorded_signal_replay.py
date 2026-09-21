"""Synthetic characterization of the offline replay instrument, not live model evidence."""

import asyncio
import copy
import importlib.util
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

SPEC = importlib.util.spec_from_file_location(
    "recorded_signal_replay",
    Path(__file__).resolve().parents[2] / "scripts/replay_recorded_judge_signals.py",
)
assert SPEC and SPEC.loader
r = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = r
SPEC.loader.exec_module(r)


def example(case_id="synthetic-example", **changes):
    case = {
        "id": case_id,
        "request": "Find public awards in Puerto Rico.",
        "proposal": {
            "tool": "find_federal_awards",
            "arguments": {"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"},
        },
        "signal": {
            "classification": "IN_SCOPE",
            "confidence": 0.96,
            "flags": [],
            "available": True,
            "provider": "synthetic-example",
        },
    }
    case.update(copy.deepcopy(changes))
    return case


def inputs(*cases):
    return r.ReplayInput.model_validate(
        {"schema_version": "civicgate.recorded-signals.v1", "cases": list(cases)}
    )


def run(*cases):
    result = asyncio.run(r.run_replay(inputs(*cases)))
    assert result["status"] == "COMPLETED_OFFLINE_REPLAY", result["abort_reason"]
    assert result["external_calls"] == result["blocked_network_attempts"] == 0
    return result


@pytest.mark.parametrize(
    "flags,available", [([], True), (["NONE"], True), (["AMBIGUOUS_TARGET"], False)]
)
def test_recorded_provider_preserves_all_five_fields_exactly(flags, available):
    raw = example()
    raw["signal"].update(flags=flags, available=available)
    case = r.ReplayCase.model_validate(raw)
    provider = r.RecordedJudgeProvider(case, forbidden=False)
    signal = asyncio.run(provider.assess(case.request, case.proposal))
    assert r.signal_summary(signal) == raw["signal"]
    signal.flags.append("PROVENANCE_RISK")
    assert provider.record == raw["signal"]
    assert provider.calls == provider.returns == 1
    with pytest.raises(r.ReplayViolation, match="UNEXPECTED_RECORDED_PROVIDER_CALL"):
        asyncio.run(provider.assess(case.request, case.proposal))


def test_offline_guards_block_real_network_before_transport():
    async def check():
        with r.OfflineOnly() as guard:
            with pytest.raises(r.ReplayViolation, match="NETWORK_PATH_BLOCKED"):
                socket.create_connection(("example.invalid", 443))
            with pytest.raises(r.ReplayViolation, match="NETWORK_PATH_BLOCKED"):
                await httpx.AsyncHTTPTransport().handle_async_request(
                    httpx.Request("GET", "https://example.invalid")
                )
            assert guard.blocked_attempts == 2
            with pytest.raises(r.ReplayViolation, match="NON_SYNTHETIC_TRANSPORT"):
                r.CountingTransport(httpx.AsyncHTTPTransport())

    asyncio.run(check())


@pytest.mark.parametrize(
    "request_text,tool",
    [
        ("Get public data", "unknown_tool"),
        ("Use hidden tool", "find_federal_awards"),
        ("Blacklist this contractor", "find_federal_awards"),
    ],
)
def test_deterministic_preflight_skips_even_permissive_recorded_provider(request_text, tool):
    case = example(request=request_text)
    case["proposal"]["tool"] = tool
    row = run(case)["cases"][0]["replay_lane"]
    assert row["decision"] == "DENY"
    assert row["preflight_skipped_judge"] and not row["signal_consumed"]
    assert row["provider_calls"] == row["provider_returns"] == row["adapter_initiations"] == 0


def test_forbidden_provider_fails_if_preflight_ever_invokes_it():
    case = r.ReplayCase.model_validate(example())
    provider = r.RecordedJudgeProvider(case, forbidden=True)
    with pytest.raises(r.ReplayViolation, match="UNEXPECTED_PREFLIGHT_PROVIDER_CALL"):
        asyncio.run(provider.assess(case.request, case.proposal))
    assert provider.calls == 1 and provider.returns == 0


def test_invalid_tool_arguments_remain_denied_without_judge_or_adapter():
    case = example()
    case["proposal"]["arguments"]["start_date"] = "invalid"
    row = run(case)["cases"][0]["replay_lane"]
    assert row["decision"] == "DENY" and "INVALID_INPUT" in row["policy_reasons"]
    assert row["provider_calls"] == row["adapter_initiations"] == 0


def permitted_reference():
    return {
        "decision": "PERMIT",
        "status": "OK",
        "policy_reasons": ["BOUNDED_PUBLIC_RESEARCH"],
        "adapter_initiated": True,
        "judge_consulted": True,
        "dispatch_state": "REQUEST_CONFIRMED",
        "response_state": "RESPONSE_RECEIVED",
        "verification_state": "RESULT_VERIFIED",
        "next_action": "NONE",
    }


def test_non_in_scope_signal_contracts_before_dispatch():
    case = example(reference=permitted_reference())
    case["signal"].update(classification="AMBIGUOUS", flags=["AMBIGUOUS_TARGET"])
    row = run(case)["cases"][0]
    assert row["authority_difference_class"] == "PRE_DISPATCH_CONTRACTION"
    assert row["authority_direction"] == "CONTRACTIVE"
    assert row["replay_lane"]["decision"] == "REVIEW_REQUIRED"
    assert row["replay_lane"]["signal_consumed"]
    assert row["replay_lane"]["adapter_initiations"] == 0


def test_known_integration_finding_literal_none_is_review_relevant_not_endorsed():
    # Characterization of OPEN_DESIGN_FINDING, not the desired future policy.
    case = example(reference=permitted_reference())
    case["signal"]["flags"] = ["NONE"]
    row = run(case)["cases"][0]
    assert row["recorded_signal"] == case["signal"]
    assert row["replay_lane"]["judge_signal"]["flags"] == ["NONE"]
    assert row["replay_lane"]["policy_reasons"] == ["SEMANTIC_REVIEW_REQUIRED"]
    assert row["replay_lane"]["decision"] == "REVIEW_REQUIRED"
    assert row["replay_lane"]["status"] == "BLOCKED"
    assert not row["replay_lane"]["adapter_initiated"]
    assert row["authority_difference_class"] == "PRE_DISPATCH_CONTRACTION"


def test_permissive_signal_executes_only_after_policy_permit_and_counters_reconcile():
    result = run(example())
    lane = result["cases"][0]["replay_lane"]
    assert lane["decision"] == lane["pre_dispatch_policy"]["decision"] == "PERMIT"
    assert lane["authority_source"] == "DETERMINISTIC_POLICY_GATE"
    assert lane["trace_stage_order"].index("policy") < lane["trace_stage_order"].index(
        "execution_started"
    )
    assert result["completed_case_counters"] == {
        "provider_calls": 1,
        "provider_returns": 1,
        "adapter_initiations": 1,
        "synthetic_transport_calls": 1,
    }


def test_direct_adapter_entry_without_policy_is_rejected():
    case = r.ReplayCase.model_validate(example())
    adapter = r.adapter_for(case, r.Trace())
    with pytest.raises(r.ReplayViolation, match="ADAPTER_WITHOUT_POLICY_EXECUTION_TRACE"):
        adapter.before_adapter()
    assert adapter.initiations == adapter.counted_transport.calls == 0


def test_permissive_signal_cannot_bypass_independent_breadth_review():
    case = example()
    del case["proposal"]["arguments"]["state_code"]
    lane = run(case)["cases"][0]["replay_lane"]
    assert lane["decision"] == "REVIEW_REQUIRED" and "QUERY_TOO_BROAD" in lane["policy_reasons"]
    assert lane["provider_returns"] == 1 and lane["adapter_initiations"] == 0


def test_fresh_gateway_between_rows_prevents_containment_carryover():
    result = run(
        example("deny-one", request="Blacklist contractor"),
        example("deny-two", request="Blacklist contractor"),
        example("permitted"),
    )
    assert [x["replay_lane"]["decision"] for x in result["cases"]] == ["DENY", "DENY", "PERMIT"]
    assert result["intended_count"] == result["completed_count"] == 3
    assert result["completed_case_counters"]["provider_calls"] == 1


def test_absent_reference_is_not_invented_and_no_rationale_or_private_metadata_is_output():
    result = run(example())
    row = result["cases"][0]
    assert row["authority_difference_class"] == "NOT_COMPARABLE" and row["reference_lane"] is None
    assert set(row["recorded_signal"]) == set(r.SIGNAL_FIELDS)
    assert set(row["replay_lane"]["judge_signal"]) == set(r.SIGNAL_FIELDS)
    encoded = json.dumps(result)
    assert '"rationale"' not in encoded and '"request_id"' not in encoded
    assert str(r.ROOT) not in encoded


@pytest.mark.parametrize("field", ["rationale", "request_id", "api_key", "raw_response"])
def test_input_rejects_unreviewed_provider_metadata(field):
    case = example()
    case["signal"][field] = "synthetic-unwanted-field"
    with pytest.raises(ValidationError):
        inputs(case)


def test_duplicate_ids_and_missing_signal_fields_are_rejected():
    with pytest.raises(ValidationError):
        inputs(example(), example())
    case = example()
    del case["signal"]["flags"]
    with pytest.raises(ValidationError):
        inputs(case)


def test_stateful_factory_is_explicit_and_synthetic():
    case = example(transport="five_hundred_then_success")
    lane = run(case)["cases"][0]["replay_lane"]
    assert lane["status"] == "OK" and lane["attempt_count"] == 2
    assert lane["synthetic_transport_calls"] == 2 and lane["adapter_initiations"] == 1


def test_invariant_failure_aborts_without_fallback_or_remaining_cases(monkeypatch):
    original = r.RecordedJudgeProvider.assess
    calls = []

    async def broken(self, request, proposal):
        calls.append(request)
        await original(self, request, proposal)
        raise r.ReplayViolation("SYNTHETIC_TEST_INVARIANT")

    monkeypatch.setattr(r.RecordedJudgeProvider, "assess", broken)
    result = asyncio.run(r.run_replay(inputs(example("one"), example("two"))))
    assert result["status"] == "REPLAY_ABORTED"
    assert result["abort_reason"] == "SYNTHETIC_TEST_INVARIANT"
    assert result["completed_count"] == 0 and result["uncompleted_count"] == 2
    assert len(calls) == 1 and result["external_calls"] == 0


def test_cli_is_portable_without_localappdata_and_preserves_existing_output(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    source, target = tmp_path / "reviewed.json", tmp_path / "result.json"
    source.write_text(inputs(example()).model_dump_json(), encoding="utf-8")
    assert r.main(["--input", str(source), "--output", str(target)]) == 0
    content = target.read_bytes()
    assert json.loads(content)["status"] == "COMPLETED_OFFLINE_REPLAY"
    assert r.main(["--input", str(source), "--output", str(target)]) == 1
    assert target.read_bytes() == content


def test_cli_refuses_repository_paths_and_does_not_echo_rejected_input(tmp_path, capsys):
    source, target = tmp_path / "reviewed.json", tmp_path / "result.json"
    source.write_text('{"private_text":"DO_NOT_ECHO_SYNTHETIC_CONTENT"}', encoding="utf-8")
    assert r.main(["--input", str(source), "--output", str(target)]) == 1
    assert "DO_NOT_ECHO_SYNTHETIC_CONTENT" not in capsys.readouterr().out
    assert not target.exists()
    assert (
        r.main(["--input", str(source), "--output", str(r.ROOT / "artifacts/not-created.json")])
        == 1
    )
    assert not (r.ROOT / "artifacts/not-created.json").exists()


def test_comparison_preserves_timing_precedence_and_missing_state():
    lane = {
        "decision": "REVIEW_REQUIRED",
        "status": "BLOCKED",
        "policy_reasons": ["SEMANTIC_REVIEW_REQUIRED"],
        "agent_k": {"signals": ["NONE"], "containment": False},
        "adapter_initiated": False,
    }
    ref = r.ReferenceLane(
        decision="REVIEW_REQUIRED",
        status="CLARIFICATION_REQUIRED",
        policy_reasons=["AMBIGUOUS_RECIPIENT"],
        adapter_initiated=True,
    )
    assert r.compare(ref, lane) == {
        "authority_difference_class": "TIMING_DIFFERENCE_SAME_FINAL_AUTHORITY",
        "authority_direction": "CONTRACTIVE",
    }
    ref = r.ReferenceLane(decision="PERMIT", status="OK", policy_reasons=[], adapter_initiated=True)
    assert (
        r.compare(ref, {**lane, "adapter_initiated": True})["authority_difference_class"]
        == "NOT_COMPARABLE"
    )
