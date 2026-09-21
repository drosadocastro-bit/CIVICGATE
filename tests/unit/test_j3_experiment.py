"""Synthetic mechanical comparison only; no historical provider outputs are replayed."""

import json

import httpx
import pytest

from civicgate.llm.live import LiveJudgeProvider
from scripts import run_j3_amendment_001 as old
from scripts import run_j3_experiment as shared
from scripts.judge_experiment_observers import observer_for

VALID = {"classification": "IN_SCOPE", "confidence": 0.91, "flags": ["NONE"]}
LONG = "INVALID_RATIONALE_DO_NOT_RETAIN_" * 25
SECRET = "synthetic-credential-for-offline-tests"
PROFILES = tuple(shared.PROFILES)


@pytest.fixture(autouse=True)
def forbid_external_boundaries(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network, credential, Gateway or adapter access")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setattr(shared.parent.WindowsDPAPIStore, "get_secret", forbidden)
    monkeypatch.setattr(shared.engine, "_preflight", forbidden)
    monkeypatch.setattr(shared.engine, "_run", forbidden)
    monkeypatch.setattr(shared.engine.Gateway, "call", forbidden)
    monkeypatch.setattr(shared.engine.USAspending, "__init__", forbidden)


def response(profile, kind="valid", *, status=200, model=None):
    wire = VALID | {"rationale": LONG} if kind == "invalid" else {} if kind == "empty" else VALID
    text = "not JSON" if kind == "malformed" else json.dumps(wire)
    model = profile.model if model is None else model
    if profile.protocol == "anthropic_messages":
        body = {
            "model": model,
            "stop_reason": {"length": "max_tokens", "refusal": "refusal", "unknown": "other"}.get(
                kind, "end_turn"
            ),
            "content": [
                {"type": "thinking", "thinking": "HIDDEN_NOT_RETAINED"},
                {"type": "text", "text": text},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 34},
        }
    else:
        body = {
            "model": model,
            "choices": [
                {
                    "finish_reason": {
                        "length": "length",
                        "unknown": "other",
                        "filter": "content_filter",
                    }.get(kind, "stop"),
                    "message": {
                        "content": text,
                        "refusal": "REFUSAL_NOT_RETAINED" if kind == "refusal" else None,
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 34,
                "total_tokens": 46,
                "completion_tokens_details": {"reasoning_tokens": 7},
            },
        }
    if kind == "missing_model":
        body.pop("model")
    return httpx.Response(status, json=body)


def harness(name, responder=None, verify=lambda: None):
    profile = shared.PROFILES[name]
    fixtures = shared.engine._load_fixtures()
    by_id = {c["id"]: c for c in fixtures}
    payloads = [
        shared.parent.payload(profile, by_id[e["id"]]) for e in shared.engine._schedule(fixtures)
    ]
    events, seen = [], []

    def handler(request):
        ordinal = len(seen) + 1
        assert events[-1][0] == "start"
        assert events[-1][1]["sequence"] == ordinal
        assert len(events) == 2 * ordinal - 1
        assert json.loads(request.content) == payloads[len(seen)]
        assert str(request.url) == profile.endpoint
        seen.append(request)
        return responder(ordinal, request) if responder else response(profile)

    transport = shared.ExperimentTransport(
        profile, payloads, SECRET, verify, lambda: httpx.MockTransport(handler)
    )
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        SECRET,
        protocol=profile.protocol,
        provider_name=profile.provider,
        timeout=30,
        transport=transport,
    )
    judge.client.max_attempts = 1

    def persist(stage, row):
        events.append((stage, row))

    return fixtures, judge, transport, seen, persist, events


async def run(parts):
    fixtures, judge, transport, _, persist, _ = parts
    return await shared.run_experiment(fixtures, judge, transport, persist, run_id="synthetic-run")


@pytest.mark.parametrize("name", PROFILES)
async def test_full_schedule_journal_order_payloads_and_request45(name):
    parts = harness(name)
    report = await run(parts)
    fixtures, judge, transport, seen, _, events = parts
    assert report["http_call_count"] == len(seen) == 44
    assert report["valid_assessment_count"] == 44
    assert report["retry_count"] == 0 and judge.client.max_attempts == 1
    assert report["gateway_executions"] == 0
    assert [stage for stage, _ in events] == ["start", "result"] * 44
    assert [
        {k: row[k] for k in ("id", "phase", "observation")}
        for stage, row in events
        if stage == "start"
    ] == shared.engine._schedule(fixtures)
    for sequence, (_stage, start) in enumerate(events[::2], 1):
        assert set(start) == {
            "run_id",
            "sequence",
            "id",
            "phase",
            "observation",
            "prior_http_count",
            "expected_request_ordinal",
            "utc_start",
        }
        assert start["run_id"] == "synthetic-run" and start["utc_start"].endswith("+00:00")
        assert start["prior_http_count"] == sequence - 1
        assert start["expected_request_ordinal"] == start["sequence"] == sequence
        assert events[sequence * 2 - 1][1] == report["assessments"][sequence - 1]
    emitted = json.loads(seen[0].content)
    assert emitted[transport.profile.token_field] == 512
    assert (
        "temperature" not in emitted
        and "top_p" not in emitted
        and "reasoning_effort" not in emitted
    )
    if name == "j2-luna":
        assert "max_tokens" not in emitted
        assert emitted["response_format"] == {"type": "json_object"}
        assert emitted["messages"][0]["content"] == shared.engine._prompt()
    else:
        assert "max_completion_tokens" not in emitted
        assert emitted["system"] == shared.engine._prompt()
    with pytest.raises(shared.engine.BenchmarkAbort, match="CALL_BUDGET_EXHAUSTED"):
        await transport.handle_async_request(seen[-1])
    assert len(seen) == 44


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize(
    ("kind", "category"),
    [
        ("invalid", "PARSEABLE_BUT_WIRE_INVALID"),
        ("empty", "PARSEABLE_BUT_WIRE_INVALID"),
        ("malformed", "MALFORMED_SEMANTIC_JSON"),
        ("length", "INCOMPLETE_MAX_TOKENS"),
        ("refusal", "PROVIDER_REFUSAL"),
        ("unknown", "RESPONSE_NOT_VALIDATED"),
    ],
)
async def test_nonfatal_failure_advances_after_three_and_never_repairs(name, kind, category):
    profile = shared.PROFILES[name]
    parts = harness(name, lambda n, _: response(profile, kind if n <= 3 else "valid"))
    report = await run(parts)
    assert report["http_call_count"] == 44 and report["schema_failure_count"] == 3
    assert report["valid_assessment_count"] == 41 and report["abort_reason"] is None
    assert report["metrics"]["engineering_reference_agreement"]["denominator"] == 32
    for row in report["assessments"][:3]:
        assert row["result_category"] == category and row["assessment"] is None
        if kind in {"length", "refusal", "unknown"}:
            assert row["structural_evidence"]["wire_validation"] == "NOT_EVALUABLE"
            assert row["structural_evidence"]["json_parseable"] is None
        if kind == "invalid":
            assert row["structural_evidence"]["rationale_length"] == len(LONG)
            assert row["structural_evidence"]["validation_errors"][0]["loc"] == ["rationale"]
            assert row["structural_evidence"]["validation_errors"][0]["type"] == "string_too_long"
    for forbidden in (LONG, "HIDDEN_NOT_RETAINED", "REFUSAL_NOT_RETAINED", SECRET):
        assert forbidden not in json.dumps(report)


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize(
    ("kind", "fatal"),
    [
        ("http", "PROVIDER_HTTP_FAILURE"),
        ("transport", "TRANSPORT_FAILURE"),
        ("model", "RETURNED_MODEL_MISMATCH"),
        ("size", "RESPONSE_SIZE_BOUND"),
        ("observer", "OBSERVER_EVIDENCE_FAILURE"),
        ("metadata_bound", "OBSERVER_EVIDENCE_FAILURE"),
    ],
)
async def test_fatal_stops_without_retry(name, kind, fatal, monkeypatch):
    profile = shared.PROFILES[name]

    def respond(n, request):
        if kind == "transport":
            raise httpx.ReadTimeout("synthetic", request=request)
        if kind == "size":
            return httpx.Response(200, content=b"x" * 200_001)
        if kind == "metadata_bound":
            body = response(profile).json()
            text = json.dumps({**VALID, **{f"field_{i}": i for i in range(65)}})
            if name == "j3-sonnet":
                body["content"][1]["text"] = text
            else:
                body["choices"][0]["message"]["content"] = text
            return httpx.Response(200, json=body)
        return response(
            profile,
            status=429 if kind == "http" else 200,
            model="wrong-model" if kind == "model" else profile.model,
        )

    parts = harness(name, respond)
    if kind == "observer":

        def broken(*args):
            raise ValueError("do not persist exception contents")

        monkeypatch.setattr(parts[2].observer, "observe", broken)
    report = await run(parts)
    assert report["http_call_count"] == len(parts[3]) == 1
    assert report["abort_reason"] == fatal and report["not_attempted_count"] == 43
    assert report["valid_assessment_count"] == 0
    assert report["assessments"][0]["assessment"] is None
    assert len(parts[5]) == 2


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("stage", ["start", "result"])
async def test_evidence_write_failure_prevents_next_dispatch(name, stage):
    parts = harness(name)

    def persist(kind, row):
        if kind == stage:
            raise OSError("synthetic disk full")
        parts[5].append((kind, row))

    report = await shared.run_experiment(
        parts[0], parts[1], parts[2], persist, run_id="synthetic-run"
    )
    assert report["abort_reason"] == "EVIDENCE_WRITE_FAILURE"
    assert len(parts[3]) == (0 if stage == "start" else 1)


@pytest.mark.parametrize("name", PROFILES)
async def test_freeze_drift_and_unjournaled_dispatch_are_blocked(name):
    parts = harness(name)
    request = httpx.Request("POST", parts[2].profile.endpoint, json=parts[2].payloads[0])
    with pytest.raises(shared.engine.BenchmarkAbort, match="CALL_ACCOUNTING"):
        await parts[2].handle_async_request(request)

    def drift():
        raise ValueError("drift")

    parts[2].verify = drift
    report = await run(parts)
    assert report["abort_reason"] == "FREEZE_OR_INSTRUMENT_MISMATCH"
    assert len(parts[3]) == len(parts[5]) == 0


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("mutation", ["endpoint", "payload", "credential"])
async def test_request_boundary_guard(name, mutation):
    parts = harness(name)
    transport = parts[2]
    profile = transport.profile
    headers = (
        {"x-api-key": SECRET} if name == "j3-sonnet" else {"authorization": "Bearer " + SECRET}
    )
    if mutation == "credential":
        headers = {}
    request = httpx.Request(
        "POST",
        "https://example.invalid" if mutation == "endpoint" else profile.endpoint,
        json={} if mutation == "payload" else transport.payloads[0],
        headers=headers,
    )
    transport.arm(1)
    with pytest.raises(
        shared.engine.BenchmarkAbort,
        match={
            "endpoint": "ENDPOINT_MISMATCH",
            "payload": "PAYLOAD_PROFILE_MISMATCH",
            "credential": "CREDENTIAL_MISMATCH",
        }[mutation],
    ):
        await transport.handle_async_request(request)
    assert transport.calls == len(parts[3]) == 0


@pytest.mark.parametrize(
    "kind", ["valid", "invalid", "empty", "malformed", "length", "refusal", "unknown"]
)
def test_bounded_observer_parity_for_synthetic_native_responses(kind):
    sonnet, luna = shared.PROFILES["j3-sonnet"], shared.PROFILES["j2-luna"]
    anthropic = response(sonnet, kind)
    _, a, state_a = observer_for(sonnet).observe(anthropic, SECRET, sonnet)
    _, b, state_b = observer_for(luna).observe(response(luna, kind), SECRET, luna)
    assert a == old.structural_evidence(anthropic, SECRET)
    assert state_a == state_b
    # Unknown native stops have the same unavailable wire; extraction diagnostics
    # retain native codes rather than pretending provider envelopes are identical.
    if kind != "unknown":
        assert a == b
    else:
        assert a["wire_validation"] == b["wire_validation"] == "NOT_EVALUABLE"


async def test_sonnet_execution_matches_historical_mechanics_and_scoring():
    profile = shared.PROFILES["j3-sonnet"]

    def respond(n, request):
        return response(
            profile, {1: "invalid", 2: "malformed", 3: "length", 4: "refusal"}.get(n, "valid")
        )

    parts = harness("j3-sonnet", respond)
    new = await run(parts)
    requests, events = [], []

    def handler(request):
        requests.append(request)
        return respond(len(requests), request)

    transport = old.AmendedTransport(
        parts[2].payloads, SECRET, lambda: None, lambda: httpx.MockTransport(handler)
    )
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        SECRET,
        protocol=profile.protocol,
        provider_name=profile.provider,
        transport=transport,
    )
    judge.client.max_attempts = 1
    previous = await old.run_amended(
        parts[0], judge, transport, lambda *event: events.append(event)
    )
    for key in (
        "valid_assessment_count",
        "schema_failure_count",
        "not_attempted_count",
        "observation_axis_counts",
        "abort_reason",
        "http_call_count",
        "retry_count",
    ):
        assert new[key] == previous[key]
    # Wall-clock duration is observed afresh, not part of scoring equivalence.
    assert {k: v for k, v in new["metrics"].items() if k != "latency_ms"} == {
        k: v for k, v in previous["metrics"].items() if k != "latency_ms"
    }
    assert len(events) == len(parts[5]) == 88 and len(requests) == 44
    for new_row, old_row in zip(new["assessments"], previous["assessments"], strict=True):
        for key in (
            "id",
            "phase",
            "observation",
            "outcome",
            "structural_evidence",
            "observation_axes",
            "telemetry",
        ):
            assert new_row[key] == old_row[key]
        assert new_row["assessment"] == old_row["j3"]


@pytest.mark.parametrize("name", PROFILES)
def test_plan_profile_and_binding_do_not_read_credentials(name):
    plan = shared.plan(name)
    assert plan["shared"] == shared.asdict(shared.SPEC)
    assert len(plan["schedule"]) == 44
    assert plan["profile"]["secret_name"] == (
        "CIVICGATE_ANTHROPIC_JUDGE_API_KEY"
        if name == "j3-sonnet"
        else "CIVICGATE_OPENAI_JUDGE_API_KEY"
    )
    assert "CIVICGATE_JUDGE_API_KEY" not in json.dumps(plan)
    with pytest.raises(shared.engine.BenchmarkAbort):
        shared.parent.select_profile("generic")


@pytest.mark.parametrize("name", PROFILES)
async def test_execute_uses_only_owned_binding_and_exclusive_journals(name, tmp_path, monkeypatch):
    profile = shared.PROFILES[name]
    output = tmp_path / "result.json"
    freeze = {"run_id": "synthetic-execute", "output": str(output), "plan": shared.plan(name)}
    monkeypatch.setattr(shared, "verify_execution", lambda _: profile)
    lookups, requests = [], []

    class SyntheticSecrets:
        def get_secret(self, key):
            lookups.append(key)
            return SECRET if key == profile.secret_name else None

    def handle(request):
        n = len(requests) + 1
        start = json.loads((tmp_path / f"observation-{n:02d}-start.json").read_text())
        assert start["expected_request_ordinal"] == n
        if n > 1:
            assert (tmp_path / f"observation-{n - 1:02d}-result.json").exists()
        requests.append(request)
        return response(profile)

    report = await shared.execute(freeze, SyntheticSecrets(), lambda: httpx.MockTransport(handle))
    assert lookups == [profile.secret_name] and len(requests) == 44
    assert len(list(tmp_path.glob("observation-*-start.json"))) == 44
    assert len(list(tmp_path.glob("observation-*-result.json"))) == 44
    assert json.loads(output.read_text()) == report
    with pytest.raises(shared.engine.BenchmarkAbort, match="EXISTING_RUN_OUTPUT"):
        await shared.execute(freeze, SyntheticSecrets(), lambda: httpx.MockTransport(handle))
    assert lookups == [profile.secret_name] and len(requests) == 44


def test_openai_native_filter_and_usage_are_preserved():
    profile = shared.PROFILES["j2-luna"]
    metadata, structural, state = observer_for(profile).observe(
        response(profile, "filter"), SECRET, profile
    )
    assert state == "REFUSED" and metadata["finish_reason"] == "content_filter"
    assert metadata["reasoning_tokens"] == 7 and metadata["total_tokens"] == 46
    assert structural["json_parseable"] is None


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("status", [400, 401, 403, 500])
async def test_all_http_rejection_classes_are_fatal(name, status):
    parts = harness(name, lambda *_: response(shared.PROFILES[name], status=status))
    report = await run(parts)
    assert report["abort_reason"] == "PROVIDER_HTTP_FAILURE"
    assert report["http_call_count"] == 1 and report["retry_count"] == 0


@pytest.mark.parametrize("name", PROFILES)
async def test_all_44_wire_invalid_never_enter_canonical_metrics(name):
    parts = harness(name, lambda *_: response(shared.PROFILES[name], "invalid"))
    report = await run(parts)
    assert report["http_call_count"] == report["schema_failure_count"] == 44
    assert report["valid_assessment_count"] == 0 and report["abort_reason"] is None
    assert report["metrics"]["engineering_reference_agreement"]["denominator"] == 0
    assert report["metrics"]["engineering_reference_agreement"]["value"] is None
    assert all(row["assessment"] is None for row in report["assessments"])


@pytest.mark.parametrize("name", PROFILES)
async def test_accounting_mismatch_stops_before_any_start(name):
    parts = harness(name)
    parts[2].calls = 1
    report = await run(parts)
    assert report["abort_reason"] == "CALL_ACCOUNTING_VIOLATION"
    assert len(parts[3]) == len(parts[5]) == 0


@pytest.mark.parametrize("name", PROFILES)
async def test_missing_owned_secret_never_falls_back_or_constructs_transport(
    name, tmp_path, monkeypatch
):
    profile = shared.PROFILES[name]
    freeze = {
        "run_id": "synthetic-missing",
        "output": str(tmp_path / "result.json"),
        "plan": shared.plan(name),
    }
    monkeypatch.setattr(shared, "verify_execution", lambda _: profile)
    lookups = []

    class SyntheticSecrets:
        def get_secret(self, key):
            lookups.append(key)
            return None if key == profile.secret_name else SECRET

    def forbidden():
        pytest.fail("Transport must not be constructed without the owned credential")

    with pytest.raises(shared.engine.BenchmarkAbort, match="PROFILE_CREDENTIAL_UNAVAILABLE"):
        await shared.execute(freeze, SyntheticSecrets(), forbidden)
    assert lookups == [profile.secret_name]


@pytest.mark.parametrize("name", PROFILES)
def test_verify_execution_rejects_plan_raw_hash_or_head_drift(name, monkeypatch):
    frozen = {
        "plan": shared.plan(name),
        "raw_source_sha256": shared.raw_hashes(),
        "head": "synthetic-head",
    }
    monkeypatch.setattr(shared.historical, "verify_manifest", lambda: None)
    monkeypatch.setattr(shared.engine, "_git", lambda *args: b"synthetic-head")
    assert shared.verify_execution(frozen) == shared.PROFILES[name]
    for key in ("plan", "raw_source_sha256", "head"):
        changed = frozen | {key: {} if key != "head" else "wrong-head"}
        with pytest.raises((shared.engine.BenchmarkAbort, KeyError)):
            shared.verify_execution(changed)


@pytest.mark.parametrize("name", PROFILES)
def test_observer_omitted_usage_is_null_and_http_error_fields_are_bounded(name):
    profile = shared.PROFILES[name]
    body = response(profile).json()
    body.pop("usage")
    metadata, _, _ = observer_for(profile).observe(httpx.Response(200, json=body), SECRET, profile)
    assert all(
        metadata.get(k) is None
        for k in ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens")
    )
    error = httpx.Response(
        400,
        json={
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_parameter",
                "param": "model",
                "message": "SENSITIVE_ERROR_NOT_RETAINED",
            }
        },
    )
    metadata, structural, _ = observer_for(profile).observe(error, SECRET, profile)
    assert metadata["error_type"] == "invalid_request_error"
    assert "SENSITIVE_ERROR_NOT_RETAINED" not in json.dumps([metadata, structural])


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize(
    "identity",
    ["expected", "wrong", "missing", "null", "wrong_type", "unsafe", "invalid_name", "nonobject"],
)
async def test_prospective_identity_is_required_despite_correct_requested_model(name, identity):
    profile = shared.PROFILES[name]

    def respond(n, request):
        # Correct configuration and endpoint never establish returned identity.
        assert json.loads(request.content)["model"] == profile.model
        assert str(request.url) == profile.endpoint
        body = response(profile).json()
        if identity == "missing":
            body.pop("model")
            body["metadata"] = {"requested_model": profile.model, "model": profile.model}
        elif identity == "nonobject":
            body = [body]
        elif identity != "expected":
            body["model"] = {
                "wrong": "different-model",
                "null": None,
                "wrong_type": {"model": profile.model},
                "unsafe": SECRET,
                "invalid_name": "not a safe identifier",
            }[identity]
        return httpx.Response(200, json=body)

    parts = harness(name, respond)
    report = await run(parts)
    if identity == "expected":
        assert report["abort_reason"] is None
        assert len(parts[3]) == report["http_call_count"] == report["valid_assessment_count"] == 44
    else:
        fatal = "RETURNED_MODEL_MISMATCH" if identity == "wrong" else "OBSERVER_EVIDENCE_FAILURE"
        assert report["abort_reason"] == fatal
        assert report["assessments"][0]["experiment_fatal_reason"] == fatal
        assert report["valid_assessment_count"] == 0
        assert report["assessments"][0]["assessment"] is None
        assert report["not_attempted_count"] == 43
        assert len(parts[3]) == report["http_call_count"] == 1
        assert [stage for stage, _ in parts[5]] == ["start", "result"]
        assert parts[5][1][1] == report["assessments"][0]
        start = parts[5][0][1]
        assert start["prior_http_count"] == 0
        assert start["expected_request_ordinal"] == start["sequence"] == 1
    assert report["retry_count"] == report["gateway_executions"] == 0
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize("name", PROFILES)
async def test_missing_identity_is_not_inferred_from_previous_correct_response(name):
    profile = shared.PROFILES[name]
    parts = harness(name, lambda n, _: response(profile, "valid" if n == 1 else "missing_model"))
    report = await run(parts)
    assert report["abort_reason"] == "OBSERVER_EVIDENCE_FAILURE"
    assert report["http_call_count"] == len(parts[3]) == 2
    assert report["valid_assessment_count"] == 1
    assert report["assessments"][1]["telemetry"]["returned_model"] is None
    assert report["assessments"][1]["assessment"] is None
    assert [stage for stage, _ in parts[5]] == ["start", "result"] * 2
    assert parts[5][-1][1] == report["assessments"][1]
    assert parts[5][2][1]["prior_http_count"] == 1
    assert parts[5][2][1]["expected_request_ordinal"] == 2
    assert report["retry_count"] == report["gateway_executions"] == 0


@pytest.mark.parametrize("name", PROFILES)
def test_plan_freezes_prospective_identity_policy(name):
    policy = shared.plan(name)["returned_model_identity"]
    assert policy["missing_null_unavailable_or_unsafe"] == "OBSERVER_EVIDENCE_FAILURE"
    assert policy["conflicting"] == "RETURNED_MODEL_MISMATCH"
