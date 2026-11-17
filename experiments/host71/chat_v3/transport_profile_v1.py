"""Independent proposed Chat identities. This file grants no LIVE authority."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import HERE, canonical, load, sha

ENDPOINTS = {
    "granite": "http://127.0.0.1:1234/v1/chat/completions",
    "nemotron": "https://integrate.api.nvidia.com/v1/chat/completions",
    "judge": "https://api.openai.com/v1/chat/completions",
}
MODELS = {
    "granite": "granite-4.2-8b",
    "nemotron": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "judge": "gpt-5.6-luna",
}


class ChatProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal["CHAT_COMPOSITION_03_TRANSPORT_V1"] = "CHAT_COMPOSITION_03_TRANSPORT_V1"
    experiment: str = Field(pattern=r"^CHAT03_[A-Z0-9_]{1,90}$")
    planner: Literal["granite", "nemotron"]
    custody_root: str
    catalog_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    planner_attempt_limit: int = Field(ge=1, le=6)
    judge_attempt_limit: int = Field(ge=1, le=5)
    observation_limit: int = Field(ge=1, le=6)
    smoke_read_only: bool = False
    allowed_request_sha256: str | None = None
    output_tokens: Literal[512] = 512
    request_bytes: Literal[32768] = 32768
    response_bytes: Literal[65536] = 65536
    retries: Literal[0] = 0
    public_api_attempt_limit: Literal[0, 1] = 0
    negative_case: Literal["NONE", "REVIEW", "DENY"] = "NONE"
    backend: Literal["SYNTHETIC_ONLY", "USASPENDING_FIXED_READ_V11", "NO_EXECUTION"] = (
        "SYNTHETIC_ONLY"
    )
    monetary_cap: Literal["NOT_TRANSACTIONALLY_ENFORCED"] = "NOT_TRANSACTIONALLY_ENFORCED"

    @model_validator(mode="after")
    def paths(self) -> ChatProfile:
        if self.backend == "USASPENDING_FIXED_READ_V11" and (
            not self.smoke_read_only or self.public_api_attempt_limit != 1
        ):
            raise ValueError("PUBLIC_SINGLE_READ_PROFILE_REQUIRED")
        if self.backend != "USASPENDING_FIXED_READ_V11" and self.public_api_attempt_limit != 0:
            raise ValueError("PUBLIC_API_NOT_ADMITTED")
        if self.backend == "NO_EXECUTION":
            if self.negative_case not in {"REVIEW", "DENY"} or not self.smoke_read_only:
                raise ValueError("NEGATIVE_PROFILE_REQUIRED")
        elif self.negative_case != "NONE":
            raise ValueError("NEGATIVE_PROFILE_BACKEND_REQUIRED")
        if self.smoke_read_only:
            question = self.fixed_question
            if (
                self.planner != "nemotron"
                or self.planner_attempt_limit != 1
                or self.judge_attempt_limit != 1
                or self.observation_limit != 1
                or self.allowed_request_sha256 != sha(question.encode())
            ):
                raise ValueError("SINGLE_READ_PROFILE_REQUIRED")
        elif self.allowed_request_sha256 is not None:
            raise ValueError("UNBOUND_REQUEST_SCOPE")
        root = Path(self.custody_root)
        if not root.is_absolute() or str(root.resolve()) != self.custody_root:
            raise ValueError("CANONICAL_EXCLUSIVE_ROOT_REQUIRED")
        if any(p.is_symlink() for p in (root, *root.parents)) or root.is_relative_to(HERE):
            raise ValueError("PRIVATE_CUSTODY_REQUIRED")
        return self

    @property
    def fixed_question(self) -> str:
        from .catalog import DENY, PUBLIC_READ, READ, REVIEW

        if self.backend == "NO_EXECUTION":
            return {"REVIEW": REVIEW, "DENY": DENY}[self.negative_case]
        return PUBLIC_READ if self.backend == "USASPENDING_FIXED_READ_V11" else READ

    @property
    def digest(self) -> str:
        return sha(canonical(self.model_dump(mode="json")))


def verify_candidate(expected_inventory: str, expected_catalog: str) -> None:
    inventory = HERE / "chat-source-inventory-v1.json"
    if sha(inventory.read_bytes()) != expected_inventory:
        raise ValueError("UNAPPROVED_SOURCE_INVENTORY")
    entries = load(inventory)["files"]
    for rel, identity in entries.items():
        path = HERE / rel
        if not path.resolve().is_relative_to(HERE) or any(
            p.is_symlink() for p in (path, *path.parents)
        ):
            raise ValueError("SOURCE_PATH_REJECTED")
        if sha(path.read_bytes()) != identity["sha256"]:
            raise ValueError("SOURCE_IDENTITY_MISMATCH")
    if sha((HERE / "guided-catalog-v1.json").read_bytes()) != expected_catalog:
        raise ValueError("CATALOG_IDENTITY_MISMATCH")


class HostApproval(BaseModel):
    """Separately controlled host document; never accepted as browser input."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    decision: Literal["HUMAN_APPROVED_CHAT03_LIVE"]
    profile_sha256: str
    source_inventory_sha256: str
    experiment: str
    expires_unix: float
    provider_account_access_verified: bool
    cloud_billing_risk_explicitly_accepted: bool
    runtime_identity_checked: bool


class LiveAdmission:
    def __init__(self, profile: ChatProfile, trusted_anchor: Path) -> None:
        # Location is chosen by host entrypoint, never by HTTP request data.
        self.profile, self.anchor = profile, trusted_anchor.resolve()
        if self.anchor.is_relative_to(HERE) or self.anchor.is_relative_to(
            Path(profile.custody_root)
        ):
            raise ValueError("INDEPENDENT_HOST_ANCHOR_REQUIRED")
        self.anchor_sha = sha(trusted_anchor.read_bytes())
        self.check()

    def check(self) -> None:
        import time

        if sha(self.anchor.read_bytes()) != self.anchor_sha:
            raise ValueError("HOST_APPROVAL_CHANGED")
        approved = HostApproval.model_validate(load(self.anchor))
        if (
            approved.profile_sha256 != self.profile.digest
            or approved.source_inventory_sha256 != self.profile.source_inventory_sha256
            or approved.experiment != self.profile.experiment
            or time.time() >= approved.expires_unix
            or not approved.provider_account_access_verified
            or not approved.cloud_billing_risk_explicitly_accepted
            or not approved.runtime_identity_checked
        ):
            raise ValueError("LIVE_APPROVAL_MISSING_OR_MISMATCHED")
        verify_candidate(self.profile.source_inventory_sha256, self.profile.catalog_sha256)
