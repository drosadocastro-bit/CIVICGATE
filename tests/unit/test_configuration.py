import os

import pytest

from civicgate.runtime_config import (
    ConfigurationError,
    EnvironmentConfiguration,
    EnvironmentSecretProvider,
    InMemoryConfiguration,
    InMemorySecretProvider,
    RuntimeSettings,
)


def test_environment_provider_does_not_load_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICGATE_PROVIDER", raising=False)
    assert (
        RuntimeSettings.from_providers(
            EnvironmentConfiguration(), EnvironmentSecretProvider()
        ).agent_provider
        == "unavailable"
    )


def test_live_provider_requires_explicit_configuration() -> None:
    with pytest.raises(ConfigurationError, match="AGENT_MODEL"):
        RuntimeSettings.from_providers(
            InMemoryConfiguration({"CIVICGATE_AGENT_PROVIDER": "lm_studio"}),
            InMemorySecretProvider(),
        )


def test_in_memory_provider_carries_secret_without_environment() -> None:
    settings = RuntimeSettings.from_providers(
        InMemoryConfiguration(
            {
                "CIVICGATE_AGENT_PROVIDER": "lm_studio",
                "CIVICGATE_AGENT_BASE_URL": "http://127.0.0.1:1234/v1",
                "CIVICGATE_AGENT_MODEL": "granite-3.1-8b-q3",
                "CIVICGATE_JUDGE_PROVIDER": "unavailable",
            }
        ),
        InMemorySecretProvider({"CIVICGATE_MODEL_API_KEY": "test-only"}),
    )
    assert settings.agent_model == "granite-3.1-8b-q3"
    assert settings.model_api_key == "test-only"


def test_legacy_mock_is_explicit_and_judge_is_mock() -> None:
    settings = RuntimeSettings.from_providers(
        InMemoryConfiguration({"CIVICGATE_PROVIDER": "mock"}), InMemorySecretProvider()
    )
    assert settings.agent_provider == settings.judge_provider == "mock"


@pytest.mark.skipif(os.name == "nt", reason="non-Windows contract test")
def test_dpapi_edge_refuses_non_windows() -> None:
    from civicgate.windows_dpapi import WindowsDPAPIStore

    with pytest.raises(RuntimeError):
        WindowsDPAPIStore(__import__("pathlib").Path("C:/tmp/civicgate.dpapi"))
