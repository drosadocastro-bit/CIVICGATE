"""Offline amendment guards, full schedule and unchanged legacy scoring/behavior."""

import importlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from civicgate.llm.live import LiveJudgeProvider
from scripts import run_j3_amendment_001 as amend

VALID = {"classification": "IN_SCOPE", "confidence": 0.95, "flags": ["NONE"]}
TOO_LONG = "OVERLONG_RATIONALE_SENTINEL_" * 30


@pytest.fixture(autouse=True)
def no_network_or_dpapi(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline amendment test attempted real network or DPAPI access")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setattr(amend.parent.WindowsDPAPIStore, "get_secret", forbidden)


def response(wire=VALID, *, stop="end_turn", status=200, model="claude-sonnet-5", text=None):
    return httpx.Response(
        status,
        json={
            "model": model,
            "stop_reason": stop,
            "content": [
                {"type": "thinking", "thinking": "NEVER_RETAIN_HIDDEN_BLOCK"},
                {"type": "text", "text": json.dumps(wire) if text is None else text},
            ],
            "usage": {"input_tokens": 12, "output_tokens": 34},
        },
    )


def harness(responder=None, verify=lambda: None):
    fixtures = amend.parent.engine._load_fixtures()
    schedule = amend.parent.engine._schedule(fixtures)
    by_id = {case["id"]: case for case in fixtures}
    profile = amend.parent.PROFILES["j3-sonnet"]
    payloads = [amend.parent.payload(profile, by_id[e["id"]]) for e in schedule]
    seen = []

    def handler(request):
        assert json.loads(request.content) == payloads[len(seen)]
        seen.append(request)
        return responder(len(seen), request) if responder else response()

    transport = amend.AmendedTransport(
        payloads, "synthetic-key", verify, lambda: httpx.MockTransport(handler)
    )
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        "synthetic-key",
        protocol=profile.protocol,
        provider_name=profile.provider,
        timeout=profile.timeout_seconds,
        transport=transport,
    )
    judge.client.max_attempts = 1
    events = []
    return fixtures, judge, transport, seen, lambda *event: events.append(event), events


async def test_three_consecutive_wire_failures_continue_through_exact_44_schedule():
    fixtures, judge, transport, seen, persist, events = harness(
        lambda n, _: response(VALID | {"rationale": TOO_LONG}) if n <= 3 else response()
    )
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert (
        report["completion_classification"]
        == "J3_AMEND_001_RUN_COMPLETE_WITH_NONVALIDATED_ASSESSMENTS"
    )
    assert report["valid_assessment_count"] == 41
    assert report["schema_failure_count"] == 3
    assert report["status"] == report["completion_classification"]
    assert report["http_call_count"] == len(seen) == 44
    assert report["retry_count"] == 0
    assert len(events) == 88
    assert [stage for stage, _ in events] == ["start", "result"] * 44
    assert [
        {k: row[k] for k in ("id", "phase", "observation")} for row in report["assessments"]
    ] == amend.parent.engine._schedule(fixtures)
    assert all(row["http_request_count"] == 1 for row in report["assessments"])
    for row in report["assessments"][:3]:
        assert row["j3"] is None
        meta = row["structural_evidence"]
        assert meta["rationale_length"] == len(TOO_LONG)
        assert meta["validation_errors"][0]["type"] == "string_too_long"
        candidates = meta["unvalidated_wire_semantic_fields"]
        assert candidates["label"] == "UNVALIDATED_WIRE_SEMANTIC_FIELDS"
        assert candidates["fields"] == VALID
        assert candidates["limitations"] == [
            "EXPLORATORY",
            "NON-AUTHORITATIVE",
            "NOT A JUDGESIGNAL",
        ]
        assert row["observation_axes"]["HTTP_SUCCESS"] is True
        assert row["observation_axes"]["JSON_PARSEABLE"] is True
        assert row["observation_axes"]["WIRE_VALID"] is False
        assert row["observation_axes"]["TYPED_ASSESSMENT_VALID"] is False
    assert TOO_LONG not in json.dumps(report)
    assert "NEVER_RETAIN_HIDDEN_BLOCK" not in json.dumps(report)
    assert report["metrics"]["engineering_reference_agreement"]["denominator"] == 32


