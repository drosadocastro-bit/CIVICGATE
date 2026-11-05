"""Host-only preparation for an optional local Granite Chat planner.

The MINI10 web/API surface cannot construct this configuration.  The synthetic
Chat composition does not call this factory.  Runtime/model availability must
be observed separately before a human may activate it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from civicgate.llm.live import GranitePlanner, ProviderError, _BoundedClient


class _Mini10ExactModelClient(_BoundedClient):
    """One-attempt client that admits only the host-selected Granite identity."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        super().__init__(
            base_url,
            local=True,
            timeout=timeout,
            transport=transport,
            max_attempts=1,
        )
        self._model = model

    async def post(
        self, path: str, *, headers: dict[str, str], payload: dict[str, object]
    ) -> tuple[dict[str, object], dict[str, object]]:
        body, usage = await super().post(path, headers=headers, payload=payload)
        if body.get("model") != self._model:
            raise ProviderError(
                "MODEL_IDENTITY_MISMATCH",
                "Granite provider did not return the exact requested model identity",
            )
        return body, usage


@dataclass(frozen=True, slots=True)
class LocalGraniteChatConfig:
    base_url: str
    model: str
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.port
            or parsed.path.rstrip("/") != "/v1"
        ):
            raise ValueError("MINI10_GRANITE_LOOPBACK_ENDPOINT_REQUIRED")
        if (
            not self.model
            or self.model != self.model.strip()
            or len(self.model) > 200
            or any(ord(character) < 32 for character in self.model)
        ):
            raise ValueError("MINI10_GRANITE_MODEL_ID_REQUIRED")
        if (
            type(self.timeout_seconds) not in {int, float}
            or not math.isfinite(self.timeout_seconds)
            or not 1 <= self.timeout_seconds <= 30
        ):
            raise ValueError("MINI10_GRANITE_TIMEOUT_INVALID")


def prepare_local_granite_planner(
    config: LocalGraniteChatConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GranitePlanner:
    """Build a single-attempt exact-identity planner; this does not activate it."""

    if type(config) is not LocalGraniteChatConfig:
        raise TypeError("Trusted host Granite configuration required")
    planner = GranitePlanner(
        config.base_url,
        config.model,
        timeout=float(config.timeout_seconds),
        metadata={
            "composition": "MINI10_OPTIONAL_LOCAL_GRANITE_PREPARED_NOT_ACTIVATED",
            "host_selected": True,
            "fallback": False,
        },
        transport=transport,
    )
    planner.client = _Mini10ExactModelClient(
        config.base_url,
        config.model,
        timeout=float(config.timeout_seconds),
        transport=transport,
    )
    return planner
