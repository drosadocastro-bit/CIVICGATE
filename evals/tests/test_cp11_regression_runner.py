"""Bounded regression launch metadata; no governance or provider execution."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def runner():
    spec = importlib.util.spec_from_file_location(
        "cp11_runner_test", ROOT / "scripts/run_cp11_regressions.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_original_selections():
    module = runner()
    assert module.EXPECTED == {"r32": 373, "a2": 221}
    assert len(module.SUITES["r32"]) == 6
    assert len(module.SUITES["a2"]) == 10
    assert all((ROOT / name).is_file() for paths in module.SUITES.values() for name in paths)


def test_all_supplemental_tests_match_explicit_pins():
    module = runner()
    for name, expected in module.A2_TEST_PINS.items():
        assert module.sha((ROOT / name).read_bytes()) == expected


def test_missing_junit_is_not_success(tmp_path):
    counts, rows = runner()._junit(tmp_path / "missing.xml")
    assert counts == {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 0}
    assert not rows


def test_junit_keeps_failures_errors_and_skips(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(
        '<testsuites><testsuite><testcase name="pass"/>'
        '<testcase name="fail"><failure/></testcase>'
        '<testcase name="error"><error/></testcase>'
        '<testcase name="skip"><skipped/></testcase></testsuite></testsuites>'
    )
    counts, rows = runner()._junit(path)
    assert counts == {"PASS": 1, "FAIL": 1, "ERROR": 1, "SKIP": 1}
    assert [row["name"] for row in rows] == ["pass", "fail", "error", "skip"]


def test_supplemental_source_change_is_rejected(tmp_path, monkeypatch):
    module = runner()
    fake = type("Worker", (), {"manifest_sources": lambda: []})
    monkeypatch.setattr(module, "console_worker", lambda: fake)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    name = next(iter(module.A2_TEST_PINS))
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed synthetic source")
    with pytest.raises(ValueError, match="CP11_SUPPLEMENTAL_TEST_IDENTITY_MISMATCH"):
        module.suite_sources("a2")
