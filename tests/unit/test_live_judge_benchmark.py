"""Offline regression coverage for the private, frozen J2 instrument."""

import gzip
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "live_benchmark", Path(__file__).resolve().parents[2] / "scripts/run_live_judge_benchmark.py"
)
assert SPEC and SPEC.loader
b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b)


def row(
    outcome="VALID",
    *,
    case_id="retrieved-injection",
    phase="fixture",
    classification="IN_SCOPE",
    confidence=0.9,
):
    return {
        "id": case_id,
        "phase": phase,
        "observation": 1,
        "outcome": outcome,
        "j1": {"classification": "IN_SCOPE"},
        "j2": {"classification": classification, "confidence": confidence}
        if outcome == "VALID"
        else None,
        "error": {"code": "MALFORMED_PROVIDER_RESPONSE" if outcome == "SCHEMA_FAILURE" else None},
        "latency_ms": None,
        "telemetry": {},
    }


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (["VALID", "VALID"], "COMPLETED_ALL_ASSESSMENTS_VALID"),
        (["VALID", "PROVIDER_FAILURE"], "PARTIAL_PROVIDER_FAILURE"),
        (["PROVIDER_FAILURE"] * 3, "NO_VALID_ASSESSMENTS"),
        (["VALID", "SCHEMA_FAILURE"], "PARTIAL_PROVIDER_FAILURE"),
        (["VALID", "NOT_ATTEMPTED"], "BENCHMARK_ABORTED"),
    ],
)
def test_status_uses_assessment_validity_not_loop_completion(outcomes, expected):
    report = b._summarize([row(o) for o in outcomes])
    assert report["status"] == expected
    assert sum(report["terminal_counts"].values()) == len(outcomes)


def test_all_terminal_categories_reconcile_without_double_counting_malformed():
    report = b._summarize([row(o) for o in b.OUTCOMES])
    assert report["intended_assessment_count"] == 6
    assert report["malformed_response_count"] == report["schema_failure_count"] == 1
    assert all(count == 1 for count in report["terminal_counts"].values())
    assert report["metrics"]["tokens"]["total_tokens"]["sum_observed"] is None


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (["PROVIDER_FAILURE"] * 3, "NOT_EVALUABLE_PROVIDER_FAILURE"),
        (["VALID", "TRANSPORT_FAILURE", "VALID"], "NOT_EVALUABLE_PROVIDER_FAILURE"),
        (["VALID", "SCHEMA_FAILURE", "VALID"], "NOT_EVALUABLE_SCHEMA_FAILURE"),
        (["VALID"] * 3, "SEMANTIC_STABLE"),
        (["VALID", "NOT_ATTEMPTED", "VALID"], "NOT_EVALUABLE_INCOMPLETE_RUN"),
    ],
)
def test_repeated_errors_are_never_semantically_stable(outcomes, expected):
    assert b._repeat_status([row(o, phase="repeat") for o in outcomes]) == expected


def test_repeat_confidence_difference_is_variable_under_exact_frozen_rule():
    assert b._repeat_status([row(confidence=c) for c in (0.9, 0.9, 0.91)]) == "SEMANTIC_VARIABLE"


@pytest.mark.parametrize(
    ("outcome", "classification", "expected"),
    [
        ("PROVIDER_FAILURE", "IN_SCOPE", "NOT_EVALUABLE"),
        ("SCHEMA_FAILURE", "IN_SCOPE", "NOT_EVALUABLE"),
        ("VALID", "POSSIBLE_AUTHORITY_OVERREACH", "PASS"),
        ("VALID", "IN_SCOPE", "FAIL"),
    ],
)
def test_injection_has_three_outcomes(outcome, classification, expected):
    report = b._summarize([row(outcome, classification=classification)])
    metric = report["metrics"]["injection_fixture_detection_under_tested_conditions"]
    assert (
        next(c for c in metric["cases"] if c["id"] == "retrieved-injection")["outcome"] == expected
    )
    assert metric["evaluated_count"] == int(outcome == "VALID")
    assert metric["not_evaluable_count"] == 6 - int(outcome == "VALID")
    assert metric["rate"] is None if outcome != "VALID" else metric["rate"] in (0, 1)


def test_reference_is_not_truth_and_excludes_invalid_and_repeat_observations():
    report = b._summarize([row(), row("PROVIDER_FAILURE"), row(phase="repeat")])
    assert report["metrics"]["engineering_reference_agreement"] == {
        "numerator": 1,
        "denominator": 1,
        "value": 1,
    }
    assert report["metrics"]["accuracy"] == "NOT_MEASURED_NO_INDEPENDENT_HUMAN_LABELS"


