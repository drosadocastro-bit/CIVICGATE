"""Explicit test provider. No claims of LLM performance or general NLP coverage."""

import re

from civicgate.governance.authority import denied_reasons
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal


class MockProvider:
    @property
    def provider_name(self) -> str:
        return "mock"

    async def propose(self, request: str) -> Proposal:
        match = re.search(r"recipient (.+?) in Puerto Rico during FY(\d{4})", request, re.I)
        if match:
            year = int(match[2])
            return Proposal(
                tool="find_federal_awards",
                arguments={
                    "recipient_name": match[1],
                    "state_code": "PR",
                    "start_date": f"{year - 1}-10-01",
                    "end_date": f"{year}-09-30",
                    "limit": 10,
                },
            )
        if "acme" in request.casefold():
            return Proposal(tool="resolve_federal_recipient", arguments={"recipient_name": "Acme"})
        return Proposal(tool="find_federal_awards", arguments={})

    async def assess(self, request: str, proposal: Proposal) -> JudgeSignal:
        return JudgeSignal(
            classification="POSSIBLE_AUTHORITY_OVERREACH"
            if denied_reasons(request)
            else "IN_SCOPE",
            confidence=0.99,
            rationale="Explicit deterministic test fixture signal; not an LLM assessment",
            available=True,
            provider="mock",
        )


class MockJudgeProvider(MockProvider):
    """Named semantic-jury fixture provider for benchmark matrix J1."""


class MockAgentProvider(MockProvider):
    """Named deterministic planner fixture provider for offline tests."""
