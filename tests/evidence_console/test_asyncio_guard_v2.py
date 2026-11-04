"""Subprocess controls for the versioned asyncio-only socketpair allowance."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "evals/demos/guarded_pytest_v2.py"
V1_SHA256 = "113b390680a4ec710c7cf44917441e86a73977f4b80b5cfd18af99a0f796f505"


def run_guard(tmp_path, body, *, configuration="valid", fixture=False):
    """Run the actual guard before importing the bounded synthetic test module."""
    layout = tmp_path / "s"
    copy = layout / "pinned-copy"
    execution = layout / "execution"
    protected = tmp_path / "protected"
    for directory in (copy, execution, protected):
        directory.mkdir(parents=True)
    (protected / "marker.txt").write_bytes(b"SYNTHETIC_PROTECTED_SOURCE")
    dataset = copy / "evals/datasets/synthetic_reserved.json"
    dataset.parent.mkdir(parents=True)
    dataset.write_bytes(b'{"synthetic_reserved":true}\n')
    (copy / "isolated-pytest.ini").write_bytes(b"[pytest]\n")
    if configuration != "missing":
        config = {"version": 1, "source_root": str(protected)}
        if configuration == "extra":
            config["unexpected"] = True
        elif configuration == "relative":
            config["source_root"] = "relative"
        elif configuration == "overlap":
            config["source_root"] = str(copy)
        raw = json.dumps(config)
        if configuration == "duplicate":
            raw = '{"version":1,"source_root":"a","source_root":"b"}'
        (execution / "guard-config.json").write_text(raw, encoding="utf-8")
    if fixture:
        for name in (
            "evals/__init__.py",
            "evals/harness/__init__.py",
            "evals/harness/synthetic_http_server_v1.py",
        ):
            target = copy / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
    script = execution / "guarded_run.py"
    script.write_bytes(GUARD.read_bytes())
    prelude = (
        "import asyncio, json, os, socket, _socket, sys\n"
        "from pathlib import Path\n"
        "import pytest\n"
        f"PROTECTED = Path({str(protected)!r})\n"
        f"DATASET = Path({str(dataset)!r})\n"
        # Installed after the candidate hook, this independent safety sentinel
        # stops a defective candidate before TEST-NET/DNS traffic can escape.
        # Triggering it always fails the probe rather than becoming a PASS.
        "SAFETY_EVENTS = []\n"
        "def independent_network_safety(event, arguments):\n"
        "    denied = False\n"
        "    if event in {'socket.connect', 'socket.connect_ex'}:\n"
        "        address = arguments[1]\n"
        "        denied = type(address) is not tuple or type(address[0]) is not str or address[0] != '127.0.0.1' or address[1] == 1\n"
        "    elif event == 'socket.bind':\n"
        "        address = arguments[1]\n"
        "        denied = type(address) is not tuple or type(address[0]) is not str or address[0] != '127.0.0.1'\n"
        "    elif event == 'socket.getaddrinfo':\n"
        "        denied = arguments[0] != '127.0.0.1'\n"
        "    elif event in {'socket.gethostbyname', 'socket.gethostbyaddr', 'socket.sendto'}:\n"
        "        denied = True\n"
        "    if denied:\n"
        "        SAFETY_EVENTS.append(event)\n"
        "        raise PermissionError('INDEPENDENT_TEST_SAFETY_SENTINEL')\n"
        "sys.addaudithook(independent_network_safety)\n"
        "@pytest.fixture(autouse=True)\n"
        "def safety_sentinel_must_not_be_used():\n"
        "    yield\n"
        "    assert SAFETY_EVENTS == [], 'Candidate failed to reject before independent safety sentinel'\n"
    )
    (copy / "test_probe.py").write_text(prelude + body, encoding="utf-8")
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC") if key in os.environ}
    env.update(
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTHONPATH=str(copy),
        TEMP=str(execution),
        TMP=str(execution),
    )
    command = [sys.executable, "-B", "-s", str(script), "test_probe.py"]
    result = subprocess.run(command, cwd=copy, env=env, capture_output=True, timeout=30)
    (execution / "stdout.log").write_bytes(result.stdout)
    (execution / "stderr.log").write_bytes(result.stderr)
    (execution / "command.json").write_text(
        json.dumps({"argv": command, "cwd": str(copy), "exit_code": result.returncode}, indent=2),
        encoding="utf-8",
    )
    facts_path = execution / "guard-evidence.json"
    facts = json.loads(facts_path.read_bytes()) if facts_path.is_file() else None
    return result, facts, execution


def require_pass(result):
    assert result.returncode == 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_guard_v1_reference_is_unchanged():
    assert (
        hashlib.sha256((ROOT / "evals/demos/guarded_pytest_v1.py").read_bytes()).hexdigest()
        == V1_SHA256
    )


def test_genuine_asyncio_initialization_succeeds_and_records_guard_identity(tmp_path):
    body = (
        "async def operation():\n"
        "    await asyncio.sleep(0)\n"
        "    return 'ASYNCIO_INITIALIZED'\n"
        "def test_probe():\n"
        "    assert asyncio.run(operation()) == 'ASYNCIO_INITIALIZED'\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert facts["guard_version"] == 2
    assert facts["guard_sha256"] == hashlib.sha256(GUARD.read_bytes()).hexdigest()
    assert facts["stdlib_sources"]
    assert isinstance(facts["network_events"], list)


DENIED_OPERATIONS = {
    "direct_socketpair": "socket.socketpair()",
    "direct_bind": "socket.socket().bind(('127.0.0.1', 0))",
    "other_loopback_connect": "socket.socket().connect(('127.0.0.1', 1))",
    "other_loopback_connect_ex": "socket.socket().connect_ex(('127.0.0.1', 1))",
    "external_connect": "socket.socket().connect(('203.0.113.9', 9))",
    "external_bind": "socket.socket().bind(('192.0.2.9', 0))",
    "dns": "socket.getaddrinfo('synthetic.invalid', 443)",
    "gethostbyname": "socket.gethostbyname('synthetic.invalid')",
    "gethostbyaddr": "socket.gethostbyaddr('192.0.2.9')",
    "udp_sendto": "socket.socket(type=socket.SOCK_DGRAM).sendto(b'NO_SEND', ('192.0.2.9', 9))",
}


@pytest.mark.parametrize("operation", DENIED_OPERATIONS.values(), ids=DENIED_OPERATIONS)
def test_unrelated_socket_operations_are_denied_before_kernel_dispatch(tmp_path, operation):
    body = (
        "def test_probe():\n    with pytest.raises(PermissionError):\n        " + operation + "\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


def test_native_socketpair_cannot_bypass_public_wrapper(tmp_path):
    body = (
        "def test_probe():\n"
        "    native = getattr(_socket, 'socketpair', None)\n"
        "    if native is not None:\n"
        "        with pytest.raises(PermissionError): native()\n"
        "    else:\n"
        "        assert not hasattr(_socket, 'socketpair')\n"
    )
    result, _, _ = run_guard(tmp_path, body)
    require_pass(result)


def test_socketpair_inside_coroutine_does_not_inherit_initialization_allowance(tmp_path):
    body = (
        "async def operation():\n"
        "    with pytest.raises(PermissionError): socket.socketpair()\n"
        "def test_probe():\n"
        "    asyncio.run(operation())\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


@pytest.mark.parametrize(
    "operation", ["socket.socketpair()", "socket.socket().bind(('127.0.0.1', 0))"]
)
def test_module_and_function_name_spoofing_does_not_grant_allowance(tmp_path, operation):
    fallback_source = "def _fallback_socketpair():\n    return " + operation + "\n"
    self_pipe_source = "def _make_self_pipe():\n    return target()\n"
    body = (
        "def test_probe():\n"
        "    first = {'__name__':'socket', 'socket':socket}\n"
        f"    exec({fallback_source!r}, first)\n"
        "    second = {'__name__':'asyncio.selector_events', 'target':first['_fallback_socketpair']}\n"
        f"    exec({self_pipe_source!r}, second)\n"
        "    with pytest.raises(PermissionError): second['_make_self_pipe']()\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


def test_real_self_pipe_method_outside_constructor_is_denied(tmp_path):
    body = (
        "def test_probe():\n"
        "    loop = asyncio.new_event_loop()\n"
        "    loop.close()\n"
        "    with pytest.raises(PermissionError): loop._make_self_pipe()\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


def test_substituted_socketpair_under_actual_constructor_is_denied(tmp_path):
    body = (
        "def test_probe(monkeypatch):\n"
        "    def unrelated(*args, **kwargs):\n"
        "        return socket.socket().bind(('127.0.0.1', 0))\n"
        "    monkeypatch.setattr(socket, 'socketpair', unrelated)\n"
        "    with pytest.raises(PermissionError): asyncio.new_event_loop()\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


@pytest.mark.skipif(os.name != "nt", reason="Windows stdlib fallback uses _LOCALHOST")
def test_mutated_windows_fallback_destination_is_denied(tmp_path):
    body = (
        "def test_probe(monkeypatch):\n"
        "    monkeypatch.setattr(socket, '_LOCALHOST', '203.0.113.9')\n"
        "    with pytest.raises(PermissionError): asyncio.new_event_loop()\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


@pytest.mark.parametrize("method", ["_make_self_pipe", "__init__"])
def test_mutating_stdlib_callable_code_does_not_redefine_trusted_identity(tmp_path, method):
    body = (
        "from asyncio.selector_events import BaseSelectorEventLoop\n"
        "def test_probe():\n"
        "    class Forged:\n"
        "        def pipe(self):\n"
        "            return socket.socketpair()\n"
        "        def constructor(self, *args, **kwargs):\n"
        "            super()\n"
        "            self._make_self_pipe()\n"
        f"    target = getattr(BaseSelectorEventLoop, {method!r})\n"
        "    original = target.__code__\n"
        f"    replacement = Forged.{'pipe' if method == '_make_self_pipe' else 'constructor'}.__code__\n"
        "    try:\n"
        "        target.__code__ = replacement\n"
        "        with pytest.raises(PermissionError): asyncio.SelectorEventLoop()\n"
        "    finally:\n"
        "        target.__code__ = original\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


@pytest.mark.skipif(os.name != "nt", reason="Windows stdlib fallback uses _LOCALHOST")
def test_custom_equality_host_cannot_substitute_loopback_endpoint(tmp_path):
    body = (
        "def test_probe(monkeypatch):\n"
        "    class EqualHost(str):\n"
        "        def __eq__(self, other): return other == '127.0.0.1'\n"
        "        __hash__ = str.__hash__\n"
        "    host = EqualHost('127.0.0.2')\n"
        "    assert str(host) == '127.0.0.2' and host == '127.0.0.1'\n"
        "    monkeypatch.setattr(socket, '_LOCALHOST', host)\n"
        "    with pytest.raises(PermissionError): asyncio.new_event_loop()\n"
    )
    result, facts, _ = run_guard(tmp_path, body)
    require_pass(result)
    assert any(row.get("allowed") is False for row in facts["network_events"])


@pytest.mark.parametrize("configuration", ["missing", "duplicate", "extra", "relative", "overlap"])
def test_invalid_configuration_rejects_before_project_import(tmp_path, configuration):
    result, facts, execution = run_guard(
        tmp_path,
        "raise AssertionError('PROJECT_IMPORTED_BEFORE_CONFIG')\n",
        configuration=configuration,
    )
    assert result.returncode != 0
    assert b"PROJECT_IMPORTED_BEFORE_CONFIG" not in result.stdout + result.stderr
    assert facts is None
    assert not list(execution.parent.rglob("*.sqlite"))
    assert any(value in result.stderr for value in (b"GUARD_CONFIG", b"ROOT", b"DISJOINT"))


@pytest.mark.parametrize("target", ["PROTECTED / 'marker.txt'", "DATASET"])
def test_protected_source_and_reserved_dataset_reads_remain_denied(tmp_path, target):
    body = (
        "def test_probe():\n    with pytest.raises(PermissionError):\n        ("
        + target
        + ").read_bytes()\n"
    )
    result, _, _ = run_guard(tmp_path, body)
    require_pass(result)


def test_owned_synthetic_http_fixture_remains_accessible(tmp_path):
    body = (
        "from evals.harness.synthetic_http_server_v1 import SyntheticHTTPServer\n"
        "async def operation():\n"
        "    async with SyntheticHTTPServer() as server:\n"
        "        reader, writer = await asyncio.open_connection('127.0.0.1', server.endpoint.port)\n"
        "        writer.write(('POST ' + server.endpoint.path + ' HTTP/1.1\\r\\nHost: 127.0.0.1\\r\\nContent-Length: 0\\r\\n\\r\\n').encode())\n"
        "        await writer.drain()\n"
        "        data = await reader.read()\n"
        "        writer.close()\n"
        "        await writer.wait_closed()\n"
        "        assert data.startswith(b'HTTP/1.1 200')\n"
        "        assert server.request_count == 1\n"
        "def test_probe():\n"
        "    asyncio.run(operation())\n"
    )
    result, facts, _ = run_guard(tmp_path, body, fixture=True)
    require_pass(result)
    assert any(
        row.get("allowed") is True and row.get("kind") == "owned_synthetic_fixture"
        for row in facts["network_events"]
    )


def current_worker():
    spec = importlib.util.spec_from_file_location(
        "cp15_guard_receipt_controls", ROOT / "scripts/run_console_synthetic_demo_v2.py"
    )
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


@pytest.mark.parametrize(
    "facts,expected",
    [
        ({"guard_version": 2, "guard_sha256": "a" * 64}, True),
        ({"guard_version": 2.0, "guard_sha256": "a" * 64}, False),
        ({"guard_version": True, "guard_sha256": "a" * 64}, False),
        ({"guard_version": 1, "guard_sha256": "a" * 64}, False),
        ({"guard_version": 3, "guard_sha256": "a" * 64}, False),
        ({"guard_version": "2", "guard_sha256": "a" * 64}, False),
        ({"guard_version": 2, "guard_sha256": "b" * 64}, False),
        ({"guard_version": 2, "guard_sha256": b"a" * 64}, False),
        ({"guard_version": 2}, False),
        ({"guard_sha256": "a" * 64}, False),
        (None, False),
    ],
)
def test_current_worker_rejects_unknown_guard_version_or_identity(facts, expected):
    assert current_worker().verify_guard_identity(facts, "a" * 64) is expected


@pytest.mark.parametrize(
    "version,event,expected",
    [
        (
            2,
            {
                "event": "socketpair.call",
                "api": "public",
                "kind": "asyncio_socketpair",
                "allowed": True,
            },
            True,
        ),
        (
            2,
            {
                "event": "socketpair.call",
                "api": "native",
                "kind": "asyncio_socketpair",
                "allowed": True,
            },
            True,
        ),
        (
            2,
            {
                "event": "socketpair.call",
                "api": "other",
                "kind": "asyncio_socketpair",
                "allowed": True,
            },
            False,
        ),
        (
            2,
            {"event": "socketpair.call", "api": "public", "kind": "unknown", "allowed": True},
            False,
        ),
        (
            2.0,
            {
                "event": "socketpair.call",
                "api": "public",
                "kind": "asyncio_socketpair",
                "allowed": True,
            },
            False,
        ),
        (
            2,
            {
                "event": "socketpair.call",
                "api": "public",
                "kind": "asyncio_socketpair",
                "allowed": "true",
            },
            False,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": True,
                "family": 1,
                "allowed": True,
            },
            True,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": True,
                "family": 2,
                "allowed": True,
            },
            True,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "unknown",
                "peer_verified": True,
                "family": 2,
                "allowed": True,
            },
            False,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": 1,
                "family": 2,
                "allowed": True,
            },
            False,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": True,
                "family": True,
                "allowed": True,
            },
            False,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": True,
                "family": 23,
                "allowed": True,
            },
            False,
        ),
        (
            2,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": True,
                "family": 2,
                "allowed": False,
            },
            False,
        ),
        (
            2.0,
            {
                "event": "socketpair.result",
                "kind": "asyncio_socketpair",
                "peer_verified": True,
                "family": 2,
                "allowed": True,
            },
            False,
        ),
        (2, {"event": "socketpair.future", "kind": "asyncio_socketpair", "allowed": True}, False),
    ],
)
def test_current_worker_rejects_unknown_or_malformed_socketpair_receipt(
    tmp_path, version, event, expected
):
    copy = tmp_path / "pinned-copy"
    sources = [{"path": "source.py", "sha256": "a" * 64}]
    facts = {
        "guard_version": version,
        "network_events": [event],
        "loaded_project_modules": {
            "civicgate": {"path": str(copy / "source.py"), "sha256": "a" * 64}
        },
    }
    assert current_worker().verify_guard_facts(facts, copy, sources) is expected
