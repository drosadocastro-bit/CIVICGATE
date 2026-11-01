"""Evaluation records only; these types cannot grant execution authority."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from civicgate.models.requests import Proposal


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlannerFixture(Record):
    mode: Literal["proposal", "error", "timeout", "malformed"] = "proposal"
    proposal: Proposal


class JudgeFixture(Record):
    mode: Literal["signal", "unavailable", "error", "timeout", "malformed"] = "signal"
    signal: dict[str, Any] = Field(default_factory=dict)


class BackendFixture(Record):
    mode: Literal[
        "normal", "malformed", "timeout", "output_injection", "audit_failure", "missing_provenance"
    ] = "normal"


class SemanticReference(Record):
    status: Literal["HISTORICAL_HUMAN_REFERENCE", "PROPOSED_PENDING_HUMAN_REVIEW", "NOT_EVALUABLE"]
    source_path: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_case_id: str | None = None
    classifications: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    provenance: str

    @model_validator(mode="after")
    def historical_binding_required(self) -> "SemanticReference":
        if self.status == "HISTORICAL_HUMAN_REFERENCE" and not all(
            (self.source_path, self.source_sha256, self.source_case_id)
        ):
            raise ValueError("Historical reference requires exact source bindings")
        return self


class Expectations(Record):
    status: Literal["ENGINEERING_SPEC_NOT_HUMAN_GOLDEN"]
    initial_decision: str | None = None
    final_decision: str | None = None
    adapter_dispatches: int = Field(ge=0, le=1)
    mcp_calls: int = Field(ge=0, le=1)
    transport_status: str | None = None
    verification_state: str | None = None
    orchestration_status: str | None = None


class Case(Record):
    case_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,100}$")
    split: Literal["development", "holdout", "adversarial"]
    family: str
    language: Literal["en", "es"]
    origin: Literal["KNOWN_REGRESSION", "NEW_AUTHOR_SPECIFICATION"]
    execution_mode: Literal["orchestrated", "direct_mcp"] = "orchestrated"
    user_request: str = Field(min_length=1, max_length=4000)
    planner: PlannerFixture
    judge: JudgeFixture
    backend: BackendFixture
    mcp_extra_fields: dict[str, Any] = Field(default_factory=dict)
    semantic_reference: SemanticReference
    expectations: Expectations
    permitted_evidence: list[str]

    @model_validator(mode="after")
    def no_claimed_new_golden_truth(self) -> "Case":
        if self.origin == "NEW_AUTHOR_SPECIFICATION" and (
            self.semantic_reference.status == "HISTORICAL_HUMAN_REFERENCE"
        ):
            raise ValueError("New author specifications are not historical human truth")
        if self.mcp_extra_fields and self.execution_mode != "direct_mcp":
            raise ValueError("Ingress attacks must be explicitly labeled direct MCP")
        if {"user_request", "query"}.intersection(self.mcp_extra_fields):
            raise ValueError("Ingress extras cannot overwrite original request or proposal")
        if any(
            k
            not in {"user_request", "original user_request", "proposed_tool", "proposed_arguments"}
            for k in self.permitted_evidence
        ):
            raise ValueError("Unsupported semantic evidence label")
        return self


class Artifact(Record):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Observation(Record):
    schema_version: Literal["civicgate.eval.observation.v1"] = "civicgate.eval.observation.v1"
    case_id: str
    repetition: int = Field(ge=1)
    split: str
    family: str
    configuration_id: str
    backend: Literal["ISOLATED_SYNTHETIC_FIXTURE"] = "ISOLATED_SYNTHETIC_FIXTURE"
    orchestration_status: str
    transport_status: str | None
    initial_decision: str | None
    final_decision: str | None
    binding_issued: bool | None
    pre_dispatch_verification: str | None
    adapter_dispatches: int | None = Field(ge=0)
    fixture_http_attempts: int | None = Field(ge=0)
    mcp_calls: int = Field(ge=0)
    synthetic_judge_calls: int | None = Field(ge=0)
    real_provider_attempts: Literal[0] = 0
    verification_state: str | None
    dispatch_state: str | None
    planner_tool: str | None
    planner_arguments_valid: bool | None
    planner_arguments_sha256: str | None
    request_sha256: str
    original_request_preserved: bool
    judge_classification: str | None
    judge_flags: list[str]
    judge_confidence: float | None
    judge_available: bool | None
    error_category: str | None
    latency_ms: dict[str, float | None]
    missing_measurements: dict[str, str]
    engineering_checks: dict[str, bool]
    semantic_scored: Literal[False] = False
    token_counts: None = None
    api_cost: None = None


class RunManifest(Record):
    schema_version: Literal["civicgate.eval.run.v1_1"] = "civicgate.eval.run.v1_1"
    run_id: str
    phase: Literal["FROZEN_INTENT", "FINAL_OBSERVATION"]
    created_utc: str
    mode: Literal["OFFLINE_SYNTHETIC_ONLY"] = "OFFLINE_SYNTHETIC_ONLY"
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_tree: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_worktree_dirty: bool
    harness_files: list[Artifact]
    dirty_overlay: list[Artifact]
    evidence_definitions: list[Artifact]
    datasets: list[Artifact]
    dataset_freeze_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_identities: dict[str, str]
    policy_identity: dict[str, Any]
    tool_schemas_sha256: str
    configuration: dict[str, Any]
    environment: dict[str, Any]
    observations: list[Artifact] = Field(default_factory=list)
    raw_artifacts: list[Artifact] = Field(default_factory=list)
    actual_counts: dict[str, int | None]
    intent_sha256: str | None = None
    failures: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    retries: Literal[0] = 0
    scored: Literal[False] = False


class MetricsRecord(Record):
    observation_count: int = Field(ge=0)
    engineering_assertions: dict[str, int]
    latency_by_split_family: dict[str, Any]
    repeat_consistency: dict[str, Any]
    policy_initial: dict[str, int]
    policy_final: dict[str, int]
    real_provider_attempts: Literal[0] = 0
    tokens: dict[str, Any]
    cost: dict[str, Any]
    semantic_accuracy: dict[str, Any]


class EvaluationReport(Record):
    schema_version: Literal["civicgate.eval.report.v1"] = "civicgate.eval.report.v1"
    run_id: str
    mode: Literal["OFFLINE_SYNTHETIC_ONLY"] = "OFFLINE_SYNTHETIC_ONLY"
    result: Literal["PASS", "FAIL"]
    observations: list[Observation]
    metrics: MetricsRecord
    judge_calibration: Literal["NOT_YET_MEASURED"] = "NOT_YET_MEASURED"
    independent_golden_references: Literal["PARTIAL"] = "PARTIAL"
    semantic_accuracy: None = None
    live_evaluation: Literal["NOT_AUTHORIZED_IN_THIS_SLICE"] = "NOT_AUTHORIZED_IN_THIS_SLICE"
    limitations: list[str]
