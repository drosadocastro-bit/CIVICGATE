"""Append-only local evaluation custody. No authority or scientific record writer."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from uuid import uuid4

from evals.harness.models import Artifact, Case

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def identity(path: Path, *, relative_to: Path = REPO) -> Artifact:
    raw = path.read_bytes()
    return Artifact(
        path=path.relative_to(relative_to).as_posix(), bytes=len(raw), sha256=sha256(raw)
    )


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def git(*args: str) -> str:
    return (
        subprocess.check_output(
            ["git", "-C", str(REPO), *args],
            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
            stderr=subprocess.PIPE,
        )
        .decode()
        .strip()
    )


def runtime() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.system(),
        "dependencies": {n: version(n) for n in ("mcp", "pydantic", "httpx", "langgraph")},
    }


def private_run_directory() -> Path:
    parent = ROOT / "private"
    parent.mkdir(exist_ok=True)
    # The repository rule must actually ignore raw runs, not merely say so.
    check = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "--quiet", "evals/private/probe.json"],
        env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
        check=False,
    )
    if check.returncode != 0:
        raise ValueError("RAW_EVIDENCE_NOT_GITIGNORED")
    path = parent / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:12])
    path.mkdir(exist_ok=False)
    return path


def load_cases(
    paths: list[Path], *, allow_holdout: bool = False, snapshots: dict[Path, bytes] | None = None
) -> list[Case]:
    result: list[Case] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_relative_to((ROOT / "datasets").resolve()):
            raise ValueError("DATASET_OUTSIDE_VERSIONED_EVAL_WORKSPACE")
        raw = snapshots[resolved] if snapshots is not None else resolved.read_bytes()
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                continue
            case = Case.model_validate_json(line)
            if case.case_id in seen:
                raise ValueError("DUPLICATE_CASE_ID")
            if case.split == "holdout" and not allow_holdout:
                raise ValueError("HOLDOUT_EXECUTION_NOT_AUTHORIZED")
            ref = case.semantic_reference
            if ref.source_path is not None:
                source = (REPO / ref.source_path).resolve()
                if not source.is_relative_to(REPO) or not source.is_file():
                    raise ValueError("INVALID_REFERENCE_PATH")
                if sha256(source.read_bytes()) != ref.source_sha256:
                    raise ValueError("HISTORICAL_REFERENCE_HASH_MISMATCH")
            if ref.status == "HISTORICAL_HUMAN_REFERENCE":
                source_obj = json.loads((REPO / str(ref.source_path)).read_bytes())
                original = next(
                    (c for c in source_obj["cases"] if c["id"] == ref.source_case_id), None
                )
                if original is None:
                    raise ValueError("UNKNOWN_HISTORICAL_REFERENCE_CASE")
                classification = original.get("human_classification")
                if classification and ref.classifications != [classification]:
                    raise ValueError("HISTORICAL_REFERENCE_LABEL_MISMATCH")
                if ref.flags != original.get("human_flags", []):
                    raise ValueError("HISTORICAL_REFERENCE_FLAGS_MISMATCH")
            seen.add(case.case_id)
            result.append(case)
    if not result:
        raise ValueError("EMPTY_DATASET")
    return result


def json_lines(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def child_environment() -> dict[str, str]:
    allowed = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "TEMP", "TMP", "COMSPEC")
        if name in os.environ
    }
    allowed.update(
        PYTHONPATH=os.pathsep.join((str(REPO / "src"), str(REPO))),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    return allowed


def deny_network() -> None:
    # Called inside the dedicated runner event loop, before MCP/provider work.
    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event in {
            "socket.connect",
            "socket.connect_ex",
            "socket.bind",
            "socket.sendto",
            "socket.getaddrinfo",
            "socket.gethostbyname",
            "socket.gethostbyaddr",
        }:
            raise PermissionError("EVAL001_NETWORK_DISABLED")
        if event == "socket.__new__" and len(args) > 1 and args[1] in (2, 10, 23):
            raise PermissionError("EVAL001_INET_DISABLED")

    sys.addaudithook(audit)
