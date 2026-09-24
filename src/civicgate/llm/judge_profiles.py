"""Declared inference profiles; model names never select payload parameters."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class OpenAIJudgeProfile:
    profile_id: str
    model: str | None
    base_url: str | None
    token_limit_field: str
    token_limit: int = 512
    reasoning_effort: str | None = None
    include_temperature: bool = False
    include_top_p: bool = False

    def payload(self, model: str, prompt: str, content: str) -> dict[str, Any]:
        if self.model is not None and model != self.model:
            raise ValueError("JUDGE_PROFILE_MODEL_MISMATCH")
        result: dict[str, Any] = {
            "model": model,
            self.token_limit_field: self.token_limit,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content},
            ],
        }
        if self.reasoning_effort is not None:
            result["reasoning_effort"] = self.reasoning_effort
        if self.include_temperature:
            result["temperature"] = 0
        if self.include_top_p:
            result["top_p"] = 1
        return result


OPENAI_JUDGE_PROFILES = MappingProxyType(
    {
        "generic-openai": OpenAIJudgeProfile(
            "generic-openai",
            None,
            None,
            "max_tokens",
            include_temperature=True,
            include_top_p=True,
        ),
        "j2-luna": OpenAIJudgeProfile(
            "j2-luna", "gpt-5.6-luna", "https://api.openai.com/v1", "max_completion_tokens"
        ),
        "j4-gpt6-luna": OpenAIJudgeProfile(
            "j4-gpt6-luna",
            "gpt-6-luna",
            "https://api.openai.com/v1",
            "max_completion_tokens",
            reasoning_effort="medium",
        ),
    }
)


def select_openai_profile(profile_id: str, *, benchmark: bool = False) -> OpenAIJudgeProfile:
    if profile_id not in OPENAI_JUDGE_PROFILES or (benchmark and profile_id == "generic-openai"):
        raise ValueError("UNKNOWN_BENCHMARK_PROFILE" if benchmark else "UNKNOWN_JUDGE_PROFILE")
    return OPENAI_JUDGE_PROFILES[profile_id]
