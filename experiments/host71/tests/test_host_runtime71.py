import pytest
from chat_v3 import capture_binding71 as binding
from chat_v3 import fresh_host71 as host
from chat_v3 import host_gate71 as gate
from chat_v3 import host_runtime71 as r


def test_secret_lookup_after_exact_stage_check(monkeypatch):
    monkeypatch.setattr(gate, "release_enabled", lambda: True)
    events = []

    class Admission:
        def check_stage(self, role):
            events.append(role)

    class Store:
        def get_secret(self, name):
            events.append("lookup")
            return "FAKE_CANARY"

    secret = r.AdmittedSecrets71(Store(), Admission(), "judge")
    assert secret.get_secret("CIVICGATE_OPENAI_JUDGE_API_KEY") == "FAKE_CANARY"
    assert events == ["judge", "lookup"]
    with pytest.raises(ValueError):
        secret.get_secret("CIVICGATE_NVIDIA_API_KEY")
    assert events == ["judge", "lookup"]


def test_expiry_stops_secret_lookup(monkeypatch):
    monkeypatch.setattr(gate, "release_enabled", lambda: True)

    class Admission:
        def check_stage(self, role):
            raise ValueError("EXPIRED")

    class Store:
        def get_secret(self, name):
            raise AssertionError("SECRET_ACCESS_FORBIDDEN")

    with pytest.raises(ValueError):
        r.AdmittedSecrets71(Store(), Admission(), "planner").get_secret("CIVICGATE_NVIDIA_API_KEY")


def test_closed_host_entry_before_any_path_or_secret():
    import asyncio

    with pytest.raises(ValueError, match="HOST71_LIVE_HARD_BLOCKED"):
        asyncio.run(host.execute_host(object(), object(), object(), object(), object(), object()))
    with pytest.raises(ValueError, match="HOST71_LIVE_HARD_BLOCKED"):
        r.open_runtime({})
    with pytest.raises(ValueError, match="HOST71_LIVE_HARD_BLOCKED"):
        binding.HostCapture71(object(), "x", "nemotron", None, mode="LIVE")
