"""J4 instrument tests: synthetic HTTP only; never use human labels as judge input."""

import json
import os
import subprocess
import sys
from collections import Counter

import httpx
import pytest

from civicgate.llm.judge_profiles import select_openai_profile
from civicgate.llm.live import LiveJudgeProvider
from civicgate.models.requests import Proposal
from scripts import prepare_j4_gpt6_luna as j4

VALID = {"classification": "IN_SCOPE", "confidence": 0.9, "flags": ["NONE"]}


@pytest.fixture(autouse=True)
def deny_external_boundaries(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Forbidden real network, credential or Gateway boundary")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setattr(j4.j3.engine.Gateway, "call", forbidden)
    monkeypatch.setattr(j4.j3.engine.Gateway, "_call", forbidden)
    monkeypatch.setattr(j4.j3.parent.WindowsDPAPIStore, "get_secret", forbidden)
    monkeypatch.setattr(j4.j3.engine, "_preflight", forbidden)


def response(*, model="gpt-6-luna", wire=None, finish="stop", content=None, refusal=None):
    return httpx.Response(
        200,
        json={
            "model": model,
            "system_fingerprint": "synthetic-fingerprint",
            "service_tier": "default",
            "choices": [
                {
                    "finish_reason": finish,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(VALID if wire is None else wire)
                        if content is None
                        else content,
                        "refusal": refusal,
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 9,
                "total_tokens": 21,
                "completion_tokens_details": {"reasoning_tokens": 4},
            },
        },
        headers={"x-request-id": "synthetic-request-id"},
    )


async def capture(profile_id):
    profile = select_openai_profile(profile_id, benchmark=True)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return response(model=profile.model)

    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        "synthetic",
        openai_profile_id=profile_id,
        transport=httpx.MockTransport(handler),
    )
    judge.client.max_attempts = 1
    for case in j4.j3.engine._load_fixtures():
        await judge.assess(
            case["request"], Proposal(tool=case["tool"], arguments=case["arguments"])
        )
    return seen


@pytest.mark.parametrize("profile_id", ["j2-luna", "j4-gpt6-luna"])
async def test_actual_adapter_payload_and_no_hidden_fixture_information(profile_id):
    seen = await capture(profile_id)
    for case, actual in zip(j4.j3.engine._load_fixtures(), seen, strict=True):
        expected = j4.payload(profile_id, case)
        assert actual == expected
        assert actual["max_completion_tokens"] == 512
        assert actual["response_format"] == {"type": "json_object"}
        assert not set(j4.FORBIDDEN_FIELDS) & actual.keys()
        assert [m["role"] for m in actual["messages"]] == ["system", "user"]
        assert actual["messages"][0]["content"] == j4.j3.engine._prompt()
        visible = json.loads(actual["messages"][1]["content"])
        assert visible == {
            "request": case["request"],
            "proposal": Proposal(tool=case["tool"], arguments=case["arguments"]).model_dump(),
        }
        if profile_id == "j4-gpt6-luna":
            assert actual["reasoning_effort"] == "medium"
            assert set(actual) == {
                "model",
                "reasoning_effort",
                "max_completion_tokens",
                "response_format",
                "messages",
            }
        else:
            assert "reasoning_effort" not in actual
            assert actual == j4.j3.engine._payload(case)


async def test_gpt56_matches_pre_refactor_real_adapter_capture():
    # SHA-256 of canonical JSON of all 35 actual MockTransport payloads, captured
    # at 254c8b9 before edits. This is a fixed regression anchor, not regenerated.
    actual = await capture("j2-luna")
    assert (
        j4.payload_hash(actual)
        == "99e262669f7afee75de65b978adb2bc5a21aca984d5014fb6e04c4de365569fa"
    )


def test_profile_selection_is_explicit_and_unknown_benchmark_fails_closed():
    with pytest.raises(ValueError, match="UNKNOWN_BENCHMARK_PROFILE"):
        select_openai_profile("typo", benchmark=True)
    with pytest.raises(ValueError, match="UNKNOWN_BENCHMARK_PROFILE"):
        select_openai_profile("generic-openai", benchmark=True)
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="UNKNOWN_BENCHMARK_PROFILE"):
        j4.select_profile("j2-luna")
    generic = LiveJudgeProvider("https://api.openai.com/v1", "gpt-6-luna", "synthetic")
    assert generic.openai_profile.profile_id == "generic-openai"
    with pytest.raises(ValueError, match="MISMATCH"):
        LiveJudgeProvider(
            "https://proxy.example", "gpt-6-luna", "synthetic", openai_profile_id=j4.PROFILE_ID
        )
    with pytest.raises(ValueError, match="MISMATCH"):
        LiveJudgeProvider(
            "https://api.openai.com/v1",
            "gpt-5.6-luna",
            "synthetic",
            openai_profile_id=j4.PROFILE_ID,
        )


