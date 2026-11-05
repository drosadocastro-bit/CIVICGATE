"""Narrow experimental deterministic WRITE authority, selected by the local host.

Reuses frozen CIVICGATE envelope/binding types, not the READ policy's authority.
No legacy module is patched. Constructor inputs are trusted composition, never
MCP fields. This is not protection from arbitrary Python or a compromised host.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from threading import Lock
from time import monotonic
from typing import Any

from civicgate.governance.authority import denied_reasons
from civicgate.governance.execution import (
    AuthorityEnvelope,
    ExecutionBinding,
    ExecutionBoundaryError,
    PolicyEvaluation,
)
from civicgate.models.governance import JudgeSignal, PolicyResult
from evals.write01.contract_v1 import (
    CONTRACT_VERSION,
    DATASET_SHA256,
    REGISTRY,
    SCOPES,
    WRITE_TOOL,
    canonical_json,
    digest,
    normalize_query,
)

POLICY_VERSION = "civicgate-write01-synthetic-v1"
MAX_APPROVALS = 128


def _text(value: object, maximum: int = 200) -> bool:
    return type(value) is str and 0 < len(value) <= maximum and all(ord(c) >= 32 for c in value)


@dataclass(frozen=True, slots=True)
class HostApproval:
    """Host-supplied exact approval, not an MCP credential or human signature.

    The trusted constructor supplies these objects before discovery. Equal JSON
    sent by a client cannot register a new approval with an existing authority.
    """

    original_request: str
    tool: str
    arguments_json: str
    owner_id: str
    store_id: str
    reference: str
    approved: bool
    dataset_sha256: str = DATASET_SHA256

    def __post_init__(self) -> None:
        if (
            not _text(self.original_request, 4000)
            or not _text(self.owner_id)
            or not _text(self.store_id, 4000)
            or not _text(self.reference)
            or type(self.approved) is not bool
            or self.dataset_sha256 != DATASET_SHA256
            or type(self.arguments_json) is not str
            or len(self.arguments_json.encode("utf-8")) > 16_000
        ):
            raise ValueError("WRITE01_HOST_APPROVAL_INVALID")
        query = normalize_query(self.tool, json.loads(self.arguments_json))
        if canonical_json(query) != self.arguments_json:
            raise ValueError("WRITE01_APPROVAL_NOT_CANONICAL")

    @classmethod
    def for_operation(
        cls,
        original_request: str,
        tool: str,
        query: dict[str, Any],
        owner_id: str,
        store_id: str,
        reference: str,
        approved: bool,
    ) -> HostApproval:
        return cls(
            original_request,
            tool,
            canonical_json(normalize_query(tool, query)),
            owner_id,
            store_id,
            reference,
            approved,
        )


@dataclass(frozen=True, slots=True)
class StateFacts:
    """State read by the host/store, rechecked atomically during persistence."""

    award_exists: bool
    status: str
    version: int

    def __post_init__(self) -> None:
        if (
            type(self.award_exists) is not bool
            or type(self.status) is not str
            or type(self.version) is not int
            or not 0 <= self.version <= 2**31 - 1
        ):
            raise ValueError("WRITE01_STATE_FACTS_INVALID")


@dataclass(frozen=True, slots=True)
class _Issued:
    envelope: AuthorityEnvelope
    serialized: str
    original_request: str
    context_json: str
    approval_reference: str
    issued_at: float
    expires_at: float


class WriteAuthority:
    """One trusted owner, exact constructor approvals and single-use bindings.

    The public MCP interface receives no approval, policy, envelope or owner
    selector. Approvals are spent at issuance and never automatically refunded.
    State/version checks here do not replace the transaction's atomic recheck.
    """

    def __init__(
        self,
        owner_id: str,
        store_id: str,
        approvals: tuple[HostApproval, ...] = (),
        *,
        clock: Callable[[], float] = monotonic,
        max_age_seconds: float = 30,
    ) -> None:
        if (
            not _text(owner_id)
            or not _text(store_id, 4000)
            or type(approvals) is not tuple
            or len(approvals) > MAX_APPROVALS
            or type(max_age_seconds) not in {int, float}
            or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0
        ):
            raise ValueError("WRITE01_AUTHORITY_CONFIGURATION_INVALID")
        for approval in approvals:
            if type(approval) is not HostApproval:
                raise ValueError("WRITE01_HOST_APPROVAL_REQUIRED")
            approval.__post_init__()
            if approval.owner_id != owner_id or approval.store_id != store_id:
                raise ValueError("WRITE01_APPROVAL_OWNER_MISMATCH")
        if len({approval.reference for approval in approvals}) != len(approvals):
            raise ValueError("WRITE01_APPROVAL_REFERENCE_REUSED")
        self._owner = owner_id
        self._store = store_id
        self._approvals = approvals
        self._approval_snapshots = {id(a): canonical_json(asdict(a)) for a in approvals}
        self._spent: set[int] = set()
        self._request_ids: set[str] = set()
        self._schemas = {
            tool: digest(model.model_json_schema()) for tool, model in REGISTRY.items()
        }
        self._clock = clock
        self._max_age = max_age_seconds
        self._issued: dict[int, _Issued] = {}
        self._lock = Lock()

    def _now(self) -> float:
        try:
            now = self._clock()
        except Exception as exc:
            raise ExecutionBoundaryError("WRITE01_TIME_INVALID") from exc
        if type(now) not in {int, float} or not math.isfinite(now):
            raise ExecutionBoundaryError("WRITE01_TIME_INVALID")
        return now

    def _context(self) -> str:
        return canonical_json(
            {
                "owner": self._owner,
                "store": self._store,
                "dataset": DATASET_SHA256,
                "contract": CONTRACT_VERSION,
            }
        )

    def _query(self, tool: str, query: dict[str, Any]) -> tuple[str, str]:
        normalized = normalize_query(tool, query)
        schema = digest(REGISTRY[tool].model_json_schema())
        if schema != self._schemas[tool]:
            raise ExecutionBoundaryError("WRITE01_SCHEMA_DRIFT")
        return canonical_json(normalized), schema

    def _approval(self, request: str, tool: str, arguments: str) -> HostApproval | None:
        for approval in self._approvals:
            if canonical_json(asdict(approval)) != self._approval_snapshots[id(approval)]:
                raise ExecutionBoundaryError("WRITE01_APPROVAL_DRIFT")
            if (
                approval.approved
                and id(approval) not in self._spent
                and approval.original_request == request
                and approval.tool == tool
                and approval.arguments_json == arguments
            ):
                return approval
        return None

    def evaluate(
        self,
        request_id: str,
        original_request: str,
        tool: str,
        query: dict[str, Any],
        state: StateFacts,
        judge: JudgeSignal | None = None,
    ) -> PolicyEvaluation:
        with self._lock:
            return self._evaluate(request_id, original_request, tool, query, state, judge)

    def _evaluate(
        self,
        request_id: str,
        original_request: str,
        tool: str,
        query: dict[str, Any],
        state: StateFacts,
        judge: JudgeSignal | None,
    ) -> PolicyEvaluation:
        if not _text(request_id) or not _text(original_request, 4000):
            raise ExecutionBoundaryError("WRITE01_REQUEST_INVALID")
        if request_id in self._request_ids:
            raise ExecutionBoundaryError("WRITE01_REQUEST_REUSED")
        if type(state) is not StateFacts:
            raise ExecutionBoundaryError("WRITE01_STATE_FACTS_REQUIRED")
        state.__post_init__()
        denial = denied_reasons(original_request)
        arguments = ""
        schema = ""
        if type(tool) is not str or tool not in REGISTRY:
            denial.append("WRITE01_UNKNOWN_TOOL")
        else:
            try:
                arguments, schema = self._query(tool, query)
            except (ValueError, TypeError, OverflowError):
                denial.append("WRITE01_INVALID_ARGUMENTS")
        if not state.award_exists:
            denial.append("WRITE01_UNKNOWN_SYNTHETIC_AWARD")
        if state.status not in {"UNREVIEWED", "PENDING_REVIEW"}:
            denial.append("WRITE01_STATE_INVALID")
        if tool == WRITE_TOOL and arguments:
            effective = json.loads(arguments)
            if effective["proposed_status"] != "PENDING_REVIEW" or state.status != "UNREVIEWED":
                denial.append("WRITE01_TRANSITION_NOT_ALLOWED")
            if effective["expected_version"] != state.version:
                denial.append("WRITE01_EXPECTED_VERSION_MISMATCH")
        if denial:
            return PolicyEvaluation(PolicyResult(decision="DENY", reasons=denial), None)
        approval = self._approval(original_request, tool, arguments)
        review: list[str] = []
        if approval is None:
            review.append("WRITE01_EXACT_HOST_APPROVAL_REQUIRED")
        if judge is not None:
            if type(judge) is not JudgeSignal:
                raise ExecutionBoundaryError("WRITE01_JUDGE_SIGNAL_INVALID")
            if (
                not judge.available
                or judge.classification != "IN_SCOPE"
                or any(flag != "NONE" for flag in judge.flags)
            ):
                review.append("WRITE01_ADVISORY_REVIEW_REQUIRED")
        if review:
            return PolicyEvaluation(PolicyResult(decision="REVIEW_REQUIRED", reasons=review), None)
        if approval is None:
            raise ExecutionBoundaryError("WRITE01_APPROVAL_REQUIRED")
        if len(self._request_ids) >= MAX_APPROVALS:
            raise ExecutionBoundaryError("WRITE01_ISSUANCE_CAPACITY_EXCEEDED")
        now = self._now()
        expires = now + self._max_age
        if not math.isfinite(expires):
            raise ExecutionBoundaryError("WRITE01_TIME_INVALID")
        context = self._context()
        policy = PolicyResult(decision="PERMIT", reasons=["WRITE01_EXACT_HOST_APPROVED_SCOPE"])
        facts = {
            "original_request": original_request,
            "tool": tool,
            "arguments_json": arguments,
            "state": asdict(state),
            "approval": asdict(approval),
            "advisory_judge": judge.model_dump(mode="json") if judge is not None else None,
        }
        binding = ExecutionBinding(
            request_id=request_id,
            tool=tool,
            arguments_json=arguments,
            arguments_sha256=digest(json.loads(arguments)),
            schema_sha256=schema,
            operation_scope=SCOPES[tool],
            policy_decision="PERMIT",
            policy_sha256=digest(policy.model_dump(mode="json")),
            policy_facts_sha256=digest(facts),
            policy_context_sha256=digest(json.loads(context)),
        )
        envelope = AuthorityEnvelope(
            binding, "PERMIT", tuple(policy.reasons), POLICY_VERSION, now, expires
        )
        self._spent.add(id(approval))
        self._request_ids.add(request_id)
        self._issued[id(envelope)] = _Issued(
            envelope,
            canonical_json(asdict(envelope)),
            original_request,
            context,
            approval.reference,
            now,
            expires,
        )
        return PolicyEvaluation(policy, envelope)

    def approval_reference(self, envelope: AuthorityEnvelope) -> str:
        with self._lock:
            retained = self._issued.get(id(envelope))
            if retained is None or retained.envelope is not envelope:
                raise ExecutionBoundaryError("WRITE01_ENVELOPE_NOT_OWNED")
            return retained.approval_reference

    def consume(
        self,
        envelope: AuthorityEnvelope | None,
        request_id: str,
        original_request: str,
        tool: str,
        query: dict[str, Any],
    ) -> ExecutionBinding:
        with self._lock:
            if type(envelope) is not AuthorityEnvelope:
                raise ExecutionBoundaryError("WRITE01_ENVELOPE_NOT_ISSUED")
            retained = self._issued.pop(id(envelope), None)
            if retained is None or retained.envelope is not envelope:
                raise ExecutionBoundaryError("WRITE01_ENVELOPE_CONSUMED_OR_FOREIGN")
            # Consume first: expiry, mismatch and success never refund approval.
            try:
                arguments, schema = self._query(tool, query)
                serialized = canonical_json(asdict(envelope))
            except (ValueError, TypeError, OverflowError, KeyError) as exc:
                raise ExecutionBoundaryError("WRITE01_BINDING_MISMATCH") from exc
            now = self._now()
            if now < retained.issued_at or now >= retained.expires_at:
                raise ExecutionBoundaryError("WRITE01_ENVELOPE_EXPIRED_OR_CLOCK_INVALID")
            binding = envelope.binding
            if (
                serialized != retained.serialized
                or retained.original_request != original_request
                or self._context() != retained.context_json
                or binding.request_id != request_id
                or binding.tool != tool
                or binding.arguments_json != arguments
                or binding.arguments_sha256 != digest(json.loads(arguments))
                or binding.schema_sha256 != schema
                or binding.operation_scope != SCOPES[tool]
                or binding.policy_decision != "PERMIT"
                or envelope.decision != "PERMIT"
                or envelope.policy_version != POLICY_VERSION
                or binding.policy_context_sha256 != digest(json.loads(self._context()))
            ):
                raise ExecutionBoundaryError("WRITE01_BINDING_MISMATCH")
            return binding
