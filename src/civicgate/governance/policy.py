from dataclasses import dataclass

from civicgate.governance.authority import denied_reasons
from civicgate.models.governance import JudgeSignal, KSignal, PolicyResult
from civicgate.models.requests import TOOLS


@dataclass(frozen=True)
class PolicyFacts:
    tool: str
    text: str
    valid_input: bool = True
    bounded: bool = True
    public_source: bool = True
    provenance_available: bool = True
    adapter_available: bool = True
    capability: str = "PUBLIC_SPENDING_RESEARCH"
    review_reason: str | None = None
    semantic_required: bool = True


def evaluate(
    facts: PolicyFacts, judge: JudgeSignal, agent_k: KSignal, threshold: float = 0.85
) -> PolicyResult:
    """Sole authority issuer. Ordered checks make denials non-annulable."""
    reasons = denied_reasons(facts.text)
    if facts.tool not in TOOLS:
        reasons.append("UNKNOWN_TOOL")
    if facts.capability != "PUBLIC_SPENDING_RESEARCH":
        reasons.append("CAPABILITY_NOT_ALLOWED")
    if not facts.valid_input:
        reasons.append("INVALID_INPUT")
    if not facts.public_source:
        reasons.append("NONPUBLIC_SOURCE")
    if agent_k.containment:
        reasons.append("CONTAINMENT_REQUIRED")
    if reasons:
        return PolicyResult(decision="DENY", reasons=reasons)
    review = []
    if not facts.bounded:
        review.append("QUERY_TOO_BROAD")
    if not facts.provenance_available:
        review.append("PROVENANCE_UNAVAILABLE")
    if not facts.adapter_available:
        review.append("ADAPTER_UNAVAILABLE")
    if facts.review_reason:
        review.append(facts.review_reason)
    if facts.semantic_required:
        if not judge.available:
            review.append("SEMANTIC_FAILURE")
        elif judge.classification != "IN_SCOPE" or judge.confidence < threshold or judge.flags:
            review.append("SEMANTIC_REVIEW_REQUIRED")
    if any(s != "NONE" for s in agent_k.signals):
        review.append("AGENT_K_REVIEW_REQUIRED")
    return (
        PolicyResult(decision="REVIEW_REQUIRED", reasons=review)
        if review
        else PolicyResult(decision="PERMIT", reasons=["BOUNDED_PUBLIC_RESEARCH"])
    )
