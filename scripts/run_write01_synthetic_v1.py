"""Pinned-copy WRITE-01 tests and three real MCP synthetic demonstrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def identity(path: Path, relative_to: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-synthetic", action="store_true")
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.evidence_root.resolve()
    if not args.execute_synthetic or root.is_relative_to(ROOT) or ROOT.is_relative_to(root):
        parser.error("explicit synthetic execution and a separate fresh evidence path required")
    root.mkdir(parents=True, exist_ok=False)
    copy, execution = root / "pinned-copy", root / "execution"
    execution.mkdir()
    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    names = {
        name
        for name in tracked
        if name.endswith(".py") and name.startswith(("src/", "evals/harness/", "evals/demos/"))
    }
    names |= {p.relative_to(ROOT).as_posix() for p in (ROOT / "evals/write01").glob("*.py")}
    names |= {
        p.relative_to(ROOT).as_posix() for p in (ROOT / "evals/tests").glob("test_write01_*_v1.py")
    }
    names |= {"evals/data01/awards_v1.json"}
    # The fixture guard imports evidence harness models. No evaluation dataset,
    # human label, private record or holdout is copied into this selection.
    names |= {"tests/mcp/test_a2_stdio.py", "tests/mcp/a2_stdio_fixture.py"}
    sources = []
    for name in sorted(names):
        path = ROOT / name
        sources.append(identity(path, ROOT))
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(path.read_bytes())
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    save(execution / "guard-config.json", {"version": 1, "source_root": str(ROOT)})
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
    selection = sorted(name for name in names if name.startswith("evals/tests/"))
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
            "sources": sources,
            "runner": identity(Path(__file__), ROOT),
        },
    )
    with (execution / "stdout.log").open("xb") as out, (execution / "stderr.log").open("xb") as err:
        process = subprocess.run(command, cwd=copy, env=env, stdout=out, stderr=err, timeout=900)
    counts = dict(PASS=0, FAIL=0, ERROR=0, SKIP=0)
    if (execution / "junit.xml").exists():
        for case in ET.parse(execution / "junit.xml").getroot().findall(".//testcase"):
            label = next(
                (
                    label
                    for tag, label in (("failure", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP"))
                    if case.find(tag) is not None
                ),
                "PASS",
            )
            counts[label] += 1
    inventory = [identity(p, root) for p in sorted(root.rglob("*")) if p.is_file()]
    ready = (
        process.returncode == 0
        and counts["PASS"] > 0
        and not any(counts[k] for k in ("FAIL", "ERROR", "SKIP"))
    )
    save(
        root / "result.json",
        {
            "returncode": process.returncode,
            "counts": counts,
            "test_selection": selection,
            "disposition": "OFFLINE_SELECTION_PASS" if ready else "WRITE01_HOLD",
            "files": inventory,
            "self_excluded": True,
            "not_human_acceptance": True,
            "durable_stop": "PARTIAL",
        },
    )
    print(json.dumps({"counts": counts, "evidence_root": str(root), "ready": ready}))
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
