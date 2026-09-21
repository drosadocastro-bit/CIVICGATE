"""Provider configuration, not credential contents, chooses the judge route.

All credentials are synthetic; tests never consult DPAPI or the environment.
Compare secret selections as booleans so assertion output cannot print values.
"""

import httpx
import pytest

from civicgate import config
from civicgate.runtime_config import (
    ConfigurationError,
    InMemoryConfiguration,
    InMemorySecretProvider,
    RuntimeSettings,
)

OPENAI = "CIVICGATE_OPENAI_JUDGE_API_KEY"
ANTHROPIC = "CIVICGATE_ANTHROPIC_JUDGE_API_KEY"
GENERIC = "CIVICGATE_JUDGE_API_KEY"
LEGACY = "CIVICGATE_MODEL_API_KEY"
VALUES = {key: f"synthetic-slot-{i}" for i, key in enumerate((OPENAI, ANTHROPIC, GENERIC, LEGACY))}


def configuration(provider="anthropic", **overrides):
    anthropic = provider == "anthropic"
    return InMemoryConfiguration(
        {
            "CIVICGATE_JUDGE_PROVIDER": provider,
            "CIVICGATE_JUDGE_MODEL": "claude-sonnet-5" if anthropic else "gpt-5.6-luna",
            "CIVICGATE_JUDGE_BASE_URL": "https://api.anthropic.com"
            if anthropic
            else "https://api.openai.com/v1",
            "CIVICGATE_JUDGE_PROTOCOL": "anthropic_messages" if anthropic else "openai_compatible",
        }
        | overrides
    )


@pytest.mark.parametrize(
    ("provider", "names", "selected"),
    [
        ("openai_compatible", [OPENAI, GENERIC, LEGACY, ANTHROPIC], OPENAI),
        ("openai_compatible", [GENERIC, LEGACY, ANTHROPIC], GENERIC),
        ("openai_compatible", [LEGACY, ANTHROPIC], LEGACY),
        ("anthropic", [ANTHROPIC, OPENAI, GENERIC, LEGACY], ANTHROPIC),
        ("anthropic", [ANTHROPIC], ANTHROPIC),
    ],
)
def test_provider_specific_selection_and_openai_legacy_precedence(provider, names, selected):
    settings = RuntimeSettings.from_providers(
        configuration(provider), InMemorySecretProvider({name: VALUES[name] for name in names})
    )
    correct_slot = settings.judge_api_key == VALUES[selected]
    assert correct_slot
    wrong_provider_slot = ANTHROPIC if provider == "openai_compatible" else OPENAI
    cross_provider = settings.judge_api_key == VALUES[wrong_provider_slot]
    assert not cross_provider


@pytest.mark.parametrize("names", [[OPENAI], [GENERIC], [LEGACY], [OPENAI, GENERIC, LEGACY], []])
def test_anthropic_missing_specific_secret_fails_before_construction_or_transport(
    monkeypatch, names
):
    calls = {"construction": 0, "transport": 0}

    def reject_construction(*args, **kwargs):
        calls["construction"] += 1
        pytest.fail("Provider construction was reached with an invalid credential binding")

    async def reject_transport(*args, **kwargs):
        calls["transport"] += 1
        pytest.fail("Network boundary was reached")

    monkeypatch.setattr(config, "LiveJudgeProvider", reject_construction)
    monkeypatch.setattr(httpx.AsyncClient, "post", reject_transport)
    with pytest.raises(ConfigurationError, match="ANTHROPIC_JUDGE_API_KEY") as error:
        config.providers(configuration(), InMemorySecretProvider({n: VALUES[n] for n in names}))
    assert calls == {"construction": 0, "transport": 0}
    leaked = any(value in str(error.value) for value in VALUES.values())
    assert not leaked