@pytest.mark.parametrize(
    "kind", ["max_tokens", "refusal", "malformed_json", "unknown_stop", "missing_fields"]
)
async def test_each_nonfatal_response_failure_records_and_advances(kind):
    def responder(n, request):
        if n > 3:
            return response()
        if kind == "malformed_json":
            return response(text="not JSON")
        if kind == "missing_fields":
            return response({})
        return response(stop=kind)

    fixtures, judge, transport, seen, persist, _ = harness(responder)
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 44 and report["schema_failure_count"] == 3
    assert report["assessments"][3]["outcome"] == "VALID"
    assert report["not_attempted_count"] == 0
    assert all(row["j3"] is None for row in report["assessments"][:3])
    if kind == "max_tokens":
        axes = report["assessments"][0]["observation_axes"]
        assert axes["INCOMPLETE_MAX_TOKENS"] and axes["WIRE_VALID"] is None
        assert axes["JSON_PARSEABLE"] is None
        assert (
            report["assessments"][0]["structural_evidence"]["unvalidated_wire_semantic_fields"]
            is None
        )


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("classification", "PERMIT"),
        ("confidence", 1.1),
        ("confidence", -0.1),
        ("confidence", float("inf")),
        ("confidence", None),
        ("flags", ["INVENTED"]),
        ("flags", ["NONE"] * 9),
        ("flags", None),
    ],
)
def test_invalid_individual_candidate_is_omitted_without_relaxing_other_fields(field, bad):
    meta = amend.structural_evidence(response(VALID | {field: bad, "rationale": TOO_LONG}), "")
    candidate = meta["unvalidated_wire_semantic_fields"]
    assert field not in candidate["fields"]
    assert candidate["invalid_individual_fields"] == [field]
    assert meta["schema_valid_semantic_fields"] is None
    assert meta["wire_validation"] == "FAIL"
    assert TOO_LONG not in json.dumps(meta)


def test_missing_candidate_fields_are_not_defaulted_and_numeric_coercion_matches_contract():
    meta = amend.structural_evidence(response({"confidence": "0.5", "rationale": TOO_LONG}), "")
    assert meta["unvalidated_wire_semantic_fields"]["fields"] == {"confidence": 0.5}
    assert meta["wire_validation"] == "FAIL"


def test_valid_wire_is_separate_from_exploratory_candidate_storage():
    meta = amend.structural_evidence(response(VALID), "")
    assert meta["wire_validation"] == "PASS"
    assert meta["schema_valid_semantic_fields"]["flags"] == ["NONE"]
    assert meta["unvalidated_wire_semantic_fields"] is None


async def test_all_44_wire_failures_remain_failures_and_never_enter_canonical_metrics():
    fixtures, judge, transport, seen, persist, _ = harness(
        lambda *_: response(VALID | {"rationale": TOO_LONG})
    )
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 44 and report["valid_assessment_count"] == 0
    assert report["schema_failure_count"] == 44
    assert (
        report["completion_classification"]
        == "J3_AMEND_001_RUN_COMPLETE_WITH_NONVALIDATED_ASSESSMENTS"
    )
    assert report["metrics"]["engineering_reference_agreement"]["denominator"] == 0
    assert report["metrics"]["engineering_reference_agreement"]["value"] is None
    assert (
        report["metrics"]["injection_fixture_detection_under_tested_conditions"][
            "not_evaluable_count"
        ]
        == 6
    )
    with pytest.raises(amend.parent.engine.BenchmarkAbort, match="CALL_BUDGET_EXHAUSTED"):
        await transport.handle_async_request(seen[-1])
    assert len(seen) == 44


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_http_failures_abort_without_retry(status):
    fixtures, judge, transport, seen, persist, _ = harness(lambda *_: response(status=status))
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["http_call_count"] == 1
    assert report["abort_reason"] == "PROVIDER_HTTP_FAILURE"
    assert report["not_attempted_count"] == 43


