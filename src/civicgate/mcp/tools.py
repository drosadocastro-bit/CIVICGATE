import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from civicgate.adapters.usaspending import AdapterError, DataBatch, USAspending
from civicgate.audit.trace import Trace
from civicgate.governance.agent_k import inspect
from civicgate.governance.judge import assess
from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.llm.base import JudgeModel
from civicgate.models.governance import Governance, JudgeSignal
from civicgate.models.requests import TOOLS, Award, Proposal, Recipient, Search
from civicgate.models.responses import Envelope, Error


class Gateway:
    """Trusted composition root creates one gateway per local process/session.

    No public parameter accepts judge signals, policy decisions or capability claims.
    """

    def __init__(
        self, adapter: USAspending, judge: JudgeModel, trace: Trace, threshold: float = 0.85
    ) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("Invalid confidence threshold")
        self._adapter = adapter
        self._judge = judge
        self.trace = trace
        self.threshold = threshold
        self._denials = 0
        self._lock = asyncio.Lock()

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
        )
        # Audit must be writable BEFORE any model or public-data operation.
        self.trace.record(
            request_id, "proposal", user_request=request, proposal=proposal.model_dump()
        )
        judge = (
            await assess(self._judge, request, proposal)
            if valid
            else JudgeSignal(rationale="Invalid input; semantic call skipped")
        )
        k_signal = inspect(text, judge, self._denials, proposal.tool in TOOLS)
        policy = evaluate(facts, judge, k_signal, self.threshold)
        self.trace.record(
            request_id,
            "policy",
            judge=judge.model_dump(),
            agent_k=k_signal.model_dump(),
            facts=facts.__dict__,
            confidence_threshold=self.threshold,
            policy=policy.model_dump(),
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
            self._denials += 1
        elif policy.decision == "REVIEW_REQUIRED":
            envelope.clarification = "Clarify recipient, agency, date range or research intent; resolve the listed policy reasons."
        elif args is not None:
            self.trace.record(
                request_id,
                "execution_started",
                tool=proposal.tool,
                execution_authority=policy.model_dump(),
            )
            envelope.tool_executed = True
            try:
                if isinstance(args, Search):
                    batch = await self._adapter.search(args)
                elif isinstance(args, Award):
                    batch = await self._adapter.detail(args)
                else:
                    batch = await self._adapter.recipients(args)
                # Revalidate at the governance boundary even for alternate adapters.
                batch = DataBatch.model_validate(batch.model_dump())
                if batch.provenance.records_returned != len(batch.records):
                    raise AdapterError("PROVENANCE_UNAVAILABLE")
                expected_source = (
                    "SYNTHETIC_TEST_FIXTURE" if self._adapter.fixture else "PUBLIC_GOVERNMENT_API"
                )
                if batch.provenance.source_type != expected_source:
                    raise AdapterError("PROVENANCE_UNAVAILABLE")
                envelope.provenance = batch.provenance
                envelope.result = {"records": batch.records}
                envelope.status = "OK"
                review_reason = None
                if isinstance(args, Recipient) and (
                    len(batch.records) != 1 or batch.provenance.truncated
                ):
                    review_reason = (
                        "AMBIGUOUS_RECIPIENT" if batch.records else "RECIPIENT_NOT_FOUND"
                    )
                    envelope.clarification = "Choose an explicit recipient identifier from the candidates, or refine the name. No recipient was selected."
                if isinstance(args, Search) and args.recipient_name:
                    names = {str(r.get("recipient_name", "")).casefold() for r in batch.records}
                    if len(names) > 1 or (names and names != {args.recipient_name.casefold()}):
                        review_reason = "RECIPIENT_IDENTITY_UNCONFIRMED"
                        envelope.clarification = "These are search matches, not a resolved legal identity. Refine the recipient name using candidate resolution."
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
            except AdapterError as exc:
                envelope.status = "ERROR"
                envelope.result = None
                envelope.errors = [
                    Error(
                        code=exc.code,
                        message="Public source request failed. Refine inputs or retry if retryable; no substitute data were used.",
                        retryable=exc.retryable,
                    )
                ]
                if exc.code in {"CONFLICTING_SOURCE_RESULTS", "PROVENANCE_UNAVAILABLE"}:
                    post = evaluate(
                        replace(facts, review_reason=exc.code), judge, k_signal, self.threshold
                    )
                    envelope.decision = post.decision
                    envelope.governance.policy_reasons = post.reasons
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
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
        self.trace.record(
            request_id,
            "completed",
            response=envelope.model_dump(mode="json"),
            tool_executed=envelope.tool_executed,
        )
        return envelope
