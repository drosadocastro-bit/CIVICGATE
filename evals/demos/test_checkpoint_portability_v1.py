"""The portable publication guard still fails closed before project access."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

COPY = Path.cwd().resolve()
INVALID = ("missing", "duplicate", "extra", "relative", "overlap")


@pytest.mark.parametrize("target", ("guard", "restart"))
@pytest.mark.parametrize("mode", INVALID)
def test_invalid_guard_config_blocks_before_project_import(tmp_path, target, mode):
    layout = tmp_path / "isolated"
    copy = layout / "pinned-copy"
    execution = layout / "execution"
    copy.mkdir(parents=True)
    execution.mkdir()
    protected = tmp_path / "protected-source"
    protected.mkdir()
    if mode == "duplicate":
        raw = '{"version":1,"source_root":"x","source_root":"y"}'
    else:
        config = {"version": 1, "source_root": str(protected)}
        if mode == "extra":
            config["unexpected"] = True
        elif mode == "relative":
            config["source_root"] = "relative"
        elif mode == "overlap":
            config["source_root"] = str(copy)
        raw = json.dumps(config)
    if mode != "missing":
        (execution / "guard-config.json").write_text(raw, encoding="utf-8")
    relative = (
        "evals/demos/guarded_pytest_v1.py"
        if target == "guard"
        else "evals/tests/eval_002b_r3_1_restart_v1.py"
    )
    script = execution / "probe.py"
    script.write_bytes((COPY / relative).read_bytes())
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(copy))
    result = subprocess.run(
        [sys.executable, "-B", "-s", str(script)],
        cwd=copy,
        env=env,
        capture_output=True,
        timeout=30,
    )
    (execution / "probe.stdout.log").write_bytes(result.stdout)
    (execution / "probe.stderr.log").write_bytes(result.stderr)
    assert result.returncode != 0
    assert (
        b"GUARD_CONFIG" in result.stderr or b"ROOT" in result.stderr or b"DISJOINT" in result.stderr
    )
    assert not (execution / "guard-evidence.json").exists()
    assert not list(layout.rglob("*.sqlite"))


def test_valid_guard_preserves_source_and_nonowned_loopback_denial(tmp_path):
    layout = tmp_path / "isolated"
    copy = layout / "pinned-copy"
    execution = layout / "execution"
    copy.mkdir(parents=True)
    execution.mkdir()
    protected = tmp_path / "protected-source"
    protected.mkdir()
    marker = protected / "synthetic-source.txt"
    marker.write_text("SYNTHETIC_SOURCE", encoding="ascii")
    (copy / "isolated-pytest.ini").write_text("[pytest]\n", encoding="ascii")
    (execution / "guard-config.json").write_text(
        json.dumps({"version": 1, "source_root": str(protected)}), encoding="utf-8"
    )
    body = (
        "from pathlib import Path\nimport socket\nimport pytest\n"
        "def test_boundary():\n"
        f"    with pytest.raises(PermissionError): Path({str(marker)!r}).read_bytes()\n"
        "    with pytest.raises(PermissionError):\n"
        "        with socket.socket() as sock: sock.connect(('127.0.0.1', 1))\n"
    )
    (copy / "test_boundary.py").write_text(body, encoding="utf-8")
    guard = execution / "guarded_run.py"
    guard.write_bytes((COPY / "evals/demos/guarded_pytest_v1.py").read_bytes())
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONPATH=str(copy),
    )
    result = subprocess.run(
        [sys.executable, "-B", "-s", str(guard), "test_boundary.py"],
        cwd=copy,
        env=env,
        capture_output=True,
        timeout=30,
    )
    (execution / "probe.stdout.log").write_bytes(result.stdout)
    (execution / "probe.stderr.log").write_bytes(result.stderr)
    assert result.returncode == 0
    observed = json.loads((execution / "guard-evidence.json").read_bytes())
    assert any(not row["allowed"] for row in observed["network_events"])
