"""Prospective dependency pinning without weakening historical validators."""

import copy
import json
import os
import shutil
import subprocess
import sys

import pytest

from scripts import j3_optimizer_stability as amendment
from scripts import run_j3_experiment as runner

OPTIMIZER_MODES = [
    pytest.param([], None, 0, id="normal"),
    pytest.param(["-O"], None, 1, id="-O"),
    pytest.param(["-OO"], None, 2, id="-OO"),
    pytest.param([], "1", 1, id="PYTHONOPTIMIZE=1"),
    pytest.param([], "2", 2, id="PYTHONOPTIMIZE=2"),
]

SCHEMA_PROBE = """
import hashlib
from pydantic import ValidationError
from civicgate.llm.live import _JudgeSignalWire
from scripts.run_live_judge_benchmark import _prompt
schema_json = json.dumps(_JudgeSignalWire.model_json_schema(), sort_keys=True)
prompt = _prompt()
valid = {"classification": "IN_SCOPE", "confidence": 0.5}
cases = {
    "valid": valid,
    "boundaries": dict(valid, confidence=1, rationale="x" * 500, flags=["NONE"] * 8),
    "zero": dict(valid, confidence=0),
    "extra": dict(valid, available=True),
    "nan": dict(valid, confidence=float("nan")),
    "inf": dict(valid, confidence=float("inf")),
    "negative_inf": dict(valid, confidence=float("-inf")),
    "missing_classification": {"confidence": 0.5},
    "missing_confidence": {"classification": "IN_SCOPE"},
    "rationale_501": dict(valid, rationale="x" * 501),
    "flags_9": dict(valid, flags=["NONE"] * 9),
    "confidence_above": dict(valid, confidence=1.01),
    "confidence_below": dict(valid, confidence=-0.01),
    "invalid_enum": dict(valid, classification="INVALID"),
}
validation = {}
for name, value in cases.items():
    try:
        _JudgeSignalWire.model_validate(value)
    except ValidationError:
        validation[name] = False
    else:
        validation[name] = True
schema_evidence = {
    "schema_json": schema_json,
    "prompt": prompt,
    "schema_sha256": hashlib.sha256(schema_json.encode()).hexdigest(),
    "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    "doc_is_none": _JudgeSignalWire.__doc__ is None,
    "extra": _JudgeSignalWire.model_config["extra"],
    "allow_inf_nan": _JudgeSignalWire.model_config["allow_inf_nan"],
    "validation": validation,
}
"""


# Run the actual production function, redirecting only its input file locations.
# Explicit subprocess checks must themselves survive optimized interpretation.
VERIFY_CHILD = """
import json
import socket
import sys
from pathlib import Path

def forbidden(*args, **kwargs):
    raise RuntimeError("Optimizer regression forbids network and native DPAPI")

socket.socket.connect = forbidden
socket.getaddrinfo = forbidden
from civicgate.windows_dpapi import WindowsDPAPIStore
WindowsDPAPIStore._windll = forbidden
WindowsDPAPIStore._read_encrypted = forbidden
from scripts import j3_optimizer_stability as amendment
from scripts import run_j3_experiment as runner

amendment.ROOT = Path(sys.argv[1])
amendment.MANIFEST = amendment.ROOT / "docs/J3_OPTIMIZER_STABILITY_001.json"
try:
    amendment.verify_amendment()
except runner.engine.BenchmarkAbort as exc:
    if str(exc) != "OPTIMIZER_STABILITY_FREEZE_MISMATCH":
        raise SystemExit("Unexpected failure classification") from None
    outcome = str(exc)
else:
    outcome = "PASS"

"""
VERIFY_CHILD += (
    SCHEMA_PROBE
    + "\nprint(json.dumps(dict(schema_evidence, outcome=outcome, optimize=sys.flags.optimize)))\n"
)


@pytest.mark.parametrize("flags,optimize_env,expected_optimization", OPTIMIZER_MODES)
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "source",
        "parent_commit",
        "parent_map",
        "allowlist",
        "contract",
        "fixture",
        "status",
    ],
)
def test_production_verifier_survives_optimizer(
    tmp_path, flags, optimize_env, expected_optimization, case
):
    for name in amendment.source_paths() | {"docs/J3_OPTIMIZER_STABILITY_001.json"}:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(amendment.ROOT / name, destination)
    path = tmp_path / "docs/J3_OPTIMIZER_STABILITY_001.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if case == "source":
        dependency = tmp_path / "src/civicgate/windows_dpapi.py"
        dependency.write_bytes(dependency.read_bytes() + b"\n# synthetic tamper\n")
    elif case == "parent_commit":
        manifest["parent_commit"] = "0" * 40
    elif case == "parent_map":
        manifest["parent_sources"]["src/civicgate/windows_dpapi.py"] = "0" * 64
    elif case == "allowlist":
        manifest["allowed_modified_dependencies"].append("src/civicgate/governance/policy.py")
    elif case == "contract":
        manifest["semantic_contract_sha256"] = "0" * 64
    elif case == "fixture":
        manifest["fixture_sha256"] = "0" * 64
    elif case == "status":
        manifest["status"] = "LIVE_AUTHORIZED"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    env = dict(os.environ)
    env.pop("PYTHONOPTIMIZE", None)
    if optimize_env is not None:
        env["PYTHONOPTIMIZE"] = optimize_env
    # Prefer this checkout over any editable install, retaining offline test guards.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(amendment.ROOT / "src"), str(amendment.ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, *flags, "-c", VERIFY_CHILD, str(tmp_path)],
        cwd=amendment.ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    actual = json.loads(result.stdout)
    assert {k: actual[k] for k in ("outcome", "optimize")} == {
        "outcome": "PASS" if case == "valid" else "OPTIMIZER_STABILITY_FREEZE_MISMATCH",
        "optimize": expected_optimization,
    }
    assert (
        actual["schema_sha256"]
        == "5241e54925bb6ab9e06abbc82b8d885b556875e0bfc1180be4ab848ec3050981"
    )
    assert actual["prompt_sha256"] == runner.CONTRACT_SHA256
    assert actual["doc_is_none"] == (expected_optimization == 2)
    assert actual["extra"] == "forbid" and actual["allow_inf_nan"] is False
    assert {k for k, v in actual["validation"].items() if v} == {"valid", "boundaries", "zero"}
    assert len(actual["validation"]) == 14


