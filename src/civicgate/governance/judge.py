import asyncio

from civicgate.llm.base import JudgeModel
from civicgate.models.governance import JudgeSignal
from civicgate.models.requests import Proposal


async def assess(provider: JudgeModel, request: str, proposal: Proposal) -> JudgeSignal:
    try:
        async with asyncio.timeout(30):
            signal = await provider.assess(request, proposal)
            return JudgeSignal.model_validate(signal.model_dump())
    except Exception:
        # Provider bodies may contain secrets; preserve failure as a component state.
        return JudgeSignal(rationale="Semantic provider failed or returned an invalid response")
