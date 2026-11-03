"""Current CP1.1 pins are separate from the preserved historical source contracts."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_cp11_sources_bind_actual_versioned_observer_and_frozen_reference():
    spec = importlib.util.spec_from_file_location(
        "cp11_worker", ROOT / "scripts/run_console_synthetic_demo_v2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.manifest_sources()
    assert len(rows) == 113
    mapping = {r["path"]: r for r in rows}
    assert (
        mapping["evals/harness/governance_observer_v2_reference.py"]["sha256"]
        == "0e71f86c8a70a110f9db18d00c8429e98890433deaac21199f27a4d9989add94"
    )
    for name in ["governance_observer_v2.py", "governance_observer_v3.py"]:
        path = "evals/harness/" + name
        assert mapping[path]["sha256"] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    historical = json.loads(
        (ROOT / "evals/manifests/mini08_cp1_console_sources_v1.json").read_bytes()
    )
    assert len(historical["source_files"]) == 111
    assert (
        next(
            r
            for r in historical["source_files"]
            if r["path"] == "evals/harness/governance_observer_v2.py"
        )["sha256"]
        == mapping["evals/harness/governance_observer_v2_reference.py"]["sha256"]
    )


def test_cp11_modified_source_rejects_without_altering_its_pin(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "cp11_worker_negative", ROOT / "scripts/run_console_synthetic_demo_v2.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = tmp_path / "fixture"
    target = fixture / "evals/manifests"
    target.mkdir(parents=True)
    for name in ["gsa_local_demo_checkpoint_v1.json", "mini08_cp1_console_sources_v1.json"]:
        (target / name).write_bytes((ROOT / "evals/manifests" / name).read_bytes())
    value = json.loads((ROOT / "evals/manifests/mini08_cp11_console_sources_v1.json").read_bytes())
    row = value["source_files"][0]
    source = fixture / row["path"]
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes((ROOT / row["path"]).read_bytes() + b"# synthetic tamper")
    pin = target / "mini08_cp11_console_sources_v1.json"
    pin.write_text(json.dumps(value))
    before = pin.read_bytes()
    monkeypatch.setattr(module, "ROOT", fixture)
    with pytest.raises(ValueError, match="CP11_SOURCE_IDENTITY_MISMATCH"):
        module.manifest_sources()
    assert pin.read_bytes() == before
