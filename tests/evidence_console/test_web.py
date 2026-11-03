"""Passive UI/API tests; documentary fixtures never invoke governed execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="Separate optional passive-console environment required")
from fastapi.testclient import TestClient
from test_reader import fixture_run, seal

from civicgate.evidence_console.app import create_app


def entry(root):
    return {"id": "example", "root": str(root), "manifest_sha256": seal(root)}


def client(entries):
    return TestClient(create_app(entries), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("decision", ["PERMIT", "DENY", "REVIEW_REQUIRED"])
def test_real_template_and_api_display_separate_facts(tmp_path, decision):
    root = fixture_run(tmp_path / "run", decision)
    config = entry(root)
    before = hashes(root)
    with client([config]) as web:
        assert web.get("/").status_code == 200
        assert web.get("/runs/example").status_code == 200
        path = "/runs/example/observations/SYNTHETIC_OBSERVATION"
        for _ in range(2):
            page = web.get(path)
            assert page.status_code == 200
            assert decision in page.text
            expected_heading = {
                "PERMIT": "Authorized read. Verified result.",
                "DENY": "Denied before execution.",
                "REVIEW_REQUIRED": "Held before execution.",
            }[decision]
            assert expected_heading in page.text
            assert "CLOSED ≠ human acceptance" in page.text
            assert "NOT_ATTEMPTED_UNSAFE_OR_INCOMPLETE" in page.text
            assert "ACKNOWLEDGED" in page.text
            assert "UNKNOWN" in page.text  # Effective real model identity.
            assert "http://" not in page.text and "https://" not in page.text
            value = web.get("/api" + path).json()
            assert value["policy"]["final_disposition"] == decision
            assert value["binding"]["consumed_count"] == int(decision == "PERMIT")
            assert value["backend"]["mock_transport_attempts"] == int(decision == "PERMIT")
            assert value["judge"]["call_observed"] is (decision != "DENY")
        assert web.get("/assets/console.css").status_code == 200
        assert web.get("/assets/console.js").status_code == 200
    assert hashes(root) == before


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD", "TRACE"])
def test_mutating_or_unsupported_methods_cannot_reach_store(tmp_path, method, monkeypatch):
    root = fixture_run(tmp_path / "run")
    config = entry(root)
    from civicgate.evidence_console.reader import EvidenceStore

    def prohibited(*args, **kwargs):
        raise AssertionError("Evidence read must not occur for this method")

    monkeypatch.setattr(EvidenceStore, "list_runs", prohibited)
    with client([config]) as web:
        response = web.request(method, "/api/runs")
        assert response.status_code == 405
        assert response.headers["Allow"] == "GET"


@pytest.mark.parametrize(
    "path",
    [
        "/api/runs/missing",
        "/api/runs/example/observations/missing",
        "/runs/%2e%2e%2fprivate",
        "/runs/%252e%252e%252fprivate",
        "/runs/C%3A%5Cprivate",
        "/assets/%2e%2e/reader.py",
        "/assets/%2e%2e%2freader.py",
        "/assets/templates/base.html",
        "/openapi.json",
        "/docs",
        "/execute",
        "/retry",
        "/accept",
        "/files",
    ],
)
def test_unknown_paths_never_browse_or_execute(tmp_path, path):
    root = fixture_run(tmp_path / "run")
    with client([entry(root)]) as web:
        response = web.get(path)
        assert response.status_code == 404
        assert str(root) not in response.text
        assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Host": "127.0.0.1.evil.example"},
        {"Host": "localhost@evil.example"},
        {"Host": "127.0.0.1", "Origin": "https://evil.example"},
        {"Host": "127.0.0.1", "Origin": "null"},
        {"Host": "127.0.0.1", "Origin": "http://[malformed"},
        {"Host": "127.0.0.1", "Sec-Fetch-Site": "cross-site"},
        {"Host": "127.0.0.1", "Sec-Fetch-Site": "same-site"},
        [("Host", "127.0.0.1"), ("Host", "localhost")],
        [("Origin", "http://127.0.0.1"), ("Origin", "http://evil.example")],
    ],
)
def test_host_origin_and_cross_site_fail_closed(headers):
    with client([]) as web:
        assert web.get("/health", headers=headers).status_code == 403


def test_untrusted_forwarded_headers_do_not_change_client_or_authority():
    web = TestClient(create_app([]), base_url="http://127.0.0.1", client=("192.0.2.40", 50000))
    with web:
        response = web.get(
            "/health", headers={"X-Forwarded-For": "127.0.0.1", "X-Forwarded-Host": "localhost"}
        )
        assert response.status_code == 403


def test_headers_and_frontend_are_local_and_non_authorizing():
    with client([]) as web:
        response = web.get("/", headers={"Origin": "http://127.0.0.1"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        js = web.get("/assets/console.js").text
        assert "fetch(" not in js and "localStorage" not in js and "innerHTML" not in js
        assert "http://" not in response.text and "https://" not in response.text
        assert web.get("/health").json()["execution_authority"] is False


def test_missing_evidence_cannot_look_successful(tmp_path):
    root = fixture_run(tmp_path / "run")
    config = entry(root)
    (root / "execution/cases/example/evidence/dispatch.jsonl").unlink()
    with client([config]) as web:
        value = web.get("/api/runs/example").json()
        assert value["integrity"] == "UNKNOWN"
        assert all(item is None for item in value["distribution"].values())
        assert value["observations"] == []
        page = web.get("/runs/example")
        assert "Evidence incomplete" in page.text
        assert '<span class="custody-status">CLOSED</span>' not in page.text


def test_post_dispatch_review_is_not_rewritten_as_pre_dispatch_hold(tmp_path, monkeypatch):
    root = fixture_run(tmp_path / "run")
    config = entry(root)
    from civicgate.evidence_console.reader import EvidenceStore

    observed = EvidenceStore([config]).get_observation("example", "SYNTHETIC_OBSERVATION")
    # Presentation-only control. No transition, policy evaluation or new evidence is issued.
    observed["policy"]["final_disposition"] = "REVIEW_REQUIRED"
    observed["result"]["verification_state"] = "UNVERIFIED"
    observed["result"]["value"] = None
    monkeypatch.setattr(EvidenceStore, "get_observation", lambda *args: observed)
    with client([config]) as web:
        page = web.get("/runs/example/observations/SYNTHETIC_OBSERVATION").text
        assert "Review required." in page
        assert "Held before execution." not in page
        assert "REQUEST_CONFIRMED" in page
        assert "PERMIT" in page


def test_rendered_text_is_escaped_and_redacted(tmp_path):
    root = fixture_run(tmp_path / "run")
    attack = "<img src=x onerror=alert(1)> Bearer TEST_ONLY_CREDENTIAL /home/private/secret"
    files = list(root.rglob("*.json")) + list(root.rglob("*.jsonl"))
    for path in files:
        raw = path.read_text()
        # Preserve cross-document identity consistently, without execution.
        raw = raw.replace("Show public federal awards.", attack)
        # Original-request hash fields must match the changed request.
        old_hash = hashlib.sha256(b"Show public federal awards.").hexdigest()
        raw = raw.replace(old_hash, hashlib.sha256(attack.encode()).hexdigest())
        path.write_text(raw)
    with client([entry(root)]) as web:
        response = web.get("/runs/example/observations/SYNTHETIC_OBSERVATION")
        assert response.status_code == 200
        assert "<img src=x" not in response.text
        assert "TEST_ONLY_CREDENTIAL" not in response.text
        assert "/home/private/secret" not in response.text
        assert "onerror=alert(1)" not in response.text or "&lt;img" in response.text
        assert "REDACTED" in response.text


def test_view_does_not_import_execution_stack_or_contact_network(tmp_path, monkeypatch):
    root = fixture_run(tmp_path / "run")
    config = entry(root)

    def no_send(*args, **kwargs):
        raise AssertionError("Console cannot send")

    with client([config]) as web:
        # Windows constructs its asyncio self-pipe before observation starts.
        # Deny every connect during actual console reads, then restore before shutdown.
        with monkeypatch.context() as scoped:
            scoped.setattr(socket.socket, "connect", no_send)
            assert web.get("/api/runs").status_code == 200
            assert web.get("/runs/example/observations/SYNTHETIC_OBSERVATION").status_code == 200
    assert not any(
        name.startswith(("civicgate.mcp", "civicgate.governance", "evals.harness"))
        for name in sys.modules
    )


def test_cli_catalog_contract_and_no_host_override(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/serve_evidence_console.py"
    spec = importlib.util.spec_from_file_location("console_cli_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"version":1,"version":1,"runs":[]}')
    with pytest.raises(ValueError):
        module.load_catalog(catalog)
    catalog.write_text('{"version":true,"runs":[]}')
    with pytest.raises(ValueError):
        module.load_catalog(catalog)
    help_result = subprocess.run(
        [sys.executable, "-B", str(path), "--help"], capture_output=True, text=True, timeout=10
    )
    assert help_result.returncode == 0
    assert "--host" not in help_result.stdout and "--execute" not in help_result.stdout


def test_genuine_preserved_mini071_mini072_views_leave_all_evidence_unchanged():
    catalog_path = os.environ.get("CIVICGATE_CONSOLE_TEST_CATALOG")
    if not catalog_path:
        pytest.skip("Operator-selected genuine local catalog not configured")
    entries = json.loads(Path(catalog_path).read_bytes())["runs"]
    before = {item["id"]: hashes(Path(item["root"])) for item in entries}
    with client(entries) as web:
        assert web.get("/").status_code == 200
        for item in entries:
            run = web.get("/api/runs/" + item["id"]).json()
            assert run["distribution"] == {
                "PERMIT": 1,
                "DENY": 1,
                "REVIEW_REQUIRED": 1,
                "UNKNOWN": 0,
            }
            for observation in run["observations"]:
                path = f"/runs/{item['id']}/observations/{observation['id']}"
                assert web.get(path).status_code == web.get(path).status_code == 200
                value = web.get("/api" + path).json()
                assert value["custody"]["database_state"] == "CLOSED"
                assert value["backend"]["adapter_entries"] == int(observation["case"] == "permit")
                if item["id"] == "mini071":
                    assert value["graph"]["state"] == "UNKNOWN"
    assert before == {item["id"]: hashes(Path(item["root"])) for item in entries}
