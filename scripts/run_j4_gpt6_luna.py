"""Execute a separately authorized J4 freeze through the existing J4 instrument."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import httpx  # noqa: E402

from scripts import prepare_j4_gpt6_luna as j4  # noqa: E402

engine = j4.j3.engine
AUTHORIZATION_VERSION = "j4-gpt6-luna-execution-authorization-v1"
DRAFT_SHA256 = "3bd74b755bbef53dde80876c15d8a43c917aa20375adf79a84f74f775dafb7df"
J2_PAYLOAD_SHA256 = "99e262669f7afee75de65b978adb2bc5a21aca984d5014fb6e04c4de365569fa"
FROZEN_HASHES = {
    "semantic_contract_sha256": "166b69f0682198a8d5f872aef5d8f5367293e209d8c2ee185719175723ac77f3",
    "fixture_sha256": "28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc",
    "source_human_adjudication_sha256": "43daa0bbfe50be610155a20e1c67493f4691bd1b6d869cce2573a9e70225fb58",
    "human_reference_sha256": "b0049ccc6ab1fc124586ee4e0b50afc219cfb363f4f93d1d96dd7ddfdb1b4279",
    "profile_sha256": "7b1af2255f399550d37fb735e5aaf2d2e0ca3b669f22f31b41535a34a946fb8e",
    "payload_contract_sha256": "2fbf5cefb4fdac6058355f3cb0b02fe415f216cad305957b7d7e61c33a7992a8",
    "j2_canonical_payload_list_sha256": J2_PAYLOAD_SHA256,
}
AUTHORIZATION_FIELDS = frozenset(
    {
        "version",
        "authorization",
        "experiment_id",
        "run_id",
        "final_freeze_sha256",
        "execution_head",
        "profile_id",
        "model",
        "maximum_requests",
        "retry_budget",
    }
)


def require(condition: bool, code: str = "FREEZE_OR_INSTRUMENT_MISMATCH") -> None:
    if not condition:
        raise engine.BenchmarkAbort(code)


def _git_state() -> tuple[str, str, bytes]:
    return (
        engine._git("rev-parse", "HEAD").decode().strip(),
        engine._git("branch", "--show-current").decode().strip(),
        engine._git("status", "--porcelain=v1"),
    )


def _evidence_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    require(bool(local_app_data), "EVIDENCE_ROOT_UNAVAILABLE")
    return (Path(local_app_data) / "CivicGate" / "evidence").resolve(strict=True)


def _read_object(path: Path) -> tuple[dict[str, Any], str]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for name, item in pairs:
            if name in value:
                raise ValueError("duplicate JSON member")
            value[name] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        raw = path.read_bytes()
        value = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)
    except (OSError, UnicodeError, ValueError):
        raise engine.BenchmarkAbort("FREEZE_OR_INSTRUMENT_MISMATCH") from None
    require(isinstance(value, dict))
    return value, hashlib.sha256(raw).hexdigest()


def required_source_paths() -> set[str]:
    draft_path = ROOT / "docs/J4_GPT6_LUNA_FREEZE_DRAFT.json"
    require(j4.raw_hash(draft_path) == DRAFT_SHA256)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    return set(draft["source_sha256_lf"]) | {
        "scripts/run_j4_gpt6_luna.py",
        "tests/unit/test_run_j4_gpt6_luna.py",
    }


def verify_execution(
    freeze_path: Path,
    expected_freeze_sha256: str,
    authorization_path: Path,
    *,
    evidence_root: Path | None = None,
    git_state: Callable[[], tuple[str, str, bytes]] = _git_state,
) -> tuple[dict[str, Any], str]:
    """Perform every non-secret gate before a credential provider is constructed."""
    try:
        path = freeze_path.resolve(strict=True)
        root = (evidence_root or _evidence_root()).resolve(strict=True)
    except OSError:
        raise engine.BenchmarkAbort("FREEZE_OR_INSTRUMENT_MISMATCH") from None
    require(path.name == "freeze.json" and path.parent.parent == root)
    require(path.parent.name.startswith("gpt6-luna-j4-frozen-"))
    require(authorization_path.resolve() == path.with_name("authorization.json"))
    require(re.fullmatch(r"[0-9a-f]{64}", expected_freeze_sha256) is not None)
    freeze, actual_sha = _read_object(path)
    require(actual_sha == expected_freeze_sha256)
    require(freeze.get("version") == "j4-gpt6-luna-final-freeze-v1")
    require(freeze.get("freeze_id") == path.parent.name)
    require(freeze.get("experiment_id") == j4.EXPERIMENT)
    require(freeze.get("run_id") == path.parent.name.replace("-frozen-", "-", 1))
    require(freeze.get("authorization") == "NOT_AUTHORIZED")
    require(freeze.get("status") == "GPT6_LUNA_FINAL_FREEZE_READY_FOR_HUMAN_AUTHORIZATION")
    require(freeze.get("no_live_entrypoint") is False)
    require(freeze.get("result_status") == "NOT_CREATED")
    require(freeze.get("historical_draft_freeze_raw_sha256") == DRAFT_SHA256)
    require(freeze.get("observability_rule") == "Fixture intent is not model evidence.")
    require(freeze.get("human_reference_role") == "EVALUATION_ONLY")
    require(
        freeze.get("judge_visible_case_information")
        == ["request", "proposal.tool", "proposal.arguments"]
    )
    head, branch, status = git_state()
    require(freeze.get("execution_head") == head and branch == "codex/dpapi-selective-access")
    require(not status, "UNCOMMITTED_EXPERIMENT_DEPENDENCY")
    profile = j4.select_profile(j4.PROFILE_ID)
    require(freeze.get("profile_id") == j4.PROFILE_ID)
    require(freeze.get("model") == profile.model == "gpt-6-luna")
    require(freeze.get("provider") == "openai")
    require(freeze.get("protocol") == profile.protocol == "openai_compatible")
    require(
        freeze.get("endpoint") == profile.endpoint == "https://api.openai.com/v1/chat/completions"
    )
    require(freeze.get("reasoning_effort") == "medium")
    require(freeze.get("max_completion_tokens") == 512)
    require(freeze.get("response_format") == {"type": "json_object"})
    require(freeze.get("primary_count") == 35 and freeze.get("repeat_count") == 9)
    require(freeze.get("scheduled_requests") == freeze.get("maximum_requests") == 44)
    require(freeze.get("retry_budget") == 0 and freeze.get("gateway_execution") is False)
    require(freeze.get("request_45") == "REJECTED_BY_INSTRUMENT")
    require(j4.raw_hash(ROOT / "docs/J4_GPT6_LUNA_FREEZE_DRAFT.json") == DRAFT_SHA256)
    require(all(freeze.get(name) == value for name, value in FROZEN_HASHES.items()))
    require(
        j4.historical_invariants()
        == {
            name: FROZEN_HASHES[name]
            for name in (
                "semantic_contract_sha256",
                "fixture_sha256",
                "source_human_adjudication_sha256",
            )
        }
    )
    for name, source in (
        ("human_reference_sha256", j4.REFERENCE_PATH),
        ("profile_sha256", j4.PROFILE_PATH),
        ("payload_contract_sha256", j4.CONTRACT_PATH),
    ):
        require(j4.raw_hash(ROOT / source) == FROZEN_HASHES[name])
    j4.verify_instrument()
    fixtures = engine._load_fixtures()
    require(len(fixtures) == 35)
    require(
        j4.payload_hash([j4.payload("j2-luna", case) for case in fixtures]) == J2_PAYLOAD_SHA256
    )
    by_id = {case["id"]: case for case in fixtures}
    schedule = engine._schedule(fixtures)
    require(len(schedule) == 44 and len(by_id) == 35)
    expected_schedule = [
        {**entry, "payload_sha256": j4.payload_hash(j4.payload(j4.PROFILE_ID, by_id[entry["id"]]))}
        for entry in schedule
    ]
    require(freeze.get("schedule") == expected_schedule)
    sources = freeze.get("source_sha256_lf")
    require(isinstance(sources, dict) and set(sources) == required_source_paths())
    for name, digest in sources.items():
        require(j4.j3.parent.file_hash(ROOT / name) == digest)
    try:
        authorization, authorization_sha = _read_object(authorization_path)
    except engine.BenchmarkAbort:
        raise engine.BenchmarkAbort("EXECUTION_NOT_AUTHORIZED") from None
    require(set(authorization) == AUTHORIZATION_FIELDS, "EXECUTION_NOT_AUTHORIZED")
    require(
        authorization
        == {
            "version": AUTHORIZATION_VERSION,
            "authorization": "AUTHORIZED_ONCE",
            "experiment_id": j4.EXPERIMENT,
            "run_id": freeze["run_id"],
            "final_freeze_sha256": actual_sha,
            "execution_head": head,
            "profile_id": j4.PROFILE_ID,
            "model": profile.model,
            "maximum_requests": 44,
            "retry_budget": 0,
        },
        "EXECUTION_NOT_AUTHORIZED",
    )
    return freeze, authorization_sha


async def run_frozen(
    freeze_path: Path,
    expected_freeze_sha256: str,
    authorization_path: Path,
    *,
    evidence_root: Path | None = None,
    git_state: Callable[[], tuple[str, str, bytes]] = _git_state,
    secret_provider_factory: Callable[[], Any] | None = None,
    inner_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
) -> dict[str, Any]:
    """Validate, claim once, then delegate all observations to the J4 instrument."""
    pinned_authorization_sha: str | None = None

    def verify() -> tuple[dict[str, Any], str]:
        result = verify_execution(
            freeze_path,
            expected_freeze_sha256,
            authorization_path,
            evidence_root=evidence_root,
            git_state=git_state,
        )
        if pinned_authorization_sha is not None:
            require(result[1] == pinned_authorization_sha, "EXECUTION_NOT_AUTHORIZED")
        return result

    freeze, pinned_authorization_sha = verify()
    directory = freeze_path.resolve(strict=True).parent
    output = directory / "result.json"
    require(
        not output.exists() and not (directory / "result.sha256").exists(), "EXISTING_RUN_OUTPUT"
    )
    require(not any(directory.glob("observation-*.json")), "EXISTING_RUN_OUTPUT")
    engine._write(
        directory / "started.json",
        {
            "run_id": freeze["run_id"],
            "freeze_raw_sha256": expected_freeze_sha256,
            "authorization_sha256": pinned_authorization_sha,
            "utc_start": j4.j3.parent.utcnow().isoformat(),
        },
        exclusive=True,
    )
    verify()
    if secret_provider_factory is None:

        def secret_provider_factory() -> Any:
            return j4.j3.parent.WindowsDPAPIStore(engine.default_store_path())

    key = secret_provider_factory().get_secret("CIVICGATE_OPENAI_JUDGE_API_KEY")
    if not key or key != key.strip() or "\n" in key or "\r" in key:
        raise engine.BenchmarkAbort("PROFILE_CREDENTIAL_UNAVAILABLE")

    def persist(stage: str, row: dict[str, Any]) -> None:
        engine._write(
            directory / f"observation-{row['sequence']:02d}-{stage}.json",
            row,
            key,
            exclusive=True,
        )

    report = await j4.observe_with_transport(
        persist,
        inner_factory or (lambda: httpx.AsyncHTTPTransport(retries=0)),
        secret=key,
        run_id=freeze["run_id"],
        verify=lambda: verify(),
    )
    report.update(
        freeze=freeze,
        freeze_raw_sha256=expected_freeze_sha256,
        authorization_sha256=pinned_authorization_sha,
        execution_head=freeze["execution_head"],
        generated_at=j4.j3.parent.utcnow().isoformat(),
    )
    try:
        verify()
    except Exception:
        report.update(
            status="J4_EXPERIMENT_INCOMPLETE",
            completion_classification="J4_EXPERIMENT_INCOMPLETE",
            abort_reason="FREEZE_OR_INSTRUMENT_MISMATCH",
        )
    engine._write(output, report, key, exclusive=True)
    result_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    require(hashlib.sha256(output.read_bytes()).hexdigest() == result_sha, "EVIDENCE_WRITE_FAILURE")
    with engine._private(directory / "result.sha256").open("x", encoding="ascii") as stream:
        stream.write(result_sha + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-frozen", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    parser.add_argument("--authorization-file", type=Path, required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if not args.yes:
        parser.error("A separate, exact-run human authorization is required")
    report = asyncio.run(run_frozen(args.run_frozen, args.freeze_sha256, args.authorization_file))
    print(report["completion_classification"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("J4 experiment stopped:", type(error).__name__)
        raise SystemExit(1) from None
