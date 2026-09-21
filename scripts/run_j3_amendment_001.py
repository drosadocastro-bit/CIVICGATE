"""J3-AMEND-001: separate failure-tolerant observation, unchanged semantic contract."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from pydantic import TypeAdapter, ValidationError  # noqa: E402

from civicgate.llm.live import (  # noqa: E402
    LiveJudgeProvider,
    _anthropic_text,
    _JudgeSignalWire,
    _validate_sonnet_stop,
)
from scripts import diagnose_j3_run001_failures as diagnostic  # noqa: E402
from scripts import run_profiled_judge_benchmark as parent  # noqa: E402

AMENDMENT = "J3-AMEND-001"
PARENT_COMMIT = "40efd42cbf0d7c2006e6b9312fb3490657e72268"
MANIFEST = ROOT / "docs/J3_AMENDMENT_001.json"
NEW_SOURCES = (
    "scripts/run_j3_amendment_001.py",
    "tests/unit/test_j3_amendment_001.py",
    "scripts/diagnose_j3_run001_failures.py",
    "tests/unit/test_j3_failure_characterization.py",
)
NONFATAL = {
    "PARSEABLE_BUT_WIRE_INVALID": "Record failure and advance once; never accept partial fields.",
    "MALFORMED_SEMANTIC_JSON": "Record failure and advance once; no JSON repair.",
    "INCOMPLETE_MAX_TOKENS": "Record incomplete and advance once; do not parse partial text.",
    "PROVIDER_REFUSAL": "Record refusal and advance once.",
    "RESPONSE_NOT_VALIDATED": "Missing/invalid structure or stop reason; record and advance.",
}
FATAL = {
    "FREEZE_OR_INSTRUMENT_MISMATCH": "Abort before the next request on any verified input drift.",
    "REQUEST_BOUNDARY_VIOLATION": "Wrong endpoint, model, payload or credential binding; no dispatch.",
    "RETURNED_MODEL_MISMATCH": "Exposed returned model differs; record response and abort.",
    "CALL_ACCOUNTING_VIOLATION": "Not exactly one request per attempted observation or over 44.",
    "EVIDENCE_WRITE_FAILURE": "Do not dispatch another request after failed evidence persistence.",
    "OBSERVER_EVIDENCE_FAILURE": "Diagnostic metadata cannot be reconstructed; record and abort.",
    "PROVIDER_HTTP_FAILURE": "Any HTTP rejection, including auth, 429 and 5xx; record and abort.",
    "TRANSPORT_FAILURE": "Network/timeout failure; record and abort without retry.",
    "RESPONSE_SIZE_BOUND": "Response exceeds the existing 200000-byte bound; abort.",
    "UNEXPECTED_INSTRUMENT_FAILURE": "Unknown error, inconsistent observer/typed state or guard failure.",
}


def structural_evidence(response, secret):
    """No invalid values or rationale text; candidates never become a JudgeSignal."""
    meta = diagnostic.diagnose(response, secret)
    meta.update(rationale_length=None, unvalidated_wire_semantic_fields=None)
    if not meta["json_parseable"]:
        return meta
    body = response.json()
    _validate_sonnet_stop(body)
    parsed = json.loads(_anthropic_text(body))
    if not isinstance(parsed, dict):
        return meta
    if isinstance(parsed.get("rationale"), str):
        meta["rationale_length"] = len(parsed["rationale"])
    if meta["wire_validation"] != "FAIL":
        return meta
    fields = {}
    invalid = []
    for name in ("classification", "confidence", "flags"):
        if name not in parsed:
            continue
        # Reuse each exact field annotation AND its Field metadata, including
        # bounds/list length. Confidence additionally inherits allow_inf_nan=False.
        field = _JudgeSignalWire.model_fields[name]
        adapter = TypeAdapter(field.rebuild_annotation(), config=_JudgeSignalWire.model_config)
        try:
            fields[name] = adapter.validate_python(parsed[name])
        except ValidationError:
            invalid.append(name)
    meta["unvalidated_wire_semantic_fields"] = {
        "label": "UNVALIDATED_WIRE_SEMANTIC_FIELDS",
        "limitations": ["EXPLORATORY", "NON-AUTHORITATIVE", "NOT A JUDGESIGNAL"],
        "fields": fields,
        "invalid_individual_fields": invalid,
    }
    return meta


class AmendedTransport(parent.ProfileTransport):
    """Same guarded request path, separate future-only diagnostic observer."""

    def __init__(self, payloads, secret, verify, inner_factory=None):
        super().__init__(parent.PROFILES["j3-sonnet"], payloads, secret, verify, inner_factory)
        self.structural = {}

    async def handle_async_request(self, request):
        self.structural = {}
        response = await super().handle_async_request(request)
        try:
            self.structural = structural_evidence(response, self.secret)
        except Exception:
            self.structural = {"observer_error": "OBSERVER_EVIDENCE_FAILURE"}
        return response


def axes(row):
    meta = row.get("telemetry", {})
    status = meta.get("http_status")
    wire = meta.get("wire_validation", "NOT_EVALUABLE")
    return {
        "HTTP_SUCCESS": 200 <= status < 300 if isinstance(status, int) else None,
        "JSON_PARSEABLE": meta.get("json_parseable"),
        "WIRE_VALID": {"PASS": True, "FAIL": False}.get(wire),
        "TYPED_ASSESSMENT_VALID": row["outcome"] == "VALID",
        "PARSEABLE_BUT_WIRE_INVALID": meta.get("json_parseable") is True and wire == "FAIL",
        "INCOMPLETE_MAX_TOKENS": meta.get("stop_reason") == "max_tokens",
        "PROVIDER_REFUSAL": meta.get("stop_reason") == "refusal",
        "PROVIDER_FAILURE": row["outcome"] == "PROVIDER_FAILURE",
        "TRANSPORT_FAILURE": row["outcome"] == "TRANSPORT_FAILURE",
    }


def fatal_reason(row, transport, call_before):
    guard = row.get("abort_reason")
    if guard in {"ENDPOINT_MISMATCH", "PAYLOAD_PROFILE_MISMATCH", "CREDENTIAL_MISMATCH"}:
        return "REQUEST_BOUNDARY_VIOLATION"
    if guard == "AUTHENTICATION_REJECTED":
        return "PROVIDER_HTTP_FAILURE"
    if guard and "FREEZE" in guard:
        return "FREEZE_OR_INSTRUMENT_MISMATCH"
    if transport.calls > 44 or transport.calls - call_before != 1:
        return "CALL_ACCOUNTING_VIOLATION"
    if row.get("abort_reason"):
        return "UNEXPECTED_INSTRUMENT_FAILURE"
    meta = row["telemetry"]
    if meta.get("returned_model") not in (None, parent.PROFILES["j3-sonnet"].model):
        return "RETURNED_MODEL_MISMATCH"
    if transport.structural.get("observer_error") or transport.structural.get("metadata_truncated"):
        return "OBSERVER_EVIDENCE_FAILURE"
    if row["outcome"] == "PROVIDER_FAILURE":
        return "PROVIDER_HTTP_FAILURE"
    if row["outcome"] == "TRANSPORT_FAILURE":
        return "TRANSPORT_FAILURE"
    if row["error"]["code"] == "PROVIDER_RESPONSE_TOO_LARGE":
        return "RESPONSE_SIZE_BOUND"
    if row["outcome"] not in {"VALID", "SCHEMA_FAILURE"}:
        return "UNEXPECTED_INSTRUMENT_FAILURE"
    if row["outcome"] == "VALID" and transport.structural.get("wire_validation") != "PASS":
        return "OBSERVER_EVIDENCE_FAILURE"
    if row["outcome"] == "SCHEMA_FAILURE" and transport.structural.get("wire_validation") == "PASS":
        return "OBSERVER_EVIDENCE_FAILURE"
    return None


async def run_amended(fixtures, judge, transport, persist):
    """Completion changes only; shared canonical scoring receives only typed validity."""
    schedule = parent.engine._schedule(fixtures)
    if len(fixtures) != 35 or len(schedule) != 44 or judge.client.max_attempts != 1:
        raise parent.engine.BenchmarkAbort("AMENDED_PLAN_MISMATCH")
    by_id = {case["id"]: case for case in fixtures}
    rows = []
    aborted = None
    for sequence, entry in enumerate(schedule, 1):
        before = transport.calls
        try:
            transport.verify()
        except Exception:
            aborted = "FREEZE_OR_INSTRUMENT_MISMATCH"
            break
        if before >= 44 or before != len(rows):
            aborted = "CALL_ACCOUNTING_VIOLATION"
            break
        try:
            persist("start", {"sequence": sequence, **entry, "prior_http_count": before})
        except Exception:
            aborted = "EVIDENCE_WRITE_FAILURE"
            break
        row = await parent.engine._assess_case(judge, transport, by_id[entry["id"]], entry)
        row.update(
            sequence=sequence,
            structural_evidence=transport.structural,
            observation_axes=axes(row),
            http_request_count=transport.calls - before,
            retry_count=0,
        )
        aborted = fatal_reason(row, transport, before)
        if aborted:
            row["amendment_fatal_reason"] = aborted
            if row["outcome"] == "VALID":
                # A valid wire from the wrong model (or an inconsistent observer)
                # cannot count as an accepted assessment of the frozen instrument.
                row.update(outcome="OTHER_FAILURE", j2=None)
                row["observation_axes"] = axes(row)
        rows.append(row)
        try:
            persist(
                "result",
                parent.public_report({"assessments": [row]}, parent.PROFILES["j3-sonnet"])[
                    "assessments"
                ][0],
            )
        except Exception:
            aborted = "EVIDENCE_WRITE_FAILURE"
        if aborted:
            break
        # No consecutive-failure stop. Advance exactly once, never retry this row.
    rows.extend({**entry, "outcome": "NOT_ATTEMPTED"} for entry in schedule[len(rows) :])
    report = parent.engine._summarize(rows, aborted)
    attempted = [r for r in rows if r["outcome"] != "NOT_ATTEMPTED"]
    if aborted or len(attempted) < 44:
        completion = "J3_AMEND_001_RUN_INCOMPLETE"
    elif all(r["outcome"] == "VALID" for r in attempted):
        completion = "J3_AMEND_001_RUN_COMPLETE_ALL_ASSESSMENTS_VALID"
    else:
        completion = "J3_AMEND_001_RUN_COMPLETE_WITH_NONVALIDATED_ASSESSMENTS"
    report.update(
        amendment=AMENDMENT,
        status=completion,
        completion_classification=completion,
        attempted_observations=len(attempted),
        http_call_count=transport.calls,
        retry_count=0,
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
    return parent.public_report(report, parent.PROFILES["j3-sonnet"])


def plan():
    baseline = parent.plan("j3-sonnet")
    return {
        "amendment": AMENDMENT,
        "parent_freeze_commit": PARENT_COMMIT,
        "profile": baseline["profile"],
        "schedule": baseline["schedule"],
        "primary_count": 35,
        "repeat_count": 9,
        "scheduled_observations": 44,
        "max_http_calls": 44,
        "retries": 0,
        "token_limit": 512,
        "semantic_contract_sha256": baseline["contract_sha256"],
        "fixture_sha256": baseline["fixture_sha256"],
        "parent_source_sha256": baseline["source_sha256"],
        "amendment_source_sha256": {name: parent.file_hash(ROOT / name) for name in NEW_SOURCES},
        "canonical_scoring": "Unchanged shared J1/injection/repeat scoring over VALID typed assessments only",
        "continue_after": NONFATAL,
        "abort_after": FATAL,
        "missing_returned_model": "Unknown, not inferred to match; a differing exposed model ID is fatal",
        "metadata_truncation": "Fatal evidence limitation; do not continue if bounded structural metadata truncates",
        "external_calls": 0,
        "credential_reads": 0,
    }


def amendment_manifest():
    return {
        "schema_version": "civicgate.j3-amendment-001.v1",
        "status": "APPROVED_FOR_FUTURE_SEPARATELY_AUTHORIZED_EXECUTION",
        "run002_authorization": "NOT_YET_AUTHORIZED",
        "version_identity": "Git commit containing this manifest; no self-embedded commit SHA",
        "principle": "J3-AMEND-001 changes observation/completion behavior, not the judge semantic contract.",
        "historical_run": {
            "id": "j3-sonnet-20260921T115723065245Z",
            "classification": "J3_BENCHMARK_RUN_INCOMPLETE",
            "attempted": 22,
            "wire_valid": 12,
            "wire_invalid": 9,
            "incomplete": 1,
            "exact_wire_failure_mechanisms": "UNKNOWN_NOT_RETAINED",
        },
        "characterization": {
            "id": "j3-run001-failure-characterization-20260921T122041026687Z",
            "classification": "MULTIPLE_FAILURE_MECHANISMS",
            "independent_observations": 10,
            "valid": 3,
            "wire_invalid": 5,
            "incomplete": 2,
            "new_wire_mechanism": "rationale/string_too_long; not attributed retroactively to Run 001",
        },
        "plan": plan(),
        "limitations": [
            "No live execution or outcome is established by this amendment.",
            "Historical failures and diagnostic observations remain separate and immutable.",
            "Candidate fields are EXPLORATORY, NON-AUTHORITATIVE, NOT A JUDGESIGNAL.",
            "No exploratory aggregate metric is declared or calculated.",
            "flags=[NONE] remains OPEN_DESIGN_FINDING; no normalization.",
            "Future prompt/schema/token/parser/stop/scoring changes require another amendment.",
        ],
    }


def verify_manifest():
    if parent.verify_versioned_manifest() != PARENT_COMMIT:
        raise parent.engine.BenchmarkAbort("PARENT_FREEZE_MISMATCH")
    if json.loads(MANIFEST.read_text(encoding="utf-8")) != amendment_manifest():
        raise parent.engine.BenchmarkAbort("AMENDMENT_FREEZE_MISMATCH")


def raw_hashes():
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in (*parent.source_hashes(), *NEW_SOURCES, "docs/J3_AMENDMENT_001.json")
    }


def seal(output):
    """Offline future execution seal; uncommitted dependencies cannot be executed."""
    verify_manifest()
    for name in (*NEW_SOURCES, "docs/J3_AMENDMENT_001.json"):
        committed = parent.engine._git("show", "HEAD:" + name)
        if committed.replace(b"\r\n", b"\n") != (ROOT / name).read_bytes().replace(b"\r\n", b"\n"):
            raise parent.engine.BenchmarkAbort("UNCOMMITTED_AMENDMENT_DEPENDENCY")
    return {
        "run_id": parent.utcnow().strftime("j3-amend001-sonnet-%Y%m%dT%H%M%S%fZ"),
        "head": parent.engine._git("rev-parse", "HEAD").decode().strip(),
        "plan": plan(),
        "raw_source_sha256": raw_hashes(),
        "output": str(parent.engine._private(output)),
    }


def verify_execution(freeze):
    verify_manifest()
    if (
        freeze["plan"] != plan()
        or freeze["raw_source_sha256"] != raw_hashes()
        or freeze["head"] != parent.engine._git("rev-parse", "HEAD").decode().strip()
    ):
        raise parent.engine.BenchmarkAbort("EXECUTION_FREEZE_MISMATCH")
    # Reuse the original profile/environment boundary without changing its seal.
    profile = parent.PROFILES["j3-sonnet"]
    for suffix, expected in (
        ("PROVIDER", profile.provider),
        ("PROTOCOL", profile.protocol),
        ("BASE_URL", profile.base_url),
        ("MODEL", profile.model),
    ):
        if os.environ.get("CIVICGATE_JUDGE_" + suffix, expected) != expected:
            raise parent.engine.BenchmarkAbort("PROFILE_ENVIRONMENT_MISMATCH")
    if os.environ.get("CIVICGATE_PROVIDER") == "openai_compatible":
        raise parent.engine.BenchmarkAbort("PROFILE_ENVIRONMENT_MISMATCH")


async def execute(freeze, secrets, inner_factory=None):
    verify_execution(freeze)
    output = parent.engine._private(Path(freeze["output"]))
    if output.exists():
        raise parent.engine.BenchmarkAbort("EXISTING_RUN_OUTPUT")
    parent.engine._write(
        output.with_name("started.json"),
        {"run_id": freeze["run_id"], "utc_start": parent.utcnow().isoformat()},
        exclusive=True,
    )
    key = secrets.get_secret("CIVICGATE_ANTHROPIC_JUDGE_API_KEY")
    if not key or key != key.strip() or "\n" in key or "\r" in key:
        raise parent.engine.BenchmarkAbort("ANTHROPIC_CREDENTIAL_UNAVAILABLE")
    profile = parent.PROFILES["j3-sonnet"]
    fixtures = parent.engine._load_fixtures()
    by_id = {c["id"]: c for c in fixtures}
    transport = AmendedTransport(
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
        parent.engine._write(
            output.with_name(f"observation-{row['sequence']:02d}-{stage}.json"),
            row,
            key,
            exclusive=True,
        )

    report = await run_amended(fixtures, judge, transport, persist)
    report.update(run_id=freeze["run_id"], freeze=freeze, generated_at=parent.utcnow().isoformat())
    try:
        verify_execution(freeze)
    except Exception:
        report.update(
            status="J3_AMEND_001_RUN_INCOMPLETE",
            completion_classification="J3_AMEND_001_RUN_INCOMPLETE",
            abort_reason="POST_RUN_FREEZE_MISMATCH",
        )
    parent.engine._write(output, report, key, exclusive=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--freeze-only", type=Path, metavar="PRIVATE_OUTPUT")
    mode.add_argument("--run-frozen", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.plan:
        if args.yes:
            parser.error("Plan mode cannot authorize execution")
        print(json.dumps(plan(), indent=2))
    elif args.freeze_only:
        if args.yes:
            parser.error("Freeze-only is offline")
        freeze = seal(args.freeze_only)
        args.freeze_only.parent.mkdir(parents=True, exist_ok=True)
        parent.engine._write(args.freeze_only.with_name("freeze.json"), freeze, exclusive=True)
    else:
        if not args.yes:
            parser.error("A future run requires separate explicit human authorization")
        freeze = json.loads(parent.engine._private(args.run_frozen).read_text())
        verify_execution(freeze)
        report = asyncio.run(
            execute(freeze, parent.WindowsDPAPIStore(parent.engine.default_store_path()))
        )
        print(report["completion_classification"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Amendment stopped:", type(error).__name__)
        raise SystemExit(1) from None
