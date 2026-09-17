import os
from pathlib import Path

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.llm.base import AgentModel, JudgeModel, UnavailableProvider
from civicgate.llm.mock import MockProvider
from civicgate.llm.openai_compatible import OpenAICompatible
from civicgate.mcp.tools import Gateway


def providers() -> tuple[AgentModel, JudgeModel]:
    mode = os.getenv("CIVICGATE_PROVIDER", "unavailable")
    if mode == "mock":
        return MockProvider(), MockProvider()
    if mode == "unavailable":
        return UnavailableProvider(), UnavailableProvider()
    if mode != "openai_compatible":
        raise ValueError("Unknown CIVICGATE_PROVIDER")
    provider = OpenAICompatible(
        os.environ["CIVICGATE_MODEL_BASE_URL"],
        os.environ["CIVICGATE_AGENT_MODEL"],
        os.environ["CIVICGATE_JUDGE_MODEL"],
        os.getenv("CIVICGATE_MODEL_API_KEY", ""),
    )
    return provider, provider


def configured_gateway() -> Gateway:
    _, judge = providers()
    return Gateway(
        USAspending(),
        judge,
        Trace(Path(os.getenv("CIVICGATE_AUDIT_PATH", "audit/trace.jsonl"))),
        float(os.getenv("CIVICGATE_MIN_CONFIDENCE", "0.85")),
    )
