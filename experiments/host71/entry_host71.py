"""Dedicated host worker entry; inert import and hard-disabled release."""

import argparse
from pathlib import Path


def main():
    from chat_v3.host_gate71 import require_release

    require_release()
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["server-worker-live"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    from bootstrap_v3 import initialize

    initialize(offline=False)
    from chat_v3 import providers_v3, worker_host71
    from chat_v3 import util71 as p
    from chat_v3.capture_binding71 import HostCapture71

    p.require(
        args.input.resolve().is_relative_to(args.root.resolve() / "turns"), "WORKER_INPUT_SCOPE"
    )
    providers_v3.Exchange = HostCapture71
    worker_host71.run(args.input)


if __name__ == "__main__":
    main()