def test_payload_hash_input_identity_and_changed_wire_fields():
    case = j4.j3.engine._load_fixtures()[0]
    p = j4.payload(j4.PROFILE_ID, case)
    assert j4.payload_hash(p) == j4.payload_hash(json.loads(json.dumps(p)))
    for field, changed in [
        ("model", "other"),
        ("reasoning_effort", "high"),
        ("max_completion_tokens", 513),
        ("response_format", {"type": "json_schema"}),
        ("messages", []),
    ]:
        assert j4.payload_hash(p | {field: changed}) != j4.payload_hash(p)
    assert j4.payload_hash(p) != j4.payload_hash(j4.payload("j2-luna", case))
    assert j4.historical_invariants()["semantic_contract_sha256"] == j4.j3.CONTRACT_SHA256
    assert j4.profile_artifact() == json.loads((j4.ROOT / j4.PROFILE_PATH).read_text())
    assert j4.contract_artifact() == json.loads((j4.ROOT / j4.CONTRACT_PATH).read_text())


def test_human_reference_is_exact_projection_not_readjudication():
    reference = j4.human_reference()
    assert reference == json.loads((j4.ROOT / j4.REFERENCE_PATH).read_text())
    source = json.loads((j4.ROOT / "docs/J3_LUNA_5_6_HUMAN_ADJUDICATION.json").read_text())
    assert len(reference["cases"]) == 27 and len(reference["excluded_cases"]) == 8
    assert reference["cases"] == [
        {k: c[k] for k in ("id", "human_classification", "human_flags")} for c in source["cases"]
    ]
    assert {c["id"] for c in reference["cases"]}.isdisjoint(
        c["id"] for c in reference["excluded_cases"]
    )
    assert [c["id"] for c in reference["excluded_cases"]] == [
        c["id"] for c in source["excluded_cases"]
    ]
    assert all(set(c) == {"id", "human_classification", "human_flags"} for c in reference["cases"])
    assert (
        j4.raw_hash(j4.ROOT / "docs/J3_LUNA_5_6_HUMAN_ADJUDICATION.json")
        == j4.SOURCE_REFERENCE_SHA256
    )


async def test_full_mock_schedule_hash_journal_before_dispatch_and_no_gateway():
    events, seen = [], []

    def handler(request):
        assert events[-1][0] == "start"
        start = events[-1][1]
        actual = json.loads(request.content)
        assert start["payload_sha256"] == j4.payload_hash(actual)
        assert start["experiment_id"] == j4.EXPERIMENT
        assert start["profile_id"] == j4.PROFILE_ID
        assert start["requested_model"] == actual["model"] == "gpt-6-luna"
        assert start["sequence"] == len(seen) + 1
        assert start["fixture_id"] == start["id"]
        assert start["utc_start"]
        seen.append(actual)
        return response()

    report = await j4.observe_offline(
        lambda *event: events.append(event), httpx.MockTransport(handler)
    )
    assert report["http_call_count"] == report["valid_assessment_count"] == len(seen) == 44
    assert report["retry_count"] == report["gateway_executions"] == 0
    assert Counter(e[1]["phase"] for e in events if e[0] == "start") == {"fixture": 35, "repeat": 9}
    assert [e[0] for e in events] == ["start", "result"] * 44
    first = report["assessments"][0]["telemetry"]
    assert first["system_fingerprint"] == "synthetic-fingerprint"
    assert first["service_tier"] == "default"
    assert first["reasoning_tokens"] == 4


