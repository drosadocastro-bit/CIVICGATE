"""Offline J4 preparation and injectable observation harness. No live execution CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import httpx  # noqa: E402

from civicgate.llm.judge_profiles import select_openai_profile  # noqa: E402
from civicgate.llm.live import LiveJudgeProvider  # noqa: E402
from civicgate.models.requests import Proposal  # noqa: E402
from scripts import run_j3_experiment as j3  # noqa: E402
from scripts.judge_experiment_observers import OpenAIObserver  # noqa: E402

EXPERIMENT = "CIVICGATE-J4-GPT6-LUNA-001"
PROFILE_ID = "j4-gpt6-luna"
BASELINE = "254c8b95ffb2d6eed4aceddd5b203d5be6f855c8"
SOURCE_REFERENCE_SHA256 = "43daa0bbfe50be610155a20e1c67493f4691bd1b6d869cce2573a9e70225fb58"
REFERENCE_PATH = "docs/JUDGE_HUMAN_SEMANTIC_REFERENCE_V1.json"
PROFILE_PATH = "docs/J4_GPT6_LUNA_PROFILE.json"
CONTRACT_PATH = "docs/J4_GPT6_LUNA_PAYLOAD_CONTRACT.json"
COMPARISON = "CONTROLLED_SEMANTIC_TASK_COMPARISON_WITH_MODEL_SPECIFIC_INFERENCE_PROFILE"
FORBIDDEN_FIELDS = (
    "max_tokens",
    "temperature",
    "top_p",
    "top_logprobs",
    "logprobs",
    "tools",
    "tool_choice",
    "stream",
    "n",
    "reasoning_mode",
    "service_tier",
    "previous_response_id",
)


def require(condition, code="FREEZE_OR_INSTRUMENT_MISMATCH"):
    if not condition:
        raise j3.engine.BenchmarkAbort(code)


def raw_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_payload_bytes(payload):
    # Exact decoded HTTP JSON, UTF-8, sorted keys, compact separators, ASCII escapes,
    # finite numbers only. Headers (including Authorization) are never included.
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def payload_hash(payload):
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def historical_invariants():
    actual = {
        "semantic_contract_sha256": hashlib.sha256(j3.engine._prompt().encode()).hexdigest(),
        "fixture_sha256": j3.parent.file_hash(ROOT / "tests/fixtures/adversarial.json"),
        "source_human_adjudication_sha256": raw_hash(
            ROOT / "docs/J3_LUNA_5_6_HUMAN_ADJUDICATION.json"
        ),
    }
    require(
        actual
        == {
            "semantic_contract_sha256": j3.CONTRACT_SHA256,
            "fixture_sha256": j3.FIXTURE_SHA256,
            "source_human_adjudication_sha256": SOURCE_REFERENCE_SHA256,
        }
    )
    return actual


def human_reference():
    historical_invariants()
    source = json.loads((ROOT / "docs/J3_LUNA_5_6_HUMAN_ADJUDICATION.json").read_text())
    result = {
        "version": "judge-human-semantic-reference-v1",
        "status": "FROZEN_HUMAN_SEMANTIC_REFERENCE_V1",
        "source_commit": BASELINE,
        "source_adjudication_sha256": SOURCE_REFERENCE_SHA256,
        "observability_rule": source["observability_rule"],
        "prohibited_privileged_information": source["prohibited_privileged_information"],
        "cases": [
            {k: c[k] for k in ("id", "human_classification", "human_flags")}
            for c in source["cases"]
        ],
        "excluded_cases": [
            {"id": c["id"], "status": "NOT_EVALUABLE"} for c in source["excluded_cases"]
        ],
        "limitations": [
            "Mechanically projected from the supplied human reference; no new adjudication.",
            "No model dispositions, severity or model-specific rationales are comparison targets.",
            "Not ground truth, accuracy certification, a model score or judge selection.",
            "Only judge-observable information is admissible; fixture intent is not model evidence.",
        ],
    }
    ids = [c["id"] for c in result["cases"] + result["excluded_cases"]]
    require(
        len(result["cases"]) == 27 and len(result["excluded_cases"]) == 8 and len(set(ids)) == 35
    )
    return result


def select_profile(profile_id):
    require(profile_id == PROFILE_ID, "UNKNOWN_BENCHMARK_PROFILE")
    declared = select_openai_profile(profile_id, benchmark=True)
    return j3.ProviderProfile(
        profile_id,
        "openai",
        "openai_compatible",
        declared.base_url,
        declared.model,
        "CIVICGATE_OPENAI_JUDGE_API_KEY",
        declared.token_limit_field,
        declared.base_url + "/chat/completions",
    )


def payload(profile_id, case):
    declared = select_openai_profile(profile_id, benchmark=True)
    content = json.dumps(
        {
            "request": case["request"],
            "proposal": Proposal(tool=case["tool"], arguments=case["arguments"]).model_dump(),
        },
        sort_keys=True,
    )
    return declared.payload(declared.model, j3.engine._prompt(), content)


def profile_artifact():
    profile = select_profile(PROFILE_ID)
    return {
        "version": "j4-gpt6-luna-profile-v1",
        "experiment_id": EXPERIMENT,
        "profile_id": PROFILE_ID,
        "provider": "openai",
        "protocol": profile.protocol,
        "base_url": profile.base_url,
        "path": "/chat/completions",
        "model": profile.model,
        "role": "judge",
        "authority": "NONE",
        "reasoning_effort": "medium",
        "max_completion_tokens": 512,
        "response_format": {"type": "json_object"},
        "retry_budget": 0,
        "gateway_execution": False,
        "schedule": {"primary": 35, "repeat": 9, "max_requests": 44},
        "comparison": COMPARISON,
    }


def contract_artifact():
    return {
        "version": "j4-gpt6-luna-payload-contract-v1",
        "experiment_id": EXPERIMENT,
        "profile_id": PROFILE_ID,
        "protocol": "openai_compatible",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "required_payload_fields": [
            "model",
            "reasoning_effort",
            "max_completion_tokens",
            "response_format",
            "messages",
        ],
        "required_values": {
            "model": "gpt-6-luna",
            "reasoning_effort": "medium",
            "max_completion_tokens": 512,
            "response_format": {"type": "json_object"},
        },
        "forbidden_payload_fields": list(FORBIDDEN_FIELDS),
        "extra_payload_fields": "FORBIDDEN",
        "semantic_serialization": {
            "system": "JUDGE_SYSTEM_PROMPT + json.dumps(_JudgeSignalWire.model_json_schema(), sort_keys=True)",
            "user": "json.dumps({'request': request, 'proposal': proposal.model_dump()}, sort_keys=True)",
            "payload_sha256": "SHA-256 of json.dumps(exact_decoded_http_payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8'); excludes all headers",
        },
        "message_roles": ["system", "user"],
        "judge_visible_case_information": ["request", "proposal.tool", "proposal.arguments"],
        "response_identity": {
            "expected": "gpt-6-luna",
            "rule": "Exact safely observable equality; no alias normalization",
            "missing": "OBSERVER_EVIDENCE_FAILURE",
            "unexpected": "RETURNED_MODEL_MISMATCH",
        },
        "response_contract": "HTTP success, identity, exactly one assistant text payload, stop without refusal, JSON object, strict _JudgeSignalWire; no repair",
        "strict_wire_validation": True,
        "failure_taxonomy_reference": "scripts/run_j3_experiment.py:category/fatal_reason; scripts/run_j3_amendment_001.py:NONFATAL/FATAL",
        "nonfatal_classes": list(j3.historical.NONFATAL),
        "fatal_classes": list(j3.historical.FATAL),
        "optional_telemetry": [
            "returned_model",
            "request_id",
            "finish_reason",
            "system_fingerprint",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "reasoning_tokens",
            "latency_ms",
            "service_tier",
        ],
        "missing_optional_telemetry": None,
        "retry_budget": 0,
        "schedule": {"primary": 35, "repeat": 9, "max_requests": 44},
        "gateway_execution": False,
    }


def prepare():
    invariants = historical_invariants()
    artifacts = {
        REFERENCE_PATH: human_reference(),
        PROFILE_PATH: profile_artifact(),
        CONTRACT_PATH: contract_artifact(),
    }
    for name, value in artifacts.items():
        data = (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode()
        path = ROOT / name
        if path.exists():
            require(path.read_bytes() == data)
        else:
            path.write_bytes(data)
    fixtures = j3.engine._load_fixtures()
    schedule = j3.engine._schedule(fixtures)
    require(len(fixtures) == 35 and len(schedule) == 44)
    by_id = {c["id"]: c for c in fixtures}
    source_paths = sorted(
        set(j3.raw_hashes())
        | {
            "src/civicgate/llm/judge_profiles.py",
            "scripts/prepare_j4_gpt6_luna.py",
            "tests/unit/test_j4_gpt6_luna.py",
            *artifacts,
            "docs/J3_LUNA_5_6_HUMAN_ADJUDICATION.json",
        }
    )
    return {
        "experiment_id": EXPERIMENT,
        "execution_head": None,
        "execution_head_status": "TBD_AFTER_AUTHORIZED_COMMIT",
        "baseline_publication_head": BASELINE,
        "model": "gpt-6-luna",
        "profile_id": PROFILE_ID,
        **invariants,
        "human_reference_sha256": raw_hash(ROOT / REFERENCE_PATH),
        "profile_sha256": raw_hash(ROOT / PROFILE_PATH),
        "payload_contract_sha256": raw_hash(ROOT / CONTRACT_PATH),
        "primary_count": 35,
        "repeat_count": 9,
        "max_requests": 44,
        "retries": 0,
        "gateway_execution": False,
        "authorization": "NOT_AUTHORIZED",
        "status": "DRAFT_PRE_EXECUTION_FREEZE_REQUIRES_AUTHORIZED_COMMIT",
        "schedule": [
            {**entry, "payload_sha256": payload_hash(payload(PROFILE_ID, by_id[entry["id"]]))}
            for entry in schedule
        ],
        "source_sha256_lf": {name: j3.parent.file_hash(ROOT / name) for name in source_paths},
        "no_live_entrypoint": True,
    }


def verify_instrument():
    historical_invariants()
    for name, expected in (
        (REFERENCE_PATH, human_reference()),
        (PROFILE_PATH, profile_artifact()),
        (CONTRACT_PATH, contract_artifact()),
    ):
        expected_bytes = (json.dumps(expected, indent=2, ensure_ascii=True) + "\n").encode()
        require((ROOT / name).read_bytes() == expected_bytes)


class J4Observer(OpenAIObserver):
    def observe(self, response, secret, profile):
        # Identity/one assistant message are checked before semantic parsing.
        try:
            body = response.json()
        except ValueError:
            body = None
        identity = (
            j3.engine._safe_text(body.get("model"), secret) if isinstance(body, dict) else None
        )
        choices = body.get("choices") if isinstance(body, dict) else None
        message = (
            choices[0].get("message")
            if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict)
            else None
        )
        shape_ok = (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and isinstance(message.get("content"), str)
            and bool(message["content"].strip())
        )
        native_failure = (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and (
                choices[0].get("finish_reason") in {"length", "content_filter"}
                or bool(message.get("refusal"))
            )
        )
        if response.status_code < 400 and (
            identity != profile.model or not (shape_ok or native_failure)
        ):
            empty = httpx.Response(response.status_code, json={}, headers=response.headers)
            metadata, structural, state = super().observe(empty, secret, profile)
            metadata["returned_model"] = identity
            structural["extraction_error_code"] = "MALFORMED_PROVIDER_RESPONSE"
        else:
            metadata, structural, state = super().observe(response, secret, profile)
        for name in ("system_fingerprint", "service_tier"):
            metadata[name] = (
                j3.engine._safe_text(body.get(name), secret) if isinstance(body, dict) else None
            )
        return metadata, structural, state


class J4Transport(j3.ExperimentTransport):
    def __init__(self, payloads, secret, verify, inner_factory):
        # An explicit injected transport is required. No default live transport here.
        super().__init__(
            select_profile(PROFILE_ID),
            payloads,
            secret,
            verify,
            inner_factory,
            profile_resolver=select_profile,
        )
        self.observer = J4Observer()
        self.payload_hashes = tuple(payload_hash(p) for p in payloads)
        self.journaled_sequence = None

    def telemetry_extension(self):
        return {name: self.metadata.get(name) for name in ("system_fingerprint", "service_tier")}

    def arm(self, sequence):
        require(sequence == self.journaled_sequence, "EVIDENCE_WRITE_FAILURE")
        super().arm(sequence)

    async def handle_async_request(self, request):
        require(
            self.calls < len(self.payload_hashes) and self.calls < 44, "CALL_ACCOUNTING_VIOLATION"
        )
        require(
            payload_hash(json.loads(request.content)) == self.payload_hashes[self.calls],
            "PAYLOAD_PROFILE_MISMATCH",
        )
        return await super().handle_async_request(request)


async def observe_with_transport(
    persist, inner_factory, *, secret, run_id, profile_id=PROFILE_ID, verify=verify_instrument
):
    """Reuse the frozen J4 observation path after an entrypoint validates execution."""
    profile = select_profile(profile_id)
    verify()
    fixtures = j3.engine._load_fixtures()
    by_id = {c["id"]: c for c in fixtures}
    transport = J4Transport(
        [payload(profile_id, by_id[e["id"]]) for e in j3.engine._schedule(fixtures)],
        secret,
        verify,
        inner_factory,
    )
    judge = LiveJudgeProvider(
        profile.base_url,
        profile.model,
        secret,
        provider_name="openai",
        openai_profile_id=profile_id,
        transport=transport,
    )
    judge.client.max_attempts = 1

    def journal(stage, row):
        if stage == "start":
            row = {
                **row,
                "experiment_id": EXPERIMENT,
                "fixture_id": row["id"],
                "profile_id": profile_id,
                "requested_model": profile.model,
                "payload_sha256": transport.payload_hashes[row["sequence"] - 1],
            }
        persist(stage, row)
        if stage == "start":
            transport.journaled_sequence = row["sequence"]

    return await j3.run_experiment(fixtures, judge, transport, journal, run_id=run_id)


async def observe_offline(
    persist, mock_transport, *, profile_id=PROFILE_ID, verify=verify_instrument
):
    """Exercise the observation path with an explicit MockTransport only."""
    require(isinstance(mock_transport, httpx.MockTransport), "LIVE_EXECUTION_NOT_AUTHORIZED")
    return await observe_with_transport(
        persist,
        lambda: mock_transport,
        secret="synthetic-offline-only",
        run_id="offline-j4-instrument-test",
        profile_id=profile_id,
        verify=verify,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "EXISTING_FREEZE_OUTPUT")
    freeze = prepare()
    args.output.write_bytes((json.dumps(freeze, indent=2) + "\n").encode())
    print(json.dumps({"status": freeze["status"], "freeze_raw_sha256": raw_hash(args.output)}))


if __name__ == "__main__":
    main()
