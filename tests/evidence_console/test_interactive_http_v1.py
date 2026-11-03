"""Real loopback HTTP → existing guarded A2/MCP/Gateway synthetic composition."""

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

import pytest

pytest.importorskip("fastapi")
import httpx

pytestmark = pytest.mark.skipif(
    not os.environ.get("CIVICGATE_SYNTHETIC_WORKER")
    or not os.environ.get("CIVICGATE_CONSOLE_TEST_CATALOG"),
    reason="Explicit local synthetic worker and preserved evidence catalog required",
)
ROOT = Path(__file__).resolve().parents[2]


def file_hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    directory = tmp_path_factory.mktemp("interactive-http")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = "http://127.0.0.1:" + str(port)
    command = [
        sys.executable,
        "-B",
        str(ROOT / "scripts/serve_evidence_console.py"),
        "--catalog",
        os.environ["CIVICGATE_CONSOLE_TEST_CATALOG"],
        "--port",
        str(port),
        "--enable-synthetic-e2e",
        "--worker-python",
        os.environ["CIVICGATE_SYNTHETIC_WORKER"],
        "--execution-root",
        str(directory / "executions"),
        "--deadline-seconds",
        "90",
        "--max-jobs",
        "6",
    ]
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    (directory / "server-command.json").write_text(json.dumps({"argv": command}, indent=2))
    out = (directory / "server-stdout.log").open("xb")
    err = (directory / "server-stderr.log").open("xb")
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err)
    web = httpx.Client(base_url=origin, trust_env=False, timeout=10, follow_redirects=False)
    try:
        deadline = time.monotonic() + 30
        while True:
            assert process.poll() is None, "Loopback console exited before ready"
            try:
                if web.get("/health").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            assert time.monotonic() < deadline, "Loopback console startup deadline"
            time.sleep(0.05)
        page = web.get("/demonstrations")
        token = re.search(r'name="civicgate-csrf" content="([^"]+)"', page.text).group(1)
        yield web, origin, token, directory
    finally:
        web.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        out.close()
        err.close()


def execute(server, scenario):
    web, origin, token, directory = server
    key = str(uuid.uuid4())
    headers = {"Origin": origin, "X-CivicGate-CSRF": token, "Idempotency-Key": key}
    response = web.post("/api/demo/executions", json={"scenario": scenario}, headers=headers)
    assert response.status_code == 202, response.text
    job = response.json()
    deadline = time.monotonic() + 110
    while job["status"] in {"RESERVED", "RUNNING"}:
        assert time.monotonic() < deadline, "Synthetic execution deadline"
        time.sleep(0.15)
        response = web.get("/api/demo/executions/" + job["id"])
        assert response.status_code == 200
        job = response.json()
    (directory / (job["id"] + "-http-receipt.json")).write_text(json.dumps(job, indent=2))
    assert job["status"] == "COMPLETE", job
    return job, key, headers


@pytest.mark.parametrize(
    "scenario,decision", [("permit", "PERMIT"), ("deny", "DENY"), ("review", "REVIEW_REQUIRED")]
)
def test_fresh_http_to_actual_pipeline(server, scenario, decision):
    web, _, _, directory = server
    job, _, _ = execute(server, scenario)
    response = web.get("/api" + job["evidence_url"])
    assert response.status_code == 200
    observation = response.json()
    assert observation["policy"]["initial_decision"] == decision
    assert observation["policy"]["final_disposition"] == decision
    assert observation["graph"]["visited_nodes"] == [
        "intake",
        "discovery",
        "planner",
        "gateway",
        "result",
    ]
    assert (
        observation["binding"]["issued_count"]
        == observation["binding"]["consumed_count"]
        == int(scenario == "permit")
    )
    assert (
        observation["backend"]["adapter_entries"]
        == observation["backend"]["mock_transport_attempts"]
        == int(scenario == "permit")
    )
    assert observation["custody"]["database_state"] == "CLOSED"
    assert observation["custody"]["returned_close_ack"] == "ACKNOWLEDGED"
    assert observation["judge"]["call_observed"] is (scenario != "deny")
    if scenario == "review":
        assert observation["judge"]["signal"]["classification"] == "IN_SCOPE"
        assert observation["judge"]["signal"]["confidence"] == 0.99
    before = file_hashes(directory / "executions")
    for _ in range(2):
        assert web.get(job["evidence_url"]).status_code == 200
        assert web.get("/api/demo/executions/" + job["id"]).json()["status"] == "COMPLETE"
    assert file_hashes(directory / "executions") == before
    (directory / (job["id"] + "-observed-view.json")).write_text(json.dumps(observation, indent=2))


def test_explicit_repeat_is_fresh_and_duplicate_request_never_redispatches(server):
    web, _, _, directory = server
    previous = web.get("/api/demo/executions").json()["jobs"]
    job, _, headers = execute(server, "permit")
    assert job["id"] not in {row["id"] for row in previous}
    assert job["observation_id"] not in {row["observation_id"] for row in previous}
    before = file_hashes(directory / "executions")
    response = web.post("/api/demo/executions", json={"scenario": "permit"}, headers=headers)
    assert response.status_code == 202
    assert response.json()["id"] == job["id"]
    assert file_hashes(directory / "executions") == before
    assert len(web.get("/api/demo/executions").json()["jobs"]) == len(previous) + 1
