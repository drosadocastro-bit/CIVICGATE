"""Real loopback HTTP with the genuine three-scenario MINI08.1 evidence catalog.

Only the mock Messages adapter runs. Reading these captures cannot run their
historical Gateway operations. No model, API credential or provider is used.
"""

from __future__ import annotations

import hashlib
import json
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

pytestmark = pytest.mark.skipif(
    not os.environ.get("CIVICGATE_ADVISOR_TEST_CATALOG"),
    reason="Explicit preserved local synthetic catalog required",
)
ROOT = Path(__file__).resolve().parents[2]


def identities(roots):
    return {
        (str(root), file.relative_to(root).as_posix()): hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
        for root in roots
        for file in root.rglob("*")
        if file.is_file()
    }


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("advisor-http")
    catalog = Path(os.environ["CIVICGATE_ADVISOR_TEST_CATALOG"])
    entries = json.loads(catalog.read_bytes())["runs"]
    roots = [Path(entry["root"]) for entry in entries]
    before = identities(roots)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = "http://127.0.0.1:" + str(port)
    command = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/serve_evidence_console.py"),
        "--catalog",
        str(catalog),
        "--port",
        str(port),
        "--advisor-mode",
        "mock",
        "--advisor-output-root",
        str(directory / "analyses"),
    ]
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    (directory / "command.json").write_text(json.dumps({"argv": command}, indent=2))
    out = (directory / "stdout.log").open("xb")
    err = (directory / "stderr.log").open("xb")
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err)
    web = httpx.Client(base_url=origin, trust_env=False, timeout=15, follow_redirects=False)
    try:
        deadline = time.monotonic() + 30
        while True:
            assert process.poll() is None, "Advisor console exited before ready"
            try:
                if web.get("/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            assert time.monotonic() < deadline
            time.sleep(0.05)
        runs = web.get("/api/runs").json()["runs"]
        observations = {
            observation["decision"]: (run["id"], observation["id"])
            for run in runs
            for observation in run["observations"]
        }
        assert set(observations) == {"PERMIT", "DENY", "REVIEW_REQUIRED"}
        yield web, origin, directory, observations
        assert identities(roots) == before
        (directory / "evidence-preservation.json").write_text(
            json.dumps({"files": len(before), "unchanged": True})
        )
    finally:
        web.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        out.close()
        err.close()


@pytest.mark.parametrize("decision", ["PERMIT", "DENY", "REVIEW_REQUIRED"])
def test_real_http_selected_genuine_evidence_to_mock_advisor(server, decision):
    web, origin, directory, observations = server
    run_id, observation_id = observations[decision]
    path = f"/runs/{run_id}/observations/{observation_id}"
    before = web.get("/api" + path).json()
    assert before["integrity"] == "VERIFIED"
    page = web.get(path)
    assert page.status_code == 200 and "Analyze Evidence" in page.text
    token = re.search(r'name="civicgate-advisor-csrf" content="([^"]+)"', page.text)[1]
    headers = {"Origin": origin, "X-CivicGate-CSRF": token, "Idempotency-Key": str(uuid.uuid4())}
    response = web.post(
        "/api/advisor/analyses",
        json={"run_id": run_id, "observation_id": observation_id},
        headers=headers,
    )
    assert response.status_code == 202
    job = response.json()
    deadline = time.monotonic() + 20
    while job["status"] in {"IDLE", "RUNNING"}:
        assert time.monotonic() < deadline
        time.sleep(0.05)
        job = web.get("/api/advisor/analyses/" + job["id"]).json()
    assert job["status"] == "COMPLETE", job
    assert job["reference_validation"] == "RESOLVED_NOT_SEMANTIC_VERIFICATION"
    assert job["semantic_verification"] == "NOT_ESTABLISHED"
    assert job["execution_authority"] is False
    assert job["model"] == "synthetic-claude-advisor-v1"
    assert any(
        fact["name"] == "policy.final_disposition" and fact["value"] == decision
        for fact in job["facts"]
    )
    assert any(
        fact["name"] == "binding.consumed_count" and fact["value"] == int(decision == "PERMIT")
        for fact in job["facts"]
    )
    (directory / (decision + "-observed-report.json")).write_text(json.dumps(job, indent=2))
    files = identities([directory / "analyses"])
    duplicate = web.post(
        "/api/advisor/analyses",
        json={"run_id": run_id, "observation_id": observation_id},
        headers=headers,
    )
    assert duplicate.status_code == 202 and duplicate.json()["id"] == job["id"]
    assert identities([directory / "analyses"]) == files
    for _ in range(2):
        assert web.get(path).status_code == 200
        assert web.get("/api" + path).json() == before
    assert identities([directory / "analyses"]) == files


def test_real_http_no_unauthorized_analysis_or_execution(server):
    web, origin, directory, _ = server
    before = identities([directory / "analyses"])
    assert web.post("/api/advisor/analyses", json={}).status_code == 403
    assert (
        web.post(
            "/api/advisor/analyses", headers={"Origin": "http://invalid.example"}, json={}
        ).status_code
        == 403
    )
    assert web.post("/api/demo/executions", json={}).status_code == 405
    assert web.get("/api/demo/executions").status_code == 404
    assert web.get("/api/advisor/analyses/%2e%2e%2fprivate").status_code == 404
    assert identities([directory / "analyses"]) == before
