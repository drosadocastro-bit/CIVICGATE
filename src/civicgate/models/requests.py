from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
AwardType = Literal["A", "B", "C", "D", "02", "03", "04", "05", "06", "09", "10", "11"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Search(StrictModel):
    recipient_name: Text | None = None
    awarding_agency: Text | None = None
    start_date: date
    end_date: date
    state_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    award_types: list[AwardType] = Field(default=["A", "B", "C", "D"], min_length=1, max_length=12)
    limit: int = Field(default=20, ge=1, le=100, strict=True)

    @model_validator(mode="after")
    def dates_and_location(self) -> "Search":
        if not 0 <= (self.end_date - self.start_date).days <= 366:
            raise ValueError("Use an ordered date range of at most 367 calendar days")
        states = "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR VI GU AS MP".split()
        if self.state_code is not None and self.state_code not in states:
            raise ValueError("Use a US state or territory code")
        return self


class Award(StrictModel):
    award_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,200}$")]


class Recipient(StrictModel):
    recipient_name: Text
    limit: int = Field(default=10, ge=1, le=25, strict=True)


class Proposal(StrictModel):
    tool: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    arguments: dict[str, Any]


TOOLS: dict[str, type[Search] | type[Award] | type[Recipient]] = {
    "find_federal_awards": Search,
    "get_federal_award": Award,
    "resolve_federal_recipient": Recipient,
    "summarize_federal_spending": Search,
}
