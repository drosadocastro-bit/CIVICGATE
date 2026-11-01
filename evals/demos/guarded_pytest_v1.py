"""Install source and owned-synthetic-endpoint guards before project imports."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COPY = HERE.parent / "pinned-copy"


def _protected_source_root():
    config_path = COPY.parent / "execution" / "guard-config.json"
    if not config_path.is_file() or config_path.stat().st_size > 4096:
        raise RuntimeError("TRUSTED_SOURCE_GUARD_CONFIG_REQUIRED")

    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError("DUPLICATE_GUARD_CONFIG_FIELD")
            result[key] = value
        return result

    config = json.loads(config_path.read_bytes(), object_pairs_hook=no_duplicates)
    if (
        type(config) is not dict
        or set(config) != {"version", "source_root"}
        or type(config["version"]) is not int
        or config["version"] != 1
        or type(config["source_root"]) is not str
    ):
        raise RuntimeError("INVALID_TRUSTED_SOURCE_GUARD_CONFIG")
    source = Path(config["source_root"])
    if not source.is_absolute() or not source.is_dir():
        raise RuntimeError("INVALID_TRUSTED_SOURCE_ROOT")
    source = source.resolve(strict=True)
    copy = COPY.resolve(strict=True)
    if source.is_relative_to(copy) or copy.is_relative_to(source):
        raise RuntimeError("SOURCE_AND_PINNED_COPY_MUST_BE_DISJOINT")
    return source


ORIGINAL = _protected_source_root()
events = []
fixture_sockets = []


def stack_matches(module, function=None):
    frame = sys._getframe(1)
    while frame:
        if frame.f_globals.get("__name__") == module and (
            function is None or frame.f_code.co_name == function
        ):
            return True
        frame = frame.f_back
    return False


def socketpair_internal():
    return stack_matches("socket", "_fallback_socketpair") and (
        stack_matches("asyncio.proactor_events", "_make_self_pipe")
        or stack_matches("asyncio.selector_events", "_make_self_pipe")
    )


def owned(address):
    if not isinstance(address, tuple) or len(address) < 2 or address[0] != "127.0.0.1":
        return False
    for server in fixture_sockets:
        try:
            if server.fileno() >= 0 and server.getsockname()[:2] == address[:2]:
                return True
        except OSError:
            pass
    return False


def audit(event, arguments):
    if event == "open" and arguments and isinstance(arguments[0], (str, bytes, os.PathLike)):
        target = Path(os.fsdecode(arguments[0])).resolve()
        synthetic_probe = (
            target == COPY / "evals" / "datasets" / "SYNTHETIC_NONEXISTENT_GUARD_PROBE.jsonl"
            and not target.exists()
        )
        if target.is_relative_to(ORIGINAL) or ("datasets" in target.parts and not synthetic_probe):
            raise PermissionError("INDEPENDENT_SOURCE_OR_DATASET_ACCESS_DENIED")
    if event == "socket.bind":
        sock, address = arguments
        fixture = (
            isinstance(address, tuple)
            and address[:2] == ("127.0.0.1", 0)
            and stack_matches("evals.harness.synthetic_http_server_v1")
        )
        internal = socketpair_internal()
        events.append(
            {
                "event": event,
                "address": str(address),
                "allowed": fixture or internal,
                "kind": "owned_synthetic_fixture"
                if fixture
                else "asyncio_socketpair"
                if internal
                else "denied",
            }
        )
        if fixture:
            fixture_sockets.append(sock)
        if not (fixture or internal):
            raise PermissionError("INDEPENDENT_NON_FIXTURE_BIND_DENIED")
    if event in {"socket.connect", "socket.connect_ex"}:
        address = arguments[1]
        internal = socketpair_internal()
        allowed = owned(address) or internal
        events.append(
            {
                "event": event,
                "address": str(address),
                "allowed": allowed,
                "kind": "asyncio_socketpair"
                if internal
                else "owned_synthetic_fixture"
                if allowed
                else "denied",
            }
        )
        if not allowed:
            raise PermissionError("INDEPENDENT_NON_OWNED_CONNECT_DENIED")
    if event == "socket.getaddrinfo":
        allowed = owned(arguments[:2])
        events.append(
            {
                "event": event,
                "host": str(arguments[0]),
                "port": str(arguments[1]),
                "allowed": allowed,
            }
        )
        if not allowed:
            raise PermissionError("INDEPENDENT_NON_OWNED_DNS_DENIED")
    if event in {"socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto"}:
        events.append({"event": event, "allowed": False})
        raise PermissionError("INDEPENDENT_EXTERNAL_NETWORK_DENIED")


sys.addaudithook(audit)


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


import pytest  # noqa: E402 - install the source/network guard before third-party imports.

try:
    exit_code = pytest.main(
        [
            "-q",
            "--noconftest",
            "-c",
            str(COPY / "isolated-pytest.ini"),
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(HERE / "pytest-tmp"),
            "--junitxml",
            str(HERE / "junit.xml"),
            *sys.argv[1:],
        ]
    )
finally:
    loaded = {}
    for name, module in tuple(sys.modules.items()):
        if (
            name == "civicgate"
            or name.startswith("civicgate.")
            or name == "evals"
            or name.startswith("evals.")
        ):
            file = getattr(module, "__file__", None)
            if file:
                path = Path(file).resolve()
                if not path.is_relative_to(COPY):
                    raise RuntimeError("LOADED_PROJECT_MODULE_OUTSIDE_COPY")
                loaded[name] = {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
    save(
        HERE / "guard-evidence.json",
        {
            "network_events": events,
            "loaded_project_modules": loaded,
            "environment_keys": sorted(os.environ),
            "limit": "Python guard, not OS isolation. Environment .pth code precedes audit-hook installation. Asyncio socketpair setup is permitted separately from fixture routes.",
        },
    )
raise SystemExit(exit_code)
