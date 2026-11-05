"""Start local evidence views; synthetic demonstrations require explicit opt-in."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_catalog(path: Path, *, allow_empty: bool = False) -> list[dict]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("INVALID_CATALOG")
            value[key] = item
        return value

    with path.open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("INVALID_CATALOG")
    value = json.loads(raw, object_pairs_hook=unique)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "runs"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["runs"], list)
        or not (0 if allow_empty else 1) <= len(value["runs"]) <= 8
    ):
        raise ValueError("INVALID_CATALOG")
    return value["runs"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--enable-synthetic-e2e", action="store_true")
    parser.add_argument("--worker-python", type=Path)
    parser.add_argument("--execution-root", type=Path)
    parser.add_argument("--deadline-seconds", type=int, default=90)
    parser.add_argument("--max-jobs", type=int, default=8)
    parser.add_argument("--enable-synthetic-chat", action="store_true")
    parser.add_argument("--chat-output-root", type=Path)
    parser.add_argument("--chat-deadline-seconds", type=int, default=90)
    parser.add_argument("--chat-max-turns", type=int, default=4)
    parser.add_argument("--advisor-mode", choices=("off", "mock"), default="off")
    parser.add_argument("--advisor-output-root", type=Path)
    parser.add_argument("--advisor-max-jobs", type=int, default=8)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        from civicgate.evidence_console.app import create_app

        entries = load_catalog(
            args.catalog,
            allow_empty=args.enable_synthetic_e2e or args.enable_synthetic_chat,
        )
        executor = None
        chat = None
        synthetic_enabled = args.enable_synthetic_e2e or args.enable_synthetic_chat
        if synthetic_enabled:
            if args.worker_python is None:
                raise ValueError("EXPLICIT_SYNTHETIC_WORKER_REQUIRED")
            if args.enable_synthetic_e2e and args.execution_root is None:
                raise ValueError("EXPLICIT_SYNTHETIC_CONFIGURATION_REQUIRED")
            if args.enable_synthetic_chat and args.chat_output_root is None:
                raise ValueError("EXPLICIT_CHAT_CONFIGURATION_REQUIRED")
            from civicgate.evidence_console.reader import MAX_RUNS

            requested_runs = (args.max_jobs if args.enable_synthetic_e2e else 0) + (
                args.chat_max_turns if args.enable_synthetic_chat else 0
            )
            if len(entries) + requested_runs > MAX_RUNS:
                raise ValueError("CATALOG_CAPACITY_EXCEEDED")
            source = Path(__file__).resolve().parents[1]
            outputs = [
                path.absolute()
                for path in (args.execution_root, args.chat_output_root)
                if path is not None
            ]
            for entry in entries:
                historical = Path(entry["root"]).absolute()
                if any(
                    output.is_relative_to(historical) or historical.is_relative_to(output)
                    for output in outputs
                ):
                    raise ValueError("HISTORICAL_EVIDENCE_OVERLAP")
            if len(outputs) == 2 and (
                outputs[0].is_relative_to(outputs[1]) or outputs[1].is_relative_to(outputs[0])
            ):
                raise ValueError("SYNTHETIC_OUTPUT_OVERLAP")
            protected = tuple(Path(entry["root"]) for entry in entries)
            if args.enable_synthetic_e2e:
                from civicgate.evidence_console.demo_execution_v1 import DemoExecutor

                assert args.execution_root is not None
                executor = DemoExecutor(
                    source,
                    args.execution_root.absolute(),
                    args.worker_python,
                    deadline_seconds=args.deadline_seconds,
                    max_jobs=args.max_jobs,
                    protected_roots=protected
                    + (
                        (args.chat_output_root.absolute(),)
                        if args.chat_output_root is not None
                        else ()
                    ),
                )
            if args.enable_synthetic_chat:
                from civicgate.evidence_console.chat_execution_v1 import ChatExecutor

                assert args.chat_output_root is not None
                chat = ChatExecutor(
                    source,
                    args.chat_output_root.absolute(),
                    args.worker_python,
                    deadline_seconds=args.chat_deadline_seconds,
                    max_jobs=args.chat_max_turns,
                    protected_roots=protected
                    + (
                        (args.execution_root.absolute(),) if args.execution_root is not None else ()
                    ),
                )
        elif (
            args.worker_python is not None
            or args.execution_root is not None
            or args.chat_output_root is not None
        ):
            raise ValueError("SYNTHETIC_OPT_IN_REQUIRED")
        advisor = None
        if args.advisor_mode == "mock":
            if args.advisor_output_root is None:
                raise ValueError("ADVISOR_EXPLICIT_OUTPUT_REQUIRED")
            from civicgate.evidence_console.anthropic_advisor_v1 import MockAdvisor, ProviderConfig
            from civicgate.evidence_console.evidence_advisor_v1 import AdvisorService
            from civicgate.evidence_console.reader import EvidenceStore

            protected = [Path(entry["root"]) for entry in entries]
            if args.execution_root is not None:
                protected.append(args.execution_root)
            if args.chat_output_root is not None:
                protected.append(args.chat_output_root)
            advisor = AdvisorService(
                lambda: EvidenceStore(
                    [
                        *entries,
                        *(executor.evidence_entries() if executor is not None else []),
                        *(chat.evidence_entries() if chat is not None else []),
                    ]
                ),
                MockAdvisor(
                    ProviderConfig(
                        model="synthetic-claude-advisor-v1", max_requests=args.advisor_max_jobs
                    )
                ),
                args.advisor_output_root,
                max_jobs=args.advisor_max_jobs,
                protected_roots=protected,
            )
        elif args.advisor_output_root is not None:
            raise ValueError("ADVISOR_EXPLICIT_OPT_IN_REQUIRED")
        app = create_app(entries, executor=executor, advisor=advisor, chat=chat)
    except Exception:
        print("Console not started: invalid or unavailable local catalog.", file=sys.stderr)
        return 2
    import uvicorn

    modes = ["read-only evidence"]
    if executor is not None:
        modes.insert(0, "synthetic E2E")
    if chat is not None:
        modes.insert(0, "synthetic governed Chat")
    mode = " + ".join(modes)
    print(f"{mode} console: http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        forwarded_allow_ips="",
        access_log=False,
        limit_concurrency=8,
        timeout_keep_alive=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
