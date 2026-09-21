"""Independent synthetic responses; diagnostic instrumentation never repairs output."""

import json

import httpx
import pytest

from civicgate.llm.live import LiveJudgeProvider, ProviderError
from civicgate.models.requests import Proposal
from scripts import diagnose_j3_run001_failures as diagnostic

WIRE = {"classification": "IN_SCOPE", "confidence": 0.95, "flags": ["NONE"]}
CASE = diagnostic.frozen.engine._load_fixtures()[0]
KEY = "synthetic-credential"


def body(wire, stop="end_turn"):
    return {
        "model": "claude-sonnet-5",
        "stop_reason": stop,
        "content": [
            {"type": "thinking", "thinking": "HIDDEN_SENTINEL_MUST_NOT_BE_RETAINED"},
            {"type": "text", "text": json.dumps(wire)},
        ],
        "usage": {"input_tokens": 20, "output_tokens": 30},
    }


async def exercise(payload, *, stop="end_turn", raw=None, status=200, transport_error=False):
    response_body = body(payload, stop) if raw is None else raw
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if transport_error:
            raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_ERROR", request=request)
        return httpx.Response(status, json=response_body)

    profile = diagnostic.frozen.PROFILES["j3-sonnet"]
    expected = diagnostic.frozen.payload(profile, CASE)
    transport = diagnostic.DiagnosticTransport(
        [expected], KEY, lambda: None, lambda: httpx.MockTransport(handler)
    )
    row = await diagnostic.observe(CASE, "WIRE_FAILURE", transport)
    baseline = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        KEY,
        protocol=profile.protocol,
        provider_name=profile.provider,
        transport=httpx.MockTransport(handler),
    )
    baseline.client.max_attempts = 1
    try:
        signal = await baseline.assess(
            CASE["request"], Proposal(tool=CASE["tool"], arguments=CASE["arguments"])
        )
    except ProviderError as error:
        assert row["error_code"] == error.code
        assert row["typed_signal"] is None
    else:
        assert row["typed_signal"] == diagnostic.sanitized_signal(signal, KEY)
        assert row["error_code"] is None
    assert seen == [expected, expected]
    assert row["http_request_count"] == 1 and transport.calls == 1
    assert row["retry_count"] == 0
    assert "HIDDEN_SENTINEL" not in json.dumps(row)
    assert "SYNTHETIC_PRIVATE_ERROR" not in json.dumps(row)
    return row


@pytest.mark.parametrize(
    ("wire", "location", "code"),
    [
        ({"confidence": 0.95}, ["classification"], "missing"),
        ({"classification": "IN_SCOPE"}, ["confidence"], "missing"),
        (WIRE | {"classification": "INVALID_SENTINEL"}, ["classification"], "literal_error"),
        (WIRE | {"classification": None}, ["classification"], "literal_error"),
        (WIRE | {"flags": ["INVALID_SENTINEL"]}, ["flags", 0], "literal_error"),
        (WIRE | {"flags": None}, ["flags"], "list_type"),
        (WIRE | {"flags": ["NONE"] * 9}, ["flags"], "too_long"),
        (WIRE | {"confidence": 1.1}, ["confidence"], "less_than_equal"),
        (WIRE | {"confidence": -0.1}, ["confidence"], "greater_than_equal"),
        (WIRE | {"confidence": "INVALID_SENTINEL"}, ["confidence"], "float_parsing"),
        (WIRE | {"confidence": None}, ["confidence"], "float_type"),
        (WIRE | {"confidence": float("inf")}, ["confidence"], "finite_number"),
        (WIRE | {"available": True}, ["available"], "extra_forbidden"),
        (WIRE | {"provider": "INVALID_SENTINEL"}, ["provider"], "extra_forbidden"),
        (WIRE | {"rationale": "x" * 501}, ["rationale"], "string_too_long"),
        (WIRE | {"rationale": None}, ["rationale"], "string_type"),
        ([], [], "model_type"),
    ],
)
async def test_wire_failure_metadata_and_unchanged_real_provider_behavior(wire, location, code):
    row = await exercise(wire)
    meta = row["diagnostic"]
    assert row["diagnostic_outcome"] == "WIRE_FAILURE"
    assert row["reproduction"] == "WIRE_FAILURE_REPRODUCED"
    assert row["same_exact_wire_mechanism_established"] is None
    assert meta["json_parseable"] is True and meta["wire_validation"] == "FAIL"
    assert {"loc": location, "type": code, "message_code": code} in meta["validation_errors"]
    assert meta["schema_valid_semantic_fields"] is None
    assert "INVALID_SENTINEL" not in json.dumps(meta)
    assert all(set(e) == {"loc", "type", "message_code"} for e in meta["validation_errors"])


