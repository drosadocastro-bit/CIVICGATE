"""Configuration contracts with no dotenv loading and no platform secret dependency.

The core package accepts providers. A Windows DPAPI implementation may live at
the edge of the process (see ``civicgate.windows_dpapi``) without becoming a
runtime dependency of governance or the MCP server.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from typing import Protocol
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Configuration is absent, contradictory or unsafe for the requested provider."""


class ConfigurationProvider(Protocol):
    def get(self, name: str) -> str | None: ...


class SecretProvider(Protocol):
    def get_secret(self, name: str) -> str | None: ...


class EnvironmentConfiguration:
    """Read the process environment only; never loads ``.env`` files implicitly."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = environ if values is None else values

    def get(self, name: str) -> str | None:
        value = self._values.get(name)
        return value if value else None


class EnvironmentSecretProvider:
    """Compatibility edge for local development; callers choose this explicitly."""

    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = environ if values is None else values

    def get_secret(self, name: str) -> str | None:
        value = self._values.get(name)
        return value if value else None


class InMemoryConfiguration:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self._values.get(name)


class InMemorySecretProvider:
    def __init__(self, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(values or {})

    def get_secret(self, name: str) -> str | None:
        return self._values.get(name)


class UnavailableSecretProvider:
    def get_secret(self, name: str) -> str | None:
        return None


@dataclass(frozen=True)
class RuntimeSettings:
    agent_provider: str
    judge_provider: str
    agent_base_url: str | None
    judge_base_url: str | None
    agent_model: str | None
    judge_model: str | None
    judge_protocol: str
    model_api_key: str | None
    agent_api_key: str | None
    judge_api_key: str | None
    audit_path: str
    min_confidence: float
    judge_profile_id: str = "generic-openai"

    @classmethod
    def from_providers(
        cls,
        configuration: ConfigurationProvider,
        secrets: SecretProvider,
    ) -> "RuntimeSettings":
        legacy = configuration.get("CIVICGATE_PROVIDER")
        agent_provider = configuration.get("CIVICGATE_AGENT_PROVIDER") or legacy or "unavailable"
        judge_provider = configuration.get("CIVICGATE_JUDGE_PROVIDER") or (
            "mock" if legacy == "mock" else "unavailable"
        )
        agent_base_url = configuration.get("CIVICGATE_AGENT_BASE_URL") or configuration.get(
            "CIVICGATE_MODEL_BASE_URL"
        )
        judge_base_url = configuration.get("CIVICGATE_JUDGE_BASE_URL") or configuration.get(
            "CIVICGATE_MODEL_BASE_URL"
        )
        agent_model = configuration.get("CIVICGATE_AGENT_MODEL")
        judge_model = configuration.get("CIVICGATE_JUDGE_MODEL")
        # Legacy model configuration remains an explicit environment choice.
        if legacy == "openai_compatible":
            if configuration.get("CIVICGATE_JUDGE_PROVIDER") not in {None, "", "openai_compatible"}:
                raise ConfigurationError("Legacy provider conflicts with explicit judge provider")
            agent_provider = "openai_compatible"
            judge_provider = "openai_compatible"
        if agent_provider == "lm_studio" and not agent_model:
            raise ConfigurationError("CIVICGATE_AGENT_MODEL is required for lm_studio")
        if agent_provider in {"lm_studio", "openai_compatible"} and not agent_base_url:
            raise ConfigurationError(f"CIVICGATE_AGENT_BASE_URL is required for {agent_provider}")
        if judge_provider in {"openai_compatible", "anthropic"}:
            if not judge_model:
                raise ConfigurationError(f"CIVICGATE_JUDGE_MODEL is required for {judge_provider}")
            if not judge_base_url:
                raise ConfigurationError(
                    f"CIVICGATE_JUDGE_BASE_URL is required for {judge_provider}"
                )
        protocol = configuration.get("CIVICGATE_JUDGE_PROTOCOL") or (
            "anthropic_messages" if judge_provider == "anthropic" else "openai_compatible"
        )
        if agent_provider not in {"mock", "unavailable", "lm_studio", "openai_compatible"}:
            raise ConfigurationError(f"Unknown agent provider: {agent_provider}")
        if judge_provider not in {"mock", "unavailable", "openai_compatible", "anthropic"}:
            raise ConfigurationError(f"Unknown judge provider: {judge_provider}")
        if protocol not in {"openai_compatible", "anthropic_messages"}:
            raise ConfigurationError(f"Unsupported judge protocol: {protocol}")
        if judge_provider == "anthropic":
            # This provider is Anthropic direct, not an inferred/proxy route.
            # Reject inherited legacy URLs and cross-provider protocol overrides
            # before resolving credentials or constructing any transport.
            if protocol != "anthropic_messages":
                raise ConfigurationError("Anthropic judge requires anthropic_messages")
            if (
                not configuration.get("CIVICGATE_JUDGE_BASE_URL")
                or not judge_base_url
                or judge_base_url.rstrip("/") != "https://api.anthropic.com"
            ):
                raise ConfigurationError(
                    "Anthropic judge requires explicit root https://api.anthropic.com"
                )
        elif judge_provider == "openai_compatible":
            if protocol != "openai_compatible":
                raise ConfigurationError("OpenAI-compatible judge requires openai_compatible")
            if judge_base_url and urlparse(judge_base_url).hostname == "api.anthropic.com":
                raise ConfigurationError(
                    "OpenAI-compatible credentials cannot use the Anthropic origin"
                )
        try:
            confidence = float(configuration.get("CIVICGATE_MIN_CONFIDENCE") or "0.85")
        except ValueError as exc:
            raise ConfigurationError("CIVICGATE_MIN_CONFIDENCE must be numeric") from exc
        if not 0 <= confidence <= 1:
            raise ConfigurationError("CIVICGATE_MIN_CONFIDENCE must be between 0 and 1")
        legacy_key = secrets.get_secret("CIVICGATE_MODEL_API_KEY")
        agent_key = secrets.get_secret("CIVICGATE_AGENT_API_KEY") or legacy_key
        if judge_provider == "anthropic":
            judge_key = secrets.get_secret("CIVICGATE_ANTHROPIC_JUDGE_API_KEY")
            if not judge_key:
                raise ConfigurationError(
                    "CIVICGATE_ANTHROPIC_JUDGE_API_KEY is required for anthropic"
                )
        elif judge_provider == "openai_compatible":
            judge_key = (
                secrets.get_secret("CIVICGATE_OPENAI_JUDGE_API_KEY")
                or secrets.get_secret("CIVICGATE_JUDGE_API_KEY")
                or legacy_key
            )
        else:
            judge_key = secrets.get_secret("CIVICGATE_JUDGE_API_KEY") or legacy_key
        if (
            agent_provider in {"openai_compatible", "lm_studio"}
            and agent_provider != "lm_studio"
            and not agent_key
        ):
            raise ConfigurationError(
                "CIVICGATE_AGENT_API_KEY is required for external agent providers"
            )
        if judge_provider in {"openai_compatible", "anthropic"} and not judge_key:
            raise ConfigurationError(
                "CIVICGATE_JUDGE_API_KEY is required for external judge providers"
            )
        return cls(
            agent_provider=agent_provider,
            judge_provider=judge_provider,
            agent_base_url=agent_base_url,
            judge_base_url=judge_base_url,
            agent_model=agent_model,
            judge_model=judge_model,
            judge_protocol=protocol,
            model_api_key=legacy_key,
            agent_api_key=agent_key,
            judge_api_key=judge_key,
            audit_path=configuration.get("CIVICGATE_AUDIT_PATH") or "audit/trace.jsonl",
            min_confidence=confidence,
            judge_profile_id=configuration.get("CIVICGATE_JUDGE_PROFILE") or "generic-openai",
        )
