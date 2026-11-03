"""Advisor ingress assertions use no Gateway, model, credential or external transport."""

from __future__ import annotations

import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from test_reader import fixture_run, seal

from civicgate.evidence_console.app import create_app


class CountingAdvisor:
    def __init__(self):
        self.calls = []
        self.closed = False

    def submit(self, run_id, observation_id, key):
        self.calls.append((run_id, observation_id, key))
        return {"id": "analysis-example", "status": "RUNNING"}

    def capabilities(self):
        return {"enabled": True, "active": False, "remaining_jobs": 8}

    def get_job(self, job_id):
        return {"id": job_id, "status": "RUNNING"}

    def shutdown(self):
        self.closed = True


@pytest.fixture
def advisor_web(tmp_path):
    root = fixture_run(tmp_path / "capture")
    entries = [{"id": "example", "root": str(root), "manifest_sha256": seal(root)}]
    advisor = CountingAdvisor()
    with TestClient(
        create_app(entries, advisor=advisor),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as web:
        page = web.get("/runs/example/observations/SYNTHETIC_OBSERVATION")
        assert page.status_code == 200
        token = re.search(r'name="civicgate-advisor-csrf" content="([^"]+)"', page.text)[1]
        headers = {
            "Origin": "http://127.0.0.1",
            "X-CivicGate-CSRF": token,
            "Idempotency-Key": str(uuid.uuid4()),
        }
        yield web, advisor, headers
    assert advisor.closed


def test_manual_selection_exactly_once_and_no_get_calls(advisor_web):
    web, advisor, headers = advisor_web
    for path in ["/", "/health", "/api/advisor/capabilities", "/api/advisor/analyses/example"]:
        assert web.get(path).status_code == 200
    assert advisor.calls == []
    value = {"run_id": "example", "observation_id": "SYNTHETIC_OBSERVATION"}
    result = web.post("/api/advisor/analyses", json=value, headers=headers)
    assert result.status_code == 202
    assert advisor.calls == [("example", "SYNTHETIC_OBSERVATION", headers["Idempotency-Key"])]
    assert "binding" not in result.text


@pytest.mark.parametrize(
    "header,value",
    [
        ("Origin", ""),
        ("Origin", "null"),
        ("Origin", "http://evil.example"),
        ("Origin", "https://127.0.0.1"),
        ("X-CivicGate-CSRF", "incorrect"),
        ("Idempotency-Key", "incorrect"),
        ("Sec-Fetch-Site", "cross-site"),
    ],
)
def test_unauthorized_ingress(advisor_web, header, value):
    web, advisor, headers = advisor_web
    headers[header] = value
    response = web.post(
        "/api/advisor/analyses", json={"run_id": "example", "observation_id": "x"}, headers=headers
    )
    assert response.status_code in {400, 403}
    assert advisor.calls == []


@pytest.mark.parametrize("field", ["Origin", "X-CivicGate-CSRF", "Idempotency-Key", "Content-Type"])
def test_duplicate_security_headers_reject(advisor_web, field):
    web, advisor, headers = advisor_web
    pairs = list({**headers, "Content-Type": "application/json"}.items())
    pairs.append((field, dict(pairs)[field]))
    assert web.post("/api/advisor/analyses", content=b"{}", headers=pairs).status_code in {
        400,
        403,
        415,
    }
    assert not advisor.calls


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        None,
        True,
        {"run_id": [], "observation_id": "x"},
        {"run_id": "../private", "observation_id": "x"},
        {"run_id": "example", "observation_id": "x", "model": "not-allowed"},
        {"run_id": "example", "observation_id": "x", "prompt": "not-allowed"},
        {"run_id": "example", "observation_id": "x", "url": "https://invalid.example"},
    ],
)
def test_no_arbitrary_payload_or_configuration(advisor_web, value):
    web, advisor, headers = advisor_web
    assert (
        web.post(
            "/api/advisor/analyses",
            content=json.dumps(value),
            headers={**headers, "Content-Type": "application/json"},
        ).status_code
        == 400
    )
    assert not advisor.calls


@pytest.mark.parametrize(
    "body",
    [
        b'{"run_id":"example","run_id":"other","observation_id":"x"}',
        b'{"run_id":NaN,"observation_id":"x"}',
        b"{",
        b"\xff",
        b" " * 513,
    ],
)
def test_malformed_payload(advisor_web, body):
    web, advisor, headers = advisor_web
    assert web.post(
        "/api/advisor/analyses",
        content=body,
        headers={**headers, "Content-Type": "application/json"},
    ).status_code in {400, 413}
    assert not advisor.calls


@pytest.mark.parametrize(
    "path",
    [
        "/api/advisor/analyses/",
        "/api/advisor/analyses?model=x",
        "/retry",
        "/execute",
        "/api/demo/executions",
    ],
)
def test_no_other_dispatch_paths(advisor_web, path):
    web, advisor, headers = advisor_web
    assert web.post(path, json={}, headers=headers).status_code in {400, 405}
    assert not advisor.calls


def test_advisor_optional_off_by_default():
    with TestClient(
        create_app([]), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as web:
        assert web.get("/api/advisor/capabilities").status_code == 404
        assert web.post("/api/advisor/analyses", json={}).status_code == 405


def test_frontend_no_html_injection_or_automatic_post(advisor_web):
    web, _, _ = advisor_web
    js = web.get("/assets/advisor.js").text
    assert "innerHTML" not in js and "eval(" not in js and "localStorage" not in js
    assert js.count('method: "POST"') == 1
    assert 'button.addEventListener("click"' in js
    assert "textContent" in js
