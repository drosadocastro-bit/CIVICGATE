"""Benchmark CivicGate proposals through a local llama.cpp OpenAI endpoint.

This runner follows the HELM local-runtime boundary: direct GBNF constrains the
outer JSON envelope, and Pydantic validates the Proposal and tool arguments
after generation. It records sanitized timing/token metadata only. Provider
responses, prompts and API keys are never written to the artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from civicgate.llm.live import PLANNER_SYSTEM_PROMPT
from civicgate.models.provenance import utcnow
from civicgate.models.requests import TOOLS, Proposal

DEFAULT_CASES = (
    "valid-recipient",
    "ambiguous-recipient",
    "private-records",
    "retrieved-injection",
)
DEFAULT_GRAMMAR = Path("src/civicgate/llm/grammars/proposal.json.gbnf")


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _system_prompt() -> str:
    schemas = {tool: model.model_json_schema() for tool, model in TOOLS.items()}
    return (
        PLANNER_SYSTEM_PROMPT + " Registered tool schemas: " + json.dumps(schemas, sort_keys=True)
    )


def _validate_proposal(content: str | None, expected_tool: str) -> dict[str, Any]:
    if content is None:
        return {
            "schema_valid": False,
            "tool": None,
            "expected_tool_match": False,
            "argument_valid": False,
            "proposal_fingerprint": None,
        }
    try:
        proposal = Proposal.model_validate(json.loads(content))
    except (ValueError, TypeError):
        return {
            "schema_valid": False,
            "tool": None,
            "expected_tool_match": False,
            "argument_valid": False,
            "proposal_fingerprint": None,
        }
    argument_valid = False
    if proposal.tool in TOOLS:
        try:
            TOOLS[proposal.tool].model_validate(proposal.arguments)
            argument_valid = True
        except ValueError:
            pass
    return {
        "schema_valid": True,
        "tool": proposal.tool,
        "expected_tool_match": proposal.tool == expected_tool,
        "argument_valid": argument_valid,
        "proposal_fingerprint": _fingerprint(proposal.model_dump(mode="json")),
    }


def _error_summary(response: httpx.Response) -> dict[str, Any]:
    error_type: str | None = None
    error_code: str | None = None
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            error_type = body["error"].get("type")
            error_code = body["error"].get("code")
    except ValueError:
        pass
    return {
        "http_status": response.status_code,
        "provider_error_type": error_type,
        "provider_error_code": error_code,
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "calls": 0,
        "completed": 0,
        "errors": 0,
        "timeouts": 0,
        "latency_ms": {"median": None, "p95": None},
        "time_to_first_token_ms": {"median": None, "exposed": False},
        "tokens": {
            "prompt_total": 0,
            "completion_total": 0,
            "prompt_median": None,
            "completion_median": None,
        },
        "prompt_tokens_per_second": {"median": None},
        "generation_tokens_per_second": {"median": None},
        "schema_valid_rate": None,
        "expected_tool_match_rate": None,
        "argument_valid_rate": None,
        "repeat_consistency_rate": None,
    }


def _summary(rows: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "COMPLETED"]
    latencies = [float(row["latency_ms"]) for row in completed]
    prompt_tokens = [
        int(row["prompt_tokens"]) for row in completed if isinstance(row.get("prompt_tokens"), int)
    ]
    completion_tokens = [
        int(row["completion_tokens"])
        for row in completed
        if isinstance(row.get("completion_tokens"), int)
    ]
    prompt_rates = [
        float(row["prompt_tokens_per_second"])
        for row in completed
        if isinstance(row.get("prompt_tokens_per_second"), (int, float))
    ]
    generation_rates = [
        float(row["generation_tokens_per_second"])
        for row in completed
        if isinstance(row.get("generation_tokens_per_second"), (int, float))
    ]
    cases_with_repeats = 0
    consistent_cases = 0
    for case in selected:
        fingerprints = [
            row.get("proposal_fingerprint")
            for row in completed
            if row.get("case_id") == case["id"] and row.get("proposal_fingerprint") is not None
        ]
        if len(fingerprints) >= 2:
            cases_with_repeats += 1
            consistent_cases += len(set(fingerprints)) == 1
    return {
        "calls": len(rows),
        "completed": len(completed),
        "errors": sum(
            row.get("status")
            in {"HTTP_FAILURE", "TRANSPORT_FAILURE", "MALFORMED_PROVIDER_RESPONSE"}
            for row in rows
        ),
        "timeouts": sum(row.get("status") == "TIMEOUT" for row in rows),
        "latency_ms": {
            "median": statistics.median(latencies) if latencies else None,
            "p95": _percentile(latencies, 95),
        },
        "time_to_first_token_ms": {"median": None, "exposed": False},
        "tokens": {
            "prompt_total": sum(prompt_tokens),
            "completion_total": sum(completion_tokens),
            "prompt_median": statistics.median(prompt_tokens) if prompt_tokens else None,
            "completion_median": statistics.median(completion_tokens)
            if completion_tokens
            else None,
        },
        "prompt_tokens_per_second": {
            "median": statistics.median(prompt_rates) if prompt_rates else None
        },
        "generation_tokens_per_second": {
            "median": statistics.median(generation_rates) if generation_rates else None
        },
        "schema_valid_rate": sum(row.get("schema_valid") is True for row in completed)
        / len(completed)
        if completed
        else None,
        "expected_tool_match_rate": sum(row.get("expected_tool_match") is True for row in completed)
        / len(completed)
        if completed
        else None,
        "argument_valid_rate": sum(row.get("argument_valid") is True for row in completed)
        / len(completed)
        if completed
        else None,
        "repeat_consistency_rate": consistent_cases / cases_with_repeats
        if cases_with_repeats
        else None,
    }


def _validate_loopback(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("LLAMA_CPP_ENDPOINT_MUST_BE_LOOPBACK")


def _model_metadata(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"filename": path.name if path else None, "sha256": None, "size_bytes": None}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"filename": path.name, "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size}


def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_loopback(args.endpoint)
    grammar_path = Path(args.grammar)
    grammar = grammar_path.read_text(encoding="utf-8")
    grammar_sha256 = hashlib.sha256(grammar.encode("utf-8")).hexdigest()
    model_path = Path(args.model)
    fixtures = json.loads(Path(args.fixtures).read_text(encoding="utf-8"))
    selected = [case for case in fixtures if case.get("id") in args.cases]
    if not selected:
        raise ValueError("NO_REQUESTED_BENCHMARK_CASES")
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(args.api_key_env)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for case in selected:
            for repetition in range(1, args.repetitions + 1):
                started = time.perf_counter()
                payload = {
                    "model": args.model,
                    "messages": [
                        {"role": "system", "content": _system_prompt()},
                        {"role": "user", "content": case["request"]},
                    ],
                    "temperature": 0,
                    "top_p": 1,
                    "top_k": 1,
                    "min_p": 0,
                    "seed": args.seed,
                    "max_tokens": 512,
                    "grammar": grammar,
                }
                fingerprint = _fingerprint({"case_id": case["id"], "request": case["request"]})
                try:
                    response = client.post(args.endpoint, headers=headers, json=payload)
                except httpx.TimeoutException:
                    rows.append(
                        {
                            "case_id": case["id"],
                            "repetition": repetition,
                            "request_fingerprint": fingerprint,
                            "status": "TIMEOUT",
                            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                        }
                    )
                    continue
                except httpx.TransportError as exc:
                    rows.append(
                        {
                            "case_id": case["id"],
                            "repetition": repetition,
                            "request_fingerprint": fingerprint,
                            "status": "TRANSPORT_FAILURE",
                            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                            "error": {"kind": type(exc).__name__},
                        }
                    )
                    continue
                latency_ms = round((time.perf_counter() - started) * 1000, 3)
                row: dict[str, Any] = {
                    "case_id": case["id"],
                    "category": case.get("category"),
                    "repetition": repetition,
                    "request_fingerprint": fingerprint,
                    "expected_tool": case.get("tool"),
                    "expected_policy_decision": case.get("expected_decision"),
                    "latency_ms": latency_ms,
                }
                if response.status_code >= 400:
                    row.update({"status": "HTTP_FAILURE", "error": _error_summary(response)})
                    rows.append(row)
                    continue
                try:
                    body = response.json()
                except ValueError:
                    row["status"] = "MALFORMED_PROVIDER_RESPONSE"
                    rows.append(row)
                    continue
                choices = body.get("choices") if isinstance(body, dict) else None
                content = None
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    message = choices[0].get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        content = message["content"]
                usage = body.get("usage") if isinstance(body, dict) else None
                usage = usage if isinstance(usage, dict) else {}
                timings = body.get("timings") if isinstance(body, dict) else None
                timings = timings if isinstance(timings, dict) else {}
                validation = _validate_proposal(content, case["tool"])
                row.update(
                    {
                        "status": "COMPLETED",
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "prompt_tokens_per_second": timings.get("prompt_per_second"),
                        "generation_tokens_per_second": timings.get("predicted_per_second"),
                        "time_to_first_token_ms": None,
                        **validation,
                    }
                )
                rows.append(row)
    return {
        "schema_version": "civicgate.granite-llama-cpp-benchmark.v1",
        "generated_at": utcnow().isoformat(),
        "status": "COMPLETED_LLAMA_CPP"
        if rows and all(row["status"] == "COMPLETED" for row in rows)
        else "PARTIAL_PROVIDER_FAILURE",
        "claimed_model": args.claimed_model,
        "model": _model_metadata(model_path),
        "runtime": {
            "provider": "LOCAL_LLAMA_CPP",
            "backend": args.backend,
            "device": args.device,
            "llama_cpp_commit": args.server_commit,
            "gpu_layers": args.gpu_layers,
            "context_tokens": args.context_tokens,
            "batch_size": args.batch_size,
            "ubatch_size": args.ubatch_size,
            "flash_attention": True,
            "kv_offload": True,
            "grammar_file": grammar_path.as_posix(),
            "grammar_sha256": grammar_sha256,
            "constraint_mode": "DIRECT_GBNF",
        },
        "endpoint": args.endpoint,
        "cases": [case["id"] for case in selected],
        "repetitions": args.repetitions,
        "rows": rows,
        "summary": _summary(rows, selected),
        "interpretation": "The grammar constrains only the Proposal envelope; deterministic CivicGate policy remains authoritative.",
        "raw_provider_traffic_saved": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1/chat/completions")
    parser.add_argument("--model", required=True)
    parser.add_argument("--claimed-model", default="Granite 3.2")
    parser.add_argument("--grammar", default=str(DEFAULT_GRAMMAR))
    parser.add_argument("--fixtures", default="tests/fixtures/adversarial.json")
    parser.add_argument("--case", dest="cases", action="append")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--seed", type=int, default=23)
    parser.add_argument("--backend", default="VULKAN")
    parser.add_argument("--device", default="Vulkan1")
    parser.add_argument("--gpu-layers", type=int, default=19)
    parser.add_argument("--context-tokens", type=int, default=8192)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--ubatch-size", type=int, default=512)
    parser.add_argument("--server-commit", default="fb27a525d28381a16a4bb038858a10e4927381ca")
    parser.add_argument("--api-key-env", default="CIVICGATE_LLAMA_CPP_API_KEY")
    parser.add_argument("--output", default="artifacts/granite-llama-cpp-benchmark.json")
    args = parser.parse_args()
    args.cases = args.cases or list(DEFAULT_CASES)
    result = run(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print(f"status={result['status']} artifact={output}")


if __name__ == "__main__":
    main()
