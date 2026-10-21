"""Bounded exact FAA monetary value and content identity; no authority or I/O.

FAA-C1-MONEY-v1: abs(amount) < 1e24, at most 38 coefficient digits,
12 effective fractional places, 96-character tokens, explicit exponents +/-38.
Strict numeric strings retain the original FAA fixture contract. Byte identity
is separate: 1, 1.00, 1e0 and "1" intentionally share a monetary identity.
"""

import hashlib
import json
import re
from decimal import Decimal
from typing import Any

MONEY_VERSION = "FAA-C1-MONEY-v1"
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE]([+-]?[0-9]+))?", re.ASCII)


def decimal_token(token: str) -> Decimal:
    """Parse the original token without rounding or an intermediate float."""
    match = _NUMBER.fullmatch(token) if len(token) <= 96 else None
    if match is None or (match[1] is not None and abs(int(match[1])) > 38):
        raise ValueError("FAA monetary token or exponent unsupported")
    return Decimal(token)


def integer_token(token: str) -> int:
    if len(token) > 96:
        raise ValueError("FAA JSON integer token too long")
    return int(token)


def exact_amount(value: Any) -> Decimal:
    if type(value) is str:
        value = decimal_token(value)
    elif type(value) is int:
        value = decimal_token(str(value))
    elif type(value) is not Decimal:
        raise ValueError("FAA amount requires exact numeric evidence; float unsupported")
    if not value.is_finite():
        raise ValueError("FAA amount must be finite")
    sign, coefficient, exponent = value.as_tuple()
    if not isinstance(exponent, int) or abs(exponent) > 38 or len(coefficient) > 38:
        raise ValueError("FAA monetary precision unsupported")
    if value.copy_abs() >= Decimal("1e24"):
        raise ValueError("FAA monetary magnitude unsupported")
    if value.is_zero():
        return Decimal(0)
    digits = list(coefficient)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    if exponent < -12:
        raise ValueError("FAA monetary scale unsupported")
    # Tuple construction and fixed-point formatting are context-independent.
    return Decimal((sign, tuple(digits), exponent))


def amount_text(value: Any) -> str:
    return format(exact_amount(value), "f")


def _plain_json(value: Any) -> None:
    if type(value) in {str, int, bool, type(None)}:
        return
    if type(value) is list:
        for item in value:
            _plain_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _plain_json(item)
        return
    raise ValueError("Unsupported FAA canonical JSON value")


def canonical_response_bytes(obj: Any) -> bytes:
    """Normalize only Award Amount; other fields remain part of content identity."""
    if type(obj) is not dict or type(obj.get("results")) is not list:
        raise ValueError("FAA response object required")
    rows = []
    for row in obj["results"]:
        if type(row) is not dict or "Award Amount" not in row:
            raise ValueError("FAA amount missing")
        rows.append(dict(row) | {"Award Amount": amount_text(row["Award Amount"])})
    canonical_obj = dict(obj) | {"results": rows}
    _plain_json(canonical_obj)
    return json.dumps(
        canonical_obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def response_fingerprint(obj: Any) -> str:
    return hashlib.sha256(
        MONEY_VERSION.encode("ascii") + b"\n" + canonical_response_bytes(obj)
    ).hexdigest()
