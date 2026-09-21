"""Explicit-profile benchmark planning and opt-in frozen execution. Import is inert."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import httpx  # noqa: E402

from civicgate.llm.live import LiveJudgeProvider, ProviderError, _JudgeSignalWire  # noqa: E402
from civicgate.models.provenance import utcnow  # noqa: E402
from civicgate.models.requests import Proposal  # noqa: E402
from civicgate.runtime_config import (  # noqa: E402
    InMemoryConfiguration,
    RuntimeSettings,
    SecretProvider,
)
from civicgate.windows_dpapi import WindowsDPAPIStore  # noqa: E402
from scripts import run_live_judge_benchmark as engine  # noqa: E402

SMOKE_COMMIT = "a5cdb8b12983c498ddf86a7425c62f03417bf029"
MANIFEST = ROOT / "docs/J3_BENCHMARK_FREEZE.json"


@dataclass(frozen=True)
class Profile:
    name: str
    provider: str
    protocol: str
    base_url: str
    model: str
    secret_name: str
    token_field: str
    endpoint: str
    timeout_seconds: float = 30.0
    max_attempts: int = 1


PROFILES = MappingProxyType(
    {
        "j2-luna": Profile(
            "j2-luna",
            "openai_compatible",
            "openai_compatible",
            "https://api.openai.com/v1",
            "gpt-5.6-luna",
            "CIVICGATE_OPENAI_JUDGE_API_KEY",
            "max_completion_tokens",
            "https://api.openai.com/v1/chat/completions",
        ),
        "j3-sonnet": Profile(
            "j3-sonnet",
            "anthropic",
            "anthropic_messages",
            "https://api.anthropic.com",
            "claude-sonnet-5",
            "CIVICGATE_ANTHROPIC_JUDGE_API_KEY",
            "max_tokens",
            "https://api.anthropic.com/v1/messages",
        ),
    }
)


def select_profile(name: str) -> Profile:
    if name not in PROFILES:
        raise engine.BenchmarkAbort("UNKNOWN_BENCHMARK_PROFILE")
    return PROFILES[name]


def payload(profile: Profile, case: dict[str, Any]) -> dict[str, Any]:
    if profile != select_profile(profile.name):
        raise engine.BenchmarkAbort("PROFILE_MISMATCH")
    content = json.dumps(
        {
            "request": case["request"],
            "proposal": Proposal(tool=case["tool"], arguments=case["arguments"]).model_dump(),
        },
        sort_keys=True,
    )
    if profile.name == "j2-luna":
        return engine._payload(case)
    return {
        "model": profile.model,
        "max_tokens": 512,
        "system": engine._prompt(),
        "messages": [{"role": "user", "content": content}],
    }


def file_hash(path: Path) -> str:
    # Portable source identity under .gitattributes; do not rewrite local files.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def source_hashes() -> dict[str, str]:
    paths = [
        Path(__file__),
        Path(engine.__file__),
        ROOT / "tests/fixtures/adversarial.json",
        ROOT / "tests/unit/test_profiled_judge_benchmark.py",
        ROOT / "tests/unit/test_live_judge_benchmark.py",
        ROOT / "tests/unit/test_j3_readiness.py",
        ROOT / "tests/unit/test_judge_credential_routing.py",
        ROOT / "scripts/replay_recorded_judge_signals.py",
        ROOT / "docs/J2_SIGNAL_REPLAY.md",
        *sorted((ROOT / "src").rglob("*.py")),
    ]
    return {p.relative_to(ROOT).as_posix(): file_hash(p) for p in paths}


def plan(name: str) -> dict[str, Any]:
    """No configuration/credential resolution, transport construction or HTTP."""
    profile = select_profile(name)
    fixtures = engine._load_fixtures()
    schedule = engine._schedule(fixtures)
    ids = [c["id"] for c in fixtures]
    if len(ids) != 35 or len(set(ids)) != 35 or len(schedule) != 44:
        raise engine.BenchmarkAbort("FIXTURE_INVENTORY_MISMATCH")
    if not (engine.INJECTION_IDS | engine.PREFLIGHT_IDS | set(engine.REPEAT_IDS)) <= set(ids):
        raise engine.BenchmarkAbort("FIXTURE_INVENTORY_MISMATCH")
    for case in fixtures:
        payload(profile, case)
    return {
        "schema_version": "civicgate.judge-profile-plan.v1",
        "hash_algorithm": "SHA-256 of file bytes with CRLF normalized to LF; local files are not rewritten",
        "profile": asdict(profile),
        "primary_fixture_count": 35,
        "repeat_observation_count": 9,
        "intended_http_calls": 44,
        "automatic_retries": 0,
        "external_calls_in_plan": 0,
        "token_limit": 512,
        "parameter_names": sorted(payload(profile, fixtures[0])),
        "fixture_ids": ids,
        "schedule": schedule,
        "fixture_sha256": file_hash(ROOT / "tests/fixtures/adversarial.json"),
        "contract_sha256": hashlib.sha256(engine._prompt().encode()).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(engine.JUDGE_SYSTEM_PROMPT.encode()).hexdigest(),
        "wire_schema_sha256": hashlib.sha256(
            json.dumps(_JudgeSignalWire.model_json_schema(), sort_keys=True).encode()
        ).hexdigest(),
        "runner_sha256": file_hash(Path(__file__)),
        "repeat_ids": engine.REPEAT_IDS,
        "repeat_observations_per_family": 3,
        "injection_ids": sorted(engine.INJECTION_IDS),
        "rules": engine.RULES,
        "provider_completion_rule": "end_turn, exactly one usable text block, strict wire, no refusal"
        if name == "j3-sonnet"
        else "stop, typed available signal, strict wire, no refusal",
        "disagreement_rules": {
            "reference": "J1 deterministic engineering classification, not human truth; J2 is not human truth",
            "population": "valid primary observations only; exact classification mismatch; repeats separate",
            "inspection": "preserve full request/proposal and literal five typed fields; inspect confidence, flags, preflight and timing without relabeling",
            "authority": "static potential effects require separate authorized offline Gateway replay; no model resampling",
            "replay_method": "docs/J2_SIGNAL_REPLAY.md; fresh Gateway and exact typed signals; flags NONE remains open",
        },
        "source_sha256": source_hashes(),
    }


def settings(profile: Profile, secrets: SecretProvider) -> RuntimeSettings:
    if profile != select_profile(profile.name):
        raise engine.BenchmarkAbort("PROFILE_MISMATCH")
    return RuntimeSettings.from_providers(
        InMemoryConfiguration(
            {
                "CIVICGATE_JUDGE_PROVIDER": profile.provider,
                "CIVICGATE_JUDGE_PROTOCOL": profile.protocol,
                "CIVICGATE_JUDGE_BASE_URL": profile.base_url,
                "CIVICGATE_JUDGE_MODEL": profile.model,
            }
        ),
        secrets,
    )


def versioned_manifest() -> dict[str, Any]:
    """SELF is resolved by Git, avoiding an impossible self-referential commit hash."""
    return {
        "schema_version": "civicgate.j3-benchmark-freeze.v1",
        "instrument_commit": {
            "resolution": "commit introducing docs/J3_BENCHMARK_FREEZE.json",
            "required_parent": SMOKE_COMMIT,
        },
        "smoke_instrument_commit": SMOKE_COMMIT,
        "live_execution_status": "NOT_RUN_REQUIRES_SEPARATE_HUMAN_AUTHORIZATION",
        "plan": plan("j3-sonnet"),
    }


def verify_versioned_manifest() -> str:
    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if frozen != versioned_manifest():
        raise engine.BenchmarkAbort("VERSIONED_FREEZE_MISMATCH")
    commit = (
        engine._git("log", "--diff-filter=A", "--format=%H", "--", "docs/J3_BENCHMARK_FREEZE.json")
        .decode()
        .splitlines()
    )
    if len(commit) != 1:
        raise engine.BenchmarkAbort("FREEZE_COMMIT_UNRESOLVED")
    if engine._git("rev-parse", commit[0] + "^").decode().strip() != SMOKE_COMMIT:
        raise engine.BenchmarkAbort("FREEZE_PARENT_MISMATCH")
    if engine._git("show", commit[0] + ":docs/J3_BENCHMARK_FREEZE.json") != MANIFEST.read_bytes():
        raise engine.BenchmarkAbort("VERSIONED_FREEZE_CHANGED")
    return commit[0]


def freeze(name: str, output: Path) -> dict[str, Any]:
    profile = select_profile(name)
    # The published J3 freeze is sealed only after commit B exists. J2 uses its own
    # explicit per-run plan, preserving the legacy engine's experimental rules.
    commit = (
        verify_versioned_manifest()
        if name == "j3-sonnet"
        else engine._git("rev-parse", "HEAD").decode().strip()
    )
    return {
        "schema_version": "civicgate.profiled-run-freeze.v1",
        "instrument_commit": commit,
        "run_id": utcnow().strftime(profile.name + "-%Y%m%dT%H%M%S%fZ"),
        "created_at": utcnow().isoformat(),
        "output": str(engine._private(output)),
        "plan": plan(name),
        "raw_source_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in source_hashes()
        },
    }


def verify_run(frozen: dict[str, Any], name: str) -> Profile:
    profile = select_profile(name)
    if frozen.get("plan") != plan(name):
        raise engine.BenchmarkAbort("RUN_FREEZE_MISMATCH")
    raw_hashes = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in source_hashes()
    }
    if frozen.get("raw_source_sha256") != raw_hashes:
        raise engine.BenchmarkAbort("RAW_SOURCE_FREEZE_MISMATCH")
    if engine._git("rev-parse", "HEAD").decode().strip() != frozen.get("instrument_commit"):
        raise engine.BenchmarkAbort("INSTRUMENT_COMMIT_MISMATCH")
    if name == "j3-sonnet" and verify_versioned_manifest() != frozen["instrument_commit"]:
        raise engine.BenchmarkAbort("INSTRUMENT_COMMIT_MISMATCH")
    for name, expected in (
        ("PROVIDER", profile.provider),
        ("PROTOCOL", profile.protocol),
        ("BASE_URL", profile.base_url),
        ("MODEL", profile.model),
    ):
        if os.environ.get("CIVICGATE_JUDGE_" + name, expected) != expected:
            raise engine.BenchmarkAbort("LOCAL_PROVIDER_CONFIGURATION_MISMATCH")
    if os.environ.get("CIVICGATE_PROVIDER") == "openai_compatible" and profile.name == "j3-sonnet":
        raise engine.BenchmarkAbort("LOCAL_PROVIDER_CONFIGURATION_MISMATCH")
    return profile


class ProfileTransport(engine.ObservedTransport):
    def __init__(self, profile: Profile, payloads, secret, verify, inner_factory=None):
        if profile != select_profile(profile.name):
            raise engine.BenchmarkAbort("PROFILE_MISMATCH")
        super().__init__(payloads, secret, verify, inner_factory)
        self.profile = profile

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.verify()
        if self.calls >= len(self.payloads) or self.calls >= 44:
            raise engine.BenchmarkAbort("CALL_BUDGET_EXHAUSTED")
        if str(request.url) != self.profile.endpoint or request.method != "POST":
            raise engine.BenchmarkAbort("ENDPOINT_MISMATCH")
        if json.loads(request.content) != self.payloads[self.calls]:
            raise engine.BenchmarkAbort("PAYLOAD_PROFILE_MISMATCH")
        anthropic = self.profile.protocol == "anthropic_messages"
        if (
            (request.headers.get("x-api-key") != self.secret or "authorization" in request.headers)
            if anthropic
            else (request.headers.get("authorization") != "Bearer " + self.secret)
        ):
            raise engine.BenchmarkAbort("CREDENTIAL_MISMATCH")
        self.calls += 1
        self.metadata = {}
        try:
            async with self.inner_factory() as inner:
                response = await inner.handle_async_request(request)
                self.metadata = {
                    "http_status": response.status_code,
                    "request_id": engine._safe_text(
                        response.headers.get("request-id" if anthropic else "x-request-id"),
                        self.secret,
                    ),
                }
                data = bytearray()
                try:
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 200_000:
                            raise ProviderError(
                                "PROVIDER_RESPONSE_TOO_LARGE", "Response exceeds bound"
                            )
                        data.extend(chunk)
                finally:
                    await response.aclose()
                buffered = httpx.Response(
                    response.status_code,
                    request=request,
                    content=bytes(data),
                    headers={
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() not in {"content-encoding", "content-length"}
                    },
                )
                self.metadata = (
                    engine.observe_judge_response(
                        buffered,
                        self.secret,
                        protocol=self.profile.protocol,
                        requested_model=self.profile.model,
                    )
                    if anthropic
                    else engine._response_metadata(buffered, self.secret)
                )
                return buffered
        except httpx.TransportError as exc:
            self.metadata["transport_error_class"] = type(exc).__name__
            raise


def public_report(report: dict[str, Any], profile: Profile) -> dict[str, Any]:
    # The shared comparator retains its legacy j2 slot internally. Only the output
    # field name changes; no semantic field or metric is transformed for J3.
    report = json.loads(json.dumps(report))
    if profile.name == "j3-sonnet":
        for row in report.get("assessments", []):
            if "j2" in row:
                row["j3"] = row.pop("j2")
    return report


async def execute(frozen: dict[str, Any], name: str, secrets: SecretProvider, inner_factory=None):
    profile = verify_run(frozen, name)
    configured = settings(profile, secrets)  # must fail before transport construction
    key = configured.judge_api_key
    if not key or key != key.strip() or "\n" in key or "\r" in key:
        raise engine.BenchmarkAbort("CREDENTIAL_UNSAFE_OR_MISSING")
    output = engine._private(Path(frozen["output"]))
    if output.exists():
        raise engine.BenchmarkAbort("EXISTING_RUN_OUTPUT")
    engine._write(output.with_name("started.json"), {"run_id": frozen["run_id"]}, exclusive=True)
    fixtures = engine._load_fixtures()
    by_id = {case["id"]: case for case in fixtures}
    transport = ProfileTransport(
        profile,
        [payload(profile, by_id[e["id"]]) for e in frozen["plan"]["schedule"]],
        key,
        lambda: verify_run(frozen, name),
        inner_factory,
    )
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        key,
        protocol=profile.protocol,
        provider_name=profile.provider,
        timeout=profile.timeout_seconds,
        transport=transport,
    )
    judge.client.max_attempts = 1

    def checkpoint(rows):
        engine._write(
            output.with_name("progress.json"),
            public_report(
                {
                    "status": "IN_PROGRESS",
                    "run_id": frozen["run_id"],
                    "assessments": rows,
                    "http_call_count": transport.calls,
                },
                profile,
            ),
            key,
        )

    report = public_report(await engine._run(fixtures, judge, transport, checkpoint), profile)
    report.update(
        {
            "profile": profile.name,
            "freeze": frozen,
            "generated_at": utcnow().isoformat(),
            "reference_status": "DETERMINISTIC_ENGINEERING_REFERENCE",
            "independent_human_accuracy": "NOT_MEASURED",
            "post_run_freeze_valid": True,
        }
    )
    try:
        verify_run(frozen, name)
    except engine.BenchmarkAbort:
        report.update(
            status="BENCHMARK_ABORTED",
            abort_reason="POST_RUN_FREEZE_MISMATCH",
            post_run_freeze_valid=False,
        )
    engine._write(output, report, key, exclusive=True)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=tuple(PROFILES))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--freeze-only", action="store_true")
    mode.add_argument("--run-frozen", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--yes", action="store_true", help="explicit human authorization for one frozen paid run"
    )
    args = parser.parse_args(argv)
    if args.plan:
        if args.output or args.yes:
            parser.error("--plan accepts no output path or execution authorization")
        print(json.dumps(plan(args.profile), indent=2))
        return 0
    if args.freeze_only:
        if not args.output or args.yes:
            parser.error("--freeze-only requires private --output and does not accept --yes")
        frozen = freeze(args.profile, args.output)
        engine._private(args.output).parent.mkdir(parents=True, exist_ok=True)
        engine._write(args.output.with_name("freeze.json"), frozen, exclusive=True)
        return 0
    if not args.yes or args.output:
        parser.error("--run-frozen requires --yes and the frozen output path only")
    frozen = json.loads(engine._private(args.run_frozen).read_text(encoding="utf-8"))
    report = asyncio.run(
        execute(frozen, args.profile, WindowsDPAPIStore(engine.default_store_path()))
    )
    print(report["status"])
    return int(report["status"] == "BENCHMARK_ABORTED")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Never print arbitrary exception values containing provider material.
        print("Benchmark stopped:", type(error).__name__)
        raise SystemExit(1) from None
