"""Explicit secret binding for a future host-constructed NVIDIA planner.

This module contains no NVIDIA client or transport and does not register a
runtime provider. The host supplies its SecretProvider and selects NVIDIA before
credential lookup. DPAPI remains an optional process-edge implementation of
that protocol, with no dependency introduced into governance or MCP.

SecretStr masks ordinary string/repr rendering, not access by local code. A
decrypted key necessarily exists in memory while being resolved or used; Python
does not supply a reliable zeroization guarantee here. This binding neither
caches keys nor writes them to configuration, logs, traces or disk.
"""

from typing import Final

from pydantic import SecretStr

from civicgate.runtime_config import SecretProvider

NVIDIA_API_KEY_NAME: Final = "CIVICGATE_NVIDIA_API_KEY"
_ERROR_CODES: Final = frozenset(
    {
        "NVIDIA_PROVIDER_NOT_SELECTED",
        "NVIDIA_CREDENTIAL_MISSING",
        "NVIDIA_CREDENTIAL_INVALID",
        "NVIDIA_SECRET_PROVIDER_ERROR",
    }
)


class NVIDIACredentialError(RuntimeError):
    """A fixed diagnostic category, without caller input or provider details."""

    def __init__(self, code: str) -> None:
        self.code = (
            code if type(code) is str and code in _ERROR_CODES else "NVIDIA_CREDENTIAL_ERROR"
        )
        super().__init__(self.code)


class NVIDIAPlannerCredentialBindingV1:
    """Resolve only NVIDIA's exact key after explicit host selection.

    This is a construction-time integration contract, not a mechanism that can
    authenticate a host or grant tool execution authority. A future
    NVIDIAPlannerProvider must receive this protocol dependency from its trusted
    host and resolve it before constructing a request/client. Agent proposals or
    tool arguments must never be used as host provider selection.
    """

    __slots__ = ("_secret_provider",)

    def __init__(self, *, secret_provider: SecretProvider) -> None:
        self._secret_provider = secret_provider

    def __repr__(self) -> str:
        # Do not invoke the injected provider's potentially sensitive repr.
        return "NVIDIAPlannerCredentialBindingV1(secret_provider=<injected>)"

    def require_api_key(self, *, host_selected_provider: str) -> SecretStr:
        """Return a masked opaque value; never trim, coerce, retry or fall back."""
        if type(host_selected_provider) is not str or host_selected_provider != "nvidia":
            raise NVIDIACredentialError("NVIDIA_PROVIDER_NOT_SELECTED")

        raw: str | None = None
        lookup_failed = False
        try:
            raw = self._secret_provider.get_secret(NVIDIA_API_KEY_NAME)
        except Exception:
            # No exception object, message or traceback is retained. Raise after
            # the handler so a provider-controlled input is not exception context.
            lookup_failed = True
        if lookup_failed:
            raise NVIDIACredentialError("NVIDIA_SECRET_PROVIDER_ERROR")
        if raw is None:
            raise NVIDIACredentialError("NVIDIA_CREDENTIAL_MISSING")
        if type(raw) is not str:
            raw = None
            raise NVIDIACredentialError("NVIDIA_CREDENTIAL_INVALID")
        if not raw.strip():
            raw = None
            raise NVIDIACredentialError("NVIDIA_CREDENTIAL_MISSING")
        if any(character in raw for character in ("\r", "\n", "\x00")):
            raw = None
            raise NVIDIACredentialError("NVIDIA_CREDENTIAL_INVALID")

        masked = SecretStr(raw)
        raw = None  # Drop this reference; do not claim memory zeroization.
        return masked
