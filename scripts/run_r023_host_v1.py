"""Run the fixed trusted-host FAA topology and a separate legacy host control.

Synthetic/offline only. This does not modify or activate the legacy server,
publish a contract, authenticate a human or grant a real operation.
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


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-synthetic", action="store_true")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--selection", choices=("unit", "fullpath", "all"), default="all")
    args = parser.parse_args()
    if not args.execute_synthetic:
        parser.error("explicit synthetic-only execution flag required")
    root = args.evidence_root.resolve()
    if root.is_relative_to(ROOT) or ROOT.is_relative_to(root):
        parser.error("source and generated evidence must be disjoint")
    root.mkdir(parents=True, exist_ok=False)
    execution, copy = root / "execution", root / "pinned-copy"
    execution.mkdir()
    worker = module("r023_original_console_worker", "scripts/run_console_synthetic_demo_v2.py")
    sources = {row["path"]: dict(row) for row in worker.manifest_sources()}
    for name, expected in (
        (
            "evals/manifests/mini09_data01_candidate_v1.json",
            "4931ef717223ca9c3876a44a261d1e220feeabcc05ff0cd88220bc803755e0db",
        ),
        (
            "evals/manifests/mini09_r021_candidate_v1.json",
            "5ec5f8146bcc60da2256f178ce9c735656b1450422eb7f865683f9670546d290",
        ),
        (
            "evals/manifests/mini09_r022_candidate_v1.json",
            "087be0c817f4261194381a6ea05fb2071eb696d5e83b6987e1aef4f59ba43b9d",
        ),
    ):
        path = ROOT / name
        if sha(path) != expected:
            raise ValueError("R023_PRIOR_MANIFEST_CHANGED")
        manifest = json.loads(path.read_bytes())
        for row in manifest["files"]:
            p = ROOT / row["path"]
            if sha(p) != row["sha256"] or p.stat().st_size != row["bytes"]:
                raise ValueError("R023_PRIOR_CANDIDATE_CHANGED")
            sources[row["path"]] = {key: row[key] for key in ("path", "bytes", "sha256")}
        sources[name] = {"path": name, "bytes": path.stat().st_size, "sha256": expected}
    # Source code only. No historical dataset/holdout directory is globbed.
    original = subprocess.check_output(["git", "ls-files", "src"], cwd=ROOT, text=True).splitlines()
    additions = [ROOT / p for p in original if p.endswith(".py")]
    additions += list((ROOT / "evals/proposals/r023").glob("*.py"))
    additions += list((ROOT / "evals/proposals/r023").glob("*.json"))
    additions += list((ROOT / "evals/tests").glob("test_r023_*_v1.py"))
    additions += list((ROOT / "evals/data01").glob("r023_*_v1.json"))
    additions += [Path(__file__)]
    for path in additions:
        name = path.relative_to(ROOT).as_posix()
        sources[name] = {"path": name, "bytes": path.stat().st_size, "sha256": sha(path)}
    for name in sources:
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write((ROOT / name).read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    save(execution / "guard-config.json", {"version": 1, "source_root": str(ROOT)})
    guard = execution / "guarded_run.py"
    guard.write_bytes((ROOT / "evals/demos/guarded_pytest_v2.py").read_bytes())
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
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
    paths = sorted((copy / "evals/tests").glob("test_r023_*_v1.py"))
    selection = [
        p.relative_to(copy).as_posix()
        for p in paths
        if args.selection == "all" or ("fullpath" in p.name) == (args.selection == "fullpath")
    ]
    if not selection:
        raise ValueError("R023_EMPTY_SELECTION")
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
            "sources": sorted(sources.values(), key=lambda row: row["path"]),
            "scope": "ISOLATED_SYNTHETIC_PROFILE_NO_PRODUCTION_PATCH",
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
    observations = [
        json.loads(p.read_bytes()) for p in sorted(execution.glob("r023-cases/*/measurement.json"))
    ]
    case_doc = json.loads((ROOT / "evals/data01/r023_cases_v1.json").read_bytes())
    cases = case_doc["cases"]
    ids = [r["case_id"] for r in observations]
    expected = (
        ({r["case_id"] for r in cases} | {case_doc["separate_legacy_control_case_id"]})
        if args.selection != "unit"
        else set()
    )
    exact = len(ids) == len(set(ids)) and set(ids) == expected
    facts = json.loads((execution / "guard-evidence.json").read_bytes())
    guard_ok = worker.verify_guard_identity(facts, sha(guard)) and worker.verify_guard_facts(
        facts, copy, list(sources.values())
    )
    unchanged = all(sha(copy / row["path"]) == row["sha256"] for row in sources.values())
    result = {
        "counts": counts,
        "exit_code": process.returncode,
        "guard_verified": guard_ok,
        "source_copy_unchanged": unchanged,
        "observation_inventory_exact": exact,
        "expected_observations": len(expected),
        "actual_observations": len(ids),
        "agent_paths_strict_or_startup_refused": all(
            r.get("host_path_verified") is True
            and r.get("fixed_target_module") == "evals.proposals.r023.observation_v1"
            and r.get("legacy_routes_offered_to_agent") == []
            and (
                r.get("primary_projection_verified") is True
                or r.get("startup_refusal_verified_no_gateway_projection") is True
            )
            for r in observations
            if r["case_id"] != case_doc["separate_legacy_control_case_id"]
        ),
        "legacy_control_separately_host_composed": any(
            r["case_id"] == case_doc["separate_legacy_control_case_id"]
            and r["initial_policy"] == "PERMIT"
            for r in observations
        ),
        "production_sources_modified": False,
        "live_execution_authorization": "HOLD",
    }
    result["final_disposition"] = (
        "FAA_HOST_COMPOSITION_READY_FOR_HUMAN_REVIEW"
        if args.selection != "unit"
        and process.returncode == 0
        and counts["SKIP"] == 0
        and exact
        and guard_ok
        and unchanged
        and result["agent_paths_strict_or_startup_refused"]
        and result["legacy_control_separately_host_composed"]
        else "UNIT_SELECTION_ONLY"
        if args.selection == "unit" and process.returncode == 0
        else "FAA_SEMANTIC_HOLD"
    )
    save(root / "observations.json", observations)
    save(root / "result.json", result)
    save(
        root / "SHA256_INVENTORY.json",
        {
            "self_excluded": True,
            "files": [
                {
                    "path": p.relative_to(root).as_posix(),
                    "bytes": p.stat().st_size,
                    "sha256": sha(p),
                }
                for p in sorted(root.rglob("*"))
                if p.is_file()
            ],
        },
    )
    print(json.dumps(result))
    return (
        0
        if process.returncode == 0 and guard_ok and unchanged and exact and counts["SKIP"] == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
