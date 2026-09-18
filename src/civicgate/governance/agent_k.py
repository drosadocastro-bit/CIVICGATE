from civicgate.governance.authority import denied_reasons
from civicgate.models.governance import JudgeSignal, KSignal, Signal


def inspect(text: str, judge: JudgeSignal, denials: int, known_tool: bool) -> KSignal:
    """Report behavioral signals only. ``denials`` counts prior tripwire denials in this process."""
    signals: list[Signal] = []
    reasons = denied_reasons(text)
    if "DENIED_AUTHORITY" in reasons:
        signals.append("AUTHORITY_OVERREACH")
    if "PRIVATE_DATA" in reasons:
        signals.append("OUT_OF_SCOPE_DATA")
    if not known_tool or "BYPASS_REQUEST" in reasons:
        signals.append("TOOL_SCOPE_VIOLATION")
    if denials >= 2:
        signals.append("REPEATED_DENIAL")
    if judge.classification == "AMBIGUOUS":
        signals.append("AMBIGUOUS_TARGET")
    containment = denials >= 2 or bool(reasons) or not known_tool
    if containment:
        signals.append("CONTAINMENT_RECOMMENDED")
    return KSignal(signals=signals or ["NONE"], containment=containment)
