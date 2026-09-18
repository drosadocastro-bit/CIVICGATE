"""Measure a loaded LM Studio Granite model without saving API traffic.

LM Studio's native ``/api/v1/chat`` endpoint exposes token and TTFT statistics
that are not always present on its OpenAI-compatible endpoint.  This runner is
an evidence tool for a local, operator-controlled model.  It stores only
sanitized metadata, hashes and typed validation results; prompts and provider
responses never enter the artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

from civicgate.llm.live import PLANNER_SYSTEM_PROMPT
from civicgate.models.provenance import utcnow
from civicgate.models.requests import TOOLS, Proposal

DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_CASES = (
    "valid-recipient",
    "ambiguous-recipient",
    "private-records",
    "retrieved-injection",
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _model_snapshot(model: dict[str, Any]) -> dict[str, Any]:
    """Keep only stable, non-secret inventory fields in the evidence artifact."""
    quantization = model.get("quantization")
    quantization = quantization if isinstance(quantization, dict) else {}
    loaded = model.get("loaded_instances")
    loaded = loaded if isinstance(loaded, list) else []
    loaded_config: dict[str, Any] | None = None
    if loaded and isinstance(loaded[0], dict):
        config = loaded[0].get("config")
        if isinstance(config, dict):
            loaded_config = {
                key: config.get(key)
                for key in (
                    "context_length",
                    "eval_batch_size",
                    "physical_batch_size",
                    "parallel",
                    "flash_attention",
                    "context_checkpoints",
                    "offload_kv_cache_to_gpu",
                )
                if key in config
            }
    return {
        "key": model.get("key"),
        "publisher": model.get("publisher"),
        "display_name": model.get("display_name"),
        "architecture": model.get("architecture"),
        "quantization": quantization.get("name"),
        "bits_per_weight": quantization.get("bits_per_weight"),
        "size_bytes": model.get("size_bytes"),
        "params": model.get("params_string"),
        "max_context_length": model.get("max_context_length"),
        "format": model.get("format"),
        "selected_variant": model.get("selected_variant"),
        "loaded_instance_count": len(loaded),
        "loaded_config": loaded_config,
    }


def _prompt(request: str) -> str:
    schemas = {tool: model.model_json_schema() for tool, model in TOOLS.items()}
    return (
        PLANNER_SYSTEM_PROMPT
        + " Registered tool schemas: "
        + json.dumps(schemas, sort_keys=True)
        + "\n\nUser request: "
        + request
    )


def _error_summary(response: httpx.Response) -> dict[str, Any]:
    """Summarize an error without retaining a provider body or request data."""
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


def _validate_proposal(content: str, expected_tool: str) -> dict[str, Any]:
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
            argument_valid = False
    return {
        "schema_valid": True,
        "tool": proposal.tool,
        "expected_tool_match": proposal.tool == expected_tool,
        "argument_valid": argument_valid,
        "proposal_fingerprint": _fingerprint(proposal.model_dump(mode="json")),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    fixtures_path = Path(args.fixtures)
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    selected = [case for case in fixtures if case.get("id") in args.cases]
    if not selected:
        raise ValueError("No requested benchmark cases were found in the fixture file")

    base_url = args.base_url.rstrip("/")
    started_inventory = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=args.timeout, trust_env=False) as client:
            inventory_response = await client.get(base_url + "/api/v1/models")
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return {
            "schema_version": "civicgate.granite-live-benchmark.v1",
            "generated_at": utcnow().isoformat(),
            "status": "PROVIDER_UNAVAILABLE",
            "claimed_model": args.claimed_model,
            "operator_conditions": _conditions(args),
            "inventory": None,
            "inventory_latency_ms": round((time.perf_counter() - started_inventory) * 1000, 3),
            "error": {"kind": type(exc).__name__},
            "rows": [],
            "summary": _empty_summary(),
            "raw_provider_traffic_saved": False,
        }
    inventory_latency_ms = round((time.perf_counter() - started_inventory) * 1000, 3)
    if inventory_response.status_code >= 400:
        return {
            "schema_version": "civicgate.granite-live-benchmark.v1",
            "generated_at": utcnow().isoformat(),
            "status": "INVENTORY_HTTP_FAILURE",
            "claimed_model": args.claimed_model,
            "operator_conditions": _conditions(args),
            "inventory": None,
            "inventory_latency_ms": inventory_latency_ms,
            "error": _error_summary(inventory_response),
            "rows": [],
            "summary": _empty_summary(),
            "raw_provider_traffic_saved": False,
        }
    try:
        inventory_body = inventory_response.json()
    except ValueError:
        inventory_body = {}
    models = inventory_body.get("models") if isinstance(inventory_body, dict) else None
    models = models if isinstance(models, list) else []
    candidates = [model for model in models if isinstance(model, dict)]
    selected_model = next((m for m in candidates if m.get("key") == args.model), None)
    if selected_model is None and args.model is None:
        selected_model = next(
            (
                m
                for m in candidates
                if m.get("loaded_instances") and m.get("architecture") == "granite"
            ),
            None,
        )
    snapshot = _model_snapshot(selected_model) if selected_model else None
    if selected_model is None or not selected_model.get("loaded_instances"):
        return {
            "schema_version": "civicgate.granite-live-benchmark.v1",
            "generated_at": utcnow().isoformat(),
            "status": "MODEL_NOT_FOUND"
            if args.model and selected_model is None
            else "MODEL_NOT_LOADED",
            "claimed_model": args.claimed_model,
            "requested_model": args.model,
            "operator_conditions": _conditions(args),
            "inventory": {
                "loaded_models": [
                    _model_snapshot(model) for model in candidates if model.get("loaded_instances")
                ]
            },
            "inventory_latency_ms": inventory_latency_ms,
            "rows": [],
            "summary": _empty_summary(),
            "raw_provider_traffic_saved": False,
        }

    model_key = selected_model.get("key")
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=args.timeout, trust_env=False) as client:
        for case in selected:
            for repetition in range(1, args.repetitions + 1):
                payload = {
                    "model": model_key,
                    "input": _prompt(case["request"]),
                    "temperature": 0,
                    "max_output_tokens": 512,
                    "stream": False,
                }
                request_fingerprint = _fingerprint(
                    {"case_id": case["id"], "request": case["request"]}
                )
                started = time.perf_counter()
                try:
                    response = await client.post(base_url + "/api/v1/chat", json=payload)
                except httpx.TimeoutException:
                    rows.append(
                        {
                            "case_id": case["id"],
                            "repetition": repetition,
                            "request_fingerprint": request_fingerprint,
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
                            "request_fingerprint": request_fingerprint,
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
                    "request_fingerprint": request_fingerprint,
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
                    row.update({"status": "MALFORMED_PROVIDER_RESPONSE"})
                    rows.append(row)
                    continue
                stats = body.get("stats") if isinstance(body, dict) else None
                stats = stats if isinstance(stats, dict) else {}
                output = body.get("output") if isinstance(body, dict) else None
                content = None
                if isinstance(output, list) and output and isinstance(output[0], dict):
                    candidate_content = output[0].get("content")
                    if isinstance(candidate_content, str):
                        content = candidate_content
                validation = (
                    _validate_proposal(content, case["tool"])
                    if content is not None
                    else {
                        "schema_valid": False,
                        "tool": None,
                        "expected_tool_match": False,
                        "argument_valid": False,
                        "proposal_fingerprint": None,
                    }
                )
                row.update(
                    {
                        "status": "COMPLETED",
                        "model_instance_id": body.get("model_instance_id"),
                        "prompt_tokens": stats.get("input_tokens"),
                        "completion_tokens": stats.get("total_output_tokens"),
                        "reasoning_tokens": stats.get("reasoning_output_tokens"),
                        "generation_tokens_per_second": stats.get("tokens_per_second"),
                        "time_to_first_token_ms": (
                            round(float(stats["time_to_first_token_seconds"]) * 1000, 3)
                            if isinstance(stats.get("time_to_first_token_seconds"), (int, float))
                            else None
                        ),
                        **validation,
                    }
                )
                rows.append(row)

    observed_display_name = snapshot.get("display_name", "") if snapshot else ""
    return {
        "schema_version": "civicgate.granite-live-benchmark.v1",
        "generated_at": utcnow().isoformat(),
        "status": "COMPLETED_NATIVE_LM_STUDIO"
        if rows and all(row["status"] == "COMPLETED" for row in rows)
        else "PARTIAL_PROVIDER_FAILURE",
        "claimed_model": args.claimed_model,
        "requested_model": args.model,
        "observed_model": snapshot,
        "model_identity_match": bool(
            args.claimed_model.lower() in str(observed_display_name).lower()
        ),
        "operator_conditions": _conditions(args),
        "endpoint": base_url + "/api/v1/chat",
        "inventory_latency_ms": inventory_latency_ms,
        "cases": [case["id"] for case in selected],
        "repetitions": args.repetitions,
        "rows": rows,
        "summary": _summary(rows, selected),
        "interpretation": (
            "Proposal measurements describe model behavior only. CivicGate deterministic policy "
            "remains authoritative; expected policy decisions are fixture context, not model labels."
        ),
        "raw_provider_traffic_saved": False,
    }


def _conditions(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "gpu_offload_layers": args.offload_layers,
        "vram_gb_operator_reported": args.vram_gb,
        "backend": args.backend,
        "sampling": {
            "temperature": 0,
            "top_p": 1,
            "max_output_tokens": 512,
            "stream": False,
        },
        "timeout_seconds": args.timeout,
        "fixture_set": args.fixtures,
        "parser": "strict Pydantic Proposal; no repair fallback",
        "prompt_contract": "provider-neutral CivicGate planner contract v2",
        "operator_note": "GPU offload and VRAM values were supplied by the operator; LM Studio API did not expose them.",
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "calls": 0,
        "completed": 0,
        "errors": 0,
        "timeouts": 0,
        "latency_ms": {"median": None, "p95": None},
        "time_to_first_token_ms": {"median": None},
        "tokens": {
            "prompt_total": 0,
            "completion_total": 0,
            "prompt_median": None,
            "completion_median": None,
        },
        "generation_tokens_per_second": {"median": None},
        "schema_valid_rate": None,
        "expected_tool_match_rate": None,
        "argument_valid_rate": None,
        "repeat_consistency_rate": None,
    }


def _summary(rows: list[dict[str, Any]], selected: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "COMPLETED"]
    latencies = [float(row["latency_ms"]) for row in completed]
    ttfts = [
        float(row["time_to_first_token_ms"])
        for row in completed
        if row.get("time_to_first_token_ms") is not None
    ]
    prompt_tokens = [
        int(row["prompt_tokens"]) for row in completed if isinstance(row.get("prompt_tokens"), int)
    ]
    completion_tokens = [
        int(row["completion_tokens"])
        for row in completed
        if isinstance(row.get("completion_tokens"), int)
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
            if len(set(fingerprints)) == 1:
                consistent_cases += 1
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
        "time_to_first_token_ms": {"median": statistics.median(ttfts) if ttfts else None},
        "tokens": {
            "prompt_total": sum(prompt_tokens),
            "completion_total": sum(completion_tokens),
            "prompt_median": statistics.median(prompt_tokens) if prompt_tokens else None,
            "completion_median": statistics.median(completion_tokens)
            if completion_tokens
            else None,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--model", default=None, help="Exact LM Studio model key; defaults to a loaded Granite"
    )
    parser.add_argument("--claimed-model", default="Granite 3.2")
    parser.add_argument("--backend", default="not supplied")
    parser.add_argument("--offload-layers", type=int, default=19)
    parser.add_argument("--vram-gb", type=float, default=6.76)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--fixtures", default="tests/fixtures/adversarial.json")
    parser.add_argument("--case", dest="cases", action="append", choices=None)
    parser.add_argument("--output", default="artifacts/granite-live-benchmark.json")
    args = parser.parse_args()
    if not args.cases:
        args.cases = list(DEFAULT_CASES)
    result = asyncio.run(_run(args))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    print(f"status={result['status']} artifact={output}")


if __name__ == "__main__":
    main()
