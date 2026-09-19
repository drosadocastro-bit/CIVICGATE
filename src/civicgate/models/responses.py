from typing import Any, Literal

from pydantic import Field

from civicgate.models.governance import Decision, Governance
from civicgate.models.provenance import Provenance
from civicgate.models.requests import StrictModel


class Error(StrictModel):
    code: str
    message: str
    retryable: bool = False


DispatchState = Literal[
    "NOT_DISPATCHED",
    "DISPATCH_ATTEMPTED",
    "REQUEST_CONFIRMED",
    "DISPATCH_UNKNOWN",
]
ResponseState = Literal["NO_RESPONSE", "RESPONSE_RECEIVED", "TRANSPORT_ERROR"]
VerificationState = Literal["UNVERIFIED", "RESULT_VERIFIED", "RESULT_UNKNOWN", "FAILED_VALIDATION"]
ValidationLane = Literal["NONE", "LANE_A_RESOLVABILITY", "LANE_B_EXECUTION"]
ValidationReason = Literal[
    "NONE",
    "MALFORMED_RESPONSE",
    "PROVENANCE_UNAVAILABLE",
    "ADAPTER_SCHEMA_OR_PROVENANCE_INVALID",
]
NextAction = Literal[
    "NONE",
    "RETRY_ALLOWED",
    "RETRY_BLOCKED",
    "HUMAN_REVIEW_REQUIRED",
    "STOP",
]
RetryClass = Literal["SAFE", "CONDITIONALLY_SAFE", "UNSAFE", "UNKNOWN"]


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
    dispatch_state: DispatchState = "NOT_DISPATCHED"
    response_state: ResponseState = "NO_RESPONSE"
    verification_state: VerificationState = "UNVERIFIED"
    validation_lane: ValidationLane = "NONE"
    validation_reason: ValidationReason = "NONE"
    next_action: NextAction = "NONE"
    attempt_count: int = Field(default=0, ge=0)
    retry_class: RetryClass = "UNKNOWN"
    attempt_metadata_available: bool = False
