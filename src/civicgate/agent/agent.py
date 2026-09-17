import asyncio
from typing import Protocol

from civicgate.llm.base import AgentModel
from civicgate.models.requests import Proposal
from civicgate.models.responses import Envelope


class GovernedTools(Protocol):
    async def call(
        self, request: str, proposal: Proposal, planning_failed: bool = False
    ) -> Envelope: ...


class CivicGateAgent:
    """Agent has only the governed interface, never an adapter or HTTP client."""

    def __init__(self, model: AgentModel, tools: GovernedTools) -> None:
        self.model = model
        self.tools = tools

    async def run(self, request: str) -> Envelope:
        try:
            if not 0 < len(request.strip()) <= 4000:
                raise ValueError("Request must contain 1 to 4000 characters")
            async with asyncio.timeout(30):
                proposal = await self.model.propose(request)
            proposal = Proposal.model_validate(proposal.model_dump())
        except Exception:
            return await self.tools.call(
                request,
                Proposal(
                    tool="resolve_federal_recipient", arguments={"recipient_name": "unresolved"}
                ),
                planning_failed=True,
            )
        return await self.tools.call(request, proposal)