@pytest.mark.asyncio
async def test_gateway_preflight_counts_zero_judge_and_adapter_calls():
    report = await b._preflight(b._load_fixtures())
    assert report["all_passed"]
    assert len(report["cases"]) == 3
    for case in report["cases"]:
        assert case["decision"] == "DENY"
        assert case["evidence_class"] == "DETERMINISTIC_PREFLIGHT_DENIAL"
        assert case["judge_consulted"] is case["adapter_executed"] is False
        assert case["judge_calls"] == case["adapter_calls"] == 0


def body(*, content=None, finish="stop"):
    return {
        "model": "gpt-5.6-luna",
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "content": content
                    if content is not None
                    else json.dumps({"classification": "IN_SCOPE", "confidence": 0.9})
                },
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }


def setup(handler, fixtures=None):
    fixtures = fixtures or b._load_fixtures()
    by_id = {c["id"]: c for c in fixtures}
    payloads = [b._payload(by_id[e["id"]]) for e in b._schedule(fixtures)]
    transport = b.ObservedTransport(
        payloads,
        "test-credential",
        lambda: None,
        inner_factory=lambda: httpx.MockTransport(handler),
    )
    judge = b.LiveJudgeProvider(
        b.BASE_URL,
        b.MODEL,
        "test-credential",
        provider_name=b.PROVIDER,
        transport=transport,
        openai_profile_id="j2-luna",
    )
    judge.client.max_attempts = 1
    return fixtures, judge, transport


@pytest.mark.asyncio
async def test_real_provider_offline_44_calls_profile_contract_and_all_telemetry():
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["max_completion_tokens"] == 512
        assert not {"max_tokens", "temperature", "top_p", "reasoning_effort"} & payload.keys()
        assert payload["messages"][0]["content"] == b._prompt()
        return httpx.Response(200, json=body(), headers={"x-request-id": "req_test"})

    fixtures, judge, transport = setup(handler)
    report = await b._run(fixtures, judge, transport)
    assert report["http_call_count"] == len(seen) == 44
    assert report["valid_assessment_count"] == 44
    assert report["status"] == "COMPLETED_ALL_ASSESSMENTS_VALID"
    assert report["metrics"]["tokens"]["reasoning_tokens"] == {
        "sum_observed": 88,
        "exposed_observation_count": 44,
    }
    assert all(r["telemetry"]["wire_validation"] == "PASS" for r in report["assessments"])
    assert all(r["telemetry"]["request_id"] == "req_test" for r in report["assessments"])


@pytest.mark.asyncio
async def test_repeated_http_failures_stop_without_retries_and_preserve_partial_rows():
    fixtures, judge, transport = setup(
        lambda req: httpx.Response(
            429, json={"error": {"type": "rate_limit", "code": "rate_limit_exceeded"}}
        )
    )
    report = await b._run(fixtures, judge, transport)
    assert report["status"] == "BENCHMARK_ABORTED"
    assert report["http_call_count"] == report["provider_failure_count"] == 3
    assert report["not_attempted_count"] == 41
    assert report["valid_assessment_count"] == 0
    assert report["assessments"][0]["telemetry"]["error_code"] == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_authentication_failure_stops_on_first_call():
    fixtures, judge, transport = setup(
        lambda req: httpx.Response(401, json={"error": {"code": "invalid_api_key"}})
    )
    report = await b._run(fixtures, judge, transport)
    assert report["http_call_count"] == 1
    assert report["abort_reason"] == "AUTHENTICATION_REJECTED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected", "code"),
    [
        (body(content="{}"), "SCHEMA_FAILURE", "MALFORMED_PROVIDER_RESPONSE"),
        (body(finish="length"), "SCHEMA_FAILURE", "INCOMPLETE_OR_REFUSED_RESPONSE"),
        (body(), "VALID", None),
    ],
)
async def test_wire_and_completion_validity_using_real_provider(response, expected, code):
    fixtures, judge, transport = setup(lambda req: httpx.Response(200, json=response))
    result = await b._assess_case(judge, transport, fixtures[0], b._schedule(fixtures)[0])
    assert result["outcome"] == expected
    assert result["error"]["code"] == code
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_transport_error_is_not_an_http_rejection_and_missing_usage_is_null():
    def handler(request):
        raise httpx.ReadTimeout("intentionally private error message", request=request)

    fixtures, judge, transport = setup(handler)
    result = await b._assess_case(judge, transport, fixtures[0], b._schedule(fixtures)[0])
    assert result["outcome"] == "TRANSPORT_FAILURE"
    assert result["telemetry"]["http_status"] is None
    assert result["telemetry"]["total_tokens"] is None
    assert "intentionally private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["payload", "freeze", "endpoint", "budget"])
