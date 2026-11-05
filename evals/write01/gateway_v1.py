"""Experimental WRITE-01 gateway. Never installed into the legacy READ owner."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from civicgate.governance.execution import ExecutionBoundaryError
from civicgate.models.governance import JudgeSignal
from evals.write01.authority_v1 import HostApproval, StateFacts, WriteAuthority
from evals.write01.contract_v1 import DATASET_SHA256, READ_TOOL, WRITE_TOOL, canonical_json, digest
from evals.write01.store_v1 import ReviewStore, StoreError


class WriteResponseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contract: Literal["WRITE01_SYNTHETIC_REVIEW_V1"] = "WRITE01_SYNTHETIC_REVIEW_V1"
    run_id: str
    observation_id: str
    tool: str
    original_request: str
    decision: Literal["PERMIT", "DENY", "REVIEW_REQUIRED"]
    reasons: list[str]
    binding_issued: bool = False
    binding_consumed: bool = False
    binding: dict[str, Any] | None = None
    adapter_entries: int = 0
    transaction_outcome: str = "NOT_DISPATCHED"
    result_verification: Literal["NOT_EXECUTED", "VERIFIED", "UNKNOWN"] = "NOT_EXECUTED"
    custody: Literal["NOT_OPENED", "OPEN", "CLOSED", "UNKNOWN", "READ_ONLY_NO_FENCE"] = "NOT_OPENED"
    result: dict[str, Any] | None = None
    evidence_sha256: str | None = None
    human_acceptance: Literal["NOT_GRANTED"] = "NOT_GRANTED"
    judge: dict[str, Any] = Field(default_factory=dict)


class AuditSink:
    """Fresh append-only synthetic log; an audit failure prevents further actions."""

    def __init__(self, path: Path):
        self.path = path
        with path.open("xb"):
            pass

    def emit(self, stage: str, **values: Any) -> None:
        raw = (canonical_json({"stage": stage, **values}) + "\n").encode("utf-8")
        with self.path.open("ab") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())


class WriteGatewayV1:
    """Host-owned one-purpose authority + transactional synthetic adapter.

    Trusted Python construction is not exposed to MCP. Agent proposals carry
    neither approval objects nor owner selectors. A hostile local interpreter
    or administrator is outside this research composition's trust boundary.
    """

    def __init__(
        self,
        store: ReviewStore,
        owner_id: str,
        store_id: str,
        approvals: tuple[HostApproval, ...],
        audit: AuditSink,
        *,
        run_id: str,
    ) -> None:
        if type(store) is not ReviewStore or store.store_id != store_id:
            raise ValueError("WRITE01_STORE_OWNER_CONTEXT_MISMATCH")
        self._store = store
        self._owner_id = owner_id
        self._store_id = store_id
        self._approvals = approvals
        self._authority = WriteAuthority(owner_id, store_id, approvals=approvals)
        self._audit = audit
        self._run_id = run_id
        self._lock = RLock()
        self._blocked = False
        self._server_owner: object | None = None

    def claim_server(self, owner: object) -> None:
        with self._lock:
            if self._server_owner is not None:
                raise ValueError("WRITE01_OWNER_ALREADY_CLAIMED")
            self._server_owner = owner

    def _emit(self, stage: str, observation_id: str, **values: Any) -> None:
        try:
            self._audit.emit(stage, run_id=self._run_id, observation_id=observation_id, **values)
        except OSError:
            self._blocked = True
            raise

    def call(self, original_request: str, tool: str, query: dict[str, Any]) -> WriteResponseV1:
        with self._lock:
            return self._call(original_request, tool, query)

    def _call(self, original_request: str, tool: str, query: dict[str, Any]) -> WriteResponseV1:
        obs = "WRITE01_OBS_" + uuid4().hex
        # Constant fixture signal, recorded as such. No live model is constructed.
        judge = JudgeSignal(
            classification="IN_SCOPE",
            confidence=0.99,
            rationale="Synthetic permissive fixture",
            available=True,
            provider="write01-synthetic-judge",
            flags=["NONE"],
        )
        response = WriteResponseV1(
            run_id=self._run_id,
            observation_id=obs,
            tool=tool,
            original_request=original_request,
            decision="REVIEW_REQUIRED",
            reasons=["CUSTODY_UNAVAILABLE"],
            judge=judge.model_dump(mode="json"),
        )
        if self._blocked:
            response.reasons = ["OWNER_STOPPED_NO_AUTOMATIC_RECOVERY"]
            response.custody = "UNKNOWN"
            return response
        intent_open = False
        close_attempted = False
        try:
            self._emit("proposal", obs, original_request=original_request, tool=tool, query=query)
            state = self._store.snapshot(str(query.get("award_id", "")))
            facts = StateFacts(award_exists=True, status=state["status"], version=state["version"])
        except StoreError as exc:
            if exc.code == "UNKNOWN_SYNTHETIC_AWARD":
                facts = StateFacts(award_exists=False, status="UNKNOWN", version=0)
            else:
                self._blocked = True
                response.reasons = [exc.code]
                response.custody = "UNKNOWN"
                return response
        except OSError:
            response.custody = "UNKNOWN"
            return response
        try:
            evaluation = self._authority.evaluate(obs, original_request, tool, query, facts, judge)
            policy = evaluation.policy
            response.decision, response.reasons = policy.decision, list(policy.reasons)
            envelope = evaluation.envelope
            if envelope is not None:
                response.binding_issued = True
                response.binding = envelope.binding.audit_record()
            self._emit("policy", obs, policy=policy.model_dump(mode="json"), judge=response.judge)
            if envelope is None:
                self._emit("completed", obs, response=response.model_dump(mode="json"))
                return response
            self._emit("binding_issued", obs, binding=response.binding)
            effective = json.loads(envelope.binding.arguments_json)
            # The host retained approvals; this lookup is evidence only. Actual
            # authority was evaluated by WriteAuthority, never by this hash match.
            approval_ref = self._authority.approval_reference(envelope)
            operation = {
                "original_request": original_request,
                "query": effective,
                "approval_ref": approval_ref,
                "owner_id": self._owner_id,
                "dataset_sha256": DATASET_SHA256,
                "store_id": self._store_id,
                "run_id": self._run_id,
                "observation_id": obs,
                "tool": tool,
                "binding": response.binding,
            }
            if tool == WRITE_TOOL:
                opened = self._store.reserve(obs, operation, envelope.binding.binding_sha256)
                durable_open = self._store.inspect(obs)
                if (
                    opened
                    != {
                        "operation_id": obs,
                        "custody": "OPEN",
                        "operation_sha256": digest(operation),
                        "binding_sha256": envelope.binding.binding_sha256,
                    }
                    or durable_open is None
                    or durable_open["custody"] != "OPEN"
                    or durable_open["operation_json"] != canonical_json(operation)
                    or durable_open["binding_sha256"] != envelope.binding.binding_sha256
                    or durable_open["receipt_json"] is not None
                ):
                    raise StoreError("OPEN_EVIDENCE_NOT_CONFIRMED", uncertain=True)
                intent_open = True
                response.custody = "OPEN"
                self._emit("intent_open_ack", obs, operation_sha256=digest(operation))
            binding = self._authority.consume(envelope, obs, original_request, tool, effective)
            response.binding_consumed = True
            self._emit("binding_consumed", obs, binding=binding.audit_record())
            # No adapter entry can occur without successful real consumption.
            self._emit("adapter_entry", obs, operation_id=obs, tool=tool)
            response.adapter_entries = 1
            if tool == WRITE_TOOL:
                receipt = self._store.commit(obs, binding.binding_sha256)
                response.transaction_outcome = "COMMIT_RESPONSE_OBSERVED"
                self._emit("commit_observed", obs, receipt=receipt)
                durable = self._store.inspect(obs)
                if (
                    durable is None
                    or digest(receipt["receipt"]) != receipt["receipt_sha256"]
                    or durable["receipt_sha256"] != receipt["receipt_sha256"]
                    or json.loads(durable["receipt_json"]) != receipt["receipt"]
                    or receipt["receipt"]["operation"] != operation
                    or receipt["receipt"]["binding_sha256"] != binding.binding_sha256
                    or self._store.snapshot(effective["award_id"]) != receipt["receipt"]["after"]
                ):
                    raise StoreError("POST_COMMIT_EVIDENCE_MISMATCH", uncertain=True)
                response.transaction_outcome = "COMMITTED"
                close_attempted = True
                ack = self._store.acknowledge(obs, receipt["receipt_sha256"])
                closed = self._store.inspect(obs)
                if (
                    ack
                    != {
                        "operation_id": obs,
                        "receipt_sha256": receipt["receipt_sha256"],
                        "custody": "CLOSED",
                        "human_acceptance": "NOT_ESTABLISHED",
                    }
                    or closed is None
                    or closed["custody"] != "CLOSED"
                    or closed["operation_id"] != obs
                    or closed["receipt_sha256"] != receipt["receipt_sha256"]
                    or closed["receipt_json"] != canonical_json(receipt["receipt"])
                    or closed["operation_json"] != canonical_json(operation)
                    or closed["binding_sha256"] != binding.binding_sha256
                ):
                    raise StoreError("CLOSE_ACK_NOT_CONFIRMED", uncertain=True)
                response.custody = "CLOSED"
                response.result = {
                    "receipt": receipt["receipt"],
                    "receipt_sha256": receipt["receipt_sha256"],
                    "custody_at_commit": "OPEN",
                    "close_ack": ack,
                }
            elif tool == READ_TOOL:
                response.result = self._store.snapshot(effective["award_id"])
                response.transaction_outcome = "READ_ONLY"
                response.custody = "READ_ONLY_NO_FENCE"
            else:
                raise ExecutionBoundaryError("WRITE01_DISPATCH_TOOL_MISMATCH")
            response.result_verification = "VERIFIED"
            response.evidence_sha256 = digest(response.result)
            self._emit("completed", obs, response=response.model_dump(mode="json"))
            return response
        except (
            StoreError,
            ExecutionBoundaryError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            # Keep an initial PERMIT visible. Failure/uncertainty is a separate
            # disposition; it must not erase authorization or observed dispatch.
            self._blocked = True
            response.reasons = [*response.reasons, getattr(exc, "code", type(exc).__name__)]
            response.result_verification = "UNKNOWN"
            response.result = None
            response.evidence_sha256 = None
            if response.transaction_outcome != "COMMITTED":
                response.transaction_outcome = (
                    "UNKNOWN" if response.adapter_entries else "NOT_DISPATCHED"
                )
            response.custody = (
                "OPEN"
                if intent_open
                and not close_attempted
                and response.custody != "CLOSED"
                and getattr(exc, "code", "") != "CUSTODY_ACK_UNKNOWN"
                else "UNKNOWN"
            )
            try:
                self._emit("stopped", obs, response=response.model_dump(mode="json"))
            except OSError:
                response.custody = "UNKNOWN"
            return response
