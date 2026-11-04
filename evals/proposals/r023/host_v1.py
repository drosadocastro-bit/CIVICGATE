"""Trusted local host composition for one synthetic FAA-only stdio route.

This is routing/lifecycle custody, never a policy authority or human identity.
Only the host receives launch parameters. Agent code receives an initialized
MCP transport; it cannot choose a server module, endpoint, profile or fallback.
Arbitrary Python in a compromised host is outside this process-local boundary.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from mcp import StdioServerParameters

from evals.harness.evidence import child_environment
from evals.proposals.r022.faa_adapter_v1 import MODES
from evals.proposals.r022.faa_contract_v1 import FAA_FY2026_PR_CONTRACT, PROFILE_ID
from evals.proposals.r022.stdio_v1 import (
    ScopedFaaGateway,
    TrustedFaaIntake,
    create_scoped_server,
)

HOST_FIXED_MODULE = "evals.proposals.r023.observation_v1"
HOST_FIXED_ROUTE = "FAA_STDIO_V1"
HOST_FIXED_TRANSPORT = "stdio"
_CONFIG_KEYS = frozenset(
    {
        "mode",
        "database",
        "run_id",
        "observation_id",
        "fence_id",
        "evidence_dir",
        "intake",
        "backend_mode",
    }
)


class HostCompositionError(ValueError):
    """Host/transport refusal; not a fabricated Gateway policy disposition."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _intake_copy(intake: TrustedFaaIntake) -> TrustedFaaIntake:
    if type(intake) is not TrustedFaaIntake:
        raise HostCompositionError("TRUSTED_HOST_INTAKE_REQUIRED")
    return TrustedFaaIntake(intake.original_request, intake.expected_query_json)


@dataclass(frozen=True, slots=True)
class HostSelection:
    route: str
    transport: str
    worker_module: str
    profile_id: str
    request_sha256: str
    intake_sha256: str
    find_schema_sha256: str
    tool_names: tuple[str, ...]


def _selection(intake: TrustedFaaIntake) -> HostSelection:
    return HostSelection(
        route=HOST_FIXED_ROUTE,
        transport=HOST_FIXED_TRANSPORT,
        worker_module=HOST_FIXED_MODULE,
        profile_id=PROFILE_ID,
        request_sha256=intake.request_sha256,
        intake_sha256=intake.intake_sha256,
        find_schema_sha256=_digest(
            _json(FAA_FY2026_PR_CONTRACT.registry["find_federal_awards"].model_json_schema())
        ),
        tool_names=tuple(sorted(FAA_FY2026_PR_CONTRACT.registry)),
    )


def _read_config(path: Path, intake: TrustedFaaIntake) -> bytes:
    raw = path.read_bytes()
    if not 0 < len(raw) <= 65536:
        raise HostCompositionError("HOST_CONFIG_SIZE_INVALID")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate host field")
            value[key] = item
        return value

    def invalid_constant(_value):
        raise ValueError("Nonfinite host value")

    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, TypeError) as exc:
        raise HostCompositionError("HOST_CONFIG_INVALID_JSON") from exc
    if type(value) is not dict or set(value) != _CONFIG_KEYS:
        raise HostCompositionError("HOST_CONFIG_FIELDS_INVALID")
    if (
        value["mode"] != "R023_SYNTHETIC_STDIO_ONLY"
        or type(value["backend_mode"]) is not str
        or value["backend_mode"] not in MODES
    ):
        raise HostCompositionError("HOST_CONFIG_MODE_INVALID")
    for key in ("database", "run_id", "observation_id", "fence_id", "evidence_dir"):
        if type(value[key]) is not str or not 0 < len(value[key]) <= 4000:
            raise HostCompositionError("HOST_CONFIG_CONTEXT_INVALID")
    expected = {"request": intake.original_request, "query_json": intake.expected_query_json}
    if value["intake"] != expected:
        raise HostCompositionError("HOST_CONFIG_INTAKE_MISMATCH")
    return raw


@dataclass(frozen=True, slots=True)
class TrustedFaaLaunch:
    """An opaque-by-interface process-local capability, not an authority receipt.

    Its fields are documentary identities. The owning host additionally checks
    Python object identity, so a coherent copied record cannot acquire the route.
    """

    selection: HostSelection
    config_sha256: str


