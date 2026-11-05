"""Versioned synthetic review-state contract; no legacy MCP schema is changed."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

DATASET_SHA256 = "7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d"
WRITE_TOOL = "update_synthetic_award_review"
READ_TOOL = "get_synthetic_award_review_v1"
WRITE_SCOPE = "SYNTHETIC_REVIEW_STATE_WRITE_V1"
READ_SCOPE = "SYNTHETIC_REVIEW_STATE_READ_V1"
CONTRACT_VERSION = "WRITE01_SYNTHETIC_REVIEW_V1"

AwardId = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^SYN-[A-Z0-9-]+$")
]
IdempotencyKey = Annotated[
    str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
]


class ReadQueryV1(BaseModel):
    """Explicit synthetic mutable-overlay read; not a legacy award response."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
    award_id: AwardId


class WriteQueryV1(ReadQueryV1):
    expected_version: int = Field(ge=0, le=2**31 - 1)
    proposed_status: str = Field(min_length=1, max_length=40)
    reviewer_note: str = Field(min_length=1, max_length=1000)
    idempotency_key: IdempotencyKey

    @field_validator("reviewer_note")
    @classmethod
    def bounded_inert_note(cls, value: str) -> str:
        # Exact content is retained, never interpreted as instructions or normalized.
        if len(value.encode("utf-8")) > 4000 or any(
            unicodedata.category(character) in {"Cc", "Cs"} for character in value
        ):
            raise ValueError("Reviewer note has prohibited control characters or byte length")
        return value


REGISTRY: Mapping[str, type[BaseModel]] = MappingProxyType(
    {WRITE_TOOL: WriteQueryV1, READ_TOOL: ReadQueryV1}
)
SCOPES = MappingProxyType({WRITE_TOOL: WRITE_SCOPE, READ_TOOL: READ_SCOPE})


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: Any) -> str:
    """Canonical-document digest, not proof of host or human identity."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_query(tool: str, raw: dict[str, Any]) -> dict[str, Any]:
    if type(raw) is not dict or any(type(key) is not str for key in raw):
        raise ValueError("WRITE01_QUERY_MAPPING_REQUIRED")
    if type(tool) is not str or tool not in REGISTRY:
        raise ValueError("WRITE01_TOOL_NOT_REGISTERED")
    canonical_json(raw)
    return REGISTRY[tool].model_validate(raw).model_dump(mode="json")
