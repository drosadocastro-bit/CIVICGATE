"""J4 launch gate tests use synthetic authorization, secrets and HTTP only."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from scripts import prepare_j4_gpt6_luna as j4
from scripts import run_j4_gpt6_luna as launcher

HEAD = "902195a0b76fec913e7777f4496f58ce6e87adf8"
VALID = {"classification": "IN_SCOPE", "confidence": 0.9, "flags": ["NONE"]}


@pytest.fixture(autouse=True)
def forbid_real_boundaries(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("real provider, Gateway or credential boundary attempted")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    monkeypatch.setattr(j4.j3.engine.Gateway, "call", forbidden)
    monkeypatch.setattr(j4.j3.engine.Gateway, "_call", forbidden)
    monkeypatch.setattr(j4.j3.parent.WindowsDPAPIStore, "get_secret", forbidden)


def git_state(head=HEAD):
    return head, "codex/dpapi-selective-access", b""


def response(model="gpt-6-luna"):
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(VALID)},
                }
            ],
        },
    )


class SyntheticSecretStore:
    def __init__(self):
        self.names = []

    def get_secret(self, name):
        self.names.append(name)
        return "synthetic-only"


def make_freeze(tmp_path, *, authorized=True):
    root = tmp_path / "evidence"
    directory = root / "gpt6-luna-j4-frozen-synthetic"
    directory.mkdir(parents=True)
    fixtures = j4.j3.engine._load_fixtures()
    by_id = {case["id"]: case for case in fixtures}
    freeze = {
        "version": "j4-gpt6-luna-final-freeze-v1",
        "freeze_id": directory.name,
        "run_id": "gpt6-luna-j4-synthetic",
        "experiment_id": j4.EXPERIMENT,
        "profile_id": j4.PROFILE_ID,
        "model": "gpt-6-luna",
        "execution_head": HEAD,
        "historical_draft_freeze_raw_sha256": launcher.DRAFT_SHA256,
        **launcher.FROZEN_HASHES,
        "provider": "openai",
        "protocol": "openai_compatible",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "reasoning_effort": "medium",
        "max_completion_tokens": 512,
        "response_format": {"type": "json_object"},
        "primary_count": 35,
        "repeat_count": 9,
        "scheduled_requests": 44,
        "maximum_requests": 44,
        "retry_budget": 0,
        "gateway_execution": False,
        "observability_rule": "Fixture intent is not model evidence.",
        "judge_visible_case_information": ["request", "proposal.tool", "proposal.arguments"],
        "human_reference_role": "EVALUATION_ONLY",
        "request_45": "REJECTED_BY_INSTRUMENT",
        "no_live_entrypoint": False,
        "result_status": "NOT_CREATED",
        "authorization": "NOT_AUTHORIZED",
        "status": "GPT6_LUNA_FINAL_FREEZE_READY_FOR_HUMAN_AUTHORIZATION",
        "schedule": [
            {
                **entry,
                "payload_sha256": j4.payload_hash(j4.payload(j4.PROFILE_ID, by_id[entry["id"]])),
            }
            for entry in j4.j3.engine._schedule(fixtures)
        ],
        "source_sha256_lf": {
            name: j4.j3.parent.file_hash(j4.ROOT / name)
            for name in sorted(launcher.required_source_paths())
        },
    }
    freeze_path = directory / "freeze.json"
    authorization_path = directory / "authorization.json"
    sha = write_freeze(freeze_path, freeze)
    if authorized:
        write_authorization(authorization_path, freeze, sha)
    return root, freeze_path, authorization_path, freeze, sha


def write_freeze(path, freeze):
    raw = (json.dumps(freeze, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def write_authorization(path, freeze, sha):
    path.write_text(
        json.dumps(
            {
                "version": launcher.AUTHORIZATION_VERSION,
                "authorization": "AUTHORIZED_ONCE",
                "experiment_id": j4.EXPERIMENT,
                "run_id": freeze["run_id"],
                "final_freeze_sha256": sha,
                "execution_head": freeze["execution_head"],
                "profile_id": j4.PROFILE_ID,
                "model": freeze["model"],
                "maximum_requests": 44,
                "retry_budget": 0,
            }
        ),
        encoding="utf-8",
    )


async def attempt(root, path, authorization, sha, store, handler, *, state=git_state):
    return await launcher.run_frozen(
        path,
        sha,
        authorization,
        evidence_root=root,
        git_state=state,
        secret_provider_factory=lambda: store,
        inner_factory=lambda: httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("semantic_contract_sha256", "0" * 64),
        ("fixture_sha256", "0" * 64),
        ("source_human_adjudication_sha256", "0" * 64),
        ("human_reference_sha256", "0" * 64),
        ("profile_sha256", "0" * 64),
        ("payload_contract_sha256", "0" * 64),
        ("model", "gpt-5.6-luna"),
        ("profile_id", "j2-luna"),
        ("no_live_entrypoint", True),
    ],
)
async def test_freeze_identity_failures_precede_credentials_and_dispatch(tmp_path, field, value):
    root, path, auth_path, freeze, _ = make_freeze(tmp_path)
    freeze[field] = value
    sha = write_freeze(path, freeze)
    write_authorization(auth_path, freeze, sha)
    store, seen = SyntheticSecretStore(), []
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="FREEZE_OR_INSTRUMENT_MISMATCH"):
        await attempt(root, path, auth_path, sha, store, lambda request: seen.append(request))
    assert not store.names and not seen
    assert not (path.parent / "started.json").exists()


@pytest.mark.parametrize(
    "kind", ["wrong_sha", "wrong_head", "wrong_schedule", "wrong_source", "missing_auth"]
)
async def test_other_preflight_failures_do_not_touch_secrets_or_network(tmp_path, kind):
    root, path, auth_path, freeze, sha = make_freeze(tmp_path, authorized=kind != "missing_auth")
    state = git_state
    if kind == "wrong_sha":
        sha = "0" * 64
    elif kind == "wrong_head":

        def state():
            return git_state("f" * 40)
    elif kind == "wrong_schedule":
        freeze["schedule"][0]["payload_sha256"] = "0" * 64
        sha = write_freeze(path, freeze)
        write_authorization(auth_path, freeze, sha)
    elif kind == "wrong_source":
        freeze["source_sha256_lf"]["scripts/run_j4_gpt6_luna.py"] = "0" * 64
        sha = write_freeze(path, freeze)
        write_authorization(auth_path, freeze, sha)
    store, seen = SyntheticSecretStore(), []
    with pytest.raises(j4.j3.engine.BenchmarkAbort):
        await attempt(
            root, path, auth_path, sha, store, lambda request: seen.append(request), state=state
        )
    assert not store.names and not seen
    assert not (path.parent / "started.json").exists()


@pytest.mark.parametrize("field", ["run_id", "final_freeze_sha256", "execution_head", "model"])
async def test_authorization_binding_fails_before_credential_access(tmp_path, field):
    root, path, auth_path, _, sha = make_freeze(tmp_path)
    authorization = json.loads(auth_path.read_text())
    authorization[field] = "invalid"
    auth_path.write_text(json.dumps(authorization), encoding="utf-8")
    store, seen = SyntheticSecretStore(), []
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="EXECUTION_NOT_AUTHORIZED"):
        await attempt(root, path, auth_path, sha, store, lambda request: seen.append(request))
    assert not store.names and not seen
    assert not (path.parent / "started.json").exists()


async def test_duplicate_authorization_member_fails_closed(tmp_path):
    root, path, auth_path, _, sha = make_freeze(tmp_path)
    raw = auth_path.read_text(encoding="utf-8")
    auth_path.write_text('{"authorization":"NOT_AUTHORIZED",' + raw.lstrip()[1:], encoding="utf-8")
    store, seen = SyntheticSecretStore(), []
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="EXECUTION_NOT_AUTHORIZED"):
        await attempt(root, path, auth_path, sha, store, lambda request: seen.append(request))
    assert not store.names and not seen


async def test_authorization_bytes_are_pinned_before_credential_access(tmp_path, monkeypatch):
    root, path, auth_path, _, sha = make_freeze(tmp_path)
    store, seen = SyntheticSecretStore(), []
    original_write = launcher.engine._write

    def mutate_after_claim(target, value, secret="", *, exclusive=False):
        original_write(target, value, secret, exclusive=exclusive)
        if Path(target).name == "started.json":
            auth_path.write_bytes(auth_path.read_bytes() + b"\n")

    monkeypatch.setattr(launcher.engine, "_write", mutate_after_claim)
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="EXECUTION_NOT_AUTHORIZED"):
        await attempt(root, path, auth_path, sha, store, lambda request: seen.append(request))
    assert not store.names and not seen
    assert (path.parent / "started.json").exists()


async def test_synthetic_authorization_runs_exact_schedule_and_seals_result(tmp_path):
    root, path, auth_path, freeze, sha = make_freeze(tmp_path)
    store, seen = SyntheticSecretStore(), []

    def handler(request):
        sequence = len(seen) + 1
        start = path.parent / f"observation-{sequence:02d}-start.json"
        assert (path.parent / "started.json").exists()
        assert start.exists()
        assert not (path.parent / f"observation-{sequence:02d}-result.json").exists()
        assert (
            j4.payload_hash(json.loads(request.content))
            == freeze["schedule"][sequence - 1]["payload_sha256"]
        )
        seen.append(request)
        return response()

    report = await attempt(root, path, auth_path, sha, store, handler)
    assert store.names == ["CIVICGATE_OPENAI_JUDGE_API_KEY"]
    assert len(seen) == report["http_call_count"] == 44
    assert report["retry_count"] == report["gateway_executions"] == 0
    assert len(list(path.parent.glob("observation-*-start.json"))) == 44
    assert len(list(path.parent.glob("observation-*-result.json"))) == 44
    assert report["freeze_raw_sha256"] == sha
    assert (
        hashlib.sha256((path.parent / "result.json").read_bytes()).hexdigest()
        == (path.parent / "result.sha256").read_text().strip()
    )
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="EXISTING_RUN_OUTPUT"):
        await attempt(root, path, auth_path, sha, store, handler)
    assert len(seen) == 44 and len(store.names) == 1


@pytest.mark.parametrize("stage", ["start", "result"])
async def test_journal_failure_stops_before_next_dispatch(tmp_path, monkeypatch, stage):
    root, path, auth_path, _, sha = make_freeze(tmp_path)
    store, seen = SyntheticSecretStore(), []
    original_write = launcher.engine._write

    def fail_selected(target, value, secret="", *, exclusive=False):
        if Path(target).name == f"observation-01-{stage}.json":
            raise OSError("synthetic journal failure")
        return original_write(target, value, secret, exclusive=exclusive)

    monkeypatch.setattr(launcher.engine, "_write", fail_selected)

    def handler(request):
        seen.append(request)
        return response()

    report = await attempt(root, path, auth_path, sha, store, handler)
    assert report["abort_reason"] == "EVIDENCE_WRITE_FAILURE"
    assert len(seen) == (0 if stage == "start" else 1)
    assert report["http_call_count"] == len(seen)
    assert (path.parent / "result.sha256").exists()


@pytest.mark.parametrize(
    ("kind", "category", "fatal"),
    [
        ("mismatch", "RESPONSE_NOT_VALIDATED", "RETURNED_MODEL_MISMATCH"),
        ("missing", "RESPONSE_NOT_VALIDATED", "OBSERVER_EVIDENCE_FAILURE"),
        ("http", "RESPONSE_NOT_VALIDATED", "PROVIDER_HTTP_FAILURE"),
        ("malformed", "MALFORMED_SEMANTIC_JSON", None),
    ],
)
async def test_launcher_preserves_existing_failure_taxonomy(tmp_path, kind, category, fatal):
    root, path, auth_path, _, sha = make_freeze(tmp_path)
    store, seen = SyntheticSecretStore(), []

    def handler(request):
        seen.append(request)
        if len(seen) > 1:
            return response()
        if kind == "http":
            return httpx.Response(429, json={"error": {"type": "rate_limit"}})
        if kind == "malformed":
            body = response().json()
            body["choices"][0]["message"]["content"] = "not-json"
            return httpx.Response(200, json=body)
        return response("unexpected" if kind == "mismatch" else None)

    report = await attempt(root, path, auth_path, sha, store, handler)
    assert report["assessments"][0]["result_category"] == category
    assert report["abort_reason"] == fatal
    assert len(seen) == (1 if fatal else 44)
    assert report["retry_count"] == report["gateway_executions"] == 0
    assert store.names == ["CIVICGATE_OPENAI_JUDGE_API_KEY"]


def test_current_historical_freeze_remains_non_executable(tmp_path):
    root, path, auth_path, freeze, _ = make_freeze(tmp_path)
    freeze["no_live_entrypoint"] = True
    sha = write_freeze(path, freeze)
    write_authorization(auth_path, freeze, sha)
    with pytest.raises(j4.j3.engine.BenchmarkAbort, match="FREEZE_OR_INSTRUMENT_MISMATCH"):
        launcher.verify_execution(path, sha, auth_path, evidence_root=root, git_state=git_state)


@pytest.mark.parametrize("flags", [[], ["-O"], ["-OO"]])
def test_optimizer_cannot_bypass_freeze_sha_gate(tmp_path, flags):
    root, path, auth_path, _, _ = make_freeze(tmp_path)
    code = """
import sys
from pathlib import Path
from scripts import run_j4_gpt6_luna as launcher
try:
    launcher.verify_execution(
        Path(sys.argv[1]), "0" * 64, Path(sys.argv[2]),
        evidence_root=Path(sys.argv[3]),
        git_state=lambda: ("902195a0b76fec913e7777f4496f58ce6e87adf8", "codex/dpapi-selective-access", b""),
    )
except launcher.engine.BenchmarkAbort:
    print("DENIED")
else:
    raise SystemExit("OPTIMIZER_BYPASS")
"""
    result = subprocess.run(
        [sys.executable, *flags, "-c", code, str(path), str(auth_path), str(root)],
        cwd=j4.ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and result.stdout.strip() == "DENIED"
