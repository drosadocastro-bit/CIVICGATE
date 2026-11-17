"""Bounded external-package identities and exclusive documentary writes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from bootstrap_v3 import SOURCE

HERE = Path(__file__).resolve().parents[1]

MODE = "OFFLINE_PROVIDER_FIXTURES"


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def load(path: Path) -> Any:
    if any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size > 2_000_000:
        raise ValueError("EVIDENCE_PATH_OR_SIZE_REJECTED")
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def save(path: Path, value: Any) -> str:
    raw = canonical(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def verify_sources() -> str:
    path = HERE / "dependency-freeze-v3.json"
    for rel, entry in load(path)["files"].items():
        source = SOURCE / rel
        if any(
            p.is_symlink() for p in (source, *source.parents)
        ) or not source.resolve().is_relative_to(SOURCE.resolve()):
            raise ValueError("SOURCE_PATH_REJECTED")
        if sha(source.read_bytes()) != entry["sha256"]:
            raise ValueError("SOURCE_IDENTITY_MISMATCH")
    return sha(path.read_bytes())


def public_path(root: Path, turn: str) -> Path:
    import re

    if not re.fullmatch(r"TURN_[0-9a-f]{32}", turn):
        raise ValueError("UNKNOWN_TURN")
    target = root / "turns" / turn
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("EVIDENCE_PATH_REJECTED")
    return target
