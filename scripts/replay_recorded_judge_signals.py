"""Offline evaluation of reviewed recorded signals through the real Gateway.

No live provider or credential configuration is accepted. Inputs and outputs stay
outside the repository. See docs/J2_SIGNAL_REPLAY.md for the input contract.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import socket
import sys
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import httpx
from pydantic import Field, ValidationError, model_validator

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from civicgate.adapters.usaspending import USAspending  # noqa: E402
from civicgate.audit.trace import Trace  # noqa: E402
from civicgate.demo import fixture_transport  # noqa: E402
from civicgate.governance.authority import denied_reasons  # noqa: E402
from civicgate.mcp.tools import Gateway  # noqa: E402
from civicgate.models.governance import (  # noqa: E402
    Classification,
    Decision,
    JudgeSignal,
    KSignal,
    Signal,
)
from civicgate.models.requests import TOOLS, Proposal, StrictModel  # noqa: E402
from civicgate.models.responses import (  # noqa: E402
    DispatchState,
    Envelope,
    NextAction,
    ResponseState,
    VerificationState,
)
from tests.fixture_transports import build_transport  # noqa: E402

SIGNAL_FIELDS = ("classification", "confidence", "flags", "available", "provider")
STATE_FIELDS = ("dispatch_state", "response_state", "verification_state", "next_action")
MAX_INPUT_BYTES = 200_000


class ReplayViolation(BaseException):
    """Stop invariants cannot be swallowed by ordinary provider error handling."""


class RecordedSignal(StrictModel):
    """Only the five preserved typed fields; no rationale or provider metadata."""

    classification: Classification
    confidence: float = Field(strict=True, ge=0, le=1)
    flags: list[Signal] = Field(max_length=8)
    available: bool = Field(strict=True)
    provider: str = Field(min_length=1, max_length=100)


class ReferenceLane(StrictModel):
    """Optional reviewed observation, never asserted to be human ground truth."""

    decision: Decision
    status: Literal["OK", "BLOCKED", "ERROR", "CLARIFICATION_REQUIRED"]
    policy_reasons: list[str] = Field(max_length=30)
    adapter_initiated: bool = Field(strict=True)
    judge_consulted: bool | None = Field(default=None, strict=True)
    agent_k: KSignal | None = None
    dispatch_state: DispatchState | None = None
    response_state: ResponseState | None = None
    verification_state: VerificationState | None = None
    next_action: NextAction | None = None


class ReplayCase(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    request: str = Field(max_length=16000)
    proposal: Proposal
    signal: RecordedSignal
    transport: Literal[
        "default", "malformed", "five_hundred_then_success", "timeout_then_changed_snapshot"
    ] = "default"
    expect_preflight_deny: bool = Field(default=False, strict=True)
    reference: ReferenceLane | None = None


class ReplayInput(StrictModel):
    schema_version: Literal["civicgate.recorded-signals.v1"]
    cases: list[ReplayCase] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> ReplayInput:
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Replay case IDs must be unique")
        return self


def signal_summary(signal: JudgeSignal) -> dict[str, Any]:
    return {name: getattr(signal, name) for name in SIGNAL_FIELDS}


class OfflineOnly:
    """Process-wide guards installed inside the existing event loop.

    This is a single-process evaluation command, not a concurrent production API.
    The loop's own startup/self-pipe is created before socket guards are installed.
    """

    def __init__(self) -> None:
        self.stack = ExitStack()
        self.blocked_attempts = 0

    def reject(self, *args: Any, **kwargs: Any) -> Any:
        self.blocked_attempts += 1
        raise ReplayViolation("NETWORK_PATH_BLOCKED")

    async def reject_async(self, *args: Any, **kwargs: Any) -> Any:
        return self.reject()

    def __enter__(self) -> OfflineOnly:
        for obj, attr in (
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
        ):
            self.stack.enter_context(patch.object(obj, attr, self.reject))
        self.stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", self.reject))
        self.stack.enter_context(
            patch.object(httpx.AsyncHTTPTransport, "handle_async_request", self.reject_async)
        )
        return self

    def __exit__(self, *args: Any) -> Any:
        return self.stack.__exit__(*args)


class RecordedJudgeProvider:
    """Evaluation-only provider: consume exactly one saved signal, without repair."""

    provider_name = "recorded_offline"

    def __init__(self, case: ReplayCase, *, forbidden: bool) -> None:
        self.record = copy.deepcopy(case.signal.model_dump())
        self.request = case.request
        self.proposal = copy.deepcopy(case.proposal.model_dump())
        self.forbidden = forbidden
        self.calls = 0
        self.returns = 0
        if signal_summary(JudgeSignal.model_validate(self.record)) != self.record:
            raise ReplayViolation("SIGNAL_CHANGED_ON_PARSE")

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        self.calls += 1
        if self.forbidden:
            raise ReplayViolation("UNEXPECTED_PREFLIGHT_PROVIDER_CALL")
        if self.calls != 1 or request != self.request or proposal.model_dump() != self.proposal:
            raise ReplayViolation("UNEXPECTED_RECORDED_PROVIDER_CALL")
        # Native rationale default completes the type; it is not reconstructed
        # model content and is excluded from replay evidence. Policy does not use it.
        signal = JudgeSignal.model_validate(copy.deepcopy(self.record))
        if signal_summary(signal) != self.record:
            raise ReplayViolation("RECORDED_SIGNAL_CHANGED")
        self.returns += 1
        return signal


class CountingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.MockTransport) -> None:
        if not isinstance(inner, httpx.MockTransport):
            raise ReplayViolation("NON_SYNTHETIC_TRANSPORT")
        self.inner = inner
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


class AuditedAdapter(USAspending):
    def __init__(self, inner: httpx.MockTransport, trace: Trace) -> None:
        self.counted_transport = CountingTransport(inner)
        super().__init__(transport=self.counted_transport, fixture=True)
        self.trace = trace
        self.initiations = 0

    def before_adapter(self) -> None:
        policies = [e for e in self.trace.events if e["stage"] == "policy"]
        starts = [e for e in self.trace.events if e["stage"] == "execution_started"]
        if len(policies) != 1 or len(starts) != 1:
            raise ReplayViolation("ADAPTER_WITHOUT_POLICY_EXECUTION_TRACE")
        if (
            policies[0]["policy"]["decision"] != "PERMIT"
            or starts[0]["execution_authority"]["decision"] != "PERMIT"
            or policies[0]["request_id"] != starts[0]["request_id"]
        ):
            raise ReplayViolation("ADAPTER_WITHOUT_DETERMINISTIC_PERMIT")
        self.initiations += 1
        if self.initiations != 1:
            raise ReplayViolation("DUPLICATE_ADAPTER_INITIATION")

    async def search(self, args: Any) -> Any:
        self.before_adapter()
        return await super().search(args)

    async def detail(self, args: Any) -> Any:
        self.before_adapter()
        return await super().detail(args)

    async def recipients(self, args: Any) -> Any:
        self.before_adapter()
        return await super().recipients(args)


def adapter_for(case: ReplayCase, trace: Trace) -> AuditedAdapter:
    if case.transport == "default":
        inner = fixture_transport()
    elif case.transport == "malformed":
        inner = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    else:
        inner = build_transport(case.transport)
    return AuditedAdapter(inner, trace)


def expected_preflight_denial(case: ReplayCase) -> bool:
    """Guard only; the real Gateway still makes every authorization decision.

    Fresh default Gateway state has no previous containment. Known deterministic
    denial triggers let the provider fail immediately if preflight regresses.
    """
    text = case.request + "\n" + json.dumps(case.proposal.model_dump(), ensure_ascii=False)
    if case.expect_preflight_deny or case.proposal.tool not in TOOLS:
        return True
    if not 0 < len(case.request.strip()) <= 4000 or len(text) > 16000 or denied_reasons(text):
        return True
    try:
        TOOLS[case.proposal.tool].model_validate(case.proposal.arguments)
    except ValidationError:
        return True
    return False


def compare(reference: ReferenceLane | None, replay: dict[str, Any]) -> dict[str, str]:
    """Exclusive categories; absent reference observations remain unknown."""
    category, direction = "NOT_COMPARABLE", "NOT_APPLICABLE"
    if reference is not None:
        before, after = reference.adapter_initiated, replay["adapter_initiated"]
        if before != after:
            direction = "CONTRACTIVE" if before else "EXPANSIVE"
            category = (
                "TIMING_DIFFERENCE_SAME_FINAL_AUTHORITY"
                if reference.decision == replay["decision"]
                else "PRE_DISPATCH_CONTRACTION"
                if before
                else "PRE_DISPATCH_EXPANSION"
            )
        elif before and any(getattr(reference, key) is None for key in STATE_FIELDS):
            pass  # Missing post-dispatch state is not evidence of equality.
        elif before and any(
            getattr(reference, key) != replay[key] for key in ("decision", "status", *STATE_FIELDS)
        ):
            category = "POST_DISPATCH_DIFFERENCE"
            rank = {"DENY": 0, "REVIEW_REQUIRED": 1, "PERMIT": 2}
            delta = rank[replay["decision"]] - rank[reference.decision]
            direction = "EXPANSIVE" if delta > 0 else "CONTRACTIVE" if delta < 0 else "NEUTRAL"
        elif reference.decision != replay["decision"]:
            pass  # The declared taxonomy does not resolve this non-dispatch case.
        elif reference.status != replay["status"]:
            pass
        elif reference.policy_reasons != replay["policy_reasons"] or (
            reference.agent_k is not None and reference.agent_k.model_dump() != replay["agent_k"]
        ):
            category, direction = "CAUTION_ONLY_DIFFERENCE", "NEUTRAL"
        else:
            category, direction = "NO_AUTHORITY_DIFFERENCE", "NEUTRAL"
    return {"authority_difference_class": category, "authority_direction": direction}


def envelope_summary(result: Envelope) -> dict[str, Any]:
    return {
        "decision": result.decision,
        "status": result.status,
        "policy_reasons": result.governance.policy_reasons,
        "judge_signal": signal_summary(result.governance.judge_signal),
        "agent_k": result.governance.agent_k_signal.model_dump(),
        "authority_source": result.governance.authority_source,
        "adapter_initiated": result.tool_executed,
        **{key: getattr(result, key) for key in STATE_FIELDS},
        "attempt_count": result.attempt_count,
        "result_released": result.result is not None,
        "error_codes": [error.code for error in result.errors],
    }


async def _execute_case(case: ReplayCase) -> dict[str, Any]:
    trace = Trace()
    forbidden = expected_preflight_denial(case)
    judge = RecordedJudgeProvider(case, forbidden=forbidden)
    adapter = adapter_for(case, trace)
    registry = dict(TOOLS)
    gateway = Gateway(
        adapter, judge, trace, threshold=0.85, require_judge=True, enable_agent_k=True
    )
    result = await gateway.call(case.request, case.proposal.model_copy(deep=True))
    events = [
        e for e in trace.events if e["stage"] == "policy" and e["request_id"] == result.request_id
    ]
    starts = [e for e in trace.events if e["stage"] == "execution_started"]
    if len(events) != 1 or registry != TOOLS:
        raise ReplayViolation("POLICY_TRACE_OR_TOOL_REGISTRY_CHANGED")
    event = events[0]
    skipped = event["judge_preflight_skipped"]
    if (judge.calls, judge.returns) != ((0, 0) if skipped else (1, 1)) or (
        forbidden and not skipped
    ):
        raise ReplayViolation("PROVIDER_COUNTER_OR_PREFLIGHT_MISMATCH")
    if judge.returns and (
        signal_summary(result.governance.judge_signal) != judge.record
        or {key: event["judge"][key] for key in SIGNAL_FIELDS} != judge.record
    ):
        raise ReplayViolation("GATEWAY_CHANGED_RECORDED_SIGNAL")
    if bool(adapter.initiations) != result.tool_executed or len(starts) != adapter.initiations:
        raise ReplayViolation("ADAPTER_COUNTER_MISMATCH")
    if event["policy"]["decision"] != "PERMIT" and (
        adapter.initiations or adapter.counted_transport.calls
    ):
        raise ReplayViolation("DISPATCH_WITHOUT_PERMIT")
    if result.governance.authority_source != "DETERMINISTIC_POLICY_GATE":
        raise ReplayViolation("AUTHORITY_SOURCE_CHANGED")
    replay = {
        **envelope_summary(result),
        "judge_consulted": judge.calls > 0,
        "signal_consumed": judge.returns > 0,
        "preflight_skipped_judge": skipped,
        "provider_calls": judge.calls,
        "provider_returns": judge.returns,
        "adapter_initiations": adapter.initiations,
        "synthetic_transport_calls": adapter.counted_transport.calls,
        "pre_dispatch_policy": event["policy"],
        "trace_stage_order": [e["stage"] for e in trace.events],
    }
    return {
        "id": case.id,
        "recorded_signal": case.signal.model_dump(),
        "transport_realization": case.transport,
        "reference_lane": case.reference.model_dump() if case.reference else None,
        "reference_label": "DETERMINISTIC_ENGINEERING_REFERENCE_LANE" if case.reference else None,
        "replay_lane": replay,
        **compare(case.reference, replay),
    }


def source_fingerprints() -> dict[str, str]:
    paths = [
        Path(__file__),
        ROOT / "tests/fixture_transports.py",
        *sorted((ROOT / "src").rglob("*.py")),
    ]
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


async def run_replay(inputs: ReplayInput) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    hashes = source_fingerprints()
    frozen_input = inputs.model_dump_json()
    abort_reason = None
    with OfflineOnly() as guard:
        try:
            for case in inputs.cases:
                if source_fingerprints() != hashes or inputs.model_dump_json() != frozen_input:
                    raise ReplayViolation("INSTRUMENT_OR_INPUT_CHANGED")
                rows.append(await _execute_case(case))
            if source_fingerprints() != hashes or inputs.model_dump_json() != frozen_input:
                raise ReplayViolation("INSTRUMENT_OR_INPUT_CHANGED")
            if guard.blocked_attempts:
                raise ReplayViolation("NETWORK_ATTEMPT")
        except ReplayViolation as exc:
            abort_reason = str(exc)  # Instrument-authored codes only, never provider bodies.
        except Exception:
            abort_reason = "UNEXPECTED_REPLAY_ERROR"
    return {
        "schema_version": "civicgate.recorded-replay.v1",
        "status": "REPLAY_ABORTED" if abort_reason else "COMPLETED_OFFLINE_REPLAY",
        "abort_reason": abort_reason,
        "intended_count": len(inputs.cases),
        "completed_count": len(rows),
        "uncompleted_count": len(inputs.cases) - len(rows),
        "completed_case_counters": {
            field: sum(row["replay_lane"][field] for row in rows)
            for field in (
                "provider_calls",
                "provider_returns",
                "adapter_initiations",
                "synthetic_transport_calls",
            )
        },
        "external_calls": 0,
        "blocked_network_attempts": guard.blocked_attempts,
        "authority_difference_counts": dict(
            Counter(row["authority_difference_class"] for row in rows)
        ),
        "authority_direction_counts": dict(Counter(row["authority_direction"] for row in rows)),
        "source_sha256": hashes,
        "cases": rows,
        "conditions": {
            "fresh_gateway_per_case": True,
            "threshold": 0.85,
            "require_judge": True,
            "enable_agent_k": True,
            "default_transport_source": "civicgate.demo.fixture_transport",
            "stateful_transport_source": "tests.fixture_transports",
        },
        "limitations": [
            "Synthetic transports only; no model is sampled or external data retrieved.",
            "Only the five recorded fields are replayed. Native rationale default is not historical evidence.",
            "Missing reference observations produce NOT_COMPARABLE, not an invented baseline.",
            "An aborted case may have made offline calls not included in completed-case counters.",
            "Contractive does not mean correct or safe; no aggregate safety score.",
        ],
    }


def outside_repository(path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Reviewed replay inputs and outputs must remain outside the repository")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="reviewed five-field signal fixtures"
    )
    parser.add_argument("--output", type=Path, required=True, help="new local-only output file")
    args = parser.parse_args(argv)
    try:
        source, target = outside_repository(args.input), outside_repository(args.output)
        with source.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("Input exceeds bound")
        inputs = ReplayInput.model_validate_json(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation rejects accidental overwrite before any replay starts.
        with target.open("x", encoding="utf-8") as stream:
            report = asyncio.run(run_replay(inputs))
            report["input_sha256"] = hashlib.sha256(raw).hexdigest()
            json.dump(report, stream, indent=2)
            stream.write("\n")
        print(
            f"{report['status']}: {report['completed_count']}/{report['intended_count']} cases; zero external calls"
        )
        return 1 if report["abort_reason"] else 0
    except (OSError, ValueError, ReplayViolation):
        # ValidationError details could echo unreviewed file content. Do not print them.
        print("Replay refused: check the input contract and new output path; no fallback used.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
