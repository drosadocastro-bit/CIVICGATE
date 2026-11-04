"""Direct-Gateway-derived unit captures; NOT primary MCP/SQLite observations."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from civicgate.mcp.tools import Gateway
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import TOOLS, Proposal
from evals.harness.evidence import write_new
from evals.harness.governance_observer_v3 import ReadOnlyGovernanceObserver
from evals.harness.synthetic_server import EvidenceLedger, SyntheticAdapter, SyntheticTrace
from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter, dataset_transport
from evals.proposals.r022.faa_contract_v1 import FAA_FY2026_PR_CONTRACT, example_query
from evals.proposals.r022.profile_capture_v1 import validate_capture


class Judge:
    async def assess(self, request, proposal):
        return JudgeSignal(
            available=True,
            classification="IN_SCOPE",
            confidence=0.99,
            flags=[],
            provider="SYNTHETIC_UNIT_FIXTURE",
        )


def stream(path):
    return [json.loads(raw) for raw in path.read_bytes().splitlines()]


def overwrite(path, rows):
    path.write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))


def capture(tmp_path, *, mode="normal", legacy=False, held=False, ingress=False):
    directory = tmp_path / "capture"
    directory.mkdir()
    ledger = EvidenceLedger(directory)
    observer = ReadOnlyGovernanceObserver(directory, "UNIT_DERIVED_R022_CAPTURE_NOT_MCP")
    request = (
        'Find public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2026.'
        if not held
        else "Find FY2026 FAA awards with a place of performance in Puerto Rico."
    )
    proposal = Proposal(tool="find_federal_awards", arguments=example_query())
    registry = FAA_FY2026_PR_CONTRACT.registry
    if legacy:
        request = "Show public federal awards."
        proposal = Proposal(
            tool="find_federal_awards",
            arguments={"start_date": "2025-01-01", "end_date": "2025-02-01", "state_code": "PR"},
        )
        registry = TOOLS
        gateway = Gateway(SyntheticAdapter(ledger, "normal"), Judge(), SyntheticTrace(ledger))
    else:
        base = dataset_transport(mode)

        async def respond(req):
            ledger.append(
                "http-attempts.jsonl",
                phase="entered",
                method=req.method,
                request_path=req.url.path,
                request_body_sha256=__import__("hashlib").sha256(req.content).hexdigest(),
            )
            write_new(directory / "backend-request.json", json.loads(req.content))
            try:
                result = await base.handle_async_request(req)
            except BaseException as exc:
                ledger.append(
                    "components.jsonl",
                    component="synthetic_http",
                    phase="finish",
                    error_class=type(exc).__name__,
                )
                raise
            with (directory / "backend-response.bin").open("xb") as response_file:
                response_file.write(result.content)
            write_new(
                directory / "backend-response-meta.json",
                {
                    "status_code": result.status_code,
                    "content_type": result.headers.get("content-type", ""),
                },
            )
            ledger.append(
                "components.jsonl",
                component="synthetic_http",
                phase="finish",
                error_class=None,
                status_code=result.status_code,
            )
            return result

        class Adapter(FaaProfileFixtureAdapter):
            async def find_profile(self, query):
                ledger.append(
                    "dispatch.jsonl",
                    phase="entered",
                    method="find_profile",
                    query=query.model_dump(mode="json"),
                )
                error = None
                try:
                    return await super().find_profile(query)
                except BaseException as exc:
                    error = type(exc).__name__
                    raise
                finally:
                    ledger.append(
                        "components.jsonl", component="adapter", phase="finish", error_class=error
                    )

        gateway = Gateway(
            Adapter(httpx.MockTransport(respond)),
            Judge(),
            SyntheticTrace(ledger),
            contract=FAA_FY2026_PR_CONTRACT,
        )
    # Match the actual MCP boundary's typed query serialization. A direct
    # Gateway call may retain omitted defaults in its proposal audit; such a
    # capture is intentionally not equivalent to the SDK path under review.
    proposal = Proposal(
        tool=proposal.tool,
        arguments=registry[proposal.tool]
        .model_validate(proposal.arguments)
        .model_dump(mode="json"),
    )
    with observer:
        envelope = None if ingress else asyncio.run(gateway.call(request, proposal))
    write_new(
        directory / "unit-provenance.json",
        {"classification": "UNIT_DERIVED_DIRECT_GATEWAY_NOT_PRIMARY_MCP_CUSTODY"},
    )
    return [
        directory,
        request,
        proposal,
        registry,
        "legacy-control" if legacy else "strict",
        envelope,
    ]


@pytest.mark.parametrize("mode", ["normal", "wrong_subagency", "forged_empty", "timeout"])
def test_legitimate_profile_success_and_error_channels_reconcile(tmp_path, mode):
    args = capture(tmp_path, mode=mode)
    result = validate_capture(*args)
    assert result["state"] == "BOUND_SINGLE_PROFILE_ATTEMPT"
    assert result["historical_r32_validator_used"] is False


def test_held_profile_and_empty_ingress_do_not_invent_policy_or_binding(tmp_path):
    held = tmp_path / "held"
    held.mkdir()
    result = validate_capture(*capture(held, held=True))
    assert result["state"] == "PRE_DISPATCH_HELD"
    empty = tmp_path / "empty"
    empty.mkdir()
    result = validate_capture(*capture(empty, ingress=True))
    assert result["state"] == "NO_GATEWAY_ACTIVITY" and result["request_id"] is None


@pytest.mark.parametrize(
    "mutation", ["result", "provenance", "status", "verification", "response", "combined"]
)
def test_held_envelope_cannot_fabricate_observed_or_verified_result(tmp_path, mutation):
    from civicgate.models.provenance import Provenance

    args = capture(tmp_path, held=True)
    assert validate_capture(*args)["state"] == "PRE_DISPATCH_HELD"
    envelope = args[-1].model_copy(deep=True)
    if mutation in {"result", "combined"}:
        envelope.result = {"records": []}
    if mutation in {"provenance", "combined"}:
        envelope.provenance = Provenance(
            source_system="CIVICGATE_TEST_FIXTURE",
            source_type="SYNTHETIC_TEST_FIXTURE",
            retrieved_at="2026-11-04T00:00:00Z",
            query_fingerprint="0" * 64,
            response_fingerprint="0" * 64,
            endpoint="synthetic-held-no-response",
            records_returned=0,
            truncated=False,
        )
    if mutation in {"status", "combined"}:
        envelope.status = "OK"
    if mutation in {"verification", "combined"}:
        envelope.verification_state = "RESULT_VERIFIED"
    if mutation in {"response", "combined"}:
        envelope.response_state = "RESPONSE_RECEIVED"
    args[-1] = envelope
    audit = stream(args[0] / "audit.jsonl")
    audit[-1]["response"] = envelope.model_dump(mode="json")
    overwrite(args[0] / "audit.jsonl", audit)
    with pytest.raises(ValueError, match="HELD_RESPONSE_CONTRADICTION"):
        validate_capture(*args)


def test_legacy_control_delegates_unchanged_r32_validator(tmp_path):
    result = validate_capture(*capture(tmp_path, legacy=True))
    assert result["state"] == "BOUND_BACKEND_CAPTURED"


@pytest.mark.parametrize(
    "mutation",
    [
        "adapter_exception",
        "terminal_exception",
        "terminal_retry",
        "dispatch_state",
        "body_scope",
        "body_hash",
        "binding_schema",
        "missing_component",
        "request",
        "facts",
        "unknown_receipt",
        "observer_failure",
    ],
)
def test_cross_channel_contradiction_is_rejected_before_custody_close(tmp_path, mutation):
    args = capture(tmp_path)
    assert validate_capture(*args)["state"] == "BOUND_SINGLE_PROFILE_ATTEMPT"
    directory = args[0]
    if mutation == "adapter_exception":
        value = stream(directory / "components.jsonl")
        value[-1]["error_class"] = "TimeoutError"
        overwrite(directory / "components.jsonl", value)
    elif mutation in {"terminal_exception", "terminal_retry", "dispatch_state", "request", "facts"}:
        value = stream(directory / "audit.jsonl")
        if mutation == "terminal_exception":
            value[-1]["attempts"][0]["exception_type"] = "ReadTimeout"
        if mutation == "terminal_retry":
            value[-1]["attempts"][0]["retry_decision"] = "RETRY_ALLOWED"
        if mutation == "dispatch_state":
            value[-1]["response"]["dispatch_state"] = "NOT_DISPATCHED"
            value[-1]["attempts"][0]["dispatch_state"] = "NOT_DISPATCHED"
        if mutation == "request":
            value[0]["user_request"] = "changed"
        if mutation == "facts":
            value[1]["facts"]["arguments_json"] = "{}"
        overwrite(directory / "audit.jsonl", value)
    elif mutation == "body_scope":
        body = json.loads((directory / "backend-request.json").read_bytes())
        body["filters"]["agencies"][0]["tier"] = "toptier"
        (directory / "backend-request.json").write_text(json.dumps(body))
    elif mutation == "body_hash":
        value = stream(directory / "http-attempts.jsonl")
        value[0]["request_body_sha256"] = "0" * 64
        overwrite(directory / "http-attempts.jsonl", value)
    elif mutation == "binding_schema":
        value = stream(directory / "governance-observations.jsonl")
        for row in value:
            if row.get("binding") is not None:
                row["binding"]["schema_sha256"] = "0" * 64
        overwrite(directory / "governance-observations.jsonl", value)
    elif mutation == "missing_component":
        overwrite(directory / "components.jsonl", stream(directory / "components.jsonl")[:-1])
    elif mutation == "unknown_receipt":
        args[-1] = None
    elif mutation == "observer_failure":
        value = stream(directory / "governance-observations.jsonl")
        value[-1]["profiler_intact"] = False
        overwrite(directory / "governance-observations.jsonl", value)
    with pytest.raises(ValueError):
        validate_capture(*args)


def test_untrusted_registry_copy_is_not_promoted_to_expected_schema(tmp_path):
    args = capture(tmp_path)
    assert validate_capture(*args)["state"] == "BOUND_SINGLE_PROFILE_ATTEMPT"
    args[3] = dict(args[3])
    with pytest.raises(ValueError, match="TRUSTED_PROFILE_REGISTRY_REQUIRED"):
        validate_capture(*args)


def test_profile_error_receipt_cannot_be_represented_as_verified_result(tmp_path):
    args = capture(tmp_path, mode="wrong_subagency")
    assert validate_capture(*args)["state"] == "BOUND_SINGLE_PROFILE_ATTEMPT"
    envelope = args[-1].model_copy(deep=True)
    envelope.verification_state = "RESULT_VERIFIED"
    envelope.result = {"records": []}
    args[-1] = envelope
    value = stream(args[0] / "audit.jsonl")
    value[-1]["response"] = envelope.model_dump(mode="json")
    overwrite(args[0] / "audit.jsonl", value)
    with pytest.raises(ValueError):
        validate_capture(*args)


@pytest.mark.parametrize(
    "mutation",
    [
        "query_fingerprint",
        "response_fingerprint",
        "coherent_wrong_body",
        "missing_bytes",
        "metadata_type",
        "metadata_status",
    ],
)
def test_actual_response_bytes_and_provenance_must_join(tmp_path, mutation):
    from civicgate.channel_b.faa_money_v1 import response_fingerprint
    from civicgate.channel_b.faa_profile_v1 import parse_response_bytes

    args = capture(tmp_path)
    assert validate_capture(*args)["state"] == "BOUND_SINGLE_PROFILE_ATTEMPT"
    directory = args[0]
    envelope = args[-1].model_copy(deep=True)
    if mutation == "query_fingerprint":
        envelope.provenance.query_fingerprint = "0" * 64
    elif mutation == "response_fingerprint":
        envelope.provenance.response_fingerprint = "0" * 64
    elif mutation == "coherent_wrong_body":
        obj = json.loads((directory / "backend-response.bin").read_bytes())
        obj["results"][0]["Award Amount"] = "1.00"
        raw = json.dumps(obj).encode()
        (directory / "backend-response.bin").write_bytes(raw)
        envelope.provenance.response_fingerprint = response_fingerprint(parse_response_bytes(raw))
        envelope.result["records"][0]["award_amount"] = "1"
    elif mutation == "missing_bytes":
        (directory / "backend-response.bin").unlink()
    else:
        metadata = json.loads((directory / "backend-response-meta.json").read_bytes())
        metadata["content_type" if mutation == "metadata_type" else "status_code"] = (
            "text/html" if mutation == "metadata_type" else 201
        )
        (directory / "backend-response-meta.json").write_text(json.dumps(metadata))
    args[-1] = envelope
    audit = stream(directory / "audit.jsonl")
    audit[-1]["response"] = envelope.model_dump(mode="json")
    overwrite(directory / "audit.jsonl", audit)
    with pytest.raises(ValueError):
        validate_capture(*args)