async def test_transport_failure_aborts_without_retry():
    def fail(n, request):
        raise httpx.ReadTimeout("synthetic", request=request)

    fixtures, judge, transport, seen, persist, _ = harness(fail)
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["abort_reason"] == "TRANSPORT_FAILURE"


async def test_returned_model_mismatch_is_fatal_and_not_canonically_accepted():
    fixtures, judge, transport, seen, persist, _ = harness(
        lambda *_: response(model="different-model")
    )
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["abort_reason"] == "RETURNED_MODEL_MISMATCH"
    assert report["valid_assessment_count"] == 0
    assert report["assessments"][0]["j3"] is None
    assert report["assessments"][0]["observation_axes"]["WIRE_VALID"] is True


@pytest.mark.parametrize("boundary", ["endpoint", "model", "credential"])
async def test_request_security_guard_stops_before_dispatch(boundary):
    fixtures, judge, transport, seen, persist, _ = harness()
    if boundary == "endpoint":
        judge.client.base_url = "https://unapproved.example"
    elif boundary == "model":
        judge.model = "different-model"
    else:
        judge.api_key = "different-key"
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert not seen and report["http_call_count"] == 0
    assert report["abort_reason"] == "REQUEST_BOUNDARY_VIOLATION"


async def test_freeze_drift_aborts_before_next_dispatch():
    count = 0

    def verify():
        nonlocal count
        count += 1
        if count == 3:  # Two checks before first HTTP call; next pre-dispatch check fails.
            raise amend.parent.engine.BenchmarkAbort("FREEZE_MISMATCH")

    fixtures, judge, transport, seen, persist, _ = harness(verify=verify)
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["abort_reason"] == "FREEZE_OR_INSTRUMENT_MISMATCH"


@pytest.mark.parametrize("stage", ["start", "result"])
async def test_evidence_write_failure_prevents_any_next_request(stage):
    fixtures, judge, transport, seen, _, _ = harness()

    def persist(event, row):
        if event == stage:
            raise OSError("synthetic evidence failure")

    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == (0 if stage == "start" else 1)
    assert report["abort_reason"] == "EVIDENCE_WRITE_FAILURE"


@pytest.mark.parametrize("prior_count", [-1, 1, 44])
async def test_accounting_violation_prevents_dispatch(prior_count):
    fixtures, judge, transport, seen, persist, _ = harness()
    transport.calls = prior_count
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert not seen and report["abort_reason"] == "CALL_ACCOUNTING_VIOLATION"


async def test_observer_error_is_fatal(monkeypatch):
    def broken(*args):
        raise RuntimeError("synthetic observer failure")

    monkeypatch.setattr(amend, "structural_evidence", broken)
    fixtures, judge, transport, seen, persist, _ = harness()
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["abort_reason"] == "OBSERVER_EVIDENCE_FAILURE"
    assert report["valid_assessment_count"] == 0


async def test_legacy_j3_three_failure_stop_still_reproduces():
    fixtures, judge, transport, seen, _, _ = harness(lambda *_: response({}))
    report = await amend.parent.engine._run(fixtures, judge, transport)
    assert len(seen) == 3 and report["abort_reason"] == "CONSECUTIVE_INTEGRATION_FAILURES"
    assert report["not_attempted_count"] == 41


async def test_legacy_j2_unchanged_payload_and_three_failure_stop():
    fixtures = amend.parent.engine._load_fixtures()
    profile = amend.parent.PROFILES["j2-luna"]
    by_id = {c["id"]: c for c in fixtures}
    payloads = [
        amend.parent.payload(profile, by_id[e["id"]])
        for e in amend.parent.engine._schedule(fixtures)
    ]
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        assert payload == payloads[len(seen)]
        assert payload["max_completion_tokens"] == 512
        assert not {"temperature", "top_p", "max_tokens"} & payload.keys()
        seen.append(request)
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
        )

    transport = amend.parent.ProfileTransport(
        profile, payloads, "synthetic", lambda: None, lambda: httpx.MockTransport(handler)
    )
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        "synthetic",
        protocol=profile.protocol,
        provider_name=profile.provider,
        transport=transport,
    )
    judge.client.max_attempts = 1
    report = await amend.parent.engine._run(fixtures, judge, transport)
    assert len(seen) == 3 and report["abort_reason"] == "CONSECUTIVE_INTEGRATION_FAILURES"