class TrustedFaaLaunchOwner:
    """A fixed host launch route, consumed once and never reset or retried.

    No legacy Gateway, alternate module, URL or fallback factory is retained.
    Nothing in this host-only API is exposed as an MCP method or planner field.
    """

    def __init__(self, config_file: Path, intake: TrustedFaaIntake):
        self._lock = Lock()
        self._intake = _intake_copy(intake)
        if not isinstance(config_file, Path) or config_file.is_symlink():
            raise HostCompositionError("HOST_CONFIG_PATH_INVALID")
        try:
            self._config = config_file.resolve(strict=True)
            raw = _read_config(self._config, self._intake)
        except OSError as exc:
            raise HostCompositionError("HOST_CONFIG_UNAVAILABLE") from exc
        self._capability = TrustedFaaLaunch(_selection(self._intake), _digest(raw))
        self._environment = child_environment()
        self._command = sys.executable
        self._args = (
            "-B",
            "-m",
            HOST_FIXED_MODULE,
            "--worker-config",
            str(self._config),
        )
        self._state = "READY"

    @property
    def capability(self) -> TrustedFaaLaunch:
        return self._capability

    @property
    def state(self) -> str:
        return self._state

    def selection_snapshot(self) -> dict[str, Any]:
        return {
            **asdict(self._capability.selection),
            "config_sha256": self._capability.config_sha256,
            "launch_state": self._state,
            "legacy_routes_exposed": False,
            "phase": "HOST_BOUND_BEFORE_DISCOVERY",
            "capability_is_not_human_or_execution_authority": True,
        }

    def consume(
        self,
        capability: TrustedFaaLaunch,
        *,
        transport: str = HOST_FIXED_TRANSPORT,
        endpoint: str | None = None,
    ) -> StdioServerParameters:
        with self._lock:
            if self._state != "READY":
                raise HostCompositionError("HOST_LAUNCH_ALREADY_CONSUMED_OR_FINISHED")
            if capability is not self._capability:
                raise HostCompositionError("HOST_LAUNCH_CAPABILITY_NOT_OWNED")
            if transport != HOST_FIXED_TRANSPORT or endpoint is not None:
                raise HostCompositionError("HOST_ROUTE_NOT_EXPOSED")
            try:
                raw = _read_config(self._config, self._intake)
                if _digest(raw) != capability.config_sha256:
                    raise HostCompositionError("HOST_CONFIG_CHANGED_AFTER_SELECTION")
                if (
                    capability.selection != _selection(self._intake)
                    or self._command != sys.executable
                    or self._args
                    != ("-B", "-m", HOST_FIXED_MODULE, "--worker-config", str(self._config))
                ):
                    raise HostCompositionError("HOST_LAUNCH_TARGET_INTEGRITY_FAILURE")
                result = StdioServerParameters(
                    command=self._command, args=list(self._args), env=dict(self._environment)
                )
            except BaseException:
                # Failed strict initialization consumes this host context. It
                # cannot silently become a fresh or legacy launch capability.
                self._state = "FAILED"
                raise
            self._state = "CONSUMED"
            return result

    def finish(self, *, success: bool) -> None:
        with self._lock:
            if self._state != "CONSUMED" or type(success) is not bool:
                raise HostCompositionError("HOST_FINISH_STATE_INVALID")
            self._state = "FINISHED" if success else "FAILED"


class HostSelectedFaaComposition:
    """Server-side immutable selection before discovery; exact existing gate.

    Ordinary closure, cancellation and initialization failure never reset the
    object or construct another owner. The bound SDK server independently checks
    its session object and rejects non-stdio transports.
    """

    @classmethod
    def from_gateway(cls, gateway: ScopedFaaGateway) -> HostSelectedFaaComposition:
        if not isinstance(gateway, ScopedFaaGateway):
            raise HostCompositionError("STRICT_FAA_GATEWAY_REQUIRED")
        if gateway.contract is not FAA_FY2026_PR_CONTRACT:
            raise HostCompositionError("STRICT_FAA_CONTRACT_REQUIRED")
        intake = _intake_copy(gateway.intake)
        gateway.contract.validate()
        server = create_scoped_server(gateway)
        result = cls.__new__(cls)
        result._lock = Lock()
        result._gateway = gateway
        result._server = server
        result._selection = _selection(intake)
        result._state = "INITIALIZED"
        return result

    @property
    def state(self) -> str:
        return self._state

    def selection_snapshot(self) -> dict[str, Any]:
        return {
            **asdict(self._selection),
            "composition_state": self._state,
            "legacy_routes_exposed": False,
            "phase": "HOST_BOUND_BEFORE_DISCOVERY",
            "identity_authentication": "NOT_ESTABLISHED_TRUSTED_LOCAL_HOST_BOUNDARY",
        }

    async def run_stdio(self) -> None:
        with self._lock:
            if self._state != "INITIALIZED":
                raise HostCompositionError("HOST_COMPOSITION_REENTRY_PROHIBITED")
            self._state = "RESERVED"
        try:
            if (
                self._gateway.contract is not FAA_FY2026_PR_CONTRACT
                or self._selection != _selection(_intake_copy(self._gateway.intake))
            ):
                raise HostCompositionError("HOST_COMPOSITION_SELECTION_CHANGED")
            self._gateway.contract.validate()
            self._state = "STDIO_ENTERED"
            await self._server.run_stdio_async()
        except BaseException:
            self._state = "FAILED"
            raise
        self._state = "CLOSED"
