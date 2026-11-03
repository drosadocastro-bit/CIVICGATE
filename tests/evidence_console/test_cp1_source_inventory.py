"""Current-main source bridge is additive and never rewrites historical identities."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def worker():
    spec = importlib.util.spec_from_file_location(
        "cp1_worker", ROOT / "scripts/run_console_synthetic_demo_v1.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_main_inventory_is_explicit_and_preserves_historical(tmp_path, monkeypatch):
    historical = ROOT / "evals/manifests/gsa_local_demo_checkpoint_v1.json"
    before = historical.read_bytes()
    # The historical 111-file contract refers to main's original V2, not the
    # separately versioned CP1.1 import facade. Keep every original assertion;
    # give this historical check its actual pinned source context.
    module = worker()
    fixture = tmp_path / "cp1-baseline"
    inventory = ROOT / "evals/manifests/mini08_cp1_console_sources_v1.json"
    for row in json.loads(inventory.read_bytes())["source_files"]:
        origin = ROOT / row["path"]
        if row["path"] == "evals/harness/governance_observer_v2.py":
            origin = ROOT / "evals/harness/governance_observer_v2_reference.py"
        target = fixture / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(origin.read_bytes())
    target = fixture / inventory.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(inventory.read_bytes())
    old_manifest = fixture / historical.relative_to(ROOT)
    old_manifest.write_bytes(before)
    monkeypatch.setattr(module, "ROOT", fixture)
    rows = module.manifest_sources()
    assert len(rows) == 111
    prior = json.loads(before)["source_files"]
    old = {row["path"]: row for row in prior}
    changed = [
        r["path"] for r in rows if r["path"] in old and old[r["path"]]["sha256"] != r["sha256"]
    ]
    assert set(changed) == {
        "src/civicgate/governance/execution.py",
        "src/civicgate/governance/policy.py",
        "src/civicgate/governance/request_risk.py",
        "src/civicgate/mcp/discovery.py",
        "src/civicgate/mcp/tools.py",
    }
    assert {r["path"] for r in rows} - set(old) == {
        "src/civicgate/channel_b/invocation_contract_v1.py"
    }
    assert historical.read_bytes() == before


def test_changed_source_is_rejected_without_repinning(tmp_path, monkeypatch):
    module = worker()
    fixture = tmp_path / "fixture"
    manifest = fixture / "evals/manifests/mini08_cp1_console_sources_v1.json"
    manifest.parent.mkdir(parents=True)
    value = json.loads((ROOT / "evals/manifests/mini08_cp1_console_sources_v1.json").read_bytes())
    historical = fixture / "evals/manifests/gsa_local_demo_checkpoint_v1.json"
    historical.write_bytes(
        (ROOT / "evals/manifests/gsa_local_demo_checkpoint_v1.json").read_bytes()
    )
    value["source_files"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(value))
    target = fixture / value["source_files"][0]["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / value["source_files"][0]["path"]).read_bytes())
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "ROOT", fixture)
    with pytest.raises(ValueError, match="CP1_SOURCE_IDENTITY_MISMATCH"):
        module.manifest_sources()
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before


def test_empty_catalog_requires_explicit_synthetic_opt_in(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "cp1_console_cli", ROOT / "scripts/serve_evidence_console.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"version":1,"runs":[]}')
    with pytest.raises(ValueError, match="INVALID_CATALOG"):
        module.load_catalog(catalog)
    assert module.load_catalog(catalog, allow_empty=True) == []