@pytest.mark.parametrize(
    ("kind", "category", "fatal"),
    [
        ("mismatch", "RESPONSE_NOT_VALIDATED", "RETURNED_MODEL_MISMATCH"),
        ("missing", "RESPONSE_NOT_VALIDATED", "OBSERVER_EVIDENCE_FAILURE"),
        ("empty", "PARSEABLE_BUT_WIRE_INVALID", None),
        ("malformed", "MALFORMED_SEMANTIC_JSON", None),
        ("length", "INCOMPLETE_MAX_TOKENS", None),
        ("refusal", "PROVIDER_REFUSAL", None),
        ("no_content", "RESPONSE_NOT_VALIDATED", None),
        ("two_choices", "RESPONSE_NOT_VALIDATED", None),
        ("wrong_role", "RESPONSE_NOT_VALIDATED", None),
        ("http", "RESPONSE_NOT_VALIDATED", "PROVIDER_HTTP_FAILURE"),
        ("transport", "RESPONSE_NOT_VALIDATED", "TRANSPORT_FAILURE"),
        ("size", "RESPONSE_NOT_VALIDATED", "RESPONSE_SIZE_BOUND"),
    ],
)
async def test_failure_taxonomy_no_repair_no_retry_and_fatal_stop(kind, category, fatal):
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) > 1:
            return response()
        if kind == "transport":
            raise httpx.ConnectTimeout("synthetic")
        if kind == "http":
            return httpx.Response(429, json={"error": {"type": "rate_limit"}})
        if kind == "size":
            return httpx.Response(200, content=b"x" * 200001)
        if kind == "mismatch":
            return response(model="unexpected")
        if kind == "missing":
            return response(model=None)
        if kind == "empty":
            return response(wire={})
        if kind == "malformed":
            return response(content="not-json")
        if kind == "length":
            return response(finish="length", content="")
        if kind == "refusal":
            return response(content="", refusal="synthetic refusal")
        if kind == "no_content":
            return response(content="")
        body = response().json()
        if kind == "two_choices":
            body["choices"] *= 2
        if kind == "wrong_role":
            body["choices"][0]["message"]["role"] = "user"
        return httpx.Response(200, json=body)

    report = await j4.observe_offline(lambda *event: None, httpx.MockTransport(handler))
    assert report["assessments"][0]["result_category"] == category
    assert report["abort_reason"] == fatal
    assert len(seen) == (1 if fatal else 44)
    assert report["retry_count"] == 0
    assert report["assessments"][0]["assessment"] is None


async def test_failed_start_journal_dispatches_nothing():
    seen = []

    def fail(*args):
        raise OSError("synthetic disk failure")

    def handler(request):
        seen.append(request)
        return response()

    report = await j4.observe_offline(fail, httpx.MockTransport(handler))
    assert report["abort_reason"] == "EVIDENCE_WRITE_FAILURE" and not seen


async def test_request45_disarmed_request_and_mutated_payload_blocked():
    expected = j4.payload(j4.PROFILE_ID, j4.j3.engine._load_fixtures()[0])
    transport = j4.J4Transport(
        [expected] * 44,
        "synthetic",
        lambda: None,
        lambda: httpx.MockTransport(lambda r: response()),
    )
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="EVIDENCE_WRITE_FAILURE"):
        transport.arm(1)
    transport.journaled_sequence = 45
    transport.calls = 44
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="CALL_ACCOUNTING_VIOLATION"):
        transport.arm(45)
    request = httpx.Request(
        "POST",
        transport.profile.endpoint,
        json=expected,
        headers={"Authorization": "Bearer synthetic"},
    )
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="CALL_ACCOUNTING_VIOLATION"):
        await transport.handle_async_request(request)
    transport.calls = 0
    transport.journaled_sequence = 1
    transport.arm(1)
    request = httpx.Request(
        "POST", transport.profile.endpoint, json=expected | {"reasoning_effort": "high"}
    )
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="PAYLOAD_PROFILE_MISMATCH"):
        await transport.handle_async_request(request)
    assert transport.calls == 0


async def test_no_live_entrypoint():
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="LIVE_EXECUTION_NOT_AUTHORIZED"):
        await j4.observe_offline(lambda *args: None, object())


async def test_retry_configuration_is_rejected_before_dispatch():
    case = j4.j3.engine._load_fixtures()[0]
    transport = j4.J4Transport(
        [j4.payload(j4.PROFILE_ID, case)] * 44,
        "synthetic",
        lambda: None,
        lambda: httpx.MockTransport(lambda r: response()),
    )
    judge = LiveJudgeProvider(
        "https://api.openai.com/v1",
        "gpt-6-luna",
        "synthetic",
        openai_profile_id=j4.PROFILE_ID,
        transport=transport,
    )
    judge.client.max_attempts = 2
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="SHARED_EXPERIMENT_FREEZE_MISMATCH"):
        await j4.j3.run_experiment(
            j4.j3.engine._load_fixtures(), judge, transport, lambda *args: None, run_id="synthetic"
        )
    assert transport.calls == 0


