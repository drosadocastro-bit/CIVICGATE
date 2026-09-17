from typing import Protocol

from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal


class AgentModel(Protocol):
    async def propose(self, request: str) -> Proposal: ...


class JudgeModel(Protocol):
    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal: ...


class UnavailableProvider:
    async def propose(self, request: str) -> Proposal:
        raise RuntimeError("Model not configured")

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        return JudgeSignal()
