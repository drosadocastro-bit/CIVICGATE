from typing import Any, Literal

from pydantic import Field

from civicgate.models.governance import Decision, Governance
from civicgate.models.provenance import Provenance
from civicgate.models.requests import StrictModel


class Error(StrictModel):
    code: str
    message: str
    retryable: bool = False


class Envelope(StrictModel):
    decision: Decision
    tool: str
    request_id: str
    status: Literal["OK", "BLOCKED", "ERROR", "CLARIFICATION_REQUIRED"]
    result: dict[str, Any] | None = None
    provenance: Provenance | None = None
    governance: Governance
    errors: list[Error] = Field(default_factory=list)
    tool_executed: bool = False
    clarification: str | None = None
