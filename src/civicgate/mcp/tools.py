import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from typing import cast
from uuid import uuid4

from pydantic import ValidationError

from civicgate.adapters.usaspending import (
    AdapterCall,
    AdapterError,
    AttemptRecord,
    DataBatch,
    USAspending,
)
from civicgate.audit.trace import Trace
from civicgate.governance.agent_k import inspect
from civicgate.governance.judge import assess
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.llm.base import JudgeModel
from civicgate.models.governance import Governance, JudgeSignal, KSignal
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope, Error, RetryClass

TRIPWIRE_REASONS = frozenset({"DENIED_AUTHORITY", "PRIVATE_DATA", "BYPASS_REQUEST"})


class Gateway:
    """Trusted composition root creates one gateway per local process/session.

    No public parameter accepts judge signals, policy decisions or capability claims.
    """

    def __init__(
        self,
        adapter: USAspending,
        judge: JudgeModel,
        trace: Trace,
        threshold: float = 0.85,
        *,
        require_judge: bool = True,
        enable_agent_k: bool = True,
    ) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("Invalid confidence threshold")
        self._adapter = adapter
        self._judge = judge
        self.trace = trace
        self.threshold = threshold
        self.require_judge = require_judge
        self.enable_agent_k = enable_agent_k
        self._denials = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _apply_attempt_summary(
        envelope: Envelope,
        attempts: tuple[AttemptRecord, ...],
        metadata_available: bool,
        retry_class: str,
    ) -> None:
        envelope.attempt_metadata_available = metadata_available
        envelope.attempt_count = len(attempts)
        envelope.retry_class = cast(RetryClass, retry_class if metadata_available else "UNKNOWN")
        if attempts:
            final = attempts[-1]
            envelope.dispatch_state = final.dispatch_state
            envelope.response_state = final.response_state
        elif envelope.tool_executed:
            envelope.dispatch_state = "DISPATCH_UNKNOWN"

    @staticmethod
    def _set_validation_state(envelope: Envelope, code: str) -> None:
        if code == "MALFORMED_RESPONSE":
            envelope.verification_state = "FAILED_VALIDATION"
            envelope.validation_lane = "LANE_B_EXECUTION"
            envelope.validation_reason = "MALFORMED_RESPONSE"
            envelope.next_action = "STOP"
        elif code in {"PROVENANCE_UNAVAILABLE", "CONFLICTING_SOURCE_RESULTS"}:
            envelope.verification_state = "FAILED_VALIDATION"
            envelope.validation_lane = "LANE_A_RESOLVABILITY"
            envelope.validation_reason = "PROVENANCE_UNAVAILABLE"
            envelope.next_action = "HUMAN_REVIEW_REQUIRED"
        elif code == "ADAPTER_SCHEMA_OR_PROVENANCE_INVALID":
            envelope.verification_state = "FAILED_VALIDATION"
            envelope.validation_lane = "LANE_A_RESOLVABILITY"
            envelope.validation_reason = "ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"
            envelope.next_action = "HUMAN_REVIEW_REQUIRED"
        elif code in {"TIMEOUT", "NETWORK_ERROR", "UPSTREAM_UNAVAILABLE"}:
            envelope.verification_state = "RESULT_UNKNOWN"
            envelope.next_action = "HUMAN_REVIEW_REQUIRED"

    async def call(
        self, request: str, proposal: Proposal, planning_failed: bool = False
    ) -> Envelope:
        async with self._lock:
            return await self._call(request, proposal, planning_failed)

    async def _call(self, request: str, proposal: Proposal, planning_failed: bool) -> Envelope:
        request_id = str(uuid4())
        text = request + "\n" + json.dumps(proposal.model_dump(), ensure_ascii=False)
        valid = 0 < len(request.strip()) <= 4000 and len(text) <= 16000
        args = None
        if proposal.tool in TOOLS:
            try:
                args = TOOLS[proposal.tool].model_validate(proposal.arguments)
            except ValidationError:
                valid = False
        bounded = not isinstance(args, Search) or bool(
            args.recipient_name or args.awarding_agency or args.state_code
        )
        facts = PolicyFacts(
            tool=proposal.tool,
            text=text,
            valid_input=valid,
            bounded=bounded,
            review_reason="PLANNER_FAILURE" if planning_failed else None,
            semantic_required=self.require_judge,
        )
        # Audit must be writable BEFORE any model or public-data operation.
        self.trace.record(
            request_id, "proposal", user_request=request, proposal=proposal.model_dump()
        )
        judge = (
            await assess(self._judge, request, proposal)
            if valid and self.require_judge
            else JudgeSignal(
                rationale=(
                    "Invalid input; semantic call skipped"
                    if not valid
                    else "Semantic judge disabled for this evaluation matrix"
                ),
                provider="disabled" if not self.require_judge else "unavailable",
            )
        )
        k_signal = (
            inspect(text, judge, self._denials, proposal.tool in TOOLS)
            if self.enable_agent_k
            else KSignal()
        )
        policy = evaluate(facts, judge, k_signal, self.threshold)
        failure_accounting: list[str] = []
        if planning_failed:
            failure_accounting.append("PLANNER_FAILURE")
        if self.require_judge and not judge.available:
            failure_accounting.append("JUDGE_SEMANTIC_FAILURE")
        if any(signal != "NONE" for signal in k_signal.signals):
            failure_accounting.append("AGENT_K_DETECTION")
        if policy.decision != "PERMIT":
            failure_accounting.append("GOVERNANCE_HELD")
        self.trace.record(
            request_id,
            "policy",
            judge=judge.model_dump(),
            agent_k=k_signal.model_dump(),
            facts=facts.__dict__,
            confidence_threshold=self.threshold,
            policy=policy.model_dump(),
            failure_accounting=failure_accounting,
        )
        envelope = Envelope(
            decision=policy.decision,
            tool=proposal.tool,
            request_id=request_id,
            status="BLOCKED",
            governance=Governance(
                judge_signal=judge, agent_k_signal=k_signal, policy_reasons=policy.reasons
            ),
        )
        if policy.decision == "DENY":
            # Containment counts scope-escape attempts (tripwires), not protocol mistakes
            # such as unknown tools or invalid arguments.
            if TRIPWIRE_REASONS & set(policy.reasons):
                self._denials += 1
            if "SESSION_CONTAINMENT_ACTIVE" in policy.reasons:
                envelope.clarification = "Session containment is active after repeated policy violations in this gateway process. Later calls are denied regardless of content; restart the gateway process to reset."
            envelope.next_action = "STOP"
        elif policy.decision == "REVIEW_REQUIRED":
            envelope.clarification = "Clarify recipient, agency, date range or research intent; resolve the listed policy reasons."
            envelope.next_action = "HUMAN_REVIEW_REQUIRED"
        elif args is not None:
            self.trace.record(
                request_id,
                "execution_started",
                tool=proposal.tool,
                execution_authority=policy.model_dump(),
            )
            envelope.tool_executed = True
            attempts: tuple[AttemptRecord, ...] = ()
            attempt_metadata_available = False
            retry_class = "UNKNOWN"
            try:
                if isinstance(args, Search):
                    adapter_result = await self._adapter.search(args)
                elif isinstance(args, Award):
                    adapter_result = await self._adapter.detail(args)
                else:
                    adapter_result = await self._adapter.recipients(args)
                if isinstance(adapter_result, AdapterCall):
                    batch = adapter_result.batch
                    attempts = adapter_result.outcome.attempts
                    attempt_metadata_available = True
                    retry_class = adapter_result.outcome.retry_class
                else:
                    batch = adapter_result
                # Revalidate at the governance boundary even for alternate adapters.
                batch = DataBatch.model_validate(batch.model_dump())
                self._apply_attempt_summary(
                    envelope, attempts, attempt_metadata_available, retry_class
                )
                if batch.provenance.records_returned != len(batch.records):
                    raise AdapterError(
                        "PROVENANCE_UNAVAILABLE",
                        attempts=attempts,
                        retry_class=retry_class,
                    )
                expected_source = (
                    "SYNTHETIC_TEST_FIXTURE" if self._adapter.fixture else "PUBLIC_GOVERNMENT_API"
                )
                if batch.provenance.source_type != expected_source:
                    raise AdapterError(
                        "PROVENANCE_UNAVAILABLE",
                        attempts=attempts,
                        retry_class=retry_class,
                    )
                envelope.provenance = batch.provenance
                envelope.result = {"records": batch.records}
                envelope.status = "OK"
                envelope.verification_state = "RESULT_VERIFIED"
                review_reason = None
                if isinstance(args, Recipient) and (
                    len(batch.records) != 1 or batch.provenance.truncated
                ):
                    review_reason = (
                        "AMBIGUOUS_RECIPIENT" if batch.records else "RECIPIENT_NOT_FOUND"
                    )
                    envelope.clarification = "Choose an explicit recipient identifier from the candidates, or refine the name. No recipient was selected."
                    envelope.next_action = "HUMAN_REVIEW_REQUIRED"
                if isinstance(args, Search) and args.recipient_name:
                    names = {str(r.get("recipient_name", "")).casefold() for r in batch.records}
                    if len(names) > 1 or (names and names != {args.recipient_name.casefold()}):
                        review_reason = "RECIPIENT_IDENTITY_UNCONFIRMED"
                        envelope.clarification = "These are search matches, not a resolved legal identity. Refine the recipient name using candidate resolution."
                        envelope.next_action = "HUMAN_REVIEW_REQUIRED"
                if review_reason:
                    post = evaluate(
                        replace(facts, review_reason=review_reason), judge, k_signal, self.threshold
                    )
                    envelope.decision = post.decision
                    envelope.governance.policy_reasons = post.reasons
                    envelope.status = "CLARIFICATION_REQUIRED"
                elif proposal.tool == "summarize_federal_spending":
                    total = sum(
                        (Decimal(str(row["award_amount"])) for row in batch.records), Decimal(0)
                    )
                    envelope.result = {
                        "record_count": len(batch.records),
                        "returned_award_amount_total_usd": str(total),
                        "scope": "RETURNED_PAGE_ONLY",
                        "note": "Sum of award amounts for matching awards, not fiscal-year transaction obligations or a population total.",
                    }
                    envelope.next_action = "NONE"
                else:
                    envelope.next_action = "NONE"
            except AdapterError as exc:
                attempts = exc.attempts
                attempt_metadata_available = bool(exc.attempts)
                retry_class = exc.retry_class
                self._apply_attempt_summary(
                    envelope, exc.attempts, bool(exc.attempts), exc.retry_class
                )
                envelope.status = "ERROR"
                envelope.result = None
                envelope.errors = [
                    Error(
                        code=exc.code,
                        message="Public source request failed. Refine inputs or retry if retryable; no substitute data were used.",
                        retryable=exc.retryable,
                    )
                ]
                self._set_validation_state(envelope, exc.code)
                if exc.code in {"TIMEOUT", "NETWORK_ERROR", "UPSTREAM_UNAVAILABLE"}:
                    envelope.next_action = "RETRY_ALLOWED" if exc.retryable else "RETRY_BLOCKED"
                if exc.code in {"CONFLICTING_SOURCE_RESULTS", "PROVENANCE_UNAVAILABLE"}:
                    post = evaluate(
                        replace(facts, review_reason=exc.code), judge, k_signal, self.threshold
                    )
                    envelope.decision = post.decision
                    envelope.governance.policy_reasons = post.reasons
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
                self._apply_attempt_summary(
                    envelope, attempts, attempt_metadata_available, retry_class
                )
                post = evaluate(
                    replace(facts, review_reason="ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"),
                    judge,
                    k_signal,
                    self.threshold,
                )
                envelope.decision = post.decision
                envelope.governance.policy_reasons = post.reasons
                envelope.status = "ERROR"
                envelope.result = None
                envelope.provenance = None
                envelope.errors = [
                    Error(
                        code="MALFORMED_ADAPTER_RESPONSE",
                        message="Adapter response failed validation; no data released.",
                    )
                ]
                self._set_validation_state(envelope, "ADAPTER_SCHEMA_OR_PROVENANCE_INVALID")
        self.trace.record(
            request_id,
            "completed",
            response=envelope.model_dump(mode="json"),
            tool_executed=envelope.tool_executed,
            attempts=[a.model_dump() for a in attempts] if "attempts" in locals() else [],
            attempt_metadata_available=envelope.attempt_metadata_available,
        )
        return envelope
