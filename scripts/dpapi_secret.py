"""Small Windows-user DPAPI secret store CLI.

The encrypted store lives outside the repository. Secret values are accepted only
through an interactive prompt and are never printed.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from civicgate.windows_dpapi import WindowsDPAPIStore  # noqa: E402


def default_store_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for the Windows DPAPI store")
    return Path(local_app_data) / "CivicGate" / "secrets.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local CivicGate DPAPI secrets")
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="override the absolute store path (for local testing only)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_parser = subparsers.add_parser("set", help="prompt for and store one secret")
    set_parser.add_argument("name", help="secret name, for example CIVICGATE_JUDGE_API_KEY")
    subparsers.add_parser("list", help="list stored secret names without values")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = WindowsDPAPIStore(args.path or default_store_path())
        if args.command == "list":
            # The edge store intentionally exposes only names for this command.
            names = sorted(store._read())
            for name in names:
                print(name)
            return 0

        value = getpass.getpass(f"Value for {args.name}: ")
        store.set_value(args.name, value)
        print(f"Stored {args.name} in the current Windows user's DPAPI store.")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Unable to update the DPAPI store: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
