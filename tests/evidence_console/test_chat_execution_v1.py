"""MINI10 controller controls; no model, MCP, or Gateway runs in these tests."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import uuid
from pathlib import Path

import pytest

from civicgate.evidence_console import chat_execution_v1 as module
from civicgate.evidence_console.chat_execution_v1 import (
    HOST_OWNER,
    PLANNER_IDENTITY,
    ChatExecutor,
)
from civicgate.evidence_console.demo_execution_v1 import DemoError, DemoExecutor

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def make_chat(tmp_path, monkeypatch):
    monkeypatch.setattr(DemoExecutor, "_verify_worker_environment", lambda self: None)

    def make(**options):
        return ChatExecutor(
            ROOT,
            tmp_path / ("chat-" + uuid.uuid4().hex),
            Path(sys.executable),
            **options,
        )

    return make


def key() -> str:
    return str(uuid.uuid4())


def hold_worker(executor: ChatExecutor, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def blocked(_: str) -> None:
        entered.set()
        release.wait(10)

    monkeypatch.setattr(executor, "_run_job", blocked)
    return entered, release


def test_owner_is_durable_and_not_browser_selectable(make_chat) -> None:
    executor = make_chat()
    owner = json.loads((executor.output_root / "chat-owner.json").read_bytes())
    assert owner["host_owner"] == HOST_OWNER
    assert owner["planner_identity"] == PLANNER_IDENTITY
    assert owner["selected_before_discovery"] is True
    assert owner["legacy_fallback"] is False
    assert owner["write_owner_composed"] is False
    assert executor.capabilities()["execution_authority"] is False


@pytest.mark.parametrize(
    "prompt",
    ["", "   ", "\x00", "x" * 4001, None, True, {}, []],
)
def test_invalid_prompt_never_reserves_or_dispatches(make_chat, prompt) -> None:
    executor = make_chat()
    with pytest.raises(DemoError) as caught:
        executor.submit_prompt(prompt, key())
    assert caught.value.code == "INVALID_CHAT_PROMPT"
    assert executor.list_turns() == []
    assert list((executor.output_root / "requests").iterdir()) == []


def test_immutable_prompt_is_persisted_before_dispatch_and_duplicate_is_not_resent(
    make_chat, monkeypatch
) -> None:
    executor = make_chat()
    entered, release = hold_worker(executor, monkeypatch)
    prompt = "Show public federal awards in Puerto Rico during FY2026."
    request_key = key()
    try:
        first = executor.submit_prompt(prompt, request_key)
        assert entered.wait(2)
        prompt_record = json.loads(
            (executor.output_root / "jobs" / first["id"] / "prompt.json").read_bytes()
        )
        assert prompt_record == {
            "host_owner": HOST_OWNER,
            "planner_identity": PLANNER_IDENTITY,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        }
        reserved = json.loads(
            (executor.output_root / "jobs" / first["id"] / "states" / "0000.json").read_bytes()
        )
        assert reserved["status"] == "RESERVED"
        duplicate = executor.submit_prompt(prompt, request_key)
        assert duplicate["id"] == first["id"]
        assert len(executor.list_turns()) == 1
        with pytest.raises(DemoError) as caught:
            executor.submit_prompt(prompt + " changed", request_key)
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    finally:
        release.set()


def test_get_views_do_not_write_or_start_worker(make_chat, monkeypatch) -> None:
    executor = make_chat()
    before = {path: path.read_bytes() for path in executor.output_root.rglob("*") if path.is_file()}
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("read-only controller view dispatched"),
    )
    assert executor.list_turns() == []
    assert executor.evidence_entries() == []
    assert executor.capabilities()["active"] is False
    with pytest.raises(DemoError):
        executor.get_turn("chat-" + "0" * 32)
    after = {path: path.read_bytes() for path in executor.output_root.rglob("*") if path.is_file()}
    assert before == after


def test_reservation_failure_fences_chat_before_worker_start(make_chat, monkeypatch) -> None:
    executor = make_chat()
    starts: list[str] = []
    monkeypatch.setattr(executor, "_run_job", lambda turn_id: starts.append(turn_id))
    monkeypatch.setattr(module, "_write_new", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(DemoError) as caught:
        executor.submit_prompt("Show public awards.", key())
    assert caught.value.code == "CHAT_RESERVATION_CUSTODY_UNCONFIRMED"
    assert starts == []
    assert executor.capabilities()["enabled"] is False


def test_chat_worker_environment_never_forwards_credentials(monkeypatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "CIVICGATE_AGENT_PROVIDER",
    ):
        monkeypatch.setenv(name, "DO_NOT_FORWARD")
    environment = ChatExecutor._environment()
    assert "DO_NOT_FORWARD" not in environment.values()
    assert set(environment) <= {
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUTF8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
    }
