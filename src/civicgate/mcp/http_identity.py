"""Synthetic local credential verification, never a cloud identity integration."""

from contextvars import ContextVar
from dataclasses import asdict, dataclass
from time import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class LocalHold(RuntimeError):
    """Execution stopped; no retry or release authority is implied."""


@dataclass(frozen=True)
class TrustDomain:
    issuer: str
    audience: str
    principal: str
    service_identity: str
    instance: str

    def __post_init__(self) -> None:
        if not all(isinstance(x, str) and 0 < len(x) <= 256 for x in asdict(self).values()):
            raise ValueError("Explicit bounded trust-domain values are required")
        if self.service_identity == self.principal:
            raise ValueError("Caller and service identities must be distinct")


@dataclass(frozen=True)
class InvocationContext:
    principal: str
    issuer: str
    audience: str
    session: str
    request: str
    expires_at: int

    def evidence(self) -> dict[str, Any]:
        return asdict(self)


invocation_context: ContextVar[InvocationContext | None] = ContextVar(
    "b2a_invocation_context", default=None
)


class LocalCredentialVerifier:
    """Pinned public key, EdDSA only; no remote keys or caller-selected issuer.

    A test issuer signs short-lived credentials outside the server. The server
    receives only its public verification key. This is not an OAuth AS.
    """

    def __init__(self, domain: TrustDomain, public_key: Ed25519PublicKey) -> None:
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("An Ed25519 public verification key is required")
        self.domain = domain
        self.public_key = public_key

    def verify(self, token: str) -> dict[str, Any]:
        if len(token) > 4096:
            raise LocalHold("AUTH_INVALID")
        try:
            claims = jwt.decode(
                token,
                self.public_key,
                algorithms=["EdDSA"],
                issuer=self.domain.issuer,
                audience=self.domain.audience,
                options={
                    "require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti"],
                    "strict_aud": True,
                },
            )
            if (
                claims["sub"] != self.domain.principal
                or any(type(claims[k]) is not int for k in ("iat", "nbf", "exp"))
                or not claims["iat"] <= claims["nbf"] < claims["exp"]
                or not 0 < claims["exp"] - claims["iat"] <= 300
                or not isinstance(claims["jti"], str)
                or not 16 <= len(claims["jti"]) <= 128
                or claims.get("scope") != "civicgate:invoke"
                or claims["exp"] <= time()
            ):
                raise LocalHold("AUTH_INVALID")
            return dict(claims)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise LocalHold("AUTH_INVALID") from exc
