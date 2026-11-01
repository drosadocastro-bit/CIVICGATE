"""EVAL-002B-R1 offline cost interface; no prices or token ceilings are assumed.

Synthetic liability units test transactional resource admission. They are not
money, tokens, prices, or evidence of an externally verified provider limit.
This candidate cannot activate a real provider, including with populated inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class MonetaryAdmission:
    """Document supplied monetary inputs without granting network authority."""

    currency: str | None = None
    budget_limit: str | None = None
    input_price_per_token: str | None = None
    output_price_per_token: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    provenance: str | None = None

    def document(self) -> dict[str, Any]:
        missing = []
        for name in ("budget_limit", "input_price_per_token", "output_price_per_token"):
            value = getattr(self, name)
            try:
                number = Decimal(value) if type(value) is str else Decimal("NaN")
                valid = number.is_finite() and number >= 0
                if name == "budget_limit":
                    valid = valid and number > 0
            except (InvalidOperation, ValueError):
                valid = False
            if not valid:
                missing.append(name)
        for name in ("max_input_tokens", "max_output_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                missing.append(name)
        if not self.currency:
            missing.append("currency")
        if not self.provenance:
            missing.append("provenance")
        return {
            "mode": "MONETARY_INTERFACE_ONLY",
            "admission_state": "BLOCKED",
            "reason": "LIVE_PROVIDER_ACTIVATION_NOT_IMPLEMENTED",
            "verified_limits_state": "UNKNOWN",
            "missing_or_invalid_inputs": sorted(missing),
            "supplied_provenance_is_external_verification": False,
            "real_provider_activation": False,
        }


@dataclass(frozen=True)
class SyntheticLiabilityPolicy:
    """Explicitly nonmonetary, upper-bound units reserved without refunds."""

    total_limit_units: int
    per_attempt_upper_bound_units: dict[str, int] = field(
        default_factory=lambda: {"planner": 1, "judge": 1}
    )
    provenance: str = "SYNTHETIC_TEST_ONLY_NOT_EXTERNAL_VERIFICATION"

    def document(self) -> dict[str, Any]:
        units = self.per_attempt_upper_bound_units
        if type(self.total_limit_units) is not int or self.total_limit_units <= 0:
            raise ValueError("POSITIVE_SYNTHETIC_LIABILITY_LIMIT_REQUIRED")
        if (
            type(units) is not dict
            or set(units) != {"planner", "judge"}
            or any(type(value) is not int or value <= 0 for value in units.values())
        ):
            raise ValueError("POSITIVE_SYNTHETIC_ROLE_UPPER_BOUNDS_REQUIRED")
        if (
            type(self.provenance) is not str
            or not self.provenance.startswith("SYNTHETIC_")
            or len(self.provenance) > 200
            or any(ord(char) < 32 for char in self.provenance)
        ):
            raise ValueError("EXPLICIT_SYNTHETIC_PROVENANCE_REQUIRED")
        return {
            "mode": "SYNTHETIC_NONMONETARY_LIABILITY_UNITS",
            "admission_state": "SYNTHETIC_ONLY",
            "total_limit_units": self.total_limit_units,
            "per_attempt_upper_bound_units": dict(units),
            "provenance": self.provenance,
            "verified_limits_state": "NOT_APPLICABLE_SYNTHETIC",
            "supplied_provenance_is_external_verification": False,
            "real_provider_activation": False,
            "refund_policy": "NO_REFUNDS_INCLUDING_UNKNOWN_OR_NO_SEND",
        }


LiabilityPolicy = MonetaryAdmission | SyntheticLiabilityPolicy


def policy_document(policy: LiabilityPolicy | None) -> dict[str, Any]:
    """Exact supported types prevent approval-like objects granting authority."""
    if policy is None:
        return MonetaryAdmission().document()
    if type(policy) not in {MonetaryAdmission, SyntheticLiabilityPolicy}:
        raise ValueError("SUPPORTED_OFFLINE_LIABILITY_POLICY_REQUIRED")
    return policy.document()
