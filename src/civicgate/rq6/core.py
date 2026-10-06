"""Shared, side-effect-free RQ6 primitives. No production initialization on import."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


class RQ6Error(ValueError):
    """A stop-gate with a stable code; never includes private evidence values."""


class ExactNumber(Decimal):
    """A JSON number retaining its original exponent and decimal representation."""

    literal: str

    def __new__(cls, literal: str) -> ExactNumber:
        require(
            re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", literal)
            is not None,
            "INVALID_NUMBER_LITERAL",
        )
        number = super().__new__(cls, literal)
        number.literal = literal
        return number


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RQ6Error(code)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exact_json(value: Any) -> bytes:
    """Serialize evidence without normalizing text, flag arrays or decimal precision.

    Decimal parsed from JSON retains its source decimal scale. Floats supplied by
    callers retain Python's round-trip representation; they cannot recover source
    digits already lost before this boundary. Commitment metadata uses the stricter
    canonical encoder in crypto.py, which rejects all non-integer numbers.
    """
    if value is None:
        return b"null"
    if type(value) is bool:
        return b"true" if value else b"false"
    if type(value) is int:
        return str(value).encode("ascii")
    if isinstance(value, ExactNumber):
        require(value.is_finite(), "NONFINITE_NUMBER")
        return value.literal.encode("ascii")
    if isinstance(value, Decimal):
        require(value.is_finite(), "NONFINITE_NUMBER")
        return str(value).encode("ascii")
    if type(value) is float:
        return json.dumps(value, allow_nan=False).encode("ascii")
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False).encode("utf-8")
    if type(value) is list:
        return b"[" + b",".join(exact_json(item) for item in value) + b"]"
    if type(value) is dict:
        require(all(type(key) is str for key in value), "NONSTRING_OBJECT_KEY")
        return (
            b"{"
            + b",".join(exact_json(key) + b":" + exact_json(value[key]) for key in sorted(value))
            + b"}"
        )
    raise RQ6Error("UNSUPPORTED_JSON_TYPE")


def decode_exact(data: bytes) -> Any:
    """Reject duplicate object keys and preserve decimal numbers at ingestion."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_OBJECT_KEY")
            result[key] = value
        return result

    def invalid_constant(_: str) -> Any:
        raise RQ6Error("NONFINITE_NUMBER")

    return json.loads(
        data, parse_float=ExactNumber, object_pairs_hook=pairs, parse_constant=invalid_constant
    )


@dataclass(frozen=True)
class ArtifactSnapshot:
    """Immutable canonical evidence bytes. Accessors return fresh decoded objects."""

    kind: str
    payload_bytes: bytes
    sha256: str

    @classmethod
    def build(cls, kind: str, payload: dict[str, Any]) -> ArtifactSnapshot:
        encoded = exact_json(payload)
        return cls(kind, encoded, sha256(encoded))

    def data(self) -> dict[str, Any]:
        require(sha256(self.payload_bytes) == self.sha256, "ARTIFACT_HASH_MISMATCH")
        result = decode_exact(self.payload_bytes)
        require(type(result) is dict, "ARTIFACT_NOT_OBJECT")
        return dict(result)