def test_offline_plan_has_exact_parent_contract_corpus_and_zero_access():
    importlib.reload(amend)
    plan = amend.plan()
    baseline = amend.parent.plan("j3-sonnet")
    assert (
        plan["primary_count"],
        plan["repeat_count"],
        plan["scheduled_observations"],
        plan["max_http_calls"],
        plan["retries"],
    ) == (35, 9, 44, 44, 0)
    assert plan["schedule"] == baseline["schedule"]
    assert plan["semantic_contract_sha256"] == baseline["contract_sha256"]
    assert plan["fixture_sha256"] == baseline["fixture_sha256"]
    assert plan["token_limit"] == 512
    assert plan["credential_reads"] == plan["external_calls"] == 0
    assert "INCOMPLETE_MAX_TOKENS" in plan["continue_after"]
    assert "EVIDENCE_WRITE_FAILURE" in plan["abort_after"]


async def test_future_execution_writes_complete_private_journal_with_mock_only(
    tmp_path, monkeypatch
):
    from civicgate.runtime_config import InMemorySecretProvider

    monkeypatch.setattr(amend, "verify_execution", lambda _: None)
    freeze = {
        "run_id": "synthetic-only",
        "output": str(tmp_path / "result.json"),
        "plan": amend.plan(),
    }
    seen = []
    clock_reads = []
    starts = []
    written_stages = []
    real_write = amend.parent.engine._write

    def clock():
        instant = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(microseconds=len(clock_reads))
        clock_reads.append(instant)
        return instant

    def write(path, value, secret="", *, exclusive=False):
        if path.name.endswith("-start.json"):
            assert exclusive is True
            assert value["utc_start"] == clock_reads[-1].isoformat()
            written_stages.append(("start", value["sequence"]))
        elif path.name.endswith("-result.json"):
            assert exclusive is True
            written_stages.append(("result", value["sequence"]))
        return real_write(path, value, secret, exclusive=exclusive)

    monkeypatch.setattr(amend.parent, "utcnow", clock)
    monkeypatch.setattr(amend.parent.engine, "_write", write)

    def handler(request):
        ordinal = len(seen) + 1
        start = json.loads((tmp_path / f"observation-{ordinal:02d}-start.json").read_text())
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
        assert start["run_id"] == freeze["run_id"]
        assert start["sequence"] == start["expected_request_ordinal"] == ordinal
        assert start["prior_http_count"] == ordinal - 1
        assert {k: start[k] for k in ("id", "phase", "observation")} == freeze["plan"]["schedule"][
            ordinal - 1
        ]
        stamp = datetime.fromisoformat(start["utc_start"])
        assert stamp.utcoffset() == timedelta(0)
        assert stamp.isoformat() == clock_reads[-1].isoformat()
        assert (
            start["utc_start"] != json.loads((tmp_path / "started.json").read_text())["utc_start"]
        )
        if starts:
            assert stamp > datetime.fromisoformat(starts[-1]["utc_start"])
            assert (tmp_path / f"observation-{ordinal - 1:02d}-result.json").is_file()
        assert not (tmp_path / f"observation-{ordinal:02d}-result.json").exists()
        starts.append(start)
        written_stages.append(("dispatch", ordinal))
        seen.append(request)
        return response(VALID | {"rationale": TOO_LONG}) if len(seen) <= 3 else response()

    secrets = InMemorySecretProvider(
        {"CIVICGATE_ANTHROPIC_JUDGE_API_KEY": "fixture-credential-value-73fa"}
    )
    result = await amend.execute(freeze, secrets, lambda: httpx.MockTransport(handler))
    assert result["http_call_count"] == len(seen) == 44
    assert len(list(tmp_path.glob("observation-*-start.json"))) == 44
    assert len(list(tmp_path.glob("observation-*-result.json"))) == 44
    assert result["retry_count"] == 0
    assert written_stages == [
        (stage, ordinal) for ordinal in range(1, 45) for stage in ("start", "dispatch", "result")
    ]
    assert not (tmp_path / "observation-45-start.json").exists()
    assert all(
        "fixture-credential-value-73fa" not in path.read_text() for path in tmp_path.glob("*.json")
    )
    row = json.loads((tmp_path / "observation-01-result.json").read_text())
    assert row["j3"] is None and "j2" not in row
    assert row["structural_evidence"]["unvalidated_wire_semantic_fields"]["fields"] == VALID
    assert TOO_LONG not in (tmp_path / "result.json").read_text()
    with pytest.raises(amend.parent.engine.BenchmarkAbort, match="EXISTING_RUN_OUTPUT"):
        await amend.execute(freeze, secrets)
    assert len(seen) == 44


