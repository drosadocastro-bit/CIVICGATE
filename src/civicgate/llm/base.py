from typing import Protocol

from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal


class AgentModel(Protocol):
    async def propose(self, request: str) -> Proposal: ...


class JudgeModel(Protocol):
    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal: ...


class JudgeProvider(JudgeModel, Protocol):
    """Semantic signal provider. It can advise policy but never issues authority."""

    @property
    def provider_name(self) -> str: ...


class UnavailableProvider:
    async def propose(self, request: str) -> Proposal:
        raise RuntimeError("Model not configured")

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        return JudgeSignal()
