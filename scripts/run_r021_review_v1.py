"""R02.1 review runner: unchanged baseline or unapplied isolated patch preview.

No production source writer, provider activation or live mode is provided.
An altered policy is permitted only in a fresh disjoint synthetic pinned copy.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open("xb") as stream:
        stream.write((json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-synthetic", action="store_true")
    parser.add_argument("--mode", choices=("baseline", "proposal", "compatibility"), required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute_synthetic:
        parser.error("explicit synthetic-only flag required")
    root = args.evidence_root.resolve()
    if root.is_relative_to(ROOT) or ROOT.is_relative_to(root):
        parser.error("source and evidence must be disjoint")
    root.mkdir(parents=True, exist_ok=False)
    execution, copy = root / "execution", root / "pinned-copy"
    execution.mkdir()
    worker = load_script("r021_existing_worker", "scripts/run_console_synthetic_demo_v2.py")
    regression = load_script("r021_existing_regressions", "scripts/run_cp11_regressions.py")
    rows = {r["path"]: dict(r) for r in regression.suite_sources("a2")}
    old_manifest = ROOT / "evals/manifests/mini09_data01_candidate_v1.json"
    if sha(old_manifest) != "4931ef717223ca9c3876a44a261d1e220feeabcc05ff0cd88220bc803755e0db":
        raise ValueError("R021_V1_MANIFEST_CHANGED")
    for row in json.loads(old_manifest.read_bytes())["files"]:
        path = ROOT / row["path"]
        if sha(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ValueError("R021_V1_CANDIDATE_CHANGED")
        rows[row["path"]] = {key: row[key] for key in ("path", "bytes", "sha256")}
    additional = [old_manifest, Path(__file__)]
    additional += list((ROOT / "evals/proposals/r021").glob("*.py"))
    additional += list((ROOT / "evals/proposals/r021").glob("*.patch"))
    additional += list((ROOT / "evals/tests").glob("test_r021_*_v1.py"))
    additional += [
        ROOT / "evals/data01" / name
        for name in (
            "benchmark_dispositions_r021_v1.json",
            "agency_scope_r021_cases_v1.json",
            "agency_scope_r021_reference_v1.json",
        )
    ]
    for path in additional:
        name = path.relative_to(ROOT).as_posix()
        rows[name] = {"path": name, "bytes": path.stat().st_size, "sha256": sha(path)}
    for name in rows:
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / name).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    save(execution / "guard-config.json", {"version": 1, "source_root": str(ROOT)})
    derivation = {"status": "UNCHANGED_BASELINE_POLICY"}
    if args.mode != "baseline":
        preview = load_script("r021_patch_derivation", "evals/proposals/r021/preview_v1.py")
        expected_patch = preview.patch_text(ROOT).encode()
        if (ROOT / "evals/proposals/r021/option_b_proposed.patch").read_bytes() != expected_patch:
            raise ValueError("R021_REVIEWED_PATCH_RENDERING_MISMATCH")
        derivation = preview.apply_to_preview(copy, ROOT)
        for name in (preview.POLICY_PATH, preview.MODULE_PATH):
            path = copy / name
            rows[name] = {"path": name, "bytes": path.stat().st_size, "sha256": sha(path)}
    save(root / "proposal-derivation.json", derivation)
    guard = execution / "guarded_run.py"
    guard.write_bytes((ROOT / "evals/demos/guarded_pytest_v2.py").read_bytes())
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "COMSPEC") if k in os.environ}
    env.update(
        PYTHONPATH=str(copy / "src") + os.pathsep + str(copy),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        TEMP=str(execution),
        TMP=str(execution),
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    selection = {
        "baseline": [
            "evals/tests/test_r021_benchmark_v1.py",
            "evals/tests/test_r021_agency_scope_v1.py",
        ],
        "proposal": ["evals/tests/test_r021_scope_fullpath_v1.py"],
        "compatibility": regression.SUITES["a2"],
    }[args.mode]
    command = [
        sys.executable,
        "-B",
        "-s",
        str(guard),
        "-p",
        "pytest_asyncio.plugin",
        "--asyncio-mode=auto",
        *selection,
    ]
    save(
        root / "command.json",
        {
            "argv": command,
            "cwd": str(copy),
            "environment": env,
            "mode": args.mode,
            "source_files": sorted(rows.values(), key=lambda r: r["path"]),
            "policy_patch_is_applied_only_to_copy": args.mode != "baseline",
        },
    )
    with (execution / "stdout.log").open("xb") as out, (execution / "stderr.log").open("xb") as err:
        process = subprocess.run(command, cwd=copy, env=env, stdout=out, stderr=err, timeout=1200)
    counts = dict(PASS=0, FAIL=0, ERROR=0, SKIP=0)
    for case in ET.parse(execution / "junit.xml").getroot().findall(".//testcase"):
        outcome = next(
            (
                label
                for tag, label in (("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP"))
                if case.find(tag) is not None
            ),
            "PASS",
        )
        counts[outcome] += 1
    facts = json.loads((execution / "guard-evidence.json").read_bytes())
    guard_ok = worker.verify_guard_identity(facts, sha(guard)) and worker.verify_guard_facts(
        facts, copy, list(rows.values())
    )
    unchanged = all(sha(copy / row["path"]) == row["sha256"] for row in rows.values())
    measurements = [
        json.loads(p.read_bytes()) for p in sorted(execution.glob("scope-cases/*/measurement.json"))
    ]
    baseline = [
        json.loads(p.read_bytes()) for p in sorted(execution.glob("cases/*/measurement.json"))
    ]
    save(
        root / "observations.json",
        {"scope_preview": measurements, "contract_disposition_baseline": baseline},
    )
    result = {
        "mode": args.mode,
        "exit_code": process.returncode,
        "counts": counts,
        "guard_verified": guard_ok,
        "source_copy_unchanged_after_derivation": unchanged,
        "baseline_observation_count": len(baseline),
        "scope_preview_observation_count": len(measurements),
        "production_policy_unchanged": sha(ROOT / "src/civicgate/governance/policy.py")
        == "50204b8374528c2f902153d9d1be83c623152d1874a754663bd3d2399549ba24",
        "proposal_applied_to_production": False,
        "operational_authorization": "HOLD",
    }
    save(root / "result.json", result)
    entries = [
        {"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
        for p in sorted(root.rglob("*"))
        if p.is_file()
    ]
    save(root / "SHA256_INVENTORY.json", {"self_excluded": True, "files": entries})
    print(json.dumps(result))
    return 0 if process.returncode == 0 and guard_ok and unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