@pytest.mark.parametrize("confidence", [0, 1, 0.5, "0.5", True])
async def test_actual_lax_numeric_conversion_is_preserved(confidence):
    row = await exercise(WIRE | {"confidence": confidence})
    assert row["diagnostic_outcome"] == "VALID_ON_DIAGNOSTIC_OBSERVATION"
    assert row["diagnostic"]["schema_valid_semantic_fields"]["confidence"] == float(confidence)
    assert row["diagnostic"]["schema_valid_semantic_fields"]["flags"] == ["NONE"]
    assert row["reproduction"] == "WIRE_FAILURE_NOT_REPRODUCED"


async def test_max_tokens_is_incomplete_without_parsing_partial_semantics():
    row = await exercise(WIRE, stop="max_tokens")
    assert row["diagnostic_outcome"] == "INCOMPLETE"
    assert row["diagnostic"]["json_parseable"] is None
    assert row["diagnostic"]["validation_errors"] == []
    assert row["diagnostic"]["wire_validation"] == "NOT_EVALUABLE"
    assert row["error_code"] == "PROVIDER_RESPONSE_INCOMPLETE"
    assert (
        diagnostic.reproduction("INCOMPLETE", row["diagnostic_outcome"]) == "INCOMPLETE_REPRODUCED"
    )


@pytest.mark.parametrize("stop", ["refusal", None, "unexpected"])
async def test_other_stop_rules_unchanged(stop):
    row = await exercise(WIRE, stop=stop)
    assert row["diagnostic_outcome"] == "RESPONSE_NOT_VALIDATED"
    assert row["diagnostic"]["json_parseable"] is None


async def test_diagnostic_failure_itself_does_not_change_provider_result(monkeypatch):
    def fail(*args):
        raise ValueError("PRIVATE_DIAGNOSTIC_ERROR")

    monkeypatch.setattr(diagnostic, "diagnose", fail)
    row = await exercise(WIRE)
    assert row["typed_signal"]["classification"] == "IN_SCOPE"
    assert row["diagnostic"] == {"observer_error": "DIAGNOSTIC_METADATA_UNAVAILABLE"}
    assert "PRIVATE_DIAGNOSTIC_ERROR" not in json.dumps(row)


async def test_metadata_redacts_secret_named_extra_fields_and_valid_rationale():
    row = await exercise(WIRE | {KEY: "DO_NOT_RETAIN_VALUE"})
    assert row["diagnostic"]["validation_errors"][0]["loc"] == ["[REDACTED_FIELD]"]
    assert KEY not in json.dumps(row) and "DO_NOT_RETAIN_VALUE" not in json.dumps(row)
    row = await exercise(WIRE | {"rationale": KEY + " sk-testsecret123456"})
    assert row["typed_signal"]["rationale"] == "[REDACTED] [REDACTED]"
    assert KEY not in json.dumps(row)


async def test_no_concatenation_or_repair_of_multiple_text_blocks():
    raw = body(WIRE)
    raw["content"].append({"type": "text", "text": "{}"})
    row = await exercise(WIRE, raw=raw)
    assert row["diagnostic_outcome"] == "RESPONSE_NOT_VALIDATED"
    assert row["diagnostic"]["json_parseable"] is None


async def test_malformed_json_is_distinct_from_parseable_wire_failure():
    raw = body(WIRE)
    raw["content"][1]["text"] = "not JSON"
    row = await exercise(WIRE, raw=raw)
    assert row["diagnostic_outcome"] == "JSON_PARSE_FAILURE"
    assert row["reproduction"] == "WIRE_FAILURE_NOT_REPRODUCED"


@pytest.mark.parametrize("status", [400, 401, 429, 500])
async def test_provider_failure_is_not_wire_failure_and_is_not_retried(status):
    row = await exercise(WIRE, status=status)
    assert row["diagnostic_outcome"] == "PROVIDER_FAILURE"
    assert row["diagnostic"]["wire_validation"] == "NOT_EVALUABLE"