async def test_guard_stops_before_network(mismatch):
    sent = []
    fixtures, judge, transport = setup(
        lambda req: sent.append(req) or httpx.Response(200, json=body())
    )
    if mismatch == "payload":
        judge.model = "other-model"
    elif mismatch == "endpoint":
        judge.client.base_url = "https://example.org/v1"
    elif mismatch == "budget":
        transport.payloads = []
    else:

        def fail():
            raise b.BenchmarkAbort("FREEZE_MISMATCH")

        transport.verify = fail
    result = await b._assess_case(judge, transport, fixtures[0], b._schedule(fixtures)[0])
    assert result["abort_reason"]
    assert transport.calls == len(sent) == 0


def test_response_metadata_never_contains_reasoning_bodies_or_error_messages():
    response = body()
    response["choices"][0]["message"]["reasoning"] = "sensitive reasoning"
    response["error"] = {"message": "private message", "code": "error_code"}
    metadata = b._response_metadata(httpx.Response(200, json=response), "test-credential")
    assert "sensitive reasoning" not in json.dumps(metadata)
    assert "private message" not in json.dumps(metadata)
    assert metadata["error_code"] == "error_code"
    with pytest.raises(b.BenchmarkAbort, match="SECRET_IN_METADATA"):
        b._response_metadata(
            httpx.Response(401, json={"error": {"code": "test-credential"}}), "test-credential"
        )


def test_private_write_refuses_repository_and_secret(tmp_path):
    with pytest.raises(b.BenchmarkAbort, match="OUTSIDE_REPOSITORY"):
        b._write(b.ROOT / "artifacts/private-test.json", {})
    with pytest.raises(b.BenchmarkAbort, match="SECRET_IN_ARTIFACT"):
        b._write(tmp_path / "result.json", {"x": "test-credential"}, "test-credential")
    assert not (tmp_path / "result.json").exists()


def test_freeze_detects_file_change_and_encodes_exact_schedule(tmp_path, monkeypatch):
    # This tests freeze integrity, not the Windows-specific default store location.
    monkeypatch.setattr(b, "default_store_path", lambda: tmp_path / "synthetic-store.json")
    frozen = b._freeze(tmp_path / "result.json")
    assert frozen["expected_live_call_count"] == len(frozen["schedule"]) == 44
    assert len(frozen["fixture_ids"]) == 35
    assert frozen["retries"] == 0
    fingerprints = b._fingerprints()
    fingerprints["contract_sha256"] = "changed"
    monkeypatch.setattr(b, "_fingerprints", lambda: fingerprints)
    with pytest.raises(b.BenchmarkAbort, match="FREEZE_MISMATCH"):
        b._verify_freeze(frozen)


@pytest.mark.asyncio
async def test_compressed_provider_response_reaches_parser_without_double_decode():
    compressed = gzip.compress(json.dumps(body()).encode())
    fixtures, judge, transport = setup(
        lambda req: httpx.Response(200, content=compressed, headers={"content-encoding": "gzip"})
    )
    result = await b._assess_case(judge, transport, fixtures[0], b._schedule(fixtures)[0])
    assert result["outcome"] == "VALID"
    assert result["telemetry"]["wire_validation"] == "PASS"


@pytest.mark.asyncio
async def test_failure_telemetry_is_included_and_does_not_leak_to_next_call():
    calls = 0

    def handler(req):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200, json=body(content="{}"), headers={"x-request-id": "req_failed"}
            )
        return httpx.Response(200, json=body())

    fixtures, judge, transport = setup(handler)
    report = await b._run(fixtures, judge, transport)
    assert report["status"] == "PARTIAL_PROVIDER_FAILURE"
    assert report["malformed_response_count"] == 1
    assert report["valid_assessment_count"] == 43
    assert report["http_call_count"] == 44
    assert report["assessments"][0]["telemetry"]["request_id"] == "req_failed"
    assert report["assessments"][1]["telemetry"]["request_id"] is None
    assert report["metrics"]["tokens"]["total_tokens"]["sum_observed"] == 660


@pytest.mark.asyncio
async def test_model_refusal_is_not_a_valid_semantic_assessment():
    response = body()
    response["choices"][0]["message"]["refusal"] = "private refusal text"
    fixtures, judge, transport = setup(lambda req: httpx.Response(200, json=response))
    result = await b._assess_case(judge, transport, fixtures[0], b._schedule(fixtures)[0])
    assert result["outcome"] == "SCHEMA_FAILURE"
    assert result["telemetry"]["refusal_present"] is True
    assert "private refusal text" not in json.dumps(result)


def test_exclusive_run_marker_cannot_be_overwritten(tmp_path):
    path = tmp_path / "started.json"
    b._write(path, {"run_id": "first"}, exclusive=True)
    with pytest.raises(FileExistsError):
        b._write(path, {"run_id": "second"}, exclusive=True)
    assert json.loads(path.read_text())["run_id"] == "first"
