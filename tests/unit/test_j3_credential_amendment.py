"""Prospective dependency pinning without weakening historical validators."""

import copy
import json
import shutil

import pytest

from scripts import j3_credential_amendment as amendment
from scripts import run_j3_experiment as runner


def test_current_prospective_manifest_and_both_profiles_validate():
    amendment.verify_amendment()
    for profile in runner.PROFILES:
        plan = runner.plan(profile)
        assert plan["credential_amendment"] == amendment.AMENDMENT
        assert plan["shared"]["semantic_contract_sha256"] == runner.CONTRACT_SHA256
        assert plan["shared"]["fixture_sha256"] == runner.FIXTURE_SHA256
    assert "docs/J3_CREDENTIAL_ACCESS_001.json" in runner.raw_hashes()


def test_historical_amendment_is_not_reinterpreted_as_current():
    with pytest.raises(runner.engine.BenchmarkAbort, match="VERSIONED_FREEZE_MISMATCH"):
        runner.historical.verify_manifest()


@pytest.fixture
def isolated_manifest(tmp_path, monkeypatch):
    paths = amendment.source_paths()
    for name in paths | {"docs/J3_CREDENTIAL_ACCESS_001.json"}:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(amendment.ROOT / name, target)
    monkeypatch.setattr(amendment, "ROOT", tmp_path)
    monkeypatch.setattr(amendment, "MANIFEST", tmp_path / "docs/J3_CREDENTIAL_ACCESS_001.json")
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
    ],
)
def test_dependency_tamper_fails_closed(isolated_manifest, path):
    target = isolated_manifest / path
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    with pytest.raises(runner.engine.BenchmarkAbort, match="CREDENTIAL_AMENDMENT_FREEZE_MISMATCH"):
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
    with pytest.raises(runner.engine.BenchmarkAbort, match="CREDENTIAL_AMENDMENT_FREEZE_MISMATCH"):
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
