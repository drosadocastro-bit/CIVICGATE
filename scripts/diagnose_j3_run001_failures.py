"""Separate, opt-in diagnostic observation; never resumes or repairs J3 Run 001."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from pydantic import ValidationError  # noqa: E402

from civicgate.llm.live import (  # noqa: E402
    LiveJudgeProvider,
    ProviderError,
    _anthropic_text,
    _JudgeSignalWire,
    _validate_sonnet_stop,
)
from civicgate.models.requests import Proposal  # noqa: E402
from scripts import run_profiled_judge_benchmark as frozen  # noqa: E402

HISTORICAL_ID = "j3-sonnet-20260921T115723065245Z"
HEAD = "40efd42cbf0d7c2006e6b9312fb3490657e72268"
CASES = (
    (1, "valid-recipient"),
    (5, "ambiguous-recipient"),
    (8, "malformed-source"),
    (9, "private-records"),
    (12, "hidden-tool"),
    (13, "repeated-denial"),
    (17, "paraphrased-exclusion"),
    (20, "retrieved-injection"),
    (21, "smuggled-authority"),
    (22, "lexical-false-positive"),
)
TEST = ROOT / "tests/unit/test_j3_failure_characterization.py"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instrument():
    return {path.relative_to(ROOT).as_posix(): digest(path) for path in (Path(__file__), TEST)}


def fingerprint():
    return hashlib.sha256(json.dumps(instrument(), sort_keys=True).encode()).hexdigest()


def safe_name(value, secret):
    if not isinstance(value, str):
        return "[REDACTED_FIELD]"
    if (secret and secret in value) or re.search(r"sk-[A-Za-z0-9_-]{8,}", value):
        return "[REDACTED_FIELD]"
    return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", value) else "[REDACTED_FIELD]"


def sanitized_signal(signal, secret):
    result = signal.model_dump()
    # Only the bounded, schema-valid semantic rationale is retained. Never blocks,
    # error inputs/contexts, arbitrary provider messages or hidden reasoning.
    rationale = result.get("rationale", "")
    if secret:
        rationale = rationale.replace(secret, "[REDACTED]")
    result["rationale"] = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", rationale)
    return result


def diagnose(response, secret):
    """Observe only; use identical stop, extraction and wire validation semantics."""
    result = {
        "json_parseable": None,
        "parsed_json_type": None,
        "top_level_fields": None,
        "field_types": None,
        "field_count": None,
        "metadata_truncated": False,
        "validation_errors": [],
        "validation_error_count": None,
        "wire_validation": "NOT_EVALUABLE",
        "extraction_error_code": None,
        "schema_valid_semantic_fields": None,
    }
    if response.status_code >= 400:
        return result
    try:
        body = response.json()
    except ValueError:
        result["extraction_error_code"] = "PROVIDER_BODY_NOT_JSON"
        return result
    if not isinstance(body, dict):
        result["extraction_error_code"] = "PROVIDER_BODY_NOT_OBJECT"
        return result
    try:
        # No parsing partial text on max_tokens; same production extraction rule.
        _validate_sonnet_stop(body)
        text = _anthropic_text(body)
    except ProviderError as error:
        result["extraction_error_code"] = error.code
        return result
    try:
        parsed = json.loads(text)
    except ValueError:
        result.update(json_parseable=False, wire_validation="FAIL")
        return result
    result.update(json_parseable=True, parsed_json_type=type(parsed).__name__)
    if isinstance(parsed, dict):
        items = list(parsed.items())[:64]
        result.update(
            top_level_fields=[safe_name(key, secret) for key, _ in items],
            field_types=[
                {"field": safe_name(key, secret), "type": type(value).__name__}
                for key, value in items
            ],
            field_count=len(parsed),
            metadata_truncated=len(parsed) > 64,
        )
    try:
        wire = _JudgeSignalWire.model_validate(parsed)
    except ValidationError as error:
        errors = error.errors(include_input=False, include_context=False, include_url=False)
        result.update(
            wire_validation="FAIL",
            validation_error_count=len(errors),
            metadata_truncated=result["metadata_truncated"] or len(errors) > 64,
            validation_errors=[
                {
                    "loc": [v if type(v) is int else safe_name(v, secret) for v in e["loc"]],
                    "type": safe_name(e["type"], secret),
                    # Do not copy Pydantic msg: custom messages may echo inputs.
                    "message_code": safe_name(e["type"], secret),
                }
                for e in errors[:64]
            ],
        )
    else:
        result.update(
            wire_validation="PASS",
            validation_error_count=0,
            schema_valid_semantic_fields=sanitized_signal(wire, secret),
        )
    return result


class DiagnosticTransport(frozen.ProfileTransport):
    """Frozen request guard plus new metadata; response bytes pass through unchanged."""

    def __init__(self, payloads, secret, verify, inner_factory=None):
        super().__init__(frozen.PROFILES["j3-sonnet"], payloads, secret, verify, inner_factory)
        self.diagnostic = {}

    async def handle_async_request(self, request):
        self.diagnostic = {}
        if self.calls >= 10:
            raise frozen.engine.BenchmarkAbort("DIAGNOSTIC_CALL_BUDGET_EXHAUSTED")
        response = await super().handle_async_request(request)
        try:
            self.diagnostic = diagnose(response, self.secret)
        except Exception:
            # A metadata failure must not change the real provider's result/error.
            self.diagnostic = {"observer_error": "DIAGNOSTIC_METADATA_UNAVAILABLE"}
        return response


def historical_outcome(row):
    return "INCOMPLETE" if row["telemetry"]["stop_reason"] == "max_tokens" else "WIRE_FAILURE"


def reproduction(historical, outcome):
    if outcome in {"PROVIDER_FAILURE", "TRANSPORT_FAILURE"}:
        return outcome
    if historical == "INCOMPLETE":
        return "INCOMPLETE_REPRODUCED" if outcome == "INCOMPLETE" else "INCOMPLETE_NOT_REPRODUCED"
    return "WIRE_FAILURE_REPRODUCED" if outcome == "WIRE_FAILURE" else "WIRE_FAILURE_NOT_REPRODUCED"


async def observe(case, historical, transport):
    profile = frozen.PROFILES["j3-sonnet"]
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        transport.secret,
        protocol=profile.protocol,
        provider_name=profile.provider,
        timeout=profile.timeout_seconds,
        transport=transport,
    )
    judge.client.max_attempts = 1
    before = transport.calls
    transport.metadata = {}
    started = time.perf_counter()
    signal = None
    error_code = None
    try:
        typed = await judge.assess(
            case["request"], Proposal(tool=case["tool"], arguments=case["arguments"])
        )
        signal = sanitized_signal(typed, transport.secret)
        outcome = "VALID_ON_DIAGNOSTIC_OBSERVATION"
    except ProviderError as error:
        error_code = error.code
        if transport.metadata.get("transport_error_class"):
            outcome = "TRANSPORT_FAILURE"
        elif (transport.metadata.get("http_status") or 0) >= 400:
            outcome = "PROVIDER_FAILURE"
        elif error.code == "PROVIDER_RESPONSE_INCOMPLETE":
            outcome = "INCOMPLETE"
        elif transport.diagnostic.get("json_parseable") is False:
            outcome = "JSON_PARSE_FAILURE"
        elif transport.diagnostic.get("wire_validation") == "FAIL":
            outcome = "WIRE_FAILURE"
        else:
            outcome = "RESPONSE_NOT_VALIDATED"
    return {
        "fixture_id": case["id"],
        "historical_outcome": historical,
        "diagnostic_outcome": outcome,
        "reproduction": reproduction(historical, outcome),
        "historical_exact_wire_mechanism": "UNKNOWN_NOT_RETAINED",
        "same_exact_wire_mechanism_established": None,
        "telemetry": transport.metadata,
        "diagnostic": transport.diagnostic,
        "typed_signal": signal,
        "error_code": error_code,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "http_request_count": transport.calls - before,
        "retry_count": 0,
    }


def verify(manifest):
    historical = Path(manifest["historical_directory"])
    frozen.verify_run(json.loads((historical / "freeze.json").read_text()), "j3-sonnet")
    if frozen.engine._git("rev-parse", "HEAD").decode().strip() != HEAD:
        raise frozen.engine.BenchmarkAbort("HEAD_MISMATCH")
    if manifest["instrument"] != instrument() or manifest["fingerprint"] != fingerprint():
        raise frozen.engine.BenchmarkAbort("DIAGNOSTIC_INSTRUMENT_CHANGED")
    actual = {p.name: digest(p) for p in historical.iterdir() if p.is_file()}
    if actual != manifest["historical_files"]:
        raise frozen.engine.BenchmarkAbort("HISTORICAL_EVIDENCE_CHANGED")
    if manifest["cases"] != [list(c) for c in CASES]:
        raise frozen.engine.BenchmarkAbort("DIAGNOSTIC_SET_CHANGED")
    if (
        manifest["semantic_plan"] != frozen.plan("j3-sonnet")
        or manifest["maximum_http_calls"] != 10
        or manifest["retries"] != 0
        or manifest["head"] != HEAD
    ):
        raise frozen.engine.BenchmarkAbort("DIAGNOSTIC_PLAN_CHANGED")
    return historical


def prepare(directory, historical):
    directory = frozen.engine._private(directory)
    historical = frozen.engine._private(historical)
    if directory == historical or directory.is_relative_to(historical):
        raise frozen.engine.BenchmarkAbort("HISTORICAL_OUTPUT_FORBIDDEN")
    before = json.loads((directory / "before.json").read_text())
    source = json.loads((historical / "result.json").read_text())
    assert source["freeze"]["run_id"] == HISTORICAL_ID
    assert source["status"] == "BENCHMARK_ABORTED" and source["http_call_count"] == 22
    for sequence, case_id in CASES:
        row = source["assessments"][sequence - 1]
        assert row["id"] == case_id and row["outcome"] == "SCHEMA_FAILURE"
    manifest = {
        "run_id": directory.name,
        "created_at": frozen.utcnow().isoformat(),
        "historical_directory": str(historical),
        "historical_files": before["historical_files"],
        "historical_run_id": HISTORICAL_ID,
        "head": HEAD,
        "instrument": instrument(),
        "fingerprint": fingerprint(),
        "cases": [list(c) for c in CASES],
        "maximum_http_calls": 10,
        "retries": 0,
        "semantic_plan": frozen.plan("j3-sonnet"),
        "retention": "Field names/types, sanitized loc/type/message_code without input/ctx/msg; schema-valid semantic signal including bounded rationale. No invalid field values, raw bodies or nontext block payloads.",
    }
    verify(manifest)
    frozen.engine._write(directory / "diagnostic-freeze.json", manifest, exclusive=True)
    return manifest


async def execute(directory):
    directory = frozen.engine._private(directory)
    manifest = json.loads((directory / "diagnostic-freeze.json").read_text())
    historical = verify(manifest)
    validation = json.loads((directory / "offline-validation.json").read_text())
    if not validation["all_passed"] or validation["fingerprint"] != fingerprint():
        raise frozen.engine.BenchmarkAbort("OFFLINE_VALIDATION_REQUIRED")
    # Exclusive marker consumes this execution even if interrupted after a call.
    frozen.engine._write(
        directory / "started.json",
        {"run_id": manifest["run_id"], "utc_start": frozen.utcnow().isoformat()},
        exclusive=True,
    )
    key = frozen.WindowsDPAPIStore(frozen.engine.default_store_path()).get_secret(
        "CIVICGATE_ANTHROPIC_JUDGE_API_KEY"
    )
    available = bool(key) and key == key.strip() and "\n" not in key and "\r" not in key
    frozen.engine._write(
        directory / "credential-status.json", {"available": available}, exclusive=True
    )
    if not available:
        raise frozen.engine.BenchmarkAbort("ANTHROPIC_CREDENTIAL_UNAVAILABLE")
    fixtures = {c["id"]: c for c in frozen.engine._load_fixtures()}
    previous = json.loads((historical / "result.json").read_text())["assessments"]
    transport = DiagnosticTransport(
        [frozen.payload(frozen.PROFILES["j3-sonnet"], fixtures[c]) for _, c in CASES],
        key,
        lambda: verify(manifest),
    )
    rows = []
    aborted = None
    try:
        for sequence, case_id in CASES:
            row = await observe(
                fixtures[case_id], historical_outcome(previous[sequence - 1]), transport
            )
            row.update(sequence=len(rows) + 1, historical_sequence=sequence)
            rows.append(row)
            frozen.engine._write(
                directory / "progress.json",
                {"rows": rows, "http_request_count": transport.calls},
                key,
            )
            print(f"Diagnostic {len(rows)}/10: {row['diagnostic_outcome']}", flush=True)
    except Exception as error:
        # Never print arbitrary provider/exception text. Do not resume after abort.
        aborted = type(error).__name__
    integrity = True
    try:
        verify(manifest)
    except Exception:
        integrity = False
    report = {
        "run_id": manifest["run_id"],
        "utc_end": frozen.utcnow().isoformat(),
        "historical_run_id": HISTORICAL_ID,
        "historical_classification": "J3_BENCHMARK_RUN_INCOMPLETE",
        "instrument_fingerprint": manifest["fingerprint"],
        "rows": rows,
        "http_request_count": transport.calls,
        "retry_count": 0,
        "abort_error_class": aborted,
        "post_run_integrity": integrity,
    }
    frozen.engine._write(directory / "diagnostic-result.json", report, key, exclusive=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", type=Path, metavar="HISTORICAL_DIRECTORY")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        if args.yes:
            parser.error("Preparation is offline")
        prepare(args.evidence_dir, args.prepare)
    else:
        if not args.yes:
            parser.error("Execution requires explicit authorization")
        report = asyncio.run(execute(args.evidence_dir))
        print("Diagnostic HTTP requests:", report["http_request_count"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Diagnostic stopped:", type(error).__name__)
        raise SystemExit(1) from None
