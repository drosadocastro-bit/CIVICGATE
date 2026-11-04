"""CP1.5 guard: bounded genuine asyncio self-pipes, before project imports."""

from __future__ import annotations

import _socket
import hashlib
import json
import marshal
import os
import socket
import sys
import sysconfig
from asyncio import proactor_events, selector_events
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


# Capture trusted stdlib objects before any project imports. This is a Python
# process boundary, not protection against a hostile interpreter or local host.
STDLIB = Path(sysconfig.get_path("stdlib")).resolve()
STDLIB_SOURCES = []
for _module in (socket, proactor_events, selector_events):
    _path = Path(_module.__file__).resolve(strict=True)
    if not _path.is_relative_to(STDLIB):
        raise RuntimeError("STDLIB_SOCKETPAIR_PROVENANCE_REQUIRED")
    STDLIB_SOURCES.append(
        {
            "module": _module.__name__,
            "path": str(_path),
            "sha256": hashlib.sha256(_path.read_bytes()).hexdigest(),
        }
    )
SOCKET_TYPE = socket.socket
PUBLIC_PAIR = socket.socketpair
NATIVE_PAIR = getattr(_socket, "socketpair", None)
PAIR_CODES = {
    function.__code__
    for function in (PUBLIC_PAIR, getattr(socket, "_fallback_socketpair", PUBLIC_PAIR))
}
SELF_PIPES = (
    (
        proactor_events.BaseProactorEventLoop._make_self_pipe,
        proactor_events.BaseProactorEventLoop.__init__,
    ),
    (
        selector_events.BaseSelectorEventLoop._make_self_pipe,
        selector_events.BaseSelectorEventLoop.__init__,
    ),
)
SELF_PIPE_CODES = tuple(
    (pipe.__code__, pipe.__globals__, constructor.__code__, constructor.__globals__)
    for pipe, constructor in SELF_PIPES
)
STDLIB_CALLABLES = [
    {
        "module": function.__module__,
        "name": function.__qualname__,
        "code_name": function.__code__.co_name,
        "first_line": function.__code__.co_firstlineno,
        "code_sha256": hashlib.sha256(marshal.dumps(function.__code__)).hexdigest(),
    }
    for function in (PUBLIC_PAIR, *(item for pair in SELF_PIPES for item in pair))
]
pair_listeners = {}


def genuine_self_pipe(frame):
    """Exact stdlib self-pipe and constructor code/globals, on the same loop."""
    if frame is None or frame.f_back is None:
        return False
    for pipe_code, pipe_globals, constructor_code, constructor_globals in SELF_PIPE_CODES:
        if (
            frame.f_code is pipe_code
            and frame.f_globals is pipe_globals
            and frame.f_back.f_code is constructor_code
            and frame.f_back.f_globals is constructor_globals
            and frame.f_locals.get("self") is frame.f_back.f_locals.get("self")
        ):
            return True
    return False


def pair_context(frame):
    """No intervening project callback may borrow the internal allowance."""
    if (
        frame is None
        or frame.f_code not in PAIR_CODES
        or frame.f_globals is not PUBLIC_PAIR.__globals__
    ):
        return None
    wrapper = frame.f_back
    if (
        wrapper is None
        or wrapper.f_code is not public_socketpair_guard.__code__
        or wrapper.f_globals is not globals()
        or not genuine_self_pipe(wrapper.f_back)
    ):
        return None
    return frame


def pair_call_event(api, allowed):
    events.append(
        {
            "event": "socketpair.call",
            "api": api,
            "allowed": allowed,
            "kind": "asyncio_socketpair" if allowed else "denied",
        }
    )
    if not allowed:
        raise PermissionError("INDEPENDENT_NON_ASYNCIO_SOCKETPAIR_DENIED")


def public_socketpair_guard(*args, **kwargs):
    # Both supported stdlib self-pipe methods call socketpair with no arguments.
    allowed = not args and not kwargs and genuine_self_pipe(sys._getframe(1))
    pair_call_event("public", allowed)
    pair = PUBLIC_PAIR(*args, **kwargs)
    left, right = pair
    try:
        verified = (
            type(left) is SOCKET_TYPE
            and type(right) is SOCKET_TYPE
            and left.family == right.family
            and left.family in (socket.AF_INET, getattr(socket, "AF_UNIX", -1))
            and left.getsockname() == right.getpeername()
            and right.getsockname() == left.getpeername()
        )
    except OSError:
        verified = False
    events.append(
        {
            "event": "socketpair.result",
            "allowed": verified,
            "kind": "asyncio_socketpair" if verified else "denied",
            "peer_verified": verified,
            "family": int(left.family),
        }
    )
    if not verified:
        left.close()
        right.close()
        raise PermissionError("INDEPENDENT_SOCKETPAIR_PEER_VERIFICATION_FAILED")
    return pair


