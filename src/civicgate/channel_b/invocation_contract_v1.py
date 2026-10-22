"""Trusted startup data/routing selection, never policy or caller authority."""

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pydantic import BaseModel

from civicgate.adapters.usaspending import AdapterCall, USAspending
from civicgate.models.requests import TOOLS

FindHandler = Callable[[USAspending, BaseModel], Awaitable[AdapterCall]]
ResultValidator = Callable[[BaseModel, AdapterCall], None]


def _schema(model: type[BaseModel]) -> str:
    return hashlib.sha256(
        json.dumps(
            model.model_json_schema(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class InvocationContract:
    """Only the trusted host composition supplies this object at startup.

    A caller possessing arbitrary Python execution is outside this boundary.
    No MCP input, model output or hash creates a contract or execution authority.
    Only find_federal_awards may differ; three other schemas remain legacy.
    """

    version: str
    find_model: type[BaseModel]
    find_literal_fields: tuple[str, ...]
    find_handler: FindHandler
    validate_find_result: ResultValidator
    registry: Mapping[str, type[BaseModel]] = field(init=False, repr=False)
    _schemas: tuple[tuple[str, str], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.version) is not str
            or not self.version
            or not isinstance(self.find_model, type)
            or not issubclass(self.find_model, BaseModel)
            or type(self.find_literal_fields) is not tuple
            or any(f not in {"awarding_agency", "recipient_name"} for f in self.find_literal_fields)
            or not callable(self.find_handler)
            or not callable(self.validate_find_result)
        ):
            raise ValueError("Invalid trusted composition contract")
        registry = MappingProxyType(dict(TOOLS) | {"find_federal_awards": self.find_model})
        object.__setattr__(self, "registry", registry)
        object.__setattr__(
            self, "_schemas", tuple((tool, _schema(model)) for tool, model in registry.items())
        )

    def validate(self) -> None:
        if tuple((tool, _schema(model)) for tool, model in self.registry.items()) != self._schemas:
            raise ValueError("Trusted contract schema changed")
