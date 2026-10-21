"""B2B-FAA-001-C1 v1 query plus Channel B integration wire-validation v1.

No network access, authority issuance, policy implementation or registry mutation.
All scope fields are explicit; a wire payload is a fresh rendering of the same
immutable scope. A matching fingerprint is integrity, not source authentication.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from civicgate.channel_b.faa_money_v1 import (
    amount_text,
    decimal_token,
    exact_amount,
    integer_token,
    response_fingerprint,
)
from civicgate.models.provenance import Provenance, fingerprint
from civicgate.models.requests import AwardType

FAA = "Federal Aviation Administration"
DOT = "Department of Transportation"
ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
VERSION = "B2B-FAA-001-C1-v1"
FIELDS = (
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Funding Sub Agency",
    "generated_internal_id",
)
MAX_BYTES = 2_000_000


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class FaaScopeV1(FrozenContract):
    contract_version: Literal["B2B-FAA-001-C1-v1"]
    method: Literal["POST"]
    endpoint: Literal["https://api.usaspending.gov/api/v2/search/spending_by_award/"]
    awarding_agency: Literal["Federal Aviation Administration"]
    agency_type: Literal["awarding"]
    agency_tier: Literal["subtier"]
    agency_toptier_name: Literal["Department of Transportation"]
    fiscal_year: int = Field(ge=2008, le=9999)
    start_date: date
    end_date: date
    date_semantics: Literal["AWARD_SEARCH_DEFAULT_OVERLAP"]
    award_types: tuple[AwardType, ...] = Field(min_length=1, max_length=12)
    page: int = Field(ge=1, le=1)
    limit: int = Field(ge=1, le=100)
    subawards: Literal[False]
    response_fields: tuple[str, ...]
    sort: Literal["Award Amount"]
    order: Literal["desc"]

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def explicit_date(cls, value: Any) -> date:
        if type(value) is date:
            return value
        if type(value) is not str:
            raise ValueError("Use an explicit ISO calendar date")
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Use YYYY-MM-DD without normalization")
        return parsed

    @field_validator("award_types", "response_fields", mode="before")
    @classmethod
    def immutable_sequence(cls, value: Any) -> tuple[str, ...]:
        if type(value) not in {list, tuple} or any(type(item) is not str for item in value):
            raise ValueError("Use an explicit sequence of strings")
        return tuple(value)

    @field_validator("subawards", mode="before")
    @classmethod
    def prime_only(cls, value: Any) -> bool:
        if value is not False:
            raise ValueError("Prime awards only; explicit false required")
        return False

    @model_validator(mode="after")
    def scope_consistency(self) -> Self:
        if self.start_date != date(self.fiscal_year - 1, 10, 1) or self.end_date != date(
            self.fiscal_year, 9, 30
        ):
            raise ValueError("Dates must express the selected full fiscal year")
        if len(set(self.award_types)) != len(self.award_types):
            raise ValueError("Duplicate award types are unsupported")
        if self.response_fields != FIELDS:
            raise ValueError("Unsupported response projection")
        return self

    def payload(self) -> dict[str, Any]:
        # Revalidate rather than trust a caller's unchecked model_copy/model_construct.
        scope = FaaScopeV1.model_validate(self.model_dump(mode="json"))
        return {
            "filters": {
                "time_period": [
                    {
                        "start_date": scope.start_date.isoformat(),
                        "end_date": scope.end_date.isoformat(),
                    }
                ],
                "award_type_codes": list(scope.award_types),
                "agencies": [
                    {
                        "type": scope.agency_type,
                        "tier": scope.agency_tier,
                        "name": scope.awarding_agency,
                        "toptier_name": scope.agency_toptier_name,
                    }
                ],
            },
            "fields": list(scope.response_fields),
            "page": scope.page,
            "limit": scope.limit,
            "sort": scope.sort,
            "order": scope.order,
            "subawards": scope.subawards,
        }

    def wire_bytes(self) -> bytes:
        return canonical(self.payload()).encode("utf-8")

    def effective_scope_json(self) -> str:
        self.payload()
        return canonical(self.model_dump(mode="json"))

    def query_fingerprint(self) -> str:
        return fingerprint({"method": self.method, "url": self.endpoint, "body": self.payload()})


Nonempty = Annotated[str, Field(min_length=1, max_length=300)]


class AwardRowV1(FrozenContract):
    internal_id: int = Field(ge=0)
    generated_internal_id: Nonempty
    award_id: Nonempty = Field(alias="Award ID")
    recipient_name: Nonempty = Field(alias="Recipient Name")
    award_amount: Decimal = Field(alias="Award Amount")
    awarding_agency: Nonempty = Field(alias="Awarding Agency")
    awarding_sub_agency: Nonempty = Field(alias="Awarding Sub Agency")
    funding_agency: Nonempty = Field(alias="Funding Agency")
    funding_sub_agency: Nonempty = Field(alias="Funding Sub Agency")

    # Documented auxiliary response metadata, never authorization or attribution.
    agency_slug: Nonempty | None = None
    awarding_agency_id: int | None = Field(default=None, ge=0)
    recipient_id: Nonempty | None = None

    @field_validator("award_amount", mode="before")
    @classmethod
    def finite_amount_input(cls, value: Any) -> Decimal:
        return exact_amount(value)

    @field_serializer("award_amount", when_used="json")
    def canonical_amount_output(self, value: Decimal) -> str:
        return amount_text(value)

    @model_validator(mode="after")
    def exact_attribution(self) -> Self:
        for value in (
            self.generated_internal_id,
            self.award_id,
            self.recipient_name,
            self.awarding_agency,
            self.awarding_sub_agency,
            self.funding_agency,
            self.funding_sub_agency,
        ):
            if value != value.strip() or any(ord(char) < 32 for char in value):
                raise ValueError("Missing or unsupported attribution text")
        if (self.awarding_agency, self.awarding_sub_agency) != (DOT, FAA):
            raise ValueError("Record is not attributed to the exact FAA awarding subtier")
        if self.funding_sub_agency == FAA and self.funding_agency != DOT:
            raise ValueError("Contradictory FAA funding parent")
        return self


class PageMetadataV1(FrozenContract):
    page: int = Field(ge=1, le=1)
    hasNext: bool
    last_record_unique_id: int | None = Field(default=None, ge=0)
    last_record_sort_value: str | None = Field(default=None, max_length=300)


class AwardPageV1(FrozenContract):
    spending_level: Literal["awards"]
    limit: int = Field(ge=1, le=100)
    results: tuple[AwardRowV1, ...] = Field(max_length=100)
    page_metadata: PageMetadataV1
    messages: tuple[str, ...] = Field(default=(), max_length=10)

    @field_validator("results", "messages", mode="before")
    @classmethod
    def sequence(cls, value: Any) -> tuple[Any, ...]:
        if type(value) not in {list, tuple}:
            raise ValueError("Expected a response sequence")
        return tuple(value)


class CandidateValidationError(ValueError):
    """No verified candidate page released; does not erase dispatch history."""


@dataclass(frozen=True)
class ValidatedCandidatePage:
    scope_json: str
    records: tuple[AwardRowV1, ...]
    page: int
    limit: int
    truncated: bool
    attribution: Literal["FAA_AWARDED_PAGE", "EMPTY_PAGE"]
    provenance_json: str
    raw_response_sha256: str
    verified_scope: Literal["SYNTHETIC_PROFILE_ONLY"] = "SYNTHETIC_PROFILE_ONLY"
    population_total_established: bool = False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateValidationError("DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise CandidateValidationError("NONFINITE_JSON_VALUE")


def parse_response_bytes(raw: bytes) -> Any:
    """Retain exact decimals from the first parse; shared JSON behavior is unchanged."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise CandidateValidationError("INVALID_RESPONSE_SIZE")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_invalid_constant,
        parse_float=decimal_token,
        parse_int=integer_token,
    )


