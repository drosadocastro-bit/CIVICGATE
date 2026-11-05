"""Loopback HTTP → Chat controller → guarded A2/MCP/Gateway composition."""

from __future__ import annotations

import hashlib
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

pytestmark = pytest.mark.skipif(
    not os.environ.get("CIVICGATE_SYNTHETIC_WORKER_PYTHON"),
    reason="Explicit existing synthetic MCP worker environment required",
)
ROOT = Path(__file__).resolve().parents[2]
CASES = (
    ("Show public federal awards in Puerto Rico during FY2026.", "PERMIT", 1),
    ("Blacklist this contractor from future federal work.", "DENY", 0),
    (
        "Show the five largest new FAA contract awards recorded during fiscal year 2026, ranked by reported award amount.",
        "REVIEW_REQUIRED",
        0,
    ),
)


def hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture(scope="module")
def chat_server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("mini10-chat-http")
    catalog = directory / "catalog.json"
    catalog.write_text('{"version":1,"runs":[]}\n', encoding="utf-8")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    command = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/serve_evidence_console.py"),
        "--catalog",
        str(catalog),
        "--port",
        str(port),
        "--enable-synthetic-chat",
        "--worker-python",
        os.environ["CIVICGATE_SYNTHETIC_WORKER_PYTHON"],
        "--chat-output-root",
        str(directory / "chat-output"),
        "--chat-deadline-seconds",
        "90",
        "--chat-max-turns",
        "3",
    ]
    environment = {
        key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ
    }
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    out = (directory / "server.stdout.log").open("xb")
    err = (directory / "server.stderr.log").open("xb")
    process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=out, stderr=err)
    web = httpx.Client(base_url=origin, trust_env=False, timeout=10, follow_redirects=False)
    try:
        deadline = time.monotonic() + 30
        while True:
            assert process.poll() is None, (directory / "server.stderr.log").read_text(
                errors="replace"
            )
            try:
                if web.get("/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            assert time.monotonic() < deadline
            time.sleep(0.05)
        page = web.get("/chat")
        token = re.search(r'name="civicgate-csrf" content="([^"]+)"', page.text).group(1)
        yield web, origin, token, directory
    finally:
        web.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        out.close()
        err.close()


@pytest.mark.parametrize(("prompt", "decision", "dispatches"), CASES)
def test_fresh_chat_turn_traverses_actual_a2_mcp_gateway(
    chat_server, prompt: str, decision: str, dispatches: int
) -> None:
    web, origin, token, directory = chat_server
    headers = {
        "Origin": origin,
        "X-CivicGate-CSRF": token,
        "Idempotency-Key": str(uuid.uuid4()),
    }
    response = web.post("/api/chat/turns", json={"prompt": prompt}, headers=headers)
    assert response.status_code == 202, response.text
    turn = response.json()
    deadline = time.monotonic() + 110
    while turn["status"] in {"RESERVED", "RUNNING"}:
        assert time.monotonic() < deadline
        time.sleep(0.1)
        turn = web.get("/api/chat/turns/" + turn["id"]).json()
    assert turn["status"] == "COMPLETE", turn
    assert turn["decision"] == decision
    assert turn["binding_issuances"] == turn["binding_consumptions"] == dispatches
    assert turn["backend_attempts"] == dispatches
    assert turn["request_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert turn["planner_identity"] == "SCRIPTED_SYNTHETIC_FIXTURE_NOT_GRANITE"
    evidence = web.get("/api" + turn["evidence_url"])
    assert evidence.status_code == 200
    observation = evidence.json()
    assert observation["policy"]["final_disposition"] == decision
    assert observation["graph"]["visited_nodes"] == [
        "intake",
        "discovery",
        "planner",
        "gateway",
        "result",
    ]
    assert observation["binding"]["issued_count"] == dispatches
    assert observation["binding"]["consumed_count"] == dispatches
    assert observation["backend"]["mock_transport_attempts"] == dispatches
    assert observation["custody"]["database_state"] == "CLOSED"
    before = hashes(directory / "chat-output")
    assert web.get("/chat").status_code == 200
    assert web.get("/api/chat/turns").status_code == 200
    assert web.get("/api/chat/turns/" + turn["id"]).status_code == 200
    assert hashes(directory / "chat-output") == before


def test_chat_surface_exposes_no_write_or_advisor_execution_route(chat_server) -> None:
    web, _, _, _ = chat_server
    assert web.post("/api/advisor/analyses", json={}).status_code == 405
    assert web.post("/api/write", json={}).status_code == 405
    capabilities = web.get("/api/chat/capabilities").json()
    assert capabilities["write_execution"] == "DISABLED_NOT_COMPOSED"
    assert capabilities["external_provider_execution"] == "NOT_AUTHORIZED"