def test_anthropic_secret_cannot_supply_an_openai_judge():
    with pytest.raises(ConfigurationError):
        RuntimeSettings.from_providers(
            configuration("openai_compatible"),
            InMemorySecretProvider({ANTHROPIC: VALUES[ANTHROPIC]}),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"CIVICGATE_JUDGE_PROTOCOL": "openai_compatible"},
        {"CIVICGATE_JUDGE_BASE_URL": "https://api.openai.com/v1"},
        {"CIVICGATE_JUDGE_BASE_URL": "https://api.anthropic.com/v1"},
        {"CIVICGATE_JUDGE_BASE_URL": "https://api.anthropic.com/v1/messages"},
        {"CIVICGATE_JUDGE_BASE_URL": "https://api.anthropic.com.evil.example"},
        {"CIVICGATE_JUDGE_BASE_URL": "http://api.anthropic.com"},
        {"CIVICGATE_JUDGE_BASE_URL": "https://api.anthropic.com?redirect=other"},
        {"CIVICGATE_JUDGE_BASE_URL": "", "CIVICGATE_MODEL_BASE_URL": "https://api.openai.com/v1"},
        {"CIVICGATE_PROVIDER": "openai_compatible"},
        {"CIVICGATE_JUDGE_MODEL": ""},
    ],
)
def test_malformed_anthropic_configuration_cannot_fall_back(monkeypatch, overrides):
    calls = []

    def reject(*args, **kwargs):
        calls.append("construction")
        pytest.fail("Malformed configuration reached provider construction")

    monkeypatch.setattr(config, "LiveJudgeProvider", reject)
    with pytest.raises(ConfigurationError):
        config.providers(configuration(**overrides), InMemorySecretProvider(VALUES))
    assert not calls


@pytest.mark.parametrize(
    "overrides",
    [
        {"CIVICGATE_JUDGE_PROTOCOL": "anthropic_messages"},
        {"CIVICGATE_JUDGE_BASE_URL": "https://api.anthropic.com"},
        {"CIVICGATE_JUDGE_PROVIDER": "unknown-provider"},
    ],
)
def test_openai_cross_protocol_origin_and_unknown_providers_rejected(overrides):
    with pytest.raises(ConfigurationError):
        RuntimeSettings.from_providers(
            configuration("openai_compatible", **overrides), InMemorySecretProvider(VALUES)
        )


@pytest.mark.parametrize("provider", ["anthropic", "openai_compatible"])
def test_valid_provider_construction_preserves_explicit_route_without_network(provider):
    cfg = configuration(provider)
    _, judge = config.providers(cfg, InMemorySecretProvider(VALUES))
    assert judge.provider_name == provider
    assert judge.protocol == cfg.get("CIVICGATE_JUDGE_PROTOCOL")
    assert judge.model == cfg.get("CIVICGATE_JUDGE_MODEL")
    assert judge.client.base_url == cfg.get("CIVICGATE_JUDGE_BASE_URL")
    correct_slot = judge.api_key == VALUES[ANTHROPIC if provider == "anthropic" else OPENAI]
    assert correct_slot


def test_legacy_openai_configuration_still_works_without_an_explicit_conflict():
    settings = RuntimeSettings.from_providers(
        InMemoryConfiguration(
            {
                "CIVICGATE_PROVIDER": "openai_compatible",
                "CIVICGATE_MODEL_BASE_URL": "https://api.openai.com/v1",
                "CIVICGATE_AGENT_MODEL": "synthetic-agent",
                "CIVICGATE_JUDGE_MODEL": "gpt-5.6-luna",
            }
        ),
        InMemorySecretProvider({LEGACY: VALUES[LEGACY]}),
    )
    assert settings.judge_provider == "openai_compatible"
    correct_slot = settings.judge_api_key == VALUES[LEGACY]
    assert correct_slot


@pytest.mark.parametrize(
    ("names", "selected"),
    [
        ([OPENAI, GENERIC, LEGACY], OPENAI),
        ([GENERIC, LEGACY], GENERIC),
        ([LEGACY], LEGACY),
    ],
)
def test_frozen_j2_runner_uses_shared_routing_without_retargeting(names, selected):
    from scripts import run_live_judge_benchmark as benchmark

    settings = benchmark._judge_settings(InMemorySecretProvider({n: VALUES[n] for n in names}))
    correct_slot = settings.judge_api_key == VALUES[selected]
    assert correct_slot
    assert settings.judge_model == "gpt-5.6-luna"
    assert settings.judge_base_url == "https://api.openai.com/v1"
    assert settings.judge_provider == settings.judge_protocol == "openai_compatible"
