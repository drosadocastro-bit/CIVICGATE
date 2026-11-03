"""Documentary mock previews; no Gateway, provider credential or external API."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
from pathlib import Path

import httpx
import pytest
from test_reader import fixture_run, seal

from civicgate.evidence_console.anthropic_advisor_v1 import (
    AnthropicAdvisor,
    ProviderConfig,
)
from civicgate.evidence_console.evidence_advisor_v1 import (
    canonical,
    validate_report,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/preview_evidence_advisor.py"
SPEC = importlib.util.spec_from_file_location("cp1_preview_under_test", SCRIPT)
assert SPEC and SPEC.loader
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)


def identities(path):
    return {
        p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob("*")
        if p.is_file()
    }


def catalog(tmp_path, decisions=("PERMIT", "DENY", "REVIEW_REQUIRED")):
    entries = []
    for index, decision in enumerate(decisions):
        root = fixture_run(tmp_path / ("capture-" + str(index)), decision)
        entries.append(
            {"id": "capture-" + str(index), "root": str(root), "manifest_sha256": seal(root)}
        )
    path = tmp_path / "catalog.json"
    path.write_bytes(canonical({"version": 1, "runs": entries}))
    return path, entries


def test_exact_three_previews_preserve_all_inputs_without_sockets(tmp_path, monkeypatch):
    path, entries = catalog(tmp_path)
    before = {entry["id"]: identities(Path(entry["root"])) for entry in entries}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No network access is allowed for a preview")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    output = tmp_path / "previews"
    result = preview.prepare_preview(path, output)
    assert result["status"] == "DRAFT_NOT_AUTHORIZATION"
    assert result["paid_execution"] == "NOT_AUTHORIZED"
    assert result["real_model_id"] is None and result["remaining_credits"] == "UNKNOWN"
    assert result["maximum_authorized_cost_usd"] is None
    assert result["mock_requests"] == 3 and result["new_mcp_calls"] == 0
    assert len(result["files"]) == 9
    assert len(list(output.iterdir())) == 10
    for row in result["files"]:
        raw = (output / row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
        assert str(tmp_path).encode() not in raw
        assert b"SYNTHETIC_OBSERVATION" not in raw and b"SYNTHETIC_BUDGET" not in raw
        assert b"Show public federal awards." not in raw
    for name, decision in preview.SCENARIOS.items():
        projection = json.loads((output / (decision + ".projection.json")).read_bytes())
        report = json.loads((output / (decision + ".mock-report.json")).read_bytes())
        assert validate_report(report, projection) == report
        assert any(
            f["name"] == "policy.final_disposition" and f["value"] == name
            for f in projection["facts"]
        )
        wire = json.loads((output / (decision + ".mock-messages-request.json")).read_bytes())
        assert set(wire) == {"model", "max_tokens", "system", "messages"}
        assert wire["model"] == "synthetic-claude-advisor-v1"
        assert wire["max_tokens"] == 2048
        assert json.loads(wire["messages"][0]["content"]) == projection
    assert {entry["id"]: identities(Path(entry["root"])) for entry in entries} == before


def test_wire_preview_matches_actual_adapter_serialization():
    payload = {"version": 1, "observation_id": "obs-1", "unicode_fixture": "é"}
    config = ProviderConfig(model="synthetic-parity-v1")
    seen = []

    def handler(request):
        seen.append(request.content)
        return httpx.Response(
            200,
            json={
                "type": "message",
                "role": "assistant",
                "model": config.model,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "{}"}],
            },
        )

    adapter = AnthropicAdvisor(config, transport=httpx.MockTransport(handler))
    adapter.analyze(payload)
    assert seen == [preview.mock_messages_wire(payload, config)]
    assert b"\\u00e9" in seen[0]
    assert b"x-api-key" not in seen[0] and b"synthetic-not-a-credential" not in seen[0]


@pytest.mark.parametrize(
    "decisions",
    [
        ("PERMIT",),
        ("PERMIT", "DENY"),
        ("PERMIT", "DENY", "PERMIT"),
        ("PERMIT", "DENY", "REVIEW_REQUIRED", "DENY"),
    ],
)
def test_missing_or_duplicate_scenarios_fail_without_output(tmp_path, decisions):
    path, _ = catalog(tmp_path, decisions)
    output = tmp_path / "previews"
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(path, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "value",
    [
        b"{}",
        b"null",
        b"{",
        b'{"version":1,"version":1,"runs":[]}',
        b'{"version":1,"runs":[]}',
        b'{"version":true,"runs":[]}',
        b" " * 16385,
    ],
)
def test_malformed_catalog_fails_without_output(tmp_path, value):
    path = tmp_path / "catalog.json"
    path.write_bytes(value)
    output = tmp_path / "previews"
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(path, output)
    assert not output.exists() and path.read_bytes() == value


def test_output_is_never_overwritten(tmp_path):
    path, _ = catalog(tmp_path)
    output = tmp_path / "previews"
    preview.prepare_preview(path, output)
    before = identities(output)
    with pytest.raises(preview.PreviewError, match="PREVIEW_FRESH_OUTPUT_REQUIRED"):
        preview.prepare_preview(path, output)
    assert identities(output) == before


def test_output_inside_input_is_rejected_before_write(tmp_path):
    path, entries = catalog(tmp_path)
    root = Path(entries[0]["root"])
    before = identities(root)
    with pytest.raises(preview.PreviewError, match="PREVIEW_OUTPUT_OVERLAP"):
        preview.prepare_preview(path, root / "previews")
    assert identities(root) == before


def test_repository_output_is_rejected(tmp_path):
    path, _ = catalog(tmp_path)
    target = preview.ROOT / "never-create-preview"
    assert not target.exists()
    with pytest.raises(preview.PreviewError, match="PREVIEW_OUTPUT_OVERLAP"):
        preview.prepare_preview(path, target)
    assert not target.exists()


def test_relative_and_unc_output_are_rejected(tmp_path):
    path, _ = catalog(tmp_path)
    for target in (Path("relative"), Path(r"\\untrusted\share\preview")):
        with pytest.raises(preview.PreviewError):
            preview.prepare_preview(path, target)


def test_tampered_manifest_identity_rejected(tmp_path):
    path, entries = catalog(tmp_path)
    root = Path(entries[0]["root"])
    with (root / "execution/cases/example/evidence/audit.jsonl").open("ab") as stream:
        stream.write(b" ")
    output = tmp_path / "previews"
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(path, output)
    assert not output.exists()


def test_cli_reports_only_stable_error(tmp_path, capsys):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_bytes(b"invalid")
    assert (
        preview.main(["--catalog", str(catalog_path), "--output-root", str(tmp_path / "previews")])
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.strip() == "PREVIEW_PREPARATION_FAILED"
    assert str(tmp_path) not in captured.err


def test_unc_catalog_rejected_before_filesystem_lookup(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("UNC catalog must be rejected before lstat")

    monkeypatch.setattr(preview, "_no_links", forbidden)
    with pytest.raises(preview.PreviewError, match="PREVIEW_CATALOG_INVALID"):
        preview._catalog(Path(r"\\untrusted\share\catalog.json"))


def test_source_change_during_mock_analysis_rejects_before_output(tmp_path, monkeypatch):
    path, entries = catalog(tmp_path)
    original = preview.MockAdvisor.analyze
    changed = False

    def mutate(self, payload):
        nonlocal changed
        reply = original(self, payload)
        if not changed:
            changed = True
            root = Path(entries[0]["root"])
            with (root / "execution/cases/example/evidence/audit.jsonl").open("ab") as stream:
                stream.write(b" ")
        return reply

    monkeypatch.setattr(preview.MockAdvisor, "analyze", mutate)
    output = tmp_path / "previews"
    with pytest.raises(preview.PreviewError):
        preview.prepare_preview(path, output)
    assert not output.exists()


def test_manifest_write_failure_preserves_partial_output_without_success(tmp_path, monkeypatch):
    path, _ = catalog(tmp_path)

    def fail_write(*_args, **_kwargs):
        raise OSError("synthetic-write-failure")

    monkeypatch.setattr(preview, "_write_new", fail_write)
    output = tmp_path / "previews"
    with pytest.raises(preview.PreviewError, match="PREVIEW_PREPARATION_FAILED"):
        preview.prepare_preview(path, output)
    assert output.is_dir() and len(list(output.iterdir())) == 9
    assert not (output / "PREVIEW_MANIFEST.json").exists()
    before = identities(output)
    with pytest.raises(preview.PreviewError, match="PREVIEW_FRESH_OUTPUT_REQUIRED"):
        preview.prepare_preview(path, output)
    assert identities(output) == before
