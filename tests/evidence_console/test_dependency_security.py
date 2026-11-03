"""Offline upgrade controls: reject unsafe resolver input before filesystem access."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="Separate optional console environment required")
from fastapi.testclient import TestClient
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from civicgate.evidence_console.app import HERE, create_app


@pytest.mark.parametrize(
    "path",
    [r"\\unc.invalid\share\console.css", "//unc.invalid/share/console.css", r"\rooted\console.css"],
)
def test_static_resolver_rejects_rooted_paths_before_resolution(monkeypatch, path):
    app = create_app([])
    assets = next(
        route.app for route in app.routes if isinstance(route, Mount) and route.path == "/assets"
    )
    assert isinstance(assets, StaticFiles)
    resolutions = []

    def prohibited_resolution(value, *args, **kwargs):
        resolutions.append(value)
        raise AssertionError("Rooted static input reached filesystem resolution")

    # The sentinel intercepts the first resolver call: no UNC lookup or network
    # operation occurs, including when this control reproduces the older defect.
    with monkeypatch.context() as patch:
        patch.setattr("starlette.staticfiles.os.path.realpath", prohibited_resolution)
        assert assets.lookup_path(path) == ("", None)
    assert resolutions == []

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        response = client.get("/assets/console.css")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/css")
        assert response.content == (HERE / "static" / "console.css").read_bytes()


@pytest.mark.parametrize(
    "headers",
    [
        [("Host", "127.0.0.1/injected?x=")],
        [("Host", "127.0.0.1#fragment")],
        [("Host", "localhost@unc.invalid")],
        [("Host", "127.0.0.1"), ("Host", "localhost")],
    ],
)
def test_malformed_host_is_rejected_before_handler(headers):
    app = create_app([])
    calls = []

    @app.get("/sentinel")
    def sentinel():
        calls.append("entered")
        return {"ok": True}

    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        response = client.get("/sentinel", headers=headers)
        assert response.status_code == 403
        assert response.json() == {"error": "LOCAL_ACCESS_REQUIRED"}
        assert calls == []
        response = client.get("/sentinel")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert calls == ["entered"]