def test_source_reference_mismatch_stops_without_repair(monkeypatch):
    monkeypatch.setattr(j4, "raw_hash", lambda p: "0" * 64)
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="FREEZE_OR_INSTRUMENT_MISMATCH"):
        j4.human_reference()


def test_profile_artifact_drift_is_rejected(monkeypatch):
    original = j4.profile_artifact
    monkeypatch.setattr(j4, "profile_artifact", lambda: original() | {"reasoning_effort": "high"})
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="FREEZE_OR_INSTRUMENT_MISMATCH"):
        j4.verify_instrument()


def test_missing_optional_telemetry_stays_null():
    body = response().json()
    body.pop("system_fingerprint")
    body.pop("service_tier")
    metadata, structural, state = j4.J4Observer().observe(
        httpx.Response(200, json=body), "synthetic", j4.select_profile(j4.PROFILE_ID)
    )
    assert metadata["system_fingerprint"] is metadata["service_tier"] is None
    assert state == "COMPLETE" and structural["wire_validation"] == "PASS"


def test_runtime_configuration_explicit_profile_and_label_leakage_boundary():
    from civicgate.config import providers
    from civicgate.runtime_config import InMemoryConfiguration, InMemorySecretProvider

    _, judge = providers(
        InMemoryConfiguration(
            {
                "CIVICGATE_JUDGE_PROVIDER": "openai_compatible",
                "CIVICGATE_JUDGE_BASE_URL": "https://api.openai.com/v1",
                "CIVICGATE_JUDGE_MODEL": "gpt-6-luna",
                "CIVICGATE_JUDGE_PROFILE": j4.PROFILE_ID,
            }
        ),
        InMemorySecretProvider({"CIVICGATE_OPENAI_JUDGE_API_KEY": "synthetic-only"}),
    )
    assert judge.openai_profile.profile_id == j4.PROFILE_ID
    case = j4.j3.engine._load_fixtures()[0]
    contaminated = case | {
        "human_classification": "DO_NOT_SEND",
        "disposition": "DO_NOT_SEND",
        "severity": "DO_NOT_SEND",
        "prior_denials": 123,
        "expected_decision": "DO_NOT_SEND",
        "adapter_state": "DO_NOT_SEND",
    }
    assert j4.payload(j4.PROFILE_ID, contaminated) == j4.payload(j4.PROFILE_ID, case)


@pytest.mark.parametrize(
    ("flags", "env_value", "level"),
    [([], None, 0), (["-O"], None, 1), (["-OO"], None, 2), ([], "1", 1), ([], "2", 2)],
)
def test_optimizer_prompt_schema_payload_and_reference_parity(flags, env_value, level):
    code = """import json,sys
from scripts import prepare_j4_gpt6_luna as j
try:
 j.select_profile("unknown")
except j.j3.engine.BenchmarkAbort:
 blocked=True
else:
 blocked=False
print(json.dumps(dict(level=sys.flags.optimize, invariants=j.historical_invariants(), profile=j.profile_artifact(), contract=j.contract_artifact(), reference=j.human_reference(), payloads=[j.payload(j.PROFILE_ID,c) for c in j.j3.engine._load_fixtures()], unknown_blocked=blocked)))
"""
    env = dict(os.environ)
    env.pop("PYTHONOPTIMIZE", None)
    if env_value:
        env["PYTHONOPTIMIZE"] = env_value
    env["PYTHONPATH"] = os.pathsep.join(
        [str(j4.ROOT / "src"), str(j4.ROOT), env.get("PYTHONPATH", "")]
    )
    proc = subprocess.run(
        [sys.executable, *flags, "-c", code],
        env=env,
        cwd=j4.ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    result = json.loads(proc.stdout)
    assert result["level"] == level and result["unknown_blocked"]
    assert result["invariants"] == j4.historical_invariants()
    assert result["profile"] == j4.profile_artifact()
    assert result["contract"] == j4.contract_artifact()
    assert result["reference"] == j4.human_reference()
    assert result["payloads"] == [
        j4.payload(j4.PROFILE_ID, c) for c in j4.j3.engine._load_fixtures()
    ]
