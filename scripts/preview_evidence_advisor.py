"""Prepare three sanitized mock Advisor previews without provider activation.

The trusted catalog and fresh output root are local operator configuration.
No model identifier, credential, URL, prompt or transport override is accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from civicgate.evidence_console.anthropic_advisor_v1 import (  # noqa: E402
    API_VERSION,
    ENDPOINT,
    SYSTEM,
    MockAdvisor,
    ProviderConfig,
)
from civicgate.evidence_console.evidence_advisor_v1 import (  # noqa: E402
    AdvisorError,
    _safe_root,
    _write_new,
    build_payload,
    canonical,
    digest,
    validate_report,
)
from civicgate.evidence_console.reader import (  # noqa: E402
    MAX_RUNS,
    EvidenceStore,
    SafeEvidenceError,
    _no_links,
)

SCENARIOS = {"PERMIT": "permit", "DENY": "deny", "REVIEW_REQUIRED": "review"}


class PreviewError(ValueError):
    """A stable preparation error without a path or evidence excerpt."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def mock_messages_wire(payload: dict, config: ProviderConfig) -> bytes:
    """Mirror the pinned adapter serializer; a parity test captures its real wire.

    This is a MOCK body with a synthetic model, not an approved live request.
    Authentication material is never part of this representation.
    """
    content = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return json.dumps(
        {
            "model": config.model,
            "max_tokens": config.max_output_tokens,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": content}],
        },
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _catalog(path: Path) -> list[dict]:
    if not path.is_absolute() or str(path).startswith(("//", "\\\\")):
        raise PreviewError("PREVIEW_CATALOG_INVALID")
    _no_links(path)
    # Reuse the console's exact bounded/duplicate-key catalog loader. Its current
    # eight-entry limit is stricter than the shared reader's twelve-run ceiling.
    spec = importlib.util.spec_from_file_location(
        "_civicgate_preview_catalog", ROOT / "scripts/serve_evidence_console.py"
    )
    if spec is None or spec.loader is None:
        raise PreviewError("PREVIEW_CATALOG_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entries = module.load_catalog(path)
    if not 1 <= len(entries) <= MAX_RUNS:
        raise PreviewError("PREVIEW_CATALOG_INVALID")
    return entries


def _select(entries: list[dict]) -> dict[str, tuple[dict, list[dict], str, str]]:
    store = EvidenceStore(entries)
    selected = {}
    for run in store.list_runs():
        if run["integrity"] != "VERIFIED":
            raise PreviewError("PREVIEW_EVIDENCE_NOT_VERIFIED")
        for row in run["observations"]:
            observation = store.get_observation(run["id"], row["id"])
            decision = observation["policy"]["final_disposition"]
            if observation["integrity"] != "VERIFIED" or decision not in SCENARIOS:
                raise PreviewError("PREVIEW_EVIDENCE_NOT_VERIFIED")
            if decision in selected:
                raise PreviewError("PREVIEW_DUPLICATE_DECISION")
            payload, sources = build_payload(run, observation)
            binding = digest({"manifest": run["manifest_sha256"], "observation": observation})
            selected[decision] = payload, sources, binding, run["manifest_sha256"]
    if set(selected) != set(SCENARIOS):
        raise PreviewError("PREVIEW_THREE_SCENARIOS_REQUIRED")
    return selected


def prepare_preview(catalog_path: Path, output_root: Path) -> dict:
    """Create one new review package, leaving inputs and existing paths intact."""
    try:
        entries = _catalog(Path(catalog_path))
        output = Path(output_root)
        if (
            not output.is_absolute()
            or str(output).startswith(("//", "\\\\"))
            or output.exists()
            or output.is_symlink()
        ):
            raise PreviewError("PREVIEW_FRESH_OUTPUT_REQUIRED")
        parent = _safe_root(output.parent)
        output = parent / output.name
        for protected in [ROOT, *(Path(entry["root"]) for entry in entries)]:
            protected = _safe_root(protected)
            if output.is_relative_to(protected) or protected.is_relative_to(output):
                raise PreviewError("PREVIEW_OUTPUT_OVERLAP")
        selected = _select(entries)
        provider = MockAdvisor()
        pending: dict[str, bytes] = {}
        records = []
        for decision, name in SCENARIOS.items():
            payload, sources, binding, source_manifest = selected[decision]
            wire = mock_messages_wire(payload, provider.config)
            if len(wire) > provider.config.max_input_bytes:
                raise PreviewError("PREVIEW_INPUT_LIMIT")
            reply = provider.analyze(payload)
            report = validate_report(reply.report, payload)
            pending[name + ".projection.json"] = canonical(payload)
            pending[name + ".mock-messages-request.json"] = wire
            pending[name + ".mock-report.json"] = canonical(report)
            records.append(
                {
                    "scenario": name,
                    "recorded_final_disposition": decision,
                    "projection_sha256": hashlib.sha256(canonical(payload)).hexdigest(),
                    "mock_wire_sha256": hashlib.sha256(wire).hexdigest(),
                    "evidence_binding_sha256": binding,
                    "source_manifest_sha256": source_manifest,
                    "sources": sources,
                    "reference_validation": "RESOLVED_NOT_SEMANTIC_VERIFICATION",
                    "semantic_verification": "NOT_ESTABLISHED",
                }
            )
        if selected != _select(entries):
            raise PreviewError("PREVIEW_EVIDENCE_CHANGED")
        files = [
            {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(pending.items())
        ]
        manifest = {
            "version": 1,
            "status": "DRAFT_NOT_AUTHORIZATION",
            "provider_mode": "MOCK_ONLY",
            "evidence_origin": "OPERATOR_CATALOG_PRESERVED_OBSERVATIONS_NOT_NEW_EXECUTION",
            "runtime_execution_compatibility": "NOT_ASSESSED_BY_PREVIEW",
            "mock_model": provider.model,
            "real_model_id": None,
            "authenticated_models_query": "NOT_PERFORMED",
            "remaining_credits": "UNKNOWN",
            "verified_pricing": "UNKNOWN",
            "maximum_authorized_cost_usd": None,
            "paid_execution": "NOT_AUTHORIZED",
            "payload_human_approval": "PENDING",
            "endpoint_contract": ENDPOINT,
            "api_version": API_VERSION,
            "max_output_tokens": provider.config.max_output_tokens,
            "headers_included": False,
            "mock_requests": provider.budget_status()["reserved_requests"],
            "new_mcp_calls": 0,
            "observations": records,
            "files": files,
            "self_excluded": True,
        }
        # Atomic directory reservation; a failed write leaves a partial package
        # for investigation and never overwrites, cleans or retries the path.
        _safe_root(output.parent)
        output.mkdir(exist_ok=False)
        for name, raw in pending.items():
            # Preserve exact raw body ordering; _write_new canonicalizes objects.
            with (output / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        _write_new(output / "PREVIEW_MANIFEST.json", manifest)
        for row in files:
            measured = (output / row["path"]).read_bytes()
            if (
                len(measured) != row["bytes"]
                or hashlib.sha256(measured).hexdigest() != row["sha256"]
            ):
                raise PreviewError("PREVIEW_OUTPUT_IDENTITY_MISMATCH")
        return manifest
    except PreviewError:
        raise
    except (AdvisorError, SafeEvidenceError, OSError, ValueError, KeyError, TypeError):
        raise PreviewError("PREVIEW_PREPARATION_FAILED") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        prepare_preview(args.catalog, args.output_root)
    except PreviewError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    print("Prepared three sanitized mock previews. Paid execution NOT_AUTHORIZED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
