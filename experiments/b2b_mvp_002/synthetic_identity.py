"""Local tests only. Excluded from the cloud deployment allowlist."""

from civicgate.mcp.http_identity import LocalCredentialVerifier, LocalHold


class SyntheticAdmission:
    def __init__(self, verifiers: tuple[LocalCredentialVerifier, ...], audience: str) -> None:
        if not 1 <= len(verifiers) <= 4:
            raise ValueError("Bounded synthetic enrollment required")
        for v in verifiers:
            d = v.domain
            if (
                type(v) is not LocalCredentialVerifier
                or d.audience != audience
                or not d.issuer.startswith("https://synthetic.")
                or not d.issuer.endswith(".invalid")
                or not d.principal.startswith("synthetic-")
                or not d.service_identity.startswith("synthetic-")
            ):
                raise ValueError("Local synthetic identities only")
        self._verifiers = verifiers
        self.principals = tuple(v.domain.principal for v in verifiers)
        if len(set(self.principals)) != len(self.principals):
            raise ValueError("Unique caller enrollment required")

    def authenticate(self, headers: dict[bytes, bytes]) -> str:
        if any(k.startswith(b"x-forwarded-") for k in headers):
            raise LocalHold("Forwarded identity is not synthetic authentication")
        authorization = headers.get(b"authorization", b"").decode("ascii")
        if not authorization.startswith("Bearer "):
            raise LocalHold("Missing credential")
        matched = []
        for verifier in self._verifiers:
            try:
                matched.append(verifier.verify(authorization[7:])["sub"])
            except LocalHold:
                pass
        if len(matched) != 1:
            raise LocalHold("Credential not uniquely verified")
        return str(matched[0])
