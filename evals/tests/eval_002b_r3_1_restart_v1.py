"""A fresh controller recovery check only: never begin/reserve/dispatch."""

import hashlib
import json
import os
import sys
from pathlib import Path

COPY = Path.cwd().resolve()


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


def audit(event, args):
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).resolve()
        if path.is_relative_to(ORIGINAL) or "datasets" in path.parts:
            raise PermissionError("MINI02_ORIGINAL_DATASET_DISABLED")
    if event.startswith("socket.") and event != "socket.__new__":
        raise PermissionError("MINI02_RESTART_NETWORK_DISABLED")


sys.addaudithook(audit)
from evals.harness.live_attempt_budget_v1 import (  # noqa: E402 - guard precedes project imports
    LiveAttemptBudget,
)

database, run_id, output = sys.argv[1:]
budget = LiveAttemptBudget(Path(database), run_id)
before = budget.snapshot()
allowed = False
error = None
try:
    budget.ensure_recoverable()
    allowed = True
except Exception as exc:
    error = {"type": type(exc).__name__, "reason": str(exc)}
after = budget.snapshot()
loaded = {}
for name, module in tuple(sys.modules.items()):
    if name.startswith(("civicgate.", "evals.")) and getattr(module, "__file__", None):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(COPY), str(path)
        loaded[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
result = {
    "pid": os.getpid(),
    "ensure_recoverable_allowed": allowed,
    "error": error,
    "before": before,
    "after": after,
    "state_unchanged": before == after,
    "new_admission_or_dispatch_performed": False,
    "loaded_project_modules": loaded,
}
with Path(output).open("x", encoding="utf-8") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
