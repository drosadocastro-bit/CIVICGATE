from typing import Literal

from pydantic import Field

from civicgate.models.requests import StrictModel

Decision = Literal["PERMIT", "DENY", "REVIEW_REQUIRED"]
Classification = Literal[
    "IN_SCOPE",
    "AMBIGUOUS",
    "OUT_OF_SCOPE",
    "CONSEQUENTIAL_INTERPRETATION",
    "POSSIBLE_AUTHORITY_OVERREACH",
    "INSUFFICIENT_INFORMATION",
]
Signal = Literal[
    "NONE",
    "AUTHORITY_OVERREACH",
    "OUT_OF_SCOPE_DATA",
    "REPEATED_DENIAL",
    "TOOL_SCOPE_VIOLATION",
    "PROVENANCE_RISK",
    "AMBIGUOUS_TARGET",
    "CONTAINMENT_RECOMMENDED",
]


class JudgeSignal(StrictModel):
    classification: Classification = "INSUFFICIENT_INFORMATION"
    confidence: float = Field(default=0, ge=0, le=1)
    rationale: str = Field(default="Semantic assessment unavailable", max_length=500)
    flags: list[Signal] = Field(default_factory=list, max_length=8)
    available: bool = False
    provider: str = Field(default="unavailable", max_length=100)


class KSignal(StrictModel):
    signals: list[Signal] = Field(default=["NONE"], max_length=8)
    containment: bool = False


class PolicyResult(StrictModel):
    decision: Decision
    reasons: list[str]


class Governance(StrictModel):
    judge_signal: JudgeSignal
    agent_k_signal: KSignal
    policy_reasons: list[str]
    authority_source: Literal["DETERMINISTIC_POLICY_GATE"] = "DETERMINISTIC_POLICY_GATE"
    policy_version: Literal["civicgate-mvp-1"] = "civicgate-mvp-1"
