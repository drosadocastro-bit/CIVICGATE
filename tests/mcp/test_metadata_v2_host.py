"""Trusted-host metadata v2 launcher: strict CLI and real synthetic STDIO."""

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from civicgate.mcp.metadata_v2_host import _parse_args


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ([], "required"),
        (["--profile", "synthetic-write"], "--host-config is required"),
        (
            ["--profile", "public-read", "--host-config", "unexpected.json"],
            "--host-config is forbidden",
        ),
        (["--profile", "unregistered"], "invalid choice"),
    ],
)
def test_v2_host_requires_explicit_trusted_profile(argv, message, capsys):
    with pytest.raises(SystemExit) as exc:
        _parse_args(argv)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("profile", ["public-read", "synthetic-write"])
async def test_v2_host_real_stdio_exposes_versioned_metadata_without_calls(tmp_path, profile):
    from evals.write01.demo_v1 import REQUEST, prepare, query

    root = Path(__file__).resolve().parents[2]
    args = ["-B", "-m", "civicgate.mcp.metadata_v2_host", "--profile", profile]
    if profile == "synthetic-write":
        work = tmp_path / "synthetic-write"
        prepare(work, REQUEST, query(), approved=True)
        args.extend(["--host-config", str(work / "host-config.json")])

    # Only the minimum process environment is inherited. No provider
    # credentials are supplied, and no tool invocation is performed.
    env = {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP")
        if key in os.environ
    }
    env.update(
        PYTHONPATH=str(root / "src") + os.pathsep + str(root),
        PYTHONDONTWRITEBYTECODE="1",
        LANGSMITH_TRACING="false",
    )
    params = StdioServerParameters(command=sys.executable, args=args, env=env)
    log = tmp_path / "stderr.log"
    try:
        with log.open("x", encoding="utf-8") as errors:
            async with stdio_client(params, errlog=errors) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    listing = await client.list_tools()
                    assert listing.meta is not None
                    assert listing.meta["civicgateMetadataContract"] == "MCP_TOOL_METADATA_V2"
                    expected_profile = (
                        "write01-stdio" if profile == "synthetic-write" else "primary-stdio"
                    )
                    assert listing.meta["profile"] == expected_profile
                    by_name = {tool.name: tool for tool in listing.tools}
                    if profile == "synthetic-write":
                        assert set(by_name) == {
                            "update_synthetic_award_review",
                            "get_synthetic_award_review_v1",
                        }
                        assert (
                            by_name["update_synthetic_award_review"].annotations.destructiveHint
                            is True
                        )
                        assert (
                            by_name["update_synthetic_award_review"].annotations.idempotentHint
                            is False
                        )
                    else:
                        assert len(by_name) == 4
                        assert all(
                            tool.annotations is not None
                            and tool.annotations.openWorldHint is True
                            and tool.annotations.readOnlyHint is True
                            for tool in by_name.values()
                        )
    except ExceptionGroup:
        if log.is_file():
            print(
                "V2 host child stderr:\n"
                + log.read_text(encoding="utf-8", errors="replace")[-12000:]
            )
        raise

    if profile == "synthetic-write":
        # tools/list cannot consume approval or mutate synthetic state.
        assert not (work / "audit.jsonl").read_text(encoding="utf-8").strip()
