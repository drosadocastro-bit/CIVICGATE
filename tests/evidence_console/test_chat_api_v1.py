"""Browser ingress can submit prompt text, never authority or a proposal."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from civicgate.evidence_console.app import create_app

ROOT = Path(__file__).resolve().parents[2]


class CountingChat:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, str]] = []
        self.stopped = False

    def submit_prompt(self, prompt: str, key: str) -> dict[str, object]:
        self.submissions.append((prompt, key))
        return {
            "id": "chat-" + uuid.uuid4().hex,
            "status": "RESERVED",
            "original_request": prompt,
            "request_sha256": "a" * 64,
        }

    def list_turns(self) -> list[dict[str, object]]:
        return []

    def get_turn(self, turn_id: str) -> dict[str, object]:
        from civicgate.evidence_console.demo_execution_v1 import DemoError

        raise DemoError("UNKNOWN_CHAT_TURN", 404)

    def evidence_entries(self) -> list[dict[str, str]]:
        return []

    def capabilities(self) -> dict[str, object]:
        return {
            "enabled": True,
            "active": False,
            "remaining_turns": 2,
            "host_owner": "CHANNEL_A_LOCAL_READ_V1",
            "planner_identity": "SCRIPTED_SYNTHETIC_FIXTURE_NOT_GRANITE",
        }

    def shutdown(self) -> None:
        self.stopped = True


@pytest.fixture
def chat_web():
    chat = CountingChat()
    with TestClient(
        create_app([], chat=chat),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as web:
        page = web.get("/chat")
        assert page.status_code == 200
        token = re.search(r'name="civicgate-csrf" content="([^"]+)"', page.text).group(1)
        headers = {
            "Origin": "http://127.0.0.1",
            "X-CivicGate-CSRF": token,
            "Idempotency-Key": str(uuid.uuid4()),
        }
        yield web, chat, headers
    assert chat.stopped


def test_exact_prompt_only_submission(chat_web) -> None:
    web, chat, headers = chat_web
    prompt = "Show public federal awards in Puerto Rico during FY2026."
    response = web.post("/api/chat/turns", json={"prompt": prompt}, headers=headers)
    assert response.status_code == 202
    assert chat.submissions == [(prompt, headers["Idempotency-Key"])]
    assert response.json()["status"] == "RESERVED"
    assert response.json().get("decision") is None


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        "prompt",
        True,
        {"prompt": True},
        {"prompt": "safe", "tool": "find_federal_awards"},
        {"prompt": "safe", "arguments": {}},
        {"prompt": "safe", "owner": "legacy"},
        {"prompt": "safe", "profile": "FAA_FY2026_PR_READ_v1"},
        {"prompt": "safe", "gateway": "weaker"},
        {"prompt": "safe", "model": "granite"},
        {"prompt": "safe", "approval": "PERMIT"},
        {"prompt": "safe", "write": {"review_status": "APPROVED"}},
    ],
)
def test_caller_cannot_supply_proposal_owner_or_authority(chat_web, value) -> None:
    web, chat, headers = chat_web
    response = web.post("/api/chat/turns", json=value, headers=headers)
    assert response.status_code in {400, 422}
    assert chat.submissions == []


@pytest.mark.parametrize(
    "raw",
    [
        b'{"prompt":"one","prompt":"two"}',
        b'{"prompt":NaN}',
        b'{"prompt":',
        b"\xff",
        b'{"prompt":"x"}' + b" " * 16_385,
    ],
)
def test_malformed_or_oversized_request_never_reaches_chat(chat_web, raw) -> None:
    web, chat, headers = chat_web
    response = web.post(
        "/api/chat/turns",
        content=raw,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code in {400, 413}
    assert chat.submissions == []


def test_get_refreshes_and_unknown_turn_never_submit(chat_web) -> None:
    web, chat, _ = chat_web
    for _ in range(2):
        for path in (
            "/",
            "/chat",
            "/health",
            "/api/runs",
            "/api/chat/capabilities",
            "/api/chat/turns",
        ):
            assert web.get(path).status_code == 200
    assert web.get("/api/chat/turns/unknown").status_code == 404
    assert chat.submissions == []


def test_origin_csrf_idempotency_and_content_type_are_required(chat_web) -> None:
    web, chat, headers = chat_web
    for missing in ("Origin", "X-CivicGate-CSRF", "Idempotency-Key"):
        reduced = {name: value for name, value in headers.items() if name != missing}
        response = web.post("/api/chat/turns", json={"prompt": "safe"}, headers=reduced)
        assert response.status_code in {400, 403}
    response = web.post(
        "/api/chat/turns",
        content=b'{"prompt":"safe"}',
        headers={**headers, "Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    assert chat.submissions == []


def test_chat_rendering_uses_text_content_and_fixed_evidence_paths() -> None:
    script = (ROOT / "src/civicgate/evidence_console/static/chat.js").read_text()
    assert ".innerHTML" not in script and "textContent" in script
    assert "safeEvidenceURL" in script
    assert "owner:" not in script and "approval:" not in script


def test_default_console_exposes_no_chat_execution_surface() -> None:
    with TestClient(
        create_app([]),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    ) as web:
        assert web.get("/chat").status_code == 404
        assert web.get("/api/chat/turns").status_code == 404
        assert web.post("/api/chat/turns", json={"prompt": "safe"}).status_code == 405
        assert web.get("/health").json()["mode"] == "READ_ONLY"
