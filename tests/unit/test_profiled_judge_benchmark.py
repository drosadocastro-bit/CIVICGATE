"""Offline profile/freeze guards and real-provider execution via MockTransport only."""

import importlib
import json
from dataclasses import FrozenInstanceError, replace

import httpx
import pytest

from civicgate.runtime_config import ConfigurationError, InMemorySecretProvider
from scripts import run_profiled_judge_benchmark as runner


def response(protocol="anthropic_messages", *, stop="end_turn", status=200, text=None):
    text = (
        text
        if text is not None
        else '{"classification":"IN_SCOPE","confidence":0.95,"flags":["NONE"]}'
    )
    if status != 200:
        return httpx.Response(status, json={"error": {"type": "synthetic_error"}})
    if protocol == "anthropic_messages":
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5",
                "stop_reason": stop,
                "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )
    return httpx.Response(
        200,
        json={
            "model": "gpt-5.6-luna",
            "choices": [{"finish_reason": "stop", "message": {"content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )


def test_profiles_are_explicit_immutable_and_exact():
    p = runner.select_profile("j3-sonnet")
    assert (p.provider, p.protocol, p.model, p.endpoint, p.secret_name, p.max_attempts) == (
        "anthropic",
        "anthropic_messages",
        "claude-sonnet-5",
        "https://api.anthropic.com/v1/messages",
        "CIVICGATE_ANTHROPIC_JUDGE_API_KEY",
        1,
    )
    with pytest.raises(FrozenInstanceError):
        p.model = "another-model"
    with pytest.raises(TypeError):
        runner.PROFILES["j3-sonnet"] = p


@pytest.mark.parametrize("name", ["", "unknown", "sonnet", None])
def test_unknown_profile_fails_before_configuration(name):
    with pytest.raises(runner.engine.BenchmarkAbort):
        runner.select_profile(name)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--plan"],
        ["--profile", "bad", "--plan"],
        ["--profile", "j3-sonnet", "--run-frozen", "unused.json"],
    ],
)
def test_cli_cannot_default_to_paid_execution(args):
    with pytest.raises(SystemExit):
        runner.main(args)


def test_plan_import_and_inspection_have_no_secret_or_network_access(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline inspection reached credential or network construction")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setattr(runner.WindowsDPAPIStore, "_read_encrypted", forbidden)
    monkeypatch.setattr(runner.RuntimeSettings, "from_providers", forbidden)
    importlib.reload(runner)
    assert runner.main(["--profile", "j3-sonnet", "--plan"]) == 0
    p = json.loads(capsys.readouterr().out)
    assert (
        p["primary_fixture_count"],
        p["repeat_observation_count"],
        p["intended_http_calls"],
        p["automatic_retries"],
        p["external_calls_in_plan"],
    ) == (35, 9, 44, 0, 0)
    assert p["fixture_ids"] == [c["id"] for c in runner.engine._load_fixtures()]
    assert p["schedule"] == runner.engine._schedule(runner.engine._load_fixtures())
    assert p["repeat_ids"] == runner.engine.REPEAT_IDS
    assert p["fixture_sha256"] == runner.file_hash(runner.ROOT / "tests/fixtures/adversarial.json")


def test_j2_and_j3_share_the_contract_and_method_without_payload_tuning():
    a, b = runner.plan("j2-luna"), runner.plan("j3-sonnet")
    for key in (
        "fixture_sha256",
        "fixture_ids",
        "schedule",
        "repeat_ids",
        "injection_ids",
        "rules",
        "contract_sha256",
        "wire_schema_sha256",
        "system_prompt_sha256",
        "disagreement_rules",
    ):
        assert a[key] == b[key]
    assert b["parameter_names"] == ["max_tokens", "messages", "model", "system"]
    for case in runner.engine._load_fixtures():
        j2 = runner.payload(runner.PROFILES["j2-luna"], case)
        j3 = runner.payload(runner.PROFILES["j3-sonnet"], case)
        assert j2 == runner.engine._payload(case)
        assert j2["messages"][0]["content"] == j3["system"]
        assert j2["messages"][1] == j3["messages"][0]
        assert j3["max_tokens"] == 512


@pytest.mark.parametrize(
    "change",
    [
        {"model": "other-model"},
        {"endpoint": "https://api.openai.com/v1/chat/completions"},
        {"base_url": "https://api.anthropic.com/v1"},
        {"protocol": "openai_compatible"},
    ],
)
def test_mutated_profile_fails_before_transport(change):
    p = replace(runner.PROFILES["j3-sonnet"], **change)
    with pytest.raises(runner.engine.BenchmarkAbort, match="PROFILE_MISMATCH"):
        runner.settings(p, InMemorySecretProvider())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key", ["CIVICGATE_OPENAI_JUDGE_API_KEY", "CIVICGATE_JUDGE_API_KEY", "CIVICGATE_MODEL_API_KEY"]
)
async def test_execution_missing_anthropic_secret_cannot_construct_transport(monkeypatch, key):
    monkeypatch.setattr(runner, "verify_run", lambda *_: runner.PROFILES["j3-sonnet"])

    def forbidden(*args, **kwargs):
        pytest.fail("Missing Anthropic credential reached transport")

    monkeypatch.setattr(runner, "ProfileTransport", forbidden)
    with pytest.raises(ConfigurationError):
        await runner.execute({}, "j3-sonnet", InMemorySecretProvider({key: "synthetic-key"}))


@pytest.mark.parametrize("field", ["model", "endpoint", "protocol", "secret_name"])
def test_frozen_profile_tampering_fails_before_credentials(field):
    p = runner.plan("j3-sonnet")
    p["profile"][field] = "unapproved"
    with pytest.raises(runner.engine.BenchmarkAbort, match="RUN_FREEZE_MISMATCH"):
        runner.verify_run({"plan": p}, "j3-sonnet")


def test_historical_manifest_rejects_amended_checkout_without_rewriting_history():
    manifest = json.loads(runner.MANIFEST.read_text())
    # Current credential code differs; the old execution instrument must reject it.
    assert manifest != runner.versioned_manifest()
    with pytest.raises(runner.engine.BenchmarkAbort, match="VERSIONED_FREEZE_MISMATCH"):
        runner.verify_versioned_manifest()
    assert manifest["plan"]["fixture_sha256"] == runner.plan("j2-luna")["fixture_sha256"]


def test_portable_hash_does_not_rewrite_crlf_files(tmp_path):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_bytes(b"first\r\nsecond\r\n")
    b.write_bytes(b"first\nsecond\n")
    assert runner.file_hash(a) == runner.file_hash(b)
    assert a.read_bytes() == b"first\r\nsecond\r\n"


def test_commit_binding_checks_manifest_bytes_and_required_parent(monkeypatch):
    commit = "b" * 40
    calls = []

    def git(*args):
        calls.append(args)
        if args[0] == "log":
            return (commit + "\n").encode()
        if args[0] == "rev-parse":
            return (runner.SMOKE_COMMIT + "\n").encode()
        return runner.MANIFEST.read_bytes()

    # Isolate Git binding from the independently tested historical source rejection.
    monkeypatch.setattr(
        runner, "versioned_manifest", lambda: json.loads(runner.MANIFEST.read_text())
    )
    monkeypatch.setattr(runner.engine, "_git", git)
    assert runner.verify_versioned_manifest() == commit
    assert ("rev-parse", commit + "^") in calls
    monkeypatch.setattr(runner.engine, "_git", lambda *args: b"unexpected")
    with pytest.raises(runner.engine.BenchmarkAbort):
        runner.verify_versioned_manifest()


def mock_run(monkeypatch, tmp_path, profile_name, responder):
    profile = runner.PROFILES[profile_name]
    monkeypatch.setattr(runner, "verify_run", lambda *_: profile)
    frozen = {
        "run_id": "synthetic-run",
        "output": str(tmp_path / "result.json"),
        "plan": runner.plan(profile_name),
    }
    calls = []

    def transport(sent):
        calls.append(sent)
        assert str(sent.url) == profile.endpoint
        return responder(sent)

    secrets = InMemorySecretProvider({profile.secret_name: "synthetic-key"})
    return frozen, secrets, calls, lambda: httpx.MockTransport(transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["j2-luna", "j3-sonnet"])
async def test_mock_44_call_execution_uses_shared_scoring_and_correct_output_label(
    monkeypatch, tmp_path, name
):
    profile = runner.PROFILES[name]
    frozen, secrets, calls, factory = mock_run(
        monkeypatch, tmp_path, name, lambda _: response(profile.protocol)
    )
    report = await runner.execute(frozen, name, secrets, factory)
    assert len(calls) == report["http_call_count"] == 44
    assert report["status"] == "COMPLETED_ALL_ASSESSMENTS_VALID"
    assert report["valid_assessment_count"] == 44
    signal_key = "j3" if name == "j3-sonnet" else "j2"
    assert all(row[signal_key]["flags"] == ["NONE"] for row in report["assessments"])
    assert all(row[signal_key]["provider"] == profile.provider for row in report["assessments"])
    assert report["gateway_preflight"]["all_passed"]
    assert report["metrics"]["engineering_reference_agreement"]["denominator"] == 35
    assert all(
        row["status"] == "SEMANTIC_STABLE" for row in report["metrics"]["repeat_consistency"]
    )
    with pytest.raises(runner.engine.BenchmarkAbort, match="EXISTING_RUN_OUTPUT"):
        await runner.execute(frozen, name, secrets, factory)
    assert len(calls) == 44


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "stop", "expected_calls", "reason"),
    [
        (401, "end_turn", 1, "AUTHENTICATION_REJECTED"),
        (429, "end_turn", 3, "CONSECUTIVE_INTEGRATION_FAILURES"),
        (500, "end_turn", 3, "CONSECUTIVE_INTEGRATION_FAILURES"),
        (200, "max_tokens", 3, "CONSECUTIVE_INTEGRATION_FAILURES"),
        (200, "refusal", 3, "CONSECUTIVE_INTEGRATION_FAILURES"),
    ],
)
async def test_j3_failures_are_preserved_not_retried_or_scored_as_success(
    monkeypatch, tmp_path, status, stop, expected_calls, reason
):
    frozen, secrets, calls, factory = mock_run(
        monkeypatch, tmp_path, "j3-sonnet", lambda _: response(status=status, stop=stop)
    )
    report = await runner.execute(frozen, "j3-sonnet", secrets, factory)
    assert len(calls) == expected_calls
    assert report["status"] == "BENCHMARK_ABORTED" and report["abort_reason"] == reason
    assert report["valid_assessment_count"] == 0
    assert report["not_attempted_count"] == 44 - expected_calls
    assert sum(report["terminal_counts"].values()) == 44
    if status == 200:
        assert report["schema_failure_count"] == expected_calls
        assert all(
            r["telemetry"]["stop_reason"] == stop for r in report["assessments"][:expected_calls]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["endpoint", "model", "credential"])
async def test_real_transport_guard_rejects_mismatch_before_inner_factory(mismatch):
    profile = runner.PROFILES["j3-sonnet"]
    p = runner.payload(profile, runner.engine._load_fixtures()[0])

    def forbidden():
        pytest.fail("Invalid request reached HTTP transport")

    t = runner.ProfileTransport(profile, [p], "synthetic-key", lambda: None, forbidden)
    sent = dict(p)
    if mismatch == "model":
        sent["model"] = "another-model"
    req = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions"
        if mismatch == "endpoint"
        else profile.endpoint,
        headers={"x-api-key": "wrong" if mismatch == "credential" else "synthetic-key"},
        json=sent,
    )
    with pytest.raises(runner.engine.BenchmarkAbort):
        await t.handle_async_request(req)
    assert t.calls == 0
