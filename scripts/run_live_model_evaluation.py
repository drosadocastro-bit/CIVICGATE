"""Opt-in live planner/judge contract check; never runs in normal CI."""

import asyncio
import json
from pathlib import Path
from typing import Any

from civicgate.llm.live import GranitePlanner, LiveJudgeProvider, ProviderError
from civicgate.models.provenance import utcnow
from civicgate.runtime_config import (
    EnvironmentConfiguration,
    EnvironmentSecretProvider,
    RuntimeSettings,
)


async def run() -> dict[str, Any]:
    settings = RuntimeSettings.from_providers(
        EnvironmentConfiguration(), EnvironmentSecretProvider()
    )
    if settings.agent_provider != "lm_studio" or settings.judge_provider not in {
        "openai_compatible",
        "anthropic",
    }:
        return {
            "status": "BLOCKED_LIVE_PROVIDERS_NOT_CONFIGURED",
            "generated_at": utcnow().isoformat(),
        }
    assert (
        settings.agent_base_url
        and settings.agent_model
        and settings.judge_base_url
        and settings.judge_model
        and settings.judge_api_key
    )
    planner = GranitePlanner(settings.agent_base_url, settings.agent_model)
    judge = LiveJudgeProvider(
        settings.judge_base_url,
        settings.judge_model,
        settings.judge_api_key,
        protocol=settings.judge_protocol,  # type: ignore[arg-type]
        provider_name=settings.judge_provider,
    )
    request = (
        "Show bounded public federal awards for EXAMPLE RECIPIENT in Puerto Rico during FY2025."
    )
    try:
        proposal = await planner.propose(request)
        signal = await judge.assess(request, proposal)
        return {
            "status": "LIVE_CONTRACT_COMPLETED",
            "generated_at": utcnow().isoformat(),
            "request_fingerprint_only": "operator-supplied request; raw model bodies are not recorded",
            "proposal": proposal.model_dump(mode="json"),
            "judge_signal": signal.model_dump(mode="json"),
            "planner_telemetry": planner.last_telemetry.as_dict()
            if planner.last_telemetry
            else None,
            "judge_telemetry": judge.last_telemetry.as_dict() if judge.last_telemetry else None,
        }
    except ProviderError as exc:
        return {
            "status": "LIVE_CONTRACT_PROVIDER_FAILURE",
            "generated_at": utcnow().isoformat(),
            "error_code": exc.code,
            "retryable": exc.retryable,
            "planner_telemetry": planner.last_telemetry.as_dict()
            if planner.last_telemetry
            else None,
            "judge_telemetry": judge.last_telemetry.as_dict() if judge.last_telemetry else None,
        }


if __name__ == "__main__":
    result = asyncio.run(run())
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/live-model-evaluation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
