"""Versioned Chat profile binding over the existing SQLite V2 attempt/lease store."""

from __future__ import annotations

from pathlib import Path

from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy

from .attempt_budget_v3 import AttemptReservation, BudgetError, LiveAttemptBudget
from .common import canonical, sha
from .transport_profile_v1 import ENDPOINTS, MODELS, ChatProfile, LiveAdmission


class ChatCustody(LiveAttemptBudget):
    def __init__(self, path: Path, run_id: str) -> None:
        super().__init__(path, run_id)
        with self._connection() as db:
            row = db.execute(
                "SELECT profile_json,profile_sha256,mode FROM chat_profile WHERE id=1"
            ).fetchone()
        if row is None or sha(row[0].encode()) != row[1]:
            raise BudgetError("CHAT_PROFILE_CUSTODY_MISMATCH")
        self.profile = ChatProfile.model_validate_json(row[0])
        self.mode = row[2]
        if (
            run_id != self.profile.experiment
            or path.resolve() != Path(self.profile.custody_root) / "custody.sqlite"
            or self.mode not in {"OFFLINE_PROVIDER_FIXTURES", "LIVE"}
        ):
            raise BudgetError("CHAT_EXPERIMENT_BINDING_MISMATCH")

    @classmethod
    def create_profile(
        cls, profile: ChatProfile, *, admission: LiveAdmission | None = None
    ) -> ChatCustody:
        if admission is not None:
            admission.check()
            if admission.profile != profile:
                raise BudgetError("PROFILE_APPROVAL_MISMATCH")
        root = Path(profile.custody_root)
        root.mkdir(exist_ok=False)
        # Existing units are request-count accounting only, never money. LIVE
        # authorization is separately checked; no claim of an enforced USD cap.
        base = LiveAttemptBudget.create(
            root / "custody.sqlite",
            profile.experiment,
            role_caps={
                "planner": profile.planner_attempt_limit,
                "judge": profile.judge_attempt_limit,
            },
            max_observations=profile.observation_limit,
            liability_policy=SyntheticLiabilityPolicy(
                profile.planner_attempt_limit + profile.judge_attempt_limit
            ),
        )
        with base._transaction() as db:
            db.execute(
                "CREATE TABLE chat_profile (id INTEGER PRIMARY KEY CHECK(id=1),profile_json TEXT NOT NULL,profile_sha256 TEXT NOT NULL,mode TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO chat_profile VALUES(1,?,?,?)",
                (
                    canonical(profile.model_dump(mode="json")).decode(),
                    profile.digest,
                    "LIVE" if admission is not None else "OFFLINE_PROVIDER_FIXTURES",
                ),
            )
        return cls(root / "custody.sqlite", profile.experiment)

    def verify_profile(self) -> None:
        current = ChatCustody(
            Path(self.profile.custody_root) / "custody.sqlite", self.profile.experiment
        )
        if current.profile != self.profile or current.mode != self.mode:
            raise BudgetError("CHAT_PROFILE_CHANGED")

    def reserve(
        self,
        observation_id: str,
        role: str,
        requested_model: str,
        request_sha256: str,
        prompt_sha256: str,
        schema_sha256: str,
        retry_count: int = 0,
        retry_reason: str | None = None,
    ) -> AttemptReservation:
        self.verify_profile()
        expected = MODELS["judge"] if role == "judge" else MODELS[self.profile.planner]
        if (
            role not in {"planner", "judge"}
            or requested_model != expected
            or retry_count != 0
            or retry_reason is not None
        ):
            raise BudgetError("CHAT_MODEL_OR_ROLE_MISMATCH")
        return super().reserve(
            observation_id, role, requested_model, request_sha256, prompt_sha256, schema_sha256
        )

    def bind_request_context(
        self,
        observation_id: str,
        role: str,
        request_sha256: str,
        schema_sha256: str,
        logical_origin: str,
        wire_fixture_origin: str,
        effective_invocation_sha256: str | None = None,
    ) -> None:
        kwargs = dict(
            observation_id=observation_id,
            role=role,
            request_sha256=request_sha256,
            schema_sha256=schema_sha256,
            logical_origin=logical_origin,
            wire_fixture_origin=wire_fixture_origin,
            effective_invocation_sha256=effective_invocation_sha256,
        )
        self.verify_profile()
        provider = "judge" if kwargs["role"] == "judge" else self.profile.planner
        origin = ENDPOINTS[provider].split("/v1/")[0]
        expected_wire = origin if self.mode == "LIVE" else "http://127.0.0.1:1"
        if kwargs["logical_origin"] != origin or kwargs["wire_fixture_origin"] != expected_wire:
            raise BudgetError("CHAT_FIXED_ORIGIN_MISMATCH")
        super().bind_request_context(
            observation_id,
            role,
            request_sha256,
            schema_sha256,
            logical_origin,
            wire_fixture_origin,
            effective_invocation_sha256,
        )
