"""Fixed public READ registry only."""

from types import MappingProxyType

from civicgate.models.requests import TOOLS


def owner_registry(owner):
    if owner != "PUBLIC_API_READ":
        raise ValueError("PUBLIC_READ_ONLY")
    return MappingProxyType(dict(TOOLS))