def test_current_prospective_manifest_and_both_profiles_validate():
    amendment.verify_amendment()
    for profile in runner.PROFILES:
        plan = runner.plan(profile)
        assert plan["optimizer_amendment"] == amendment.AMENDMENT
        assert plan["shared"]["semantic_contract_sha256"] == runner.CONTRACT_SHA256
        assert plan["shared"]["fixture_sha256"] == runner.FIXTURE_SHA256
    assert "docs/J3_OPTIMIZER_STABILITY_001.json" in runner.raw_hashes()


def test_historical_amendment_is_not_reinterpreted_as_current():
    with pytest.raises(runner.engine.BenchmarkAbort, match="VERSIONED_FREEZE_MISMATCH"):
        runner.historical.verify_manifest()


@pytest.fixture
def isolated_manifest(tmp_path, monkeypatch):
    paths = amendment.source_paths()
    for name in paths | {"docs/J3_OPTIMIZER_STABILITY_001.json"}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(amendment.ROOT / name, target)
    monkeypatch.setattr(amendment, "ROOT", tmp_path)
    monkeypatch.setattr(amendment, "MANIFEST", tmp_path / "docs/J3_OPTIMIZER_STABILITY_001.json")
    monkeypatch.setattr(amendment, "source_paths", lambda: paths)
    return tmp_path


@pytest.mark.parametrize(
    "path",
    [
        "src/civicgate/windows_dpapi.py",
        "src/civicgate/governance/policy.py",
        "scripts/run_j3_experiment.py",
        "scripts/judge_experiment_observers.py",
        "scripts/j3_credential_amendment.py",
        "tests/fixtures/adversarial.json",
        "docs/J3_BENCHMARK_FREEZE.json",
        "docs/J3_AMENDMENT_001.json",
        "docs/J3_CREDENTIAL_ACCESS_001.json",
    ],
)
def test_dependency_tamper_fails_closed(isolated_manifest, path):
    target = isolated_manifest / path
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    with pytest.raises(runner.engine.BenchmarkAbort, match="OPTIMIZER_STABILITY_FREEZE_MISMATCH"):
        amendment.verify_amendment()


@pytest.mark.parametrize("kind", ["parent_map", "parent_commit", "allowlist", "contract", "status"])
def test_manifest_tamper_fails_closed(isolated_manifest, kind):
    manifest = json.loads(amendment.MANIFEST.read_text())
    if kind == "parent_map":
        manifest["parent_sources"]["src/civicgate/windows_dpapi.py"] = "0" * 64
    elif kind == "parent_commit":
        manifest["parent_commit"] = "0" * 40
    elif kind == "allowlist":
        manifest["allowed_modified_dependencies"].append("src/civicgate/governance/policy.py")
    elif kind == "contract":
        manifest["semantic_contract_sha256"] = "0" * 64
    else:
        manifest["status"] = "LIVE_AUTHORIZED"
    amendment.MANIFEST.write_text(json.dumps(manifest))
    with pytest.raises(runner.engine.BenchmarkAbort, match="OPTIMIZER_STABILITY_FREEZE_MISMATCH"):
        amendment.verify_amendment()


def test_manifest_rehash_cannot_hide_unapproved_dependency_change(isolated_manifest):
    manifest = json.loads(amendment.MANIFEST.read_text())
    name = "src/civicgate/governance/policy.py"
    path = isolated_manifest / name
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    manifest["source_sha256"][name] = amendment.canonical_hash(path.read_bytes())
    amendment.MANIFEST.write_text(json.dumps(manifest))
    with pytest.raises(runner.engine.BenchmarkAbort):
        amendment.verify_amendment()


def test_additional_source_cannot_hide_in_rehashed_manifest(isolated_manifest, monkeypatch):
    paths = copy.copy(amendment.source_paths())
    path = "src/civicgate/unreviewed.py"
    paths.add(path)
    (isolated_manifest / path).write_text("# unreviewed\n")
    monkeypatch.setattr(amendment, "source_paths", lambda: paths)
    manifest = json.loads(amendment.MANIFEST.read_text())
    manifest["source_sha256"] = amendment.current_hashes()
    amendment.MANIFEST.write_text(json.dumps(manifest))
    with pytest.raises(runner.engine.BenchmarkAbort):
        amendment.verify_amendment()


def test_new_seal_requires_committed_dependencies(tmp_path, monkeypatch):
    # Simulate missing Git content; source validity alone must not allow a seal.
    monkeypatch.setattr(runner.engine, "_git", lambda *args: b"not the reviewed content")
    with pytest.raises(runner.engine.BenchmarkAbort, match="UNCOMMITTED_EXPERIMENT_DEPENDENCY"):
        runner.seal("j2-luna", tmp_path / "result.json")
    assert not (tmp_path / "result.json").exists()
