import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from civicgate.models.requests import StrictModel


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class Provenance(StrictModel):
    source_system: Literal["USAspending", "CIVICGATE_TEST_FIXTURE"]
    source_type: Literal["PUBLIC_GOVERNMENT_API", "SYNTHETIC_TEST_FIXTURE"]
    retrieved_at: AwareDatetime
    query_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    endpoint: str = Field(min_length=1, max_length=400)
    records_returned: int = Field(ge=0, le=100)
    truncated: bool


def utcnow() -> datetime:
    return datetime.now(UTC)
