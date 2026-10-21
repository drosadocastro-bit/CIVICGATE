"""Required FAA properties, deliberately separate unmodified failure assertions.

Run explicitly. These failures are integration blockers, not xfails.
No real API request: Capture requires httpx.MockTransport.
"""

from experiments.b2b_faa_001.test_contract_characterization import (
    FAA,
    OTHER,
    Capture,
    arguments,
    response,
)


async def test_required_faa_subtier_is_not_supported_by_existing_gateway() -> None:
    capture = Capture(response())
    await capture.gateway(arguments())
    assert capture.payloads[0]["filters"]["agencies"] == [
        {"type": "awarding", "tier": "subtier", "name": FAA}
    ]


async def test_required_wrong_subtier_attribution_is_not_released() -> None:
    capture = Capture(response(OTHER, FAA))
    envelope, _ = await capture.gateway(arguments())
    assert envelope.result is None, "Wrong awarding subtier must not be released as FAA awards"
