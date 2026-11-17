from pathlib import Path

from . import host_gate71 as gate
from . import util71 as p
from .capture_host71 import DormantCapturingExchange


class HostCapture71(DormantCapturingExchange):
    def __init__(self, budget, observation, provider, fixture, **kwargs):
        gate.require_release()
        p.require(kwargs.get("mode") == "LIVE" and fixture is None, "GENUINE_HOST_MODE_REQUIRED")
        admission = kwargs.get("admission")
        admission.check_stage("judge" if provider == "judge" else "planner")
        read = Path(budget.profile.custody_root)
        session = p.parse(p.read(read / "session.json"))
        p.require(
            session.get("fresh_host71") is True
            and session["run_id"] == budget.run_id
            and observation.startswith(budget.run_id + "_"),
            "HOST_CAPTURE_SCOPE",
        )
        super().__init__(
            budget,
            observation,
            provider,
            fixture,
            capture_root=read / "captured-wires" / ("judge" if provider == "judge" else "planner"),
            **kwargs,
        )

    async def post(self, payload, headers):
        role = "judge" if self.provider == "judge" else "planner"
        self.admission.check_stage(role)
        allowed = (
            {"model", "messages", "max_completion_tokens", "response_format"}
            if role == "judge"
            else {
                "model",
                "messages",
                "max_tokens",
                "temperature",
                "top_p",
                "stream",
                "chat_template_kwargs",
                "tools",
                "tool_choice",
                "response_format",
            }
        )
        p.require(set(payload) <= allowed, "UNAPPROVED_REQUEST_FIELDS")
        p.require(payload.get("stream", False) is False, "STREAM_HOLD")
        return await super().post(payload, headers)
