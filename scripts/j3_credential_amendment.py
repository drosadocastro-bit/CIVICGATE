"""Prospective credential amendment; historical validators remain fail-closed."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = "ab561de8bf0a5cf61cc38e7f7caaba3c5861b9b0"
AMENDMENT = "J3-CREDENTIAL-ACCESS-001"
MANIFEST = ROOT / "docs/J3_CREDENTIAL_ACCESS_001.json"
# Filled from the reviewed parent's canonical dependency map, not the new checkout.
PARENT_MAP_SHA256 = "c2fa9e332e0822fcc52b4a4183b96c8b60416a996760d49aca9c73607dadb674"
ALLOWED_CHANGES = frozenset(
    {
        "src/civicgate/windows_dpapi.py",
        "scripts/dpapi_secret.py",
        "scripts/run_j3_experiment.py",
        "tests/unit/test_profiled_judge_benchmark.py",
        "tests/unit/test_j3_experiment.py",
    }
)
ADDITIONS = frozenset(
    {
        "scripts/j3_credential_amendment.py",
        "tests/unit/test_dpapi_selective.py",
        "tests/unit/test_j3_credential_amendment.py",
        "docs/J3_CREDENTIAL_ACCESS_001.md",
    }
)
HISTORICAL = ("docs/J3_BENCHMARK_FREEZE.json", "docs/J3_AMENDMENT_001.json")


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
        raise ValueError("CREDENTIAL_AMENDMENT_FREEZE_MISMATCH")


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
    except (KeyError, ValueError, OSError):
        raise runner.engine.BenchmarkAbort("CREDENTIAL_AMENDMENT_FREEZE_MISMATCH") from None
