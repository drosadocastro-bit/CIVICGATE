"""Pure JSON/path utilities; no historical custody or authority."""

import hashlib
import json
import os
import stat
from pathlib import Path

QUESTION = "Show 5 public federal contract awards in Puerto Rico from 2025-10-01 to 2026-09-30."


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value, ascii=False):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=ascii, allow_nan=False
    ).encode()


def require(value, code):
    if not value:
        raise ValueError(code)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_FIELD")
        result[key] = value
    return result


def parse(raw):
    def reject(value):
        raise ValueError("NONFINITE_JSON")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    require(type(value) is dict, "OBJECT_REQUIRED")
    return value


def safe(path):
    path = Path(path)
    require(path.is_absolute() and not str(path).startswith("\\\\"), "LOCAL_PATH_REQUIRED")
    for part in (path, *path.parents):
        require(not part.is_symlink(), "LINK_HOLD")
        if part.exists():
            require(
                not getattr(part.lstat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024),
                "REPARSE_HOLD",
            )
    return path


def read(path):
    path = safe(path)
    require(path.is_file() and path.stat().st_size <= 2_000_000, "FILE_HOLD")
    return path.read_bytes()


def _write(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)
