"""Verify copied dependencies before loading project source. Offline only."""

import hashlib
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NoReturn
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def source_root():
    for parent in HERE.parents:
        if (parent / "src/civicgate/__init__.py").is_file() and (
            parent / "pyproject.toml"
        ).is_file():
            return parent
    import importlib.util

    spec = importlib.util.find_spec("civicgate")
    if spec is None or spec.origin is None:
        raise RuntimeError("REPOSITORY_SOURCE_REQUIRED")
    root = Path(spec.origin).resolve().parents[2]
    if not (root / "pyproject.toml").is_file():
        raise RuntimeError("REPOSITORY_SOURCE_REQUIRED")
    return root


SOURCE = source_root()
NETWORK_GUARD = ExitStack()


def initialize(*, offline: bool = True) -> None:
    inventory = json.loads((HERE / "dependency-freeze-v3.json").read_bytes())
    for relative, identity in inventory["files"].items():
        path = SOURCE / relative
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(
            SOURCE.resolve()
        ):
            raise RuntimeError("SOURCE_PATH_REJECTED")
        if hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]:
            raise RuntimeError("SOURCE_IDENTITY_MISMATCH")
    sys.path[:0] = [str(HERE), str(SOURCE / "src"), str(SOURCE)]
    if not offline:
        return
    import socket

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_dns = socket.getaddrinfo

    def check_address(address: Any) -> None:
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("OFFLINE_EXTERNAL_SOCKET_FORBIDDEN")

    def connect(sock: Any, address: Any) -> Any:
        check_address(address)
        return original_connect(sock, address)

    def connect_ex(sock: Any, address: Any) -> Any:
        check_address(address)
        return original_connect_ex(sock, address)

    def dns(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in {None, "127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("OFFLINE_EXTERNAL_DNS_FORBIDDEN")
        return original_dns(host, *args, **kwargs)

    NETWORK_GUARD.enter_context(patch.object(socket.socket, "connect", connect))
    NETWORK_GUARD.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
    NETWORK_GUARD.enter_context(patch.object(socket, "getaddrinfo", dns))
    import httpx

    def denied(*args: Any, **kwargs: Any) -> NoReturn:
        raise RuntimeError("OFFLINE_GENUINE_HTTP_TRANSPORT_FORBIDDEN")

    NETWORK_GUARD.enter_context(patch.object(httpx.AsyncHTTPTransport, "__init__", denied))
    NETWORK_GUARD.enter_context(patch.object(httpx.HTTPTransport, "__init__", denied))


def verify_live_source(root: Path, profile_path: Path | None, anchor_path: Path | None) -> None:
    import time

    if profile_path is None:
        record = json.loads((root / "session.json").read_bytes())
        profile, anchor_path = record["profile"], Path(record["anchor"])
    else:
        profile = json.loads(profile_path.read_bytes())
    if anchor_path is None or anchor_path.resolve().is_relative_to(HERE):
        raise RuntimeError("SEPARATE_HOST_APPROVAL_REQUIRED")
    if any(p.is_symlink() for p in (anchor_path, *anchor_path.parents)):
        raise RuntimeError("APPROVAL_PATH_REJECTED")
    anchor = json.loads(anchor_path.read_bytes())
    encoded = json.dumps(
        profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    if (
        anchor.get("decision") != "HUMAN_APPROVED_CHAT03_LIVE"
        or anchor.get("profile_sha256") != hashlib.sha256(encoded).hexdigest()
        or anchor.get("experiment") != profile["experiment"]
        or time.time() >= anchor.get("expires_unix", 0)
    ):
        raise RuntimeError("UNAPPROVED_LIVE_PROFILE")
    manifest = HERE / "chat-source-inventory-v1.json"
    identity = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if (
        identity != anchor.get("source_inventory_sha256")
        or identity != profile["source_inventory_sha256"]
    ):
        raise RuntimeError("UNAPPROVED_LIVE_SOURCE")
    for relative, entry in json.loads(manifest.read_bytes())["files"].items():
        target = HERE / relative
        if (
            not target.resolve().is_relative_to(HERE)
            or any(p.is_symlink() for p in (target, *target.parents))
            or hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]
        ):
            raise RuntimeError("SOURCE_IDENTITY_MISMATCH")