def validate_synthetic_page(
    scope: FaaScopeV1,
    raw: bytes,
    provenance: Provenance,
    *,
    status_code: int,
    content_type: str,
) -> ValidatedCandidatePage:
    """Offline validator. Externally supplied hashes do not authenticate an origin.

    This accepts only fixture provenance. No production transport or live release
    is provided. A caller must retain initial policy/dispatch evidence separately.
    """
    try:
        scope = FaaScopeV1.model_validate(scope.model_dump(mode="json"))
        provenance = Provenance.model_validate(provenance.model_dump(mode="json"))
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
            raise CandidateValidationError("INVALID_RESPONSE_SIZE")
        if type(status_code) is not int or status_code != 200 or content_type != "application/json":
            raise CandidateValidationError("UNSUPPORTED_HTTP_RESPONSE")
        obj = parse_response_bytes(raw)
        page = AwardPageV1.model_validate(obj)
        if page.limit != scope.limit or page.page_metadata.page != scope.page:
            raise CandidateValidationError("PAGE_SCOPE_MISMATCH")
        if len(page.results) > scope.limit or page.messages:
            raise CandidateValidationError("EXCESS_ROWS_OR_UPSTREAM_WARNING")
        if not page.results and page.page_metadata.hasNext:
            raise CandidateValidationError("EMPTY_TRUNCATED_PAGE")
        if len({r.internal_id for r in page.results}) != len(page.results) or len(
            {r.generated_internal_id for r in page.results}
        ) != len(page.results):
            raise CandidateValidationError("DUPLICATE_AWARD")
        if (
            provenance.endpoint != scope.endpoint
            or provenance.query_fingerprint != scope.query_fingerprint()
            or provenance.response_fingerprint != response_fingerprint(obj)
            or provenance.records_returned != len(page.results)
            or provenance.truncated is not page.page_metadata.hasNext
            or provenance.source_system != "CIVICGATE_TEST_FIXTURE"
            or provenance.source_type != "SYNTHETIC_TEST_FIXTURE"
        ):
            raise CandidateValidationError("PROVENANCE_BINDING_MISMATCH")
        return ValidatedCandidatePage(
            scope_json=scope.effective_scope_json(),
            records=page.results,
            page=page.page_metadata.page,
            limit=page.limit,
            truncated=page.page_metadata.hasNext,
            attribution="FAA_AWARDED_PAGE" if page.results else "EMPTY_PAGE",
            provenance_json=provenance.model_dump_json(),
            raw_response_sha256=sha256(raw),
        )
    except (ValueError, TypeError, AttributeError, UnicodeError) as exc:
        raise CandidateValidationError("FAA_CANDIDATE_VALIDATION_FAILED") from exc
