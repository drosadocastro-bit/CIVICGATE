import re
import unicodedata


def denied_reasons(text: str) -> list[str]:
    """Conservative tripwires, not a complete natural-language security classifier."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    checks = {
        "DENIED_AUTHORITY": r"blacklist|debar|barred|fraud|eligib|approve.{0,30}(award|contract)|deny.{0,30}award|procurement decision|(?:execute|send).{0,20}payment|modify.{0,30}(government|data)|impersonat|lista negra|inhabilit|fraude|aprobar.{0,20}contrato|exclude.{0,30}(vendor|supplier)|exclude.{0,30}future",
        "PRIVATE_DATA": r"private|internal.{0,20}(system|record|government)|tax record|credential|password|secret|datos privados|credencial",
        "BYPASS_REQUEST": r"bypass|hidden tool|unapproved tool|another system|alternate system|ignore.{0,30}(policy|guardrail)|disable.{0,20}(audit|policy)|herramienta oculta",
    }
    return [reason for reason, pattern in checks.items() if re.search(pattern, normalized)]
