"""Prospective optimizer-stability amendment; historical validators remain fail-closed."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = "c06550cfd235c8d3c7690ebbdbb06a3d252cb3e1"
AMENDMENT = "J3-OPTIMIZER-STABILITY-001"
MANIFEST = ROOT / "docs/J3_OPTIMIZER_STABILITY_001.json"
# Filled from the reviewed parent's canonical dependency map, not the new checkout.
PARENT_MAP_SHA256 = "7c1bcd879f20f73ca043a01b7595d9ca583772de643432ea4b4614a1ba545905"
ALLOWED_CHANGES = frozenset(
    {
        "scripts/j3_credential_amendment.py",
        "src/civicgate/llm/live.py",
        "scripts/run_j3_experiment.py",
        "tests/unit/test_j3_credential_amendment.py",
        "tests/unit/test_j3_experiment.py",
    }
)
ADDITIONS = frozenset(
    {
        "scripts/j3_optimizer_stability.py",
        "tests/unit/test_j3_optimizer_stability.py",
        "docs/J3_OPTIMIZER_STABILITY_001.md",
    }
)
HISTORICAL = (
    "docs/J3_BENCHMARK_FREEZE.json",
    "docs/J3_AMENDMENT_001.json",
    "docs/J3_CREDENTIAL_ACCESS_001.json",
)


def canonical_hash(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def map_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_paths():
    from scripts import run_j3_experiment as runner

    return (
        set(runner.parent.source_hashes())
        | set(runner.historical.NEW_SOURCES)
        | set(runner.NEW_SOURCES)
        | set(HISTORICAL)
    )


def current_hashes():
    return {p: canonical_hash((ROOT / p).read_bytes()) for p in sorted(source_paths())}


def _require(condition):
    if not condition:
        raise ValueError("OPTIMIZER_STABILITY_FREEZE_MISMATCH")


def verify_amendment():
    from scripts import run_j3_experiment as runner

    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        parent = manifest["parent_sources"]
        _require(manifest["amendment"] == AMENDMENT and manifest["parent_commit"] == PARENT)
        _require(
            manifest["status"] == "PROSPECTIVE_REQUIRES_PUBLICATION_AND_SEPARATE_LIVE_AUTHORIZATION"
        )
        _require(map_hash(parent) == PARENT_MAP_SHA256)
        _require(manifest["allowed_modified_dependencies"] == sorted(ALLOWED_CHANGES))
        _require(manifest["added_dependencies"] == sorted(ADDITIONS))
        current = current_hashes()
        _require(current == manifest["source_sha256"])
        _require(set(current) == set(parent) | ADDITIONS)
        _require({p for p in parent if current[p] != parent[p]} == ALLOWED_CHANGES)
        _require(all(current[p] == parent[p] for p in HISTORICAL))
        _require(manifest["semantic_contract_sha256"] == runner.CONTRACT_SHA256)
        _require(manifest["fixture_sha256"] == runner.FIXTURE_SHA256)
        _require(
            hashlib.sha256(runner.engine._prompt().encode()).hexdigest() == runner.CONTRACT_SHA256
        )
        _require(
            canonical_hash((ROOT / "tests/fixtures/adversarial.json").read_bytes())
            == runner.FIXTURE_SHA256
        )
    except (KeyError, ValueError, OSError, TypeError):
        raise runner.engine.BenchmarkAbort("OPTIMIZER_STABILITY_FREEZE_MISMATCH") from None
