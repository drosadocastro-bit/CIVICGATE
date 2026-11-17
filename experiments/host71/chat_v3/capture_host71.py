"""Dormant capture wrapper over existing genuine Exchange LIVE branch.
The release gate is unconditionally closed; tests replace it and only inject MockTransport.
No runtime option, environment variable or HTTP field can open the gate.
"""

import asyncio
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from . import util71 as n
from . import util71 as p
from .providers_v3 import MODE, DemoError, Exchange


def preflight(requests=None):
    contract = "NOT_CHECKED"
    if requests is not None:
        p.require(
            type(requests) is dict and set(requests) == {"planner", "judge", "answer"},
            "REQUEST_SET_HOLD",
        )
        for role, request in requests.items():
            p.require(
                type(request) is dict and len(p.canonical(request)) <= 32768, "REQUEST_SIZE_HOLD"
            )
            model = "gpt-5.6-luna" if role == "judge" else "nvidia/nemotron-3.5-lightning-30b-a3b"
            p.require(request.get("model") == model, "REQUEST_MODEL_HOLD")
            key = "max_completion_tokens" if role == "judge" else "max_tokens"
            p.require(
                type(request.get(key)) is int
                and request[key] == (2000 if role == "answer" else 512),
                "REQUEST_TOKEN_HOLD",
            )
            p.require(request.get("stream", False) is False, "STREAM_HOLD")
            if role != "planner":
                p.require("tools" not in request and "tool_choice" not in request, "TOOLS_HOLD")
            if role == "answer":
                p.require(request.get("reasoning_budget") == 256, "REASONING_HOLD")
        contract = "BOUNDED_REQUEST_FIELDS_CHECKED_NOT_AUTHORIZATION"
    return {
        "request_contract": contract,
        "stage_attempt_limits": {"planner": 1, "judge": 1, "public_read": 1, "answer": 1},
        "requested_output_tokens": {"planner": 512, "judge": 512, "answer": 2000},
        "proposed_judge_usd_limit": "0.05_NOT_APPROVED_NOT_ENFORCED",
        "monetary_cap_enforced": False,
        "cost_status": "HOLD_PENDING_HOST_APPROVAL_AND_COST_CONTROLS",
        "live_allowed": False,
        "retry_allowed": False,
    }


def observed(raw, status, provider):
    try:
        env = p.parse(raw)
        choice = env.get("choices", [{}])[0]
        message = choice.get("message", {})
        model = env.get("model")
        finish = choice.get("finish_reason")
        usage = env.get("usage")
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, AttributeError):
        model = finish = usage = None
        message = {}
    expected = "gpt-5.6-luna" if provider == "judge" else "nvidia/nemotron-3.5-lightning-30b-a3b"
    return {
        "http_status": status,
        "body_sha256": p.sha(raw),
        "body_bytes": len(raw),
        "returned_model": model if isinstance(model, str) else None,
        "model_identity": "MATCH"
        if model == expected
        else "MISSING"
        if model is None
        else "MISMATCH",
        "completion": "COMPLETE" if finish in ("stop", "tool_calls") else "INCOMPLETE",
        "refusal": "ABSENT_OR_NULL"
        if isinstance(message, dict) and message.get("refusal") is None
        else "PRESENT",
        "usage": "KNOWN"
        if type(usage) is dict
        and all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("prompt_tokens", "completion_tokens")
        )
        else "UNKNOWN",
        "typed_schema": "NOT_PARSED",
        "contract": "PASS" if status == 200 else "FAIL",
        "errors": [],
    }


def release_enabled():
    from .host_gate71 import release_enabled as check

    return check()


class DormantCapturingExchange(Exchange):
    def __init__(self, *args, capture_root, **kwargs):
        # Guard before budget/profile/transport/secret side effects.
        if kwargs.get("mode", MODE) != MODE and not release_enabled():
            raise DemoError("LIVE_HARD_BLOCKED")
        super().__init__(*args, **kwargs)
        self.capture_root = Path(capture_root)
        if not self.capture_root.is_absolute():
            raise ValueError("ABSOLUTE_FRESH_CAPTURE_REQUIRED")

    async def _send(self, request):
        if self.mode != MODE and not release_enabled():
            raise DemoError("LIVE_HARD_BLOCKED")
        if not self.facts["lease_consumed"] or self._wire_entered:
            raise DemoError("CAPTURE_UNRESERVED_OR_USED")
        root = p.safe(self.capture_root).resolve()
        custody = p.safe(Path(self.budget.profile.custody_root)).resolve()
        p.require(
            root.is_relative_to(custody) and root != custody, "CAPTURE_CUSTODY_SCOPE_REQUIRED"
        )
        # Exclusive directory is the durable capture reservation; no overwrite/resume.
        root.mkdir(parents=False, exist_ok=False)
        secrets = [
            v.encode()
            for k, v in request.headers.items()
            if k.lower() in ("authorization", "x-api-key", "api-key")
        ]
        secrets += [v.split(b" ", 1)[1] for v in list(secrets) if b" " in v]

        def sensitive(raw):
            return any(s and s in raw for s in secrets)

        raw = bytearray()
        response = None
        try:
            n._write(
                root / "reserved.json",
                p.canonical(
                    {
                        "state": "CONSUMED_OUTCOME_UNKNOWN",
                        "request_sha256": p.sha(request.content),
                        "observation": self.observation,
                        "provider": self.provider,
                        "provenance": "HOST71_PROVIDER_ATTEMPT"
                        if self.mode == "LIVE"
                        else "OFFLINE_TRANSPORT_SEAM_TEST",
                    }
                ),
            )
            if sensitive(request.content):
                raise DemoError("SENSITIVE_CAPTURE_WITHHELD")
            n._write(root / "request.bin", request.content)
            # Existing single-send boundary: mode LIVE executes its genuine branch.
            # Current release gate makes that unreachable outside isolated monkeypatched tests.
            response = await super()._send(request)
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > 65536:
                    raise DemoError("RESPONSE_SIZE_REJECTED")
                raw.extend(chunk)
            if sensitive(raw):
                raise DemoError("SENSITIVE_CAPTURE_WITHHELD")
            n._write(root / "response.bin", bytes(raw))
            facts = observed(bytes(raw), response.status_code, self.provider)
            ack = self.budget.record_response_facts(
                observation_id=self.observation,
                role="judge" if self.provider == "judge" else "planner",
                request_sha256=p.sha(request.content),
                facts=facts,
            )
            n._write(
                root / "observed.json",
                p.canonical(
                    {
                        "state": "BODY_OBSERVED_NOT_TYPED",
                        "facts": facts,
                        "ack": asdict(ack),
                        "observed_ns": time.time_ns(),
                    }
                ),
            )
            return httpx.Response(response.status_code, content=bytes(raw))
        except BaseException as error:
            # No exception strings/headers. Sensitive echoes never become raw artifacts.
            if raw and not sensitive(raw) and not (root / "response.bin").exists():
                n._write(root / "partial.bin", bytes(raw))
            n._write(
                root / "unknown.json",
                p.canonical(
                    {
                        "state": "UNKNOWN_CONSUMED",
                        "retry_allowed": False,
                        "capture_withheld_sensitive": sensitive(raw),
                    }
                ),
            )
            if isinstance(error, asyncio.CancelledError):
                raise asyncio.CancelledError() from None
            raise DemoError("CAPTURE_OR_DELIVERY_UNKNOWN") from None
        finally:
            if response is not None:
                await response.aclose()
