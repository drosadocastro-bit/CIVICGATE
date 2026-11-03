"""Ingress contracts use a counting executor, not simulated Gateway verdicts."""

from __future__ import annotations

import re
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from civicgate.evidence_console.app import create_app


class CountingExecutor:
    def __init__(self):
        self.submissions = []
        self.stopped = False

    def submit(self, scenario, key):
        self.submissions.append((scenario, key))
        return {
            "id": uuid.uuid4().hex,
            "scenario": scenario,
            "status": "RESERVED",
            "run_id": None,
            "observation_id": None,
            "evidence_url": None,
        }

    def list_jobs(self):
        return []

    def get_job(self, job_id):
        from civicgate.evidence_console.demo_execution_v1 import DemoError

        raise DemoError("UNKNOWN_JOB", 404)

    def evidence_entries(self):
        return []

    def capabilities(self):
        return {"mode": "SYNTHETIC_E2E_ONLY", "concurrency": 1}

    def shutdown(self):
        self.stopped = True


@pytest.fixture
def interactive():
    executor = CountingExecutor()
    with TestClient(
        create_app([], executor=executor),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as web:
        page = web.get("/demonstrations")
        assert page.status_code == 200
        token = re.search(r'name="civicgate-csrf" content="([^"]+)"', page.text).group(1)
        headers = {
            "Origin": "http://127.0.0.1",
            "X-CivicGate-CSRF": token,
            "Idempotency-Key": str(uuid.uuid4()),
        }
        yield web, executor, headers
    assert executor.stopped


@pytest.mark.parametrize("scenario", ["permit", "deny", "review"])
def test_only_explicit_scenario_submission(interactive, scenario):
    web, executor, headers = interactive
    response = web.post("/api/demo/executions", json={"scenario": scenario}, headers=headers)
    assert response.status_code == 202
    assert len(executor.submissions) == 1
    assert executor.submissions[0][0] == scenario
    assert response.json()["status"] == "RESERVED"  # No fabricated policy outcome.
    assert "PERMIT" not in response.text and "CLOSED" not in response.text


@pytest.mark.parametrize(
    "value",
    [
        {"scenario": "real"},
        {"scenario": "PERMIT"},
        {"scenario": True},
        {"scenario": None},
        {"scenario": []},
        {"scenario": {}},
        {"scenario": "permit", "provider": "openai"},
        {"scenario": "permit", "url": "https://invalid.example/DO_NOT_REFLECT"},
        {"scenario": "permit", "tool": "unregistered_admin"},
        {"scenario": "permit", "model": "DO_NOT_REFLECT"},
        {"scenario": "permit", "token": "DO_NOT_REFLECT"},
        {},
        [],
        "permit",
        True,
    ],
)
def test_arbitrary_configuration_cannot_reach_executor(interactive, value):
    web, executor, headers = interactive
    response = web.post("/api/demo/executions", json=value, headers=headers)
    assert response.status_code == 400
    assert not executor.submissions
    assert "DO_NOT_REFLECT" not in response.text


@pytest.mark.parametrize(
    "raw",
    [
        b'{"scenario":"permit","scenario":"deny"}',
        b'{"scenario":NaN}',
        b'{"scenario":"permit"}' + b"x" * 257,
        b"\xff",
        b'{"scenario":',
    ],
)
def test_malformed_and_oversized_requests(interactive, raw):
    web, executor, headers = interactive
    response = web.post(
        "/api/demo/executions",
        content=raw,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code in {400, 413}
    assert not executor.submissions


@pytest.mark.parametrize("missing", ["Origin", "X-CivicGate-CSRF", "Idempotency-Key"])
def test_required_submission_safeguards(interactive, missing):
    web, executor, headers = interactive
    headers = {key: value for key, value in headers.items() if key != missing}
    response = web.post("/api/demo/executions", json={"scenario": "permit"}, headers=headers)
    assert response.status_code in {400, 403}
    assert not executor.submissions


def test_empty_origin_does_not_satisfy_explicit_post_origin(interactive):
    web, executor, headers = interactive
    response = web.post(
        "/api/demo/executions",
        json={"scenario": "permit"},
        headers={**headers, "Origin": ""},
    )
    assert response.status_code == 403
    assert not executor.submissions


@pytest.mark.parametrize("csrf", ["wrong", "", "x" * 129])
def test_invalid_csrf_never_dispatches(interactive, csrf):
    web, executor, headers = interactive
    response = web.post(
        "/api/demo/executions",
        json={"scenario": "permit"},
        headers={**headers, "X-CivicGate-CSRF": csrf},
    )
    assert response.status_code == 403
    assert not executor.submissions
    assert csrf not in response.text or csrf == ""


def test_non_ascii_csrf_is_safe_rejection(interactive):
    web, executor, headers = interactive
    raw = [
        (key.encode(), value.encode())
        for key, value in headers.items()
        if key != "X-CivicGate-CSRF"
    ]
    raw.append((b"X-CivicGate-CSRF", b"\xff"))
    response = web.post("/api/demo/executions", json={"scenario": "permit"}, headers=raw)
    assert response.status_code == 403
    assert not executor.submissions


def test_header_duplicates_and_query_overrides(interactive):
    web, executor, headers = interactive
    for name, value in [
        ("Origin", "http://127.0.0.1"),
        ("X-CivicGate-CSRF", headers["X-CivicGate-CSRF"]),
        ("Idempotency-Key", headers["Idempotency-Key"]),
        ("Content-Type", "application/json"),
    ]:
        pairs = list({**headers, "Content-Type": "application/json"}.items()) + [(name, value)]
        response = web.post("/api/demo/executions", content=b'{"scenario":"permit"}', headers=pairs)
        assert response.status_code in {400, 403, 415}
    assert (
        web.post(
            "/api/demo/executions?provider=DO_NOT_REFLECT",
            json={"scenario": "permit"},
            headers=headers,
        ).status_code
        == 400
    )
    assert not executor.submissions


def test_get_reads_and_refreshes_never_submit(interactive):
    web, executor, _ = interactive
    for _ in range(2):
        for path in [
            "/",
            "/demonstrations",
            "/health",
            "/api/runs",
            "/api/demo/capabilities",
            "/api/demo/executions",
        ]:
            assert web.get(path).status_code == 200
    assert not executor.submissions
    assert web.get("/api/demo/executions/unknown").status_code == 404


def test_only_one_exact_post_endpoint_and_no_redirect(interactive):
    web, executor, headers = interactive
    for method in ["PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]:
        assert (
            web.request(
                method, "/api/demo/executions", json={"scenario": "permit"}, headers=headers
            ).status_code
            == 405
        )
    for path in ["/", "/health", "/api/runs", "/api/demo/executions/", "/execute", "/retry"]:
        assert web.post(path, json={"scenario": "permit"}, headers=headers).status_code == 405
    assert not executor.submissions


def test_default_composition_remains_read_only():
    with TestClient(
        create_app([]), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as web:
        assert web.post("/api/demo/executions", json={"scenario": "permit"}).status_code == 405
        assert web.get("/demonstrations").status_code == 404
        assert web.get("/health").json()["mode"] == "READ_ONLY"
