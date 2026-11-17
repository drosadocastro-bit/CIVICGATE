import asyncio
from types import SimpleNamespace

import httpx
import pytest
from chat_v3 import public_capture71 as c
from chat_v3 import util71 as p
from chat_v3.public_read_v11.contract import SEARCH_PATH

from civicgate.adapters.usaspending import AdapterError


def public_response():
    return {
        "spending_level": "awards",
        "limit": 5,
        "results": [
            {
                "internal_id": i,
                "generated_internal_id": f"CONT_AWD_PUBLIC71_{i}",
                "Award ID": f"PUBLIC71_{i}",
                "Recipient Name": f"PUBLIC FIXTURE {i}",
                "Award Amount": str(600000 - i * 10000),
                "Awarding Agency": "Department of Defense",
            }
            for i in range(1, 6)
        ],
        "page_metadata": {"page": 1, "hasNext": True},
    }


def setup(tmp_path, monkeypatch, handler):
    (tmp_path / "captures").mkdir()
    calls = []

    class Admission:
        profile = SimpleNamespace(custody_root=str(tmp_path))

        def check(self):
            calls.append("admit")

    ad = Admission()
    monkeypatch.setattr(c.host_gate71, "release_enabled", lambda: True)

    def factory(**kwargs):
        assert kwargs["retries"] == 0 and kwargs["trust_env"] is False
        calls.append("factory")
        return httpx.MockTransport(handler)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", factory)
    adapter = c.CapturedPublicRead71(
        live_authorized=True, admission=ad, capture_root=tmp_path / "captures/public"
    )
    return adapter, ad, calls


def test_exact_public_capture_before_normalization(tmp_path, monkeypatch):
    def handler(request):
        assert (tmp_path / "captures/public/request.bin").read_bytes() == request.content
        assert p.parse(request.content) == c.LIVE_PAYLOAD
        return httpx.Response(200, json=public_response())

    adapter, ad, calls = setup(tmp_path, monkeypatch, handler)
    asyncio.run(adapter._request(SEARCH_PATH, c.LIVE_PAYLOAD))
    root = tmp_path / "captures/public"
    observed = p.parse(p.read(root / "observed.json"))
    assert observed["response_sha256"] == p.sha(p.read(root / "response.bin"))
    assert observed["request_sha256"] == p.sha(p.read(root / "request.bin"))
    assert observed["state"] == "BODY_OBSERVED_NOT_VALIDATED"
    assert adapter.observations[0]["outcome"] == "RESPONSE_VALIDATED"
    assert adapter.observations[0]["body_sha256"] == observed["response_sha256"]
    assert calls.count("factory") == 1 and calls.count("admit") >= 4
    with pytest.raises((ValueError, AdapterError)):
        asyncio.run(adapter._request(SEARCH_PATH, c.LIVE_PAYLOAD))
    assert calls.count("factory") == 1


@pytest.mark.parametrize("kind", ["timeout", "partial", "429", "invalid"])
def test_failures_consume_and_hold(tmp_path, monkeypatch, kind):
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            raise httpx.ReadError("offline failure")

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("offline timeout")
        if kind == "partial":
            return httpx.Response(
                200, headers={"content-type": "application/json"}, stream=Partial()
            )
        if kind == "429":
            return httpx.Response(429, content=b"{}")
        return httpx.Response(
            200, content=b"not json", headers={"content-type": "application/json"}
        )

    adapter, ad, calls = setup(tmp_path, monkeypatch, handler)
    with pytest.raises((ValueError, AdapterError)):
        asyncio.run(adapter._request(SEARCH_PATH, c.LIVE_PAYLOAD))
    root = tmp_path / "captures/public"
    if kind == "invalid":
        assert (root / "response.bin").read_bytes() == b"not json"
    else:
        assert p.parse(p.read(root / "unknown.json"))["state"] == "UNKNOWN_CONSUMED"
    assert adapter.used is True and calls.count("factory") == 1
    with pytest.raises((ValueError, AdapterError)):
        asyncio.run(adapter._request(SEARCH_PATH, c.LIVE_PAYLOAD))
    assert calls.count("factory") == 1


def test_gate_before_admission_and_factory(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("MUST_NOT_ACCESS")

    monkeypatch.setattr(c.host_gate71, "release_enabled", lambda: False)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)
    with pytest.raises(ValueError, match="LIVE_HOST_RELEASE_DISABLED"):
        c.CapturedPublicRead71(
            live_authorized=True, admission=object(), capture_root=tmp_path / "new"
        )
    assert not (tmp_path / "new").exists()


def test_expiry_blocks_before_factory(tmp_path, monkeypatch):
    adapter, ad, calls = setup(
        tmp_path, monkeypatch, lambda request: httpx.Response(200, json=public_response())
    )

    def expired():
        raise ValueError("EXPIRED")

    ad.check = expired
    with pytest.raises(ValueError, match="EXPIRED"):
        asyncio.run(adapter._request(SEARCH_PATH, c.LIVE_PAYLOAD))
    assert calls.count("factory") == 0 and not adapter.capture_root.exists()


def test_other_query_rejected_without_transport(tmp_path, monkeypatch):
    adapter, ad, calls = setup(
        tmp_path, monkeypatch, lambda request: httpx.Response(200, json=public_response())
    )
    changed = dict(c.LIVE_PAYLOAD, limit=4)
    with pytest.raises(ValueError):
        asyncio.run(adapter._request(SEARCH_PATH, changed))
    assert calls.count("factory") == 0