def native_socketpair_guard(*args, **kwargs):
    # Native socketpair has no bind/connect audit event. Intercept its module API
    # too, before project imports, and delegate only from the real Python wrapper.
    frame = pair_context(sys._getframe(1))
    values = frame.f_locals if frame is not None else {}
    expected = (values.get("family"), values.get("type"), values.get("proto"))
    allowed = (
        frame is not None
        and not kwargs
        and args == expected
        and expected[0] in (socket.AF_INET, socket.AF_INET6, getattr(socket, "AF_UNIX", -1))
        and expected[1:] == (socket.SOCK_STREAM, 0)
    )
    pair_call_event("native", allowed)
    return NATIVE_PAIR(*args, **kwargs)


def unbound_socket(sock):
    try:
        return sock.getsockname()[1] == 0
    except OSError as error:
        # Winsock reports WSAEINVAL for getsockname before the initial bind.
        # No other failure or unknown socket state grants the allowance.
        return os.name == "nt" and getattr(error, "winerror", None) == 10022


def internal_bind(sock, address, caller):
    frame = pair_context(caller)
    if frame is None:
        return False
    values = frame.f_locals
    allowed = (
        type(sock) is SOCKET_TYPE
        and values.get("lsock") is sock
        and values.get("family") == socket.AF_INET
        and values.get("type") == socket.SOCK_STREAM
        and values.get("proto") == 0
        and sock.family == socket.AF_INET
        and sock.type == socket.SOCK_STREAM
        and sock.proto == 0
        and type(address) is tuple
        and len(address) == 2
        and type(address[0]) is str
        and type(address[1]) is int
        and address == ("127.0.0.1", 0)
        and unbound_socket(sock)
    )
    # Retain only live, unconsumed listener records. A successful connect removes
    # its record before delivery; an unknown/rejected attempt is never refunded.
    for key, value in tuple(pair_listeners.items()):
        if value[1].fileno() < 0:
            del pair_listeners[key]
    if not allowed or id(frame) in pair_listeners:
        return False
    pair_listeners[id(frame)] = (frame, sock)
    return True


def internal_connect(event, sock, address, caller):
    frame = pair_context(caller)
    if frame is None:
        return False
    record = pair_listeners.pop(id(frame), None)
    if record is None or record[0] is not frame:
        return False
    listener = record[1]
    values = frame.f_locals
    return (
        event == "socket.connect"
        and type(sock) is SOCKET_TYPE
        and values.get("csock") is sock
        and values.get("lsock") is listener
        and sock.family == socket.AF_INET
        and sock.type == socket.SOCK_STREAM
        and sock.proto == 0
        and listener.fileno() >= 0
        and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1
        and listener.getsockname() == address
        and type(address) is tuple
        and len(address) == 2
        and type(address[0]) is str
        and address[0] == "127.0.0.1"
        and type(address[1]) is int
        and 1 <= address[1] <= 65535
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
        internal = internal_bind(sock, address, sys._getframe(1))
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
        sock, address = arguments
        internal = internal_connect(event, sock, address, sys._getframe(1))
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
socket.socketpair = public_socketpair_guard
if NATIVE_PAIR is not None:
    _socket.socketpair = native_socketpair_guard
LEGACY_ALIAS_INSTALLED = False
if (
    os.name == "nt"
    and sys.version_info[:2] == (3, 11)
    and not hasattr(socket, "_fallback_socketpair")
):
    if PUBLIC_PAIR.__code__.co_name != "socketpair":
        raise RuntimeError("UNKNOWN_WINDOWS311_SOCKETPAIR_IMPLEMENTATION")
    # Frozen compositions recognize this stdlib code by its newer attribute
    # name. Expose the genuine original function, never a fabricated frame or a
    # replacement hook. The independent V2 audit gate still constrains every
    # bind/connect; directly calling this alias cannot borrow its allowance.
    socket._fallback_socketpair = PUBLIC_PAIR
    LEGACY_ALIAS_INSTALLED = True


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
            "guard_version": 2,
            "guard_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "stdlib_sources": STDLIB_SOURCES,
            "stdlib_callables": STDLIB_CALLABLES,
            "compatibility_alias": {
                "installed": LEGACY_ALIAS_INSTALLED,
                "name": "socket._fallback_socketpair",
                "target_code_sha256": STDLIB_CALLABLES[0]["code_sha256"]
                if LEGACY_ALIAS_INSTALLED
                else None,
            },
            "network_events": events,
            "loaded_project_modules": loaded,
            "environment_keys": sorted(os.environ),
            "limit": "Python guard, not OS isolation. Environment .pth code precedes audit-hook installation. Exact stdlib self-pipe initialization and live listener ownership are required; module API interception does not certify hostile-host/native-code isolation.",
        },
    )
raise SystemExit(exit_code)
