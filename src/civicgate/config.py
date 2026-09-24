from pathlib import Path

from civicgate.adapters.usaspending import USAspending
from civicgate.audit.trace import Trace
from civicgate.llm.base import AgentModel, JudgeModel, UnavailableProvider
from civicgate.llm.live import GranitePlanner, LiveJudgeProvider
from civicgate.llm.mock import MockProvider
from civicgate.llm.openai_compatible import OpenAICompatible
from civicgate.mcp.tools import Gateway
from civicgate.runtime_config import (
    ConfigurationProvider,
    EnvironmentConfiguration,
    EnvironmentSecretProvider,
    RuntimeSettings,
    SecretProvider,
)


def providers(
    configuration: ConfigurationProvider | None = None,
    secrets: SecretProvider | None = None,
) -> tuple[AgentModel, JudgeModel]:
    settings = RuntimeSettings.from_providers(
        configuration or EnvironmentConfiguration(), secrets or EnvironmentSecretProvider()
    )
    if settings.agent_provider == "mock" and settings.judge_provider == "mock":
        return MockProvider(), MockProvider()
    if settings.agent_provider == "unavailable":
        agent: AgentModel = UnavailableProvider()
    elif settings.agent_provider == "lm_studio":
        assert settings.agent_base_url and settings.agent_model
        agent = GranitePlanner(settings.agent_base_url, settings.agent_model)
    elif settings.agent_provider == "openai_compatible":
        assert settings.agent_base_url and settings.agent_model and settings.judge_model
        agent = OpenAICompatible(
            settings.agent_base_url,
            settings.agent_model,
            settings.judge_model,
            settings.agent_api_key or "",
        )
    else:
        raise ValueError(f"Unknown agent provider: {settings.agent_provider}")
    if settings.judge_provider == "unavailable":
        judge: JudgeModel = UnavailableProvider()
    elif settings.judge_provider == "mock":
        judge = MockProvider()
    elif settings.judge_provider in {"openai_compatible", "anthropic"}:
        assert settings.judge_base_url and settings.judge_model and settings.judge_api_key
        judge = LiveJudgeProvider(
            settings.judge_base_url,
            settings.judge_model,
            settings.judge_api_key,
            protocol=settings.judge_protocol,  # type: ignore[arg-type]
            provider_name=settings.judge_provider,
            openai_profile_id=settings.judge_profile_id,
        )
    else:
        raise ValueError(f"Unknown judge provider: {settings.judge_provider}")
    return agent, judge


def configured_gateway() -> Gateway:
    settings = RuntimeSettings.from_providers(
        EnvironmentConfiguration(), EnvironmentSecretProvider()
    )
    _, judge = providers()
    return Gateway(
        USAspending(),
        judge,
        Trace(Path(settings.audit_path)),
        settings.min_confidence,
    )
