"""Existing Granite serializer/parser with an immutable host-selected registry."""

import json
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from civicgate.llm.live import (
    PLANNER_SYSTEM_PROMPT,
    GranitePlanner,
    ModelTelemetry,
    ProviderError,
    _content_json,
    _parse_model,
)
from civicgate.models.requests import Proposal


class ScopedGranitePlanner(GranitePlanner):
    def __init__(self, *args: Any, registry: Mapping[str, type[BaseModel]], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.registry = MappingProxyType(dict(registry))

    async def propose(self, request: str) -> Proposal:
        schemas = {tool: model.model_json_schema() for tool, model in self.registry.items()}
        prompt = (
            PLANNER_SYSTEM_PROMPT
            + " Registered tool schemas: "
            + json.dumps(schemas, sort_keys=True)
        )
        started = time.perf_counter()
        try:
            body, usage = await self.client.post(
                "/chat/completions",
                headers={"Content-Type": "application/json"},
                payload={
                    "model": self.model,
                    "temperature": 0,
                    "top_p": 1,
                    "max_tokens": 512,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": request},
                    ],
                },
            )
            proposal = _parse_model(_content_json(body, self.protocol), Proposal)
            self.last_telemetry = ModelTelemetry(
                provider="lm_studio",
                model=self.model,
                role="planner",
                latency_ms=(time.perf_counter() - started) * 1000,
                prompt_tokens=usage.get("prompt_tokens")
                if isinstance(usage.get("prompt_tokens"), int)
                else None,
                completion_tokens=usage.get("completion_tokens")
                if isinstance(usage.get("completion_tokens"), int)
                else None,
            )
            return proposal
        except ProviderError as exc:
            self.last_telemetry = ModelTelemetry(
                "lm_studio",
                self.model,
                "planner",
                (time.perf_counter() - started) * 1000,
                error_code=exc.code,
            )
            raise
