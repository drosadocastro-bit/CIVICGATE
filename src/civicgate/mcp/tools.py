import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from threading import Lock
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
from civicgate.audit.dispatch import DispatchJournal
from civicgate.audit.trace import Trace
from civicgate.channel_b.invocation_contract_v1 import InvocationContract
from civicgate.governance.agent_k import inspect
from civicgate.governance.execution import ExecutionBoundary, ExecutionBoundaryError
from civicgate.governance.judge import assess
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.llm.base import JudgeModel
from civicgate.models.governance import Governance, JudgeSignal, KSignal, PolicyResult
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope, Error, RetryClass

TRIPWIRE_REASONS = frozenset({"DENIED_AUTHORITY", "PRIVATE_DATA", "BYPASS_REQUEST"})


class Gateway:
    """Trusted composition root creates one gateway per local owner.

    No public parameter accepts judge signals, policy decisions or capability claims.
    Sharing direct references or multiplexing clients is prohibited; this class
    cannot authenticate logical callers in the trusted host process.
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
        dispatch_journal: DispatchJournal | None = None,
        contract: InvocationContract | None = None,
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
        self._dispatch_journal = dispatch_journal
        self._lock = asyncio.Lock()
        if contract is not None:
            contract.validate()
        self._contract = contract
        self._registry = TOOLS if contract is None else contract.registry
        self._execution_boundary = ExecutionBoundary(self._registry, contract=contract)
        self._mcp_owner: object | None = None
        self._mcp_owner_lock = Lock()

    def _claim_mcp_owner(self, owner: object) -> None:
        """Permanently attach one server; rejection never resets containment."""
        with self._mcp_owner_lock:
            if self._mcp_owner is not None:
                raise ValueError("Gateway already has an MCP server owner; sharing is prohibited")
            self._mcp_owner = owner

    @property
    def contract(self) -> InvocationContract | None:
        return self._contract

    def _evaluate(
        self, facts: PolicyFacts, judge: JudgeSignal, agent_k: KSignal, threshold: float
    ) -> PolicyResult:
        if self._contract is None:
            return evaluate(facts, judge, agent_k, threshold)
        return evaluate(facts, judge, agent_k, threshold, contract=self._contract)

    def _policy_context(self) -> tuple[bool, bool, float, int]:
        return (self.require_judge, self.enable_agent_k, self.threshold, self._denials)

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
        # The caller can retain and mutate its proposal while this call waits for the lock.
        proposal = proposal.model_copy(deep=True)
        async with self._lock:
            journal = self._dispatch_journal
            if journal is not None:
                self._denials = journal.admit()
            try:
                return await self._call(request, proposal, planning_failed)
            except BaseException as exc:
                if journal is not None:
                    journal.failed(exc)
                raise

    async def _call(self, request: str, proposal: Proposal, planning_failed: bool) -> Envelope:
        proposal = proposal.model_copy(deep=True)
        policy_context = self._policy_context()
        require_judge, enable_agent_k, threshold, denials = policy_context
        request_id = str(uuid4())
        if self._dispatch_journal is not None:
            self._dispatch_journal.begin(request_id)
        text = request + "\n" + json.dumps(proposal.model_dump(), ensure_ascii=False)
        valid = 0 < len(request.strip()) <= 4000 and len(text) <= 16000
        args = None
        if proposal.tool in self._registry:
            try:
                args = self._registry[proposal.tool].model_validate(proposal.arguments)
            except ValidationError:
                valid = False
        bounded = not isinstance(args, Search) or bool(
            args.recipient_name or args.awarding_agency or args.state_code
        )
        facts = PolicyFacts(
            tool=proposal.tool,
            text=text,
            request_text=request,
            arguments_json=args.model_dump_json() if args is not None else None,
            valid_input=valid,
            bounded=bounded,
            review_reason="PLANNER_FAILURE" if planning_failed else None,
            semantic_required=require_judge,
        )
        # Audit must be writable BEFORE any model or public-data operation.
        self.trace.record(
            request_id, "proposal", user_request=request, proposal=proposal.model_dump()
        )
        # Preflight: check whether deterministic policy already denies this request using
        # only signals that never depend on the judge (text tripwires, unknown tool,
        # invalid input, active containment). If so, skip the paid/external judge call
        # entirely rather than sending a request that was never going anywhere.
        probe_judge = JudgeSignal(available=False, provider="unavailable")
        preflight_k_signal = (
            inspect(text, probe_judge, denials, proposal.tool in self._registry)
            if enable_agent_k
            else KSignal()
        )
        preflight_policy = self._evaluate(facts, probe_judge, preflight_k_signal, threshold)
        call_judge = valid and require_judge and preflight_policy.decision != "DENY"
        judge_preflight_skipped = require_judge and preflight_policy.decision == "DENY"
        if call_judge:
            judge = await assess(self._judge, request, proposal.model_copy(deep=True))
            k_signal = (
                inspect(text, judge, denials, proposal.tool in self._registry)
                if enable_agent_k
                else KSignal()
            )
        else:
            if not valid:
                rationale = "Invalid input; semantic call skipped"
            elif not require_judge:
                rationale = "Semantic judge disabled for this evaluation matrix"
            else:
                rationale = (
                    "Deterministic policy already denies this request; semantic call skipped"
                )
            judge = JudgeSignal(
                rationale=rationale,
                provider="disabled" if not require_judge else "unavailable",
            )
            k_signal = preflight_k_signal
        authority_envelope = None
        issuance_error = None
        try:
            evaluation = self._execution_boundary.evaluate(
                request_id=request_id,
                facts=facts,
                judge=judge,
                agent_k=k_signal,
                threshold=threshold,
                arguments=args.model_dump(mode="json") if args is not None else None,
                policy_context=policy_context,
            )
            policy = evaluation.policy
            authority_envelope = evaluation.envelope
        except ExecutionBoundaryError as exc:
            # Preserve the policy decision separately from a failed issuance check.
            policy = self._evaluate(facts, judge, k_signal, threshold)
            issuance_error = exc.code
        pre_dispatch_verification = "NOT_REQUIRED"
        execution_boundary_error = issuance_error
        failure_accounting: list[str] = []
        if planning_failed:
            failure_accounting.append("PLANNER_FAILURE")
        if judge_preflight_skipped:
            failure_accounting.append("JUDGE_SKIPPED_PREFLIGHT_DENY")
        elif call_judge and not judge.available:
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
            confidence_threshold=threshold,
            policy=policy.model_dump(),
            binding_issued=authority_envelope is not None,
            binding_issuance_error=issuance_error,
            failure_accounting=failure_accounting,
            judge_preflight_skipped=judge_preflight_skipped,
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
        if self._dispatch_journal is not None:
            self._dispatch_journal.policy(
                request_id,
                {
                    "initial_decision": policy.decision,
                    "reasons": policy.reasons,
                    "binding_issued": authority_envelope is not None,
                    "binding_issuance_error": issuance_error,
                },
            )
        if policy.decision == "DENY":
            # Containment counts scope-escape attempts (tripwires), not protocol mistakes
            # such as unknown tools or invalid arguments.
            if TRIPWIRE_REASONS & set(policy.reasons):
                self._denials += 1
            if "SESSION_CONTAINMENT_ACTIVE" in policy.reasons:
                envelope.clarification = "Session containment is active after repeated policy violations in this gateway process. Later calls are denied regardless of content; restart the gateway process to reset."
                if self._dispatch_journal is not None:
                    envelope.clarification = "Durable containment is active. Restart and reconnect do not clear it; human review is required."
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
                execution_binding=(
                    authority_envelope.binding.audit_record() if authority_envelope else None
                ),
                pre_dispatch_verification="PENDING_PRE_DISPATCH",
                dispatch_state="NOT_DISPATCHED",
            )
            attempts: tuple[AttemptRecord, ...] = ()
            attempt_metadata_available = False
            retry_class = "UNKNOWN"
            try:
                if issuance_error is not None:
                    raise ExecutionBoundaryError(issuance_error)
                if self._dispatch_journal is not None:
                    self._dispatch_journal.intent(authority_envelope)
                binding = self._execution_boundary.consume(
                    authority_envelope,
                    request_id=request_id,
                    tool=proposal.tool,
                    arguments=args.model_dump(mode="json"),
                    policy_context=self._policy_context(),
                )
                # Dispatch from the checked binding, never from caller-owned objects.
                # No await or external callback occurs between this gate and dispatch.
                args = self._registry[binding.tool].model_validate_json(binding.arguments_json)
                pre_dispatch_verification = "PASS"
                if self._contract is not None and binding.tool == "find_federal_awards":
                    envelope.tool_executed = True
                    adapter_result = await self._contract.find_handler(self._adapter, args)
                elif isinstance(args, Search):
                    envelope.tool_executed = True
                    adapter_result = await self._adapter.search(args)
                elif isinstance(args, Award):
                    envelope.tool_executed = True
                    adapter_result = await self._adapter.detail(args)
                elif isinstance(args, Recipient):
                    envelope.tool_executed = True
                    adapter_result = await self._adapter.recipients(args)
                else:
                    raise ExecutionBoundaryError("TOOL_ROUTE_INVALID")
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
                if self._contract is not None and binding.tool == "find_federal_awards":
                    if not isinstance(adapter_result, AdapterCall):
                        raise ValueError("FAA outcome evidence required")
                    self._contract.validate_find_result(args, adapter_result)
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
                    post = self._evaluate(
                        replace(facts, review_reason=review_reason), judge, k_signal, threshold
                    )
                    envelope.decision = post.decision
                    envelope.governance.policy_reasons = post.reasons
                    envelope.status = "CLARIFICATION_REQUIRED"
                elif binding.tool == "summarize_federal_spending":
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
            except ExecutionBoundaryError as exc:
                pre_dispatch_verification = "FAIL"
                execution_boundary_error = exc.code
                envelope.decision = "DENY"
                envelope.governance.policy_reasons = ["EXECUTION_BINDING_INVALID"]
                envelope.next_action = "STOP"
                envelope.errors = [
                    Error(
                        code=exc.code,
                        message="Pre-dispatch binding verification failed; no backend invoked.",
                    )
                ]
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
                    post = self._evaluate(
                        replace(facts, review_reason=exc.code), judge, k_signal, threshold
                    )
                    envelope.decision = post.decision
                    envelope.governance.policy_reasons = post.reasons
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
                self._apply_attempt_summary(
                    envelope, attempts, attempt_metadata_available, retry_class
                )
                post = self._evaluate(
                    replace(facts, review_reason="ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"),
                    judge,
                    k_signal,
                    threshold,
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
        if self._dispatch_journal is not None:
            self._dispatch_journal.finish(
                envelope,
                self._denials,
                {
                    "pre_dispatch_verification": pre_dispatch_verification,
                    "execution_boundary_error": execution_boundary_error,
                    "attempts": [a.model_dump() for a in attempts]
                    if "attempts" in locals()
                    else [],
                },
            )
        self.trace.record(
            request_id,
            "completed",
            response=envelope.model_dump(mode="json"),
            tool_executed=envelope.tool_executed,
            pre_dispatch_verification=pre_dispatch_verification,
            execution_boundary_error=execution_boundary_error,
            attempts=[a.model_dump() for a in attempts] if "attempts" in locals() else [],
            attempt_metadata_available=envelope.attempt_metadata_available,
        )
        return envelope
