"""Optional durable evidence seam; it never issues execution authority."""

from typing import Any, Protocol

from civicgate.governance.execution import AuthorityEnvelope
from civicgate.models.responses import Envelope


class DispatchJournal(Protocol):
    def admit(self) -> int: ...

    def begin(self, request_id: str) -> None: ...

    def policy(self, request_id: str, evidence: dict[str, Any]) -> None: ...

    def intent(self, authority: AuthorityEnvelope | None) -> None: ...

    def finish(self, envelope: Envelope, denials: int, evidence: dict[str, Any]) -> None: ...

    def failed(self, error: BaseException) -> None: ...
