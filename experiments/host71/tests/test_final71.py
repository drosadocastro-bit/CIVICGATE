import asyncio

import httpx
import pytest
from chat_v3 import host_final71 as final
from chat_v3 import util71 as p
from wire_fixtures71 import fixture_envelope

KEY = "FAKE_FINAL71_CANARY_NOT_A_REAL_KEY"


@pytest.fixture
def data():
    payload = {
        "question": p.QUESTION,
        "records": [
            {
                "record_id": f"R{i}",
                "award_id": f"F71_{i}",
                "recipient_name": f"FIXTURE CONTRACTOR {i}",
                "award_amount": f"{i}00.00",
                "awarding_agency": "Department of Defense",
            }
            for i in range(1, 6)
        ],
    }
    return payload, {"payload": payload, "snapshot_sha256": "f" * 64}


class Admission:
    def __init__(self, fail_at=None):
        self.calls = 0
        self.fail_at = fail_at

    def check_stage(self, stage):
        assert stage == "answer"
        self.calls += 1
        if self.calls == self.fail_at:
            raise ValueError("expired")


class Secrets:
    def __init__(self, root, key=KEY):
        self.root = root
        self.key = key
        self.calls = 0

    def get_secret(self, name):
        assert name == "CIVICGATE_NVIDIA_API_KEY"
        assert (self.root / "reserved.json").exists()
        self.calls += 1
        return self.key


def run(root, data, handler, monkeypatch, admission=None, secrets=None, reconcile=None):
    payload, proof = data
    monkeypatch.setattr(final.gate, "release_enabled", lambda: True)
    return asyncio.run(
        final.execute(
            root,
            payload,
            proof,
            admission or Admission(),
            secrets or Secrets(root),
            reconcile or (lambda: proof),
            _test_transport=httpx.MockTransport(handler),
        )
    )


def good(data):
    env = fixture_envelope(data[0])
    env["choices"][0]["message"]["content"] = env["choices"][0]["message"]["content"].replace(
        "historical page", "fresh same-turn page"
    )
    return env


def test_gate_before_all_access(tmp_path, data):
    with pytest.raises(ValueError, match="HOST71_LIVE_HARD_BLOCKED"):
        asyncio.run(final.execute(tmp_path / "answer", *data, object(), object(), object()))
    assert not (tmp_path / "answer").exists()


def test_exact_wire_and_readback_no_release(tmp_path, data, monkeypatch):
    root = tmp_path / "answer"
    calls = []

    def handler(sent):
        calls.append(1)
        assert sent.content == (root / "request.json").read_bytes()
        assert str(sent.url) == final.ENDPOINT and sent.headers["authorization"] == "Bearer " + KEY
        request = p.parse(sent.content)
        assert (
            "tools" not in request
            and request["max_tokens"] == 2000
            and request["reasoning_budget"] == 256
        )
        assert (
            request["chat_template_kwargs"] == {"enable_thinking": False}
            and request["stream"] is False
        )
        assert (
            "historical" not in request["messages"][0]["content"]
            and "offline" not in request["messages"][1]["content"].lower()
        )
        return httpx.Response(200, json=good(data))

    value = run(root, data, handler, monkeypatch)
    assert value["status"] == "REVIEW_REQUIRED" and len(value["claims"]) == 5
    assert value["provenance"] == "MOCK_TRANSPORT_TEST" and value["external_requests"] == 0
    assert (
        value["model_executed"] is False
        and value["released_answer"] is None
        and value["verified_answer"] is False
    )
    assert len(calls) == 1 and all(KEY.encode() not in file.read_bytes() for file in root.iterdir())
    before = {f.name: f.read_bytes() for f in root.iterdir()}
    assert final.read_run(root, *data) == value
    assert before == {f.name: f.read_bytes() for f in root.iterdir()}
    with pytest.raises(ValueError):
        run(root, data, handler, monkeypatch)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "kind",
    ["timeout", "echo", "partial_echo", "partial", "http429", "invalid", "truncated", "cancel"],
)
def test_failure_consumed_never_retry_or_leak(tmp_path, data, monkeypatch, kind):
    root = tmp_path / "answer"
    calls = []

    class Broken(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield KEY.encode() if kind == "partial_echo" else b"partial"
            raise httpx.ReadError(KEY)

    def handler(sent):
        calls.append(1)
        if kind == "timeout":
            raise httpx.ReadTimeout(KEY)
        if kind == "cancel":
            raise asyncio.CancelledError()
        if kind == "echo":
            return httpx.Response(200, content=KEY.encode())
        if kind in ("partial_echo", "partial"):
            return httpx.Response(200, stream=Broken())
        if kind == "http429":
            return httpx.Response(429, content=b"{}")
        if kind == "invalid":
            return httpx.Response(200, content=b"notjson")
        env = good(data)
        env["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=env)

    if kind == "cancel":
        with pytest.raises(asyncio.CancelledError):
            run(root, data, handler, monkeypatch)
    else:
        assert run(root, data, handler, monkeypatch)["status"] == "UNKNOWN_CONSUMED"
    assert (root / "unknown.json").exists() and not (root / "terminal.json").exists()
    assert all(KEY.encode() not in f.read_bytes() for f in root.iterdir())
    if "echo" in kind:
        assert not (root / "response.bin").exists() and not (root / "partial.bin").exists()
    with pytest.raises(ValueError):
        run(root, data, handler, monkeypatch)
    assert len(calls) == 1


def test_missing_secret_after_consumption_no_dispatch(tmp_path, data, monkeypatch):
    root = tmp_path / "answer"
    secrets = Secrets(root, None)

    def forbidden(sent):
        raise AssertionError("DISPATCH_FORBIDDEN")

    value = run(root, data, forbidden, monkeypatch, secrets=secrets)
    assert (
        value["status"] == "UNKNOWN_CONSUMED"
        and value["dispatch_attempted"] is False
        and secrets.calls == 1
    )
    assert not (root / "request.json").exists()


def test_expired_final_dispatch_check_holds(tmp_path, data, monkeypatch):
    root = tmp_path / "answer"

    def forbidden(sent):
        raise AssertionError("DISPATCH_FORBIDDEN")

    value = run(root, data, forbidden, monkeypatch, admission=Admission(fail_at=4))
    assert value["status"] == "UNKNOWN_CONSUMED" and value["dispatch_attempted"] is False


def test_proof_payload_mismatch_and_changed_source_hold(tmp_path, data, monkeypatch):
    root = tmp_path / "answer"
    with pytest.raises(ValueError):
        run(root, data, lambda sent: None, monkeypatch, reconcile=lambda: {"different": True})
    assert not root.exists()
    data[1]["payload"] = {}
    with pytest.raises(ValueError):
        run(root, data, lambda sent: None, monkeypatch)
    assert not root.exists()


def test_tampered_response_withheld(tmp_path, data, monkeypatch):
    root = tmp_path / "answer"
    assert (
        run(root, data, lambda sent: httpx.Response(200, json=good(data)), monkeypatch)["status"]
        == "REVIEW_REQUIRED"
    )
    (root / "response.bin").write_bytes(b"{}")
    assert final.read_run(root, *data)["status"] == "UNKNOWN_CONSUMED"
