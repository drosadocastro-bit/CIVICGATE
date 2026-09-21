"""Shared direct-judge experiment. Planning is offline; execution requires a sealed release."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import httpx  # noqa: E402

from civicgate.llm.live import LiveJudgeProvider, ProviderError  # noqa: E402
from scripts import run_j3_amendment_001 as historical  # noqa: E402
from scripts.judge_experiment_observers import observer_for  # noqa: E402

parent = historical.parent
engine = parent.engine
ProviderProfile = parent.Profile
PROFILES = parent.PROFILES
NEW_SOURCES = (
    "scripts/run_j3_experiment.py",
    "scripts/judge_experiment_observers.py",
    "tests/unit/test_j3_experiment.py",
    "docs/PROVIDER_CONFIGURATION_DECISION.md",
)
CONTRACT_SHA256 = "166b69f0682198a8d5f872aef5d8f5367293e209d8c2ee185719175723ac77f3"
FIXTURE_SHA256 = "28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc"


@dataclass(frozen=True)
class SharedExperimentSpec:
    semantic_contract_sha256: str = CONTRACT_SHA256
    fixture_sha256: str = FIXTURE_SHA256
    primary_count: int = 35
    repeat_count: int = 9
    max_http_calls: int = 44
    retries: int = 0
    response_byte_bound: int = 200_000
    gateway_executions: int = 0


SPEC = SharedExperimentSpec()


def plan(profile_name):
    baseline = parent.plan(profile_name)
    if (
        baseline["contract_sha256"] != CONTRACT_SHA256
        or baseline["fixture_sha256"] != FIXTURE_SHA256
    ):
        raise engine.BenchmarkAbort("SHARED_EXPERIMENT_FREEZE_MISMATCH")
    return {
        "schema_version": "civicgate.shared-j3-experiment.v1",
        "shared": asdict(SPEC),
        "profile": baseline["profile"],
        "schedule": baseline["schedule"],
        "parameter_names": baseline["parameter_names"],
        "token_limit": 512,
        "continue_after": historical.NONFATAL,
        "abort_after": historical.FATAL,
        "missing_returned_model": "OBSERVER_EVIDENCE_FAILURE; explicit returned identity required",
        "returned_model_identity": {
            "required": "Safely observable identifier equal to the frozen expected model",
            "missing_null_unavailable_or_unsafe": "OBSERVER_EVIDENCE_FAILURE",
            "conflicting": "RETURNED_MODEL_MISMATCH",
            "scope": "Prospective only; historical J3-AMEND-001 remains unchanged",
        },
        "scoring": "Unchanged J3-AMEND-001: VALID typed assessments only; J1 is not human truth",
        "comparison": "PRACTICAL_PROVIDER_COMPATIBLE_JUDGE_COMPARISON",
        "source_sha256": {
            **parent.source_hashes(),
            **{p: parent.file_hash(ROOT / p) for p in (*historical.NEW_SOURCES, *NEW_SOURCES)},
        },
    }


def public_row(row):
    result = json.loads(json.dumps(row))
    if "j2" in result:
        result["assessment"] = result.pop("j2")
    return result


class ExperimentTransport(httpx.AsyncBaseTransport):
    """One native request per armed journal; bounded response before the real parser."""

    def __init__(self, profile, payloads, secret, verify, inner_factory=None):
        if profile != parent.select_profile(profile.name):
            raise engine.BenchmarkAbort("PROFILE_MISMATCH")
        self.profile, self.payloads, self.secret = profile, payloads, secret
        self.verify = verify
        self.inner_factory = inner_factory or (lambda: httpx.AsyncHTTPTransport(retries=0))
        self.observer = observer_for(profile)
        self.calls = 0
        self.metadata, self.structural = {}, {}
        self.completion_state = "UNKNOWN"
        self.armed_sequence = None

    def arm(self, sequence):
        if self.armed_sequence is not None or sequence != self.calls + 1 or sequence > 44:
            raise engine.BenchmarkAbort("CALL_ACCOUNTING_VIOLATION")
        self.armed_sequence = sequence

    async def handle_async_request(self, request):
        self.metadata, self.structural = {}, {}
        self.completion_state = "UNKNOWN"
        try:
            self.verify()
        except Exception:
            raise engine.BenchmarkAbort("EXECUTION_FREEZE_MISMATCH") from None
        if self.calls >= 44 or self.calls >= len(self.payloads):
            raise engine.BenchmarkAbort("CALL_BUDGET_EXHAUSTED")
        if self.armed_sequence != self.calls + 1:
            raise engine.BenchmarkAbort("CALL_ACCOUNTING_VIOLATION")
        if str(request.url) != self.profile.endpoint or request.method != "POST":
            raise engine.BenchmarkAbort("ENDPOINT_MISMATCH")
        if json.loads(request.content) != self.payloads[self.calls]:
            raise engine.BenchmarkAbort("PAYLOAD_PROFILE_MISMATCH")
        anthropic = self.profile.protocol == "anthropic_messages"
        if (
            (request.headers.get("x-api-key") != self.secret or "authorization" in request.headers)
            if anthropic
            else (
                request.headers.get("authorization") != "Bearer " + self.secret
                or "x-api-key" in request.headers
            )
        ):
            raise engine.BenchmarkAbort("CREDENTIAL_MISMATCH")
        self.armed_sequence = None
        self.calls += 1
        try:
            async with self.inner_factory() as inner:
                response = await inner.handle_async_request(request)
                self.metadata = {"http_status": response.status_code}
                data = bytearray()
                try:
                    self.metadata["request_id"] = engine._safe_text(
                        response.headers.get("request-id" if anthropic else "x-request-id"),
                        self.secret,
                    )
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > SPEC.response_byte_bound:
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
                try:
                    self.metadata, self.structural, self.completion_state = self.observer.observe(
                        buffered, self.secret, self.profile
                    )
                except Exception:
                    self.structural = {"observer_error": "OBSERVER_EVIDENCE_FAILURE"}
                    raise ProviderError("MALFORMED_PROVIDER_RESPONSE", "Observer failed") from None
                # The legacy OpenAI parser ignores finish/refusal. Gate native state
                # before invoking it, without parsing partial text or altering bytes.
                if response.status_code < 400 and self.completion_state != "COMPLETE":
                    code = {
                        "INCOMPLETE": "PROVIDER_RESPONSE_INCOMPLETE",
                        "REFUSED": "PROVIDER_REFUSAL",
                    }.get(self.completion_state, "MALFORMED_PROVIDER_RESPONSE")
                    raise ProviderError(code, "Provider response is not complete")
                return buffered
        except httpx.TransportError as error:
            self.metadata["transport_error_class"] = type(error).__name__
            raise


def axes(row):
    result = historical.axes(row)
    result.update(
        INCOMPLETE_MAX_TOKENS=row.get("completion_state") == "INCOMPLETE",
        PROVIDER_REFUSAL=row.get("completion_state") == "REFUSED",
    )
    return result


def category(row):
    if row["outcome"] == "VALID":
        return "TYPED_VALID"
    state, meta = row.get("completion_state"), row["telemetry"]
    if state == "INCOMPLETE":
        return "INCOMPLETE_MAX_TOKENS"
    if state == "REFUSED":
        return "PROVIDER_REFUSAL"
    if meta.get("json_parseable") is True and meta.get("wire_validation") == "FAIL":
        return "PARSEABLE_BUT_WIRE_INVALID"
    if meta.get("json_parseable") is False:
        return "MALFORMED_SEMANTIC_JSON"
    return "RESPONSE_NOT_VALIDATED"


def fatal_reason(row, transport, before):
    guard = row.get("abort_reason")
    if guard in {"ENDPOINT_MISMATCH", "PAYLOAD_PROFILE_MISMATCH", "CREDENTIAL_MISMATCH"}:
        return "REQUEST_BOUNDARY_VIOLATION"
    if guard == "AUTHENTICATION_REJECTED":
        return "PROVIDER_HTTP_FAILURE"
    if guard and "FREEZE" in guard:
        return "FREEZE_OR_INSTRUMENT_MISMATCH"
    if transport.calls > 44 or transport.calls - before != 1:
        return "CALL_ACCOUNTING_VIOLATION"
    if guard:
        return "UNEXPECTED_INSTRUMENT_FAILURE"
    if row["telemetry"].get("returned_model") not in (None, transport.profile.model):
        return "RETURNED_MODEL_MISMATCH"
    if transport.structural.get("observer_error") or transport.structural.get("metadata_truncated"):
        return "OBSERVER_EVIDENCE_FAILURE"
    if row["outcome"] == "PROVIDER_FAILURE":
        return "PROVIDER_HTTP_FAILURE"
    if row["outcome"] == "TRANSPORT_FAILURE":
        return "TRANSPORT_FAILURE"
    if row["error"]["code"] == "PROVIDER_RESPONSE_TOO_LARGE":
        return "RESPONSE_SIZE_BOUND"
    # Transport/HTTP/size failures retain their established fatal causes. A
    # returned assessment cannot proceed without explicit, safely observed ID.
    if row["telemetry"].get("returned_model") is None:
        return "OBSERVER_EVIDENCE_FAILURE"
    if row["outcome"] not in {"VALID", "SCHEMA_FAILURE"}:
        return "UNEXPECTED_INSTRUMENT_FAILURE"
    if (row["outcome"] == "VALID") != (transport.structural.get("wire_validation") == "PASS"):
        return "OBSERVER_EVIDENCE_FAILURE"
    return None


async def run_experiment(fixtures, judge, transport, persist, *, run_id):
    """Direct judge only. Persistence callbacks must complete exclusive writes synchronously."""
    schedule = engine._schedule(fixtures)
    if fixtures != engine._load_fixtures() or len(schedule) != 44 or judge.client.max_attempts != 1:
        raise engine.BenchmarkAbort("SHARED_EXPERIMENT_FREEZE_MISMATCH")
    by_id, rows, aborted = {c["id"]: c for c in fixtures}, [], None
    for sequence, entry in enumerate(schedule, 1):
        before = transport.calls
        try:
            transport.verify()
        except Exception:
            aborted = "FREEZE_OR_INSTRUMENT_MISMATCH"
            break
        if before >= 44 or before != sequence - 1:
            aborted = "CALL_ACCOUNTING_VIOLATION"
            break
        try:
            persist(
                "start",
                {
                    "run_id": run_id,
                    "sequence": sequence,
                    **entry,
                    "prior_http_count": before,
                    "expected_request_ordinal": before + 1,
                    "utc_start": parent.utcnow().isoformat(),
                },
            )
        except Exception:
            aborted = "EVIDENCE_WRITE_FAILURE"
            break
        transport.arm(sequence)
        row = await engine._assess_case(judge, transport, by_id[entry["id"]], entry)
        row.update(
            run_id=run_id,
            sequence=sequence,
            structural_evidence=transport.structural,
            completion_state=transport.completion_state,
            http_request_count=transport.calls - before,
            retry_count=0,
        )
        aborted = fatal_reason(row, transport, before)
        if aborted:
            row["experiment_fatal_reason"] = aborted
            if row["outcome"] == "VALID":
                row.update(outcome="OTHER_FAILURE", j2=None)
        if row["outcome"] != "VALID":
            row["j2"] = None
        row.update(observation_axes=axes(row), result_category=category(row))
        rows.append(row)
        try:
            persist("result", public_row(row))
        except Exception:
            aborted = "EVIDENCE_WRITE_FAILURE"
        if aborted:
            break
    rows.extend({**entry, "outcome": "NOT_ATTEMPTED"} for entry in schedule[len(rows) :])
    report = engine._summarize(rows, aborted)
    attempted = [r for r in rows if r["outcome"] != "NOT_ATTEMPTED"]
    completion = (
        "J3_EXPERIMENT_INCOMPLETE"
        if aborted or len(attempted) != 44
        else "J3_EXPERIMENT_COMPLETE_ALL_ASSESSMENTS_VALID"
        if all(r["outcome"] == "VALID" for r in attempted)
        else "J3_EXPERIMENT_COMPLETE_WITH_NONVALIDATED_ASSESSMENTS"
    )
    report.update(
        run_id=run_id,
        profile=asdict(transport.profile),
        status=completion,
        completion_classification=completion,
        attempted_observations=len(attempted),
        http_call_count=transport.calls,
        retry_count=0,
        gateway_executions=0,
        observation_axis_counts={
            name: {
                "true": sum(r["observation_axes"][name] is True for r in attempted),
                "false": sum(r["observation_axes"][name] is False for r in attempted),
                "unavailable": sum(r["observation_axes"][name] is None for r in attempted),
            }
            for name in axes({"outcome": "NOT_ATTEMPTED"})
        },
        exploratory_metrics="NOT_CALCULATED; candidates are not canonical assessments or authority evidence",
    )
    report["assessments"] = [public_row(row) for row in rows]
    return report


def raw_hashes():
    return {
        **historical.raw_hashes(),
        **{name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in NEW_SOURCES},
    }


def seal(profile_name, output):
    historical.verify_manifest()
    for name in raw_hashes():
        committed = engine._git("show", "HEAD:" + name)
        if committed.replace(b"\r\n", b"\n") != (ROOT / name).read_bytes().replace(b"\r\n", b"\n"):
            raise engine.BenchmarkAbort("UNCOMMITTED_EXPERIMENT_DEPENDENCY")
    return {
        "run_id": parent.utcnow().strftime("shared-" + profile_name + "-%Y%m%dT%H%M%S%fZ"),
        "head": engine._git("rev-parse", "HEAD").decode().strip(),
        "plan": plan(profile_name),
        "raw_source_sha256": raw_hashes(),
        "output": str(engine._private(output)),
    }


def verify_execution(freeze):
    historical.verify_manifest()
    profile = parent.select_profile(freeze["plan"]["profile"]["name"])
    if (
        freeze["plan"] != plan(profile.name)
        or freeze["raw_source_sha256"] != raw_hashes()
        or freeze["head"] != engine._git("rev-parse", "HEAD").decode().strip()
    ):
        raise engine.BenchmarkAbort("EXECUTION_FREEZE_MISMATCH")
    return profile


async def execute(freeze, secrets, inner_factory=None):
    profile = verify_execution(freeze)
    output = engine._private(Path(freeze["output"]))
    if output.exists():
        raise engine.BenchmarkAbort("EXISTING_RUN_OUTPUT")
    engine._write(
        output.with_name("started.json"),
        {"run_id": freeze["run_id"], "utc_start": parent.utcnow().isoformat()},
        exclusive=True,
    )
    key = secrets.get_secret(profile.secret_name)
    if not key or key != key.strip() or "\n" in key or "\r" in key:
        raise engine.BenchmarkAbort("PROFILE_CREDENTIAL_UNAVAILABLE")
    fixtures = engine._load_fixtures()
    by_id = {c["id"]: c for c in fixtures}
    transport = ExperimentTransport(
        profile,
        [parent.payload(profile, by_id[e["id"]]) for e in freeze["plan"]["schedule"]],
        key,
        lambda: verify_execution(freeze),
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

    def persist(stage, row):
        engine._write(
            output.with_name(f"observation-{row['sequence']:02d}-{stage}.json"),
            row,
            key,
            exclusive=True,
        )

    report = await run_experiment(fixtures, judge, transport, persist, run_id=freeze["run_id"])
    report.update(freeze=freeze, generated_at=parent.utcnow().isoformat())
    try:
        verify_execution(freeze)
    except Exception:
        report.update(
            status="J3_EXPERIMENT_INCOMPLETE",
            completion_classification="J3_EXPERIMENT_INCOMPLETE",
            abort_reason="FREEZE_OR_INSTRUMENT_MISMATCH",
        )
    engine._write(output, report, key, exclusive=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=tuple(PROFILES))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--freeze-only", type=Path)
    mode.add_argument("--run-frozen", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.plan:
        if args.yes:
            parser.error("Plan mode cannot authorize execution")
        print(json.dumps(plan(args.profile), indent=2))
    elif args.freeze_only:
        if args.yes:
            parser.error("Freeze-only is offline")
        freeze = seal(args.profile, args.freeze_only)
        args.freeze_only.parent.mkdir(parents=True, exist_ok=True)
        engine._write(args.freeze_only.with_name("freeze.json"), freeze, exclusive=True)
    else:
        if not args.yes:
            parser.error("Requires separate human authorization for this sealed run")
        freeze = json.loads(engine._private(args.run_frozen).read_text())
        if verify_execution(freeze).name != args.profile:
            raise engine.BenchmarkAbort("PROFILE_MISMATCH")
        report = asyncio.run(execute(freeze, parent.WindowsDPAPIStore(engine.default_store_path())))
        print(report["completion_classification"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Shared experiment stopped:", type(error).__name__)
        raise SystemExit(1) from None
