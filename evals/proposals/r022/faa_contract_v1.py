"""Experimental explicit FAA/FY2026/PR READ contract; no authority issuer.

Synthetic DATA-01 award dates only. This is not an assertion about live
USAspending date defaults, new-award events, transaction activity or spending.
Only a trusted local composition selects the InvocationContract at startup.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from civicgate.adapters.usaspending import AdapterCall, USAspending
from civicgate.channel_b.invocation_contract_v1 import InvocationContract
from civicgate.models.provenance import fingerprint
from civicgate.models.requests import Text

PROFILE_ID = "FAA_FY2026_PR_READ_v1"
FAA = "Federal Aviation Administration"
DOT = "Department of Transportation"
ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
FIELDS = (
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Funding Sub Agency",
    "generated_internal_id",
    "Award Date",
    "Fiscal Year",
    "Place of Performance State Code",
    "Award Type",
)


class FaaFy2026PrReadV1(BaseModel):
    """All fixed scope fields are required; omission is not a legacy fallback."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)

    profile_id: Literal["FAA_FY2026_PR_READ_v1"]
    awarding_agency: Literal["Federal Aviation Administration"]
    agency_type: Literal["awarding"]
    agency_tier: Literal["subtier"]
    agency_toptier_name: Literal["Department of Transportation"]
    fiscal_year: Literal[2026]
    start_date: Literal["2025-10-01"]
    end_date: Literal["2026-09-30"]
    date_semantics: Literal["AWARD_DATE_SYNTHETIC_ONLY"]
    state_code: Literal["PR"]
    award_types: tuple[Literal["A", "B", "C", "D"], ...] = Field(min_length=1, max_length=4)
    page: Literal[1]
    limit: int = Field(ge=1, le=20)
    subawards: Literal[False]
    recipient_name: Text | None = None

    @field_validator("award_types", mode="before")
    @classmethod
    def explicit_types(cls, value: Any) -> tuple[str, ...]:
        if type(value) not in {tuple, list} or any(type(v) is not str for v in value):
            raise ValueError("Explicit contract-type sequence required")
        return tuple(value)

    @field_validator("fiscal_year", "page", "limit", mode="before")
    @classmethod
    def exact_integer(cls, value: Any) -> int:
        if type(value) is not int:
            raise ValueError("Exact integer required")
        return value

    @field_validator("subawards", mode="before")
    @classmethod
    def prime_only(cls, value: Any) -> bool:
        if value is not False:
            raise ValueError("Explicit prime-awards false required")
        return False

    @model_validator(mode="after")
    def no_duplicate_types(self) -> Self:
        if len(self.award_types) != len(set(self.award_types)):
            raise ValueError("Duplicate award types unsupported")
        return self

    def payload(self) -> dict[str, Any]:
        scope = type(self).model_validate(self.model_dump(mode="json"))
        filters: dict[str, Any] = {
            "time_period": [{"start_date": scope.start_date, "end_date": scope.end_date}],
            "award_type_codes": list(scope.award_types),
            "agencies": [
                {
                    "type": scope.agency_type,
                    "tier": scope.agency_tier,
                    "name": scope.awarding_agency,
                    "toptier_name": scope.agency_toptier_name,
                }
            ],
            "place_of_performance_locations": [{"country": "USA", "state": scope.state_code}],
        }
        if scope.recipient_name is not None:
            filters["recipient_search_text"] = [scope.recipient_name]
        return {
            "filters": filters,
            "fields": list(FIELDS),
            "page": scope.page,
            "limit": scope.limit,
            "sort": "Award Amount",
            "order": "desc",
            "subawards": False,
        }

    def wire_bytes(self) -> bytes:
        return json.dumps(
            self.payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()

    def query_fingerprint(self) -> str:
        return fingerprint({"method": "POST", "url": ENDPOINT, "body": self.payload()})


async def _find(adapter: USAspending, args: BaseModel) -> AdapterCall:
    from evals.proposals.r022.faa_adapter_v1 import FaaProfileFixtureAdapter

    if not isinstance(adapter, FaaProfileFixtureAdapter):
        raise ValueError("R022 synthetic profile adapter required")
    return await adapter.find_profile(
        FaaFy2026PrReadV1.model_validate(args.model_dump(mode="json"))
    )


def _validate(args: BaseModel, call: AdapterCall) -> None:
    from evals.proposals.r022.faa_adapter_v1 import validate_profile_result

    validate_profile_result(FaaFy2026PrReadV1.model_validate(args.model_dump(mode="json")), call)


FAA_FY2026_PR_CONTRACT = InvocationContract(
    version=PROFILE_ID,
    find_model=FaaFy2026PrReadV1,
    find_literal_fields=("awarding_agency", "recipient_name"),
    find_handler=_find,
    validate_find_result=_validate,
)


def example_query(**changes: Any) -> dict[str, Any]:
    """Synthetic test factory; never caller authority or implicit server defaults."""
    return {
        "profile_id": PROFILE_ID,
        "awarding_agency": FAA,
        "agency_type": "awarding",
        "agency_tier": "subtier",
        "agency_toptier_name": DOT,
        "fiscal_year": 2026,
        "start_date": "2025-10-01",
        "end_date": "2026-09-30",
        "date_semantics": "AWARD_DATE_SYNTHETIC_ONLY",
        "state_code": "PR",
        "award_types": ["A", "B", "C", "D"],
        "page": 1,
        "limit": 20,
        "subawards": False,
        **changes,
    }