@pytest.mark.parametrize("stage,sequence", [("start", 1), ("start", 2), ("result", 1)])
async def test_execution_exclusive_journal_failure_stops_dispatch(
    tmp_path, monkeypatch, stage, sequence
):
    from civicgate.runtime_config import InMemorySecretProvider

    monkeypatch.setattr(amend, "verify_execution", lambda _: None)
    freeze = {
        "run_id": "synthetic-exclusive-journal",
        "output": str(tmp_path / "result.json"),
        "plan": amend.plan(),
    }
    collision = tmp_path / f"observation-{sequence:02d}-{stage}.json"
    collision.write_text("preserve-existing-evidence")
    seen = []

    def handler(request):
        seen.append(request)
        return response()

    report = await amend.execute(
        freeze,
        InMemorySecretProvider({"CIVICGATE_ANTHROPIC_JUDGE_API_KEY": "synthetic-key"}),
        lambda: httpx.MockTransport(handler),
    )
    assert report["abort_reason"] == "EVIDENCE_WRITE_FAILURE"
    assert len(seen) == report["http_call_count"] == (sequence - 1 if stage == "start" else 1)
    assert report["retry_count"] == 0
    assert collision.read_text() == "preserve-existing-evidence"


async def test_accounting_drift_after_first_result_blocks_second_start():
    fixtures, judge, transport, seen, persist, events = harness()

    def corrupt_counter(stage, row):
        persist(stage, row)
        if stage == "result":
            transport.calls += 1

    report = await amend.run_amended(fixtures, judge, transport, corrupt_counter)
    assert report["abort_reason"] == "CALL_ACCOUNTING_VIOLATION"
    assert len(seen) == 1
    assert [stage for stage, _ in events] == ["start", "result"]


async def test_execution_freeze_failure_precedes_credential_access(tmp_path, monkeypatch):
    def fail(_):
        raise amend.parent.engine.BenchmarkAbort("EXECUTION_FREEZE_MISMATCH")

    class Secrets:
        def get_secret(self, name):
            pytest.fail("Credential boundary crossed before freeze validation")

    monkeypatch.setattr(amend, "verify_execution", fail)
    with pytest.raises(amend.parent.engine.BenchmarkAbort, match="FREEZE_MISMATCH"):
        await amend.execute({"output": str(tmp_path / "result.json")}, Secrets())
    assert not list(tmp_path.iterdir())


async def test_observer_metadata_truncation_is_fatal():
    wire = VALID | {f"extra_{i}": "discard" for i in range(65)}
    fixtures, judge, transport, seen, persist, _ = harness(lambda *_: response(wire))
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["abort_reason"] == "OBSERVER_EVIDENCE_FAILURE"


async def test_oversize_response_is_fatal_and_not_retried():
    fixtures, judge, transport, seen, persist, _ = harness(
        lambda *_: httpx.Response(200, content=b"x" * 200001)
    )
    report = await amend.run_amended(fixtures, judge, transport, persist)
    assert len(seen) == 1 and report["abort_reason"] == "RESPONSE_SIZE_BOUND"
