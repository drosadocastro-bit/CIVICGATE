"""Process-local issuance and exact invocation checks for the Gateway boundary.

The existing deterministic policy remains the sole authority issuer. Digests here
describe bindings; they do not authenticate a caller's claim. An envelope is
accepted only when this boundary retained that exact object after evaluating
policy itself. This is a trusted-server-process boundary, not a sandbox against
arbitrary Python code with access to its internals.
"""

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from time import monotonic
from typing import Any

from pydantic import BaseModel, ValidationError

from civicgate.governance.policy import PolicyFacts, evaluate
from civicgate.models.governance import Decision, JudgeSignal, KSignal, PolicyResult
from civicgate.models.requests import TOOLS

PolicyContext = tuple[bool, bool, float, int]
POLICY_VERSION = "civicgate-mvp-1"
OPERATION_SCOPE = "PUBLIC_SPENDING_RESEARCH"
MAX_OUTSTANDING_ENVELOPES = 256


class ExecutionBoundaryError(ValueError):
    """A binding failed before backend dispatch; no caller approval can fix it."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExecutionBinding:
    request_id: str
    tool: str
    arguments_json: str
    arguments_sha256: str
    schema_sha256: str
    operation_scope: str
    policy_decision: Decision
    policy_sha256: str
    policy_facts_sha256: str
    policy_context_sha256: str

    @property
    def binding_sha256(self) -> str:
        return _digest(_canonical(asdict(self)))

    def audit_record(self) -> dict[str, Any]:
        """Audit identities only: this representation cannot be used for dispatch."""
        return {key: value for key, value in asdict(self).items() if key != "arguments_json"} | {
            "binding_sha256": self.binding_sha256
        }


@dataclass(frozen=True)
class AuthorityEnvelope:
    binding: ExecutionBinding
    decision: Decision
    reasons: tuple[str, ...]
    policy_version: str
    issued_at: float
    expires_at: float

    def audit_record(self) -> dict[str, Any]:
        return {
            "authority_source": "DETERMINISTIC_POLICY_GATE",
            "decision": self.decision,
            "reasons": list(self.reasons),
            "policy_version": self.policy_version,
            "binding": self.binding.audit_record(),
        }


@dataclass(frozen=True)
class PolicyEvaluation:
    policy: PolicyResult
    envelope: AuthorityEnvelope | None


@dataclass(frozen=True)
class _IssuedEnvelope:
    envelope: AuthorityEnvelope
    serialized: str
    context_json: str
    issued_at: float
    expires_at: float


class ExecutionBoundary:
    """One Gateway's private, single-use policy issuance and dispatch verifier.

    Registry, clock and lifetime are trusted composition configuration, never MCP
    or planner inputs. Issued envelopes are never exported as bearer credentials.
    """

    def __init__(
        self,
        registry: Mapping[str, type[BaseModel]] = TOOLS,
        *,
        clock: Callable[[], float] = monotonic,
        max_age_seconds: float = 30,
    ) -> None:
        if (
            isinstance(max_age_seconds, bool)
            or not math.isfinite(max_age_seconds)
            or max_age_seconds <= 0
        ):
            raise ValueError("Envelope lifetime must be finite and positive")
        self._registry = registry
        self._models = dict(registry)
        self._schemas = {
            tool: _digest(_canonical(model.model_json_schema()))
            for tool, model in self._models.items()
        }
        self._clock = clock
        self._max_age_seconds = max_age_seconds
        self._issued: dict[int, _IssuedEnvelope] = {}

    @staticmethod
    def _context(context: PolicyContext) -> str:
        if (
            type(context) is not tuple
            or len(context) != 4
            or type(context[0]) is not bool
            or type(context[1]) is not bool
            or type(context[2]) not in {int, float}
            or not math.isfinite(context[2])
            or not 0 <= context[2] <= 1
            or type(context[3]) is not int
            or context[3] < 0
        ):
            raise ExecutionBoundaryError("POLICY_CONTEXT_INVALID")
        return _canonical(context)

    def _schema(self, tool: str) -> tuple[type[BaseModel], str]:
        model = self._models.get(tool)
        if model is None:
            raise ExecutionBoundaryError("TOOL_NOT_REGISTERED")
        if dict(self._registry) != self._models:
            raise ExecutionBoundaryError("TOOL_REGISTRY_DRIFT")
        try:
            current_schema = _digest(_canonical(model.model_json_schema()))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ExecutionBoundaryError("TOOL_REGISTRY_DRIFT") from exc
        if current_schema != self._schemas[tool]:
            raise ExecutionBoundaryError("TOOL_REGISTRY_DRIFT")
        return model, current_schema

    def _arguments(self, tool: str, arguments: dict[str, Any] | None) -> tuple[str, str]:
        model, schema_sha256 = self._schema(tool)
        if type(arguments) is not dict or any(type(key) is not str for key in arguments):
            raise ExecutionBoundaryError("ARGUMENTS_INVALID")
        try:
            # Check JSON/non-finite values before model coercion, then snapshot
            # the validated effective invocation, including defaults.
            _canonical(arguments)
            normalized = model.model_validate(arguments).model_dump(mode="json")
            arguments_json = _canonical(normalized)
        except (ValidationError, ValueError, TypeError, OverflowError) as exc:
            raise ExecutionBoundaryError("ARGUMENTS_INVALID") from exc
        return arguments_json, schema_sha256

    def _now(self) -> float:
        try:
            value = self._clock()
        except Exception as exc:
            raise ExecutionBoundaryError("ENVELOPE_TIME_INVALID") from exc
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ExecutionBoundaryError("ENVELOPE_TIME_INVALID")
        return value

    def evaluate(
        self,
        request_id: str,
        facts: PolicyFacts,
        judge: JudgeSignal,
        agent_k: KSignal,
        threshold: float,
        arguments: dict[str, Any] | None,
        policy_context: PolicyContext,
    ) -> PolicyEvaluation:
        context_json = self._context(policy_context)
        if (
            type(request_id) is not str
            or not request_id
            or not isinstance(facts, PolicyFacts)
            or type(threshold) not in {int, float}
            or not math.isfinite(threshold)
            or threshold != policy_context[2]
            or facts.semantic_required != policy_context[0]
        ):
            raise ExecutionBoundaryError("POLICY_CONTEXT_INVALID")
        # No decision, approval, envelope or expected digest is accepted here.
        # Only the existing policy evaluates the actual invocation facts/signals.
        policy = evaluate(facts, judge, agent_k, threshold)
        if policy.decision != "PERMIT":
            return PolicyEvaluation(policy=policy.model_copy(deep=True), envelope=None)
        if facts.capability != OPERATION_SCOPE:
            raise ExecutionBoundaryError("OPERATION_SCOPE_MISMATCH")
        arguments_json, schema_sha256 = self._arguments(facts.tool, arguments)
        # Policy's effective proposal facts must describe the invocation being
        # bound. A matching name in a separate facts copy cannot authorize a
        # different actual filter. Legacy unnamed facts may omit this context.
        if facts.arguments_json is not None:
            try:
                fact_arguments_json, _ = self._arguments(
                    facts.tool, json.loads(facts.arguments_json)
                )
            except (ValueError, TypeError) as exc:
                raise ExecutionBoundaryError("POLICY_ARGUMENTS_MISMATCH") from exc
            if fact_arguments_json != arguments_json:
                raise ExecutionBoundaryError("POLICY_ARGUMENTS_MISMATCH")
        binding = ExecutionBinding(
            request_id=request_id,
            tool=facts.tool,
            arguments_json=arguments_json,
            arguments_sha256=_digest(arguments_json),
            schema_sha256=schema_sha256,
            operation_scope=OPERATION_SCOPE,
            policy_decision=policy.decision,
            policy_sha256=_digest(_canonical(policy.model_dump(mode="json"))),
            policy_facts_sha256=_digest(_canonical(asdict(facts))),
            policy_context_sha256=_digest(context_json),
        )
        now = self._now()
        # Abandoned pre-dispatch audit failures cannot grow an unbounded issuer
        # registry. Request IDs are generated by Gateway, not accepted from MCP.
        # Token replay is rejected by retained object identity, without permanent
        # request-ID tombstones or a second authority/replay registry.
        expired = [
            identity for identity, issued in self._issued.items() if now >= issued.expires_at
        ]
        for identity in expired:
            del self._issued[identity]
        if any(
            issued.envelope.binding.request_id == request_id for issued in self._issued.values()
        ):
            raise ExecutionBoundaryError("REQUEST_ID_REUSED")
        if len(self._issued) >= MAX_OUTSTANDING_ENVELOPES:
            raise ExecutionBoundaryError("ISSUANCE_CAPACITY_EXCEEDED")
        expires_at = now + self._max_age_seconds
        if not math.isfinite(expires_at):
            raise ExecutionBoundaryError("ENVELOPE_TIME_INVALID")
        envelope = AuthorityEnvelope(
            binding=binding,
            decision=policy.decision,
            reasons=tuple(policy.reasons),
            policy_version=POLICY_VERSION,
            issued_at=now,
            expires_at=expires_at,
        )
        self._issued[id(envelope)] = _IssuedEnvelope(
            envelope=envelope,
            serialized=_canonical(asdict(envelope)),
            context_json=context_json,
            issued_at=now,
            expires_at=expires_at,
        )
        return PolicyEvaluation(policy=policy.model_copy(deep=True), envelope=envelope)

    def consume(
        self,
        envelope: AuthorityEnvelope | None,
        request_id: str,
        tool: str,
        arguments: dict[str, Any] | None,
        policy_context: PolicyContext,
    ) -> ExecutionBinding:
        if type(envelope) is not AuthorityEnvelope:
            raise ExecutionBoundaryError("ENVELOPE_NOT_ISSUED")
        # Consume first: a failed or successful verification never permits replay.
        retained = self._issued.pop(id(envelope), None)
        if retained is None or retained.envelope is not envelope:
            raise ExecutionBoundaryError("ENVELOPE_ALREADY_CONSUMED_OR_UNKNOWN")
        try:
            serialized = _canonical(asdict(envelope))
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise ExecutionBoundaryError("ENVELOPE_BINDING_MISMATCH") from exc
        if serialized != retained.serialized:
            raise ExecutionBoundaryError("ENVELOPE_BINDING_MISMATCH")
        now = self._now()
        if now < retained.issued_at:
            raise ExecutionBoundaryError("ENVELOPE_TIME_INVALID")
        if now >= retained.expires_at:
            raise ExecutionBoundaryError("ENVELOPE_EXPIRED")
        context_json = self._context(policy_context)
        if context_json != retained.context_json:
            raise ExecutionBoundaryError("POLICY_CONTEXT_MISMATCH")
        binding = envelope.binding
        if (
            request_id != binding.request_id
            or tool != binding.tool
            or envelope.decision != "PERMIT"
            or binding.policy_decision != "PERMIT"
            or envelope.policy_version != POLICY_VERSION
            or binding.operation_scope != OPERATION_SCOPE
            or _digest(context_json) != binding.policy_context_sha256
        ):
            raise ExecutionBoundaryError("ENVELOPE_BINDING_MISMATCH")
        arguments_json, schema_sha256 = self._arguments(tool, arguments)
        if (
            arguments_json != binding.arguments_json
            or _digest(arguments_json) != binding.arguments_sha256
            or schema_sha256 != binding.schema_sha256
        ):
            raise ExecutionBoundaryError("ENVELOPE_BINDING_MISMATCH")
        return binding