async def test_transport_failure_is_not_retried():
    row = await exercise(WIRE, transport_error=True)
    assert row["diagnostic_outcome"] == "TRANSPORT_FAILURE"


async def test_eleventh_request_is_blocked_before_inner_transport():
    def forbidden():
        pytest.fail("Unauthorized transport construction")

    transport = diagnostic.DiagnosticTransport([], KEY, lambda: None, forbidden)
    transport.calls = 10
    with pytest.raises(diagnostic.frozen.engine.BenchmarkAbort, match="CALL_BUDGET"):
        await transport.handle_async_request(httpx.Request("POST", "https://api.anthropic.com"))
    assert transport.calls == 10


def test_diagnostic_set_has_only_the_ten_historical_failures_in_original_order():
    assert [seq for seq, _ in diagnostic.CASES] == [1, 5, 8, 9, 12, 13, 17, 20, 21, 22]
    assert len({name for _, name in diagnostic.CASES}) == 10
    assert not any(seq >= 23 for seq, _ in diagnostic.CASES)


async def test_import_and_missing_offline_validation_cannot_read_credentials(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("Offline stage attempted credential/network access")

    monkeypatch.setattr(diagnostic.frozen.WindowsDPAPIStore, "get_secret", forbidden)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    with pytest.raises(FileNotFoundError):
        await diagnostic.execute(tmp_path)


@pytest.mark.parametrize("valid", [True, False])
async def test_ten_case_execution_is_separate_bounded_and_has_no_three_failure_stop(
    tmp_path, monkeypatch, valid
):
    # This execution test does not exercise host-specific DPAPI path resolution.
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(
        diagnostic.frozen.engine,
        "default_store_path",
        lambda: tmp_path / "synthetic-secrets.json",
    )
    history = tmp_path / "history"
    history.mkdir()
    previous = [{"id": c["id"]} for c in diagnostic.frozen.engine._load_fixtures()]
    for sequence, _ in diagnostic.CASES:
        previous[sequence - 1]["telemetry"] = {
            "stop_reason": "max_tokens" if sequence == 21 else "end_turn"
        }
    history_file = history / "result.json"
    history_file.write_text(json.dumps({"assessments": previous}))
    original = history_file.read_bytes()
    directory = tmp_path / "diagnostic"
    directory.mkdir()
    (directory / "diagnostic-freeze.json").write_text(
        json.dumps({"run_id": "synthetic-diagnostic", "fingerprint": diagnostic.fingerprint()})
    )
    (directory / "offline-validation.json").write_text(
        json.dumps({"all_passed": True, "fingerprint": diagnostic.fingerprint()})
    )
    monkeypatch.setattr(diagnostic, "verify", lambda _: history)
    secrets_requested = []

    def secret(self, name):
        secrets_requested.append(name)
        return KEY

    monkeypatch.setattr(diagnostic.frozen.WindowsDPAPIStore, "get_secret", secret)
    # WindowsDPAPIStore's platform guard is irrelevant for the fake secret provider.
    monkeypatch.setattr(diagnostic.frozen.WindowsDPAPIStore, "__init__", lambda *args: None)
    seen = []
    real_transport = diagnostic.DiagnosticTransport

    def transport(payloads, key, verify):
        def respond(request):
            assert json.loads(request.content) == payloads[len(seen)]
            seen.append(request)
            return httpx.Response(200, json=body(WIRE if valid else {"confidence": 0.5}))

        return real_transport(payloads, key, verify, lambda: httpx.MockTransport(respond))

    monkeypatch.setattr(diagnostic, "DiagnosticTransport", transport)
    report = await diagnostic.execute(directory)
    assert report["http_request_count"] == len(seen) == len(report["rows"]) == 10
    assert report["retry_count"] == 0 and report["abort_error_class"] is None
    assert all(row["http_request_count"] == 1 for row in report["rows"])
    assert [row["fixture_id"] for row in report["rows"]] == [c for _, c in diagnostic.CASES]
    assert secrets_requested == ["CIVICGATE_ANTHROPIC_JUDGE_API_KEY"]
    assert history_file.read_bytes() == original
    with pytest.raises(FileExistsError):
        await diagnostic.execute(directory)
    assert len(seen) == 10 and len(secrets_requested) == 1
