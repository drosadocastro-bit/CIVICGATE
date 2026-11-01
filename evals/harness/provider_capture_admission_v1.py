"""R3 shape admission for untrusted worker/supervisor documentary captures.

This establishes readable structure only. Wire/lease/facts correspondence is
checked separately against the acknowledged coordinator snapshot. Rejected
objects are never exposed for downstream field access or treated as zero activity.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from evals.harness.live_attempt_budget_v1 import _response_facts
from evals.harness.provider_response_admission_v2 import strict_json_loads


def _integer(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _finite_number(value: Any) -> bool:
    # Integers are finite without a lossy/overflowing conversion to float.
    return type(value) is int or (type(value) is float and math.isfinite(value))


def validate_provider_capture(value: Any) -> dict[str, Any]:
    """Validate every structure later dereferenced; raise fixed bounded errors."""
    if type(value) is not dict or set(value) != {
        "roles",
        "server_receipts",
        "server_connections",
        "server_errors",
    }:
        raise ValueError("PROVIDER_CAPTURE_FIELDS")
    if type(value["roles"]) is not dict or set(value["roles"]) != {"planner", "judge"}:
        raise ValueError("PROVIDER_CAPTURE_ROLES")
    if not _integer(value["server_connections"], 1):
        raise ValueError("PROVIDER_CAPTURE_CONNECTIONS")
    errors = value["server_errors"]
    if (
        type(errors) is not list
        or len(errors) > 16
        or any(type(error) is not str or len(error) > 120 for error in errors)
    ):
        raise ValueError("PROVIDER_CAPTURE_ERRORS")
    receipts = value["server_receipts"]
    if type(receipts) is not list or len(receipts) > 1:
        raise ValueError("PROVIDER_CAPTURE_RECEIPTS")
    for receipt in receipts:
        if type(receipt) is not dict or set(receipt) != {
            "body_received",
            "declared_body_bytes",
            "fixture_source",
            "headers",
            "headers_received",
            "http_version",
            "method",
            "path",
            "received_body_bytes",
            "request_index",
            "request_sha256",
        }:
            raise ValueError("PROVIDER_CAPTURE_RECEIPT_FIELDS")
        if (
            type(receipt["body_received"]) is not bool
            or type(receipt["headers_received"]) is not bool
            or not _integer(receipt["declared_body_bytes"], 200_000)
            or not _integer(receipt["received_body_bytes"], 200_000)
            or type(receipt["request_index"]) is not int
            or receipt["request_index"] != 1
            or receipt["fixture_source"] != "SYNTHETIC_OWNED_LOOPBACK_HTTP1"
            or receipt["http_version"] != "HTTP/1.1"
            or receipt["method"] != "POST"
            or type(receipt["path"]) is not str
            or not receipt["path"].startswith("/synthetic-http-v1/")
        ):
            raise ValueError("PROVIDER_CAPTURE_RECEIPT_TYPES")
        if receipt["request_sha256"] is not None and (
            type(receipt["request_sha256"]) is not str
            or re.fullmatch(r"[a-f0-9]{64}", receipt["request_sha256"]) is None
        ):
            raise ValueError("PROVIDER_CAPTURE_REQUEST_HASH")
        headers = receipt["headers"]
        if (
            type(headers) is not list
            or len(headers) != 4
            or any(
                type(pair) is not list
                or len(pair) != 2
                or any(type(item) is not str for item in pair)
                for pair in headers
            )
            or {pair[0].lower() for pair in headers}
            != {"host", "content-type", "content-length", "connection"}
        ):
            raise ValueError("PROVIDER_CAPTURE_HEADER_FIELDS")
    for role in ("planner", "judge"):
        captured = value["roles"][role]
        if type(captured) is not dict or set(captured) != {
            "events",
            "wire",
            "response_contract",
            "response_facts_acknowledged",
        }:
            raise ValueError("PROVIDER_CAPTURE_ROLE_FIELDS")
        if type(captured["response_facts_acknowledged"]) is not bool:
            raise ValueError("PROVIDER_CAPTURE_FACTS_ACK")
        if captured["wire"] is not None and type(captured["wire"]) is not dict:
            raise ValueError("PROVIDER_CAPTURE_WIRE_FIELDS")
        wire = captured["wire"]
        if wire is not None:
            for name in (
                "connection_attempts",
                "header_emission_attempts",
                "body_emission_attempted_bytes",
                "socket_write_calls",
                "socket_received_bytes",
                "response_retained_bytes",
            ):
                if not _integer(wire.get(name), 1_000_000):
                    raise ValueError("PROVIDER_CAPTURE_WIRE_COUNTER_TYPES")
            for name in (
                "response_observed",
                "headers_socket_write_completed",
                "send_lease_acknowledged",
                "proxy_used",
            ):
                if type(wire.get(name)) is not bool:
                    raise ValueError("PROVIDER_CAPTURE_WIRE_BOOLEAN_TYPES")
            for name in (
                "wire_fixture_origin",
                "wire_fixture_path",
                "logical_origin",
                "wire_completion_state",
            ):
                if type(wire.get(name)) is not str:
                    raise ValueError("PROVIDER_CAPTURE_WIRE_IDENTITY_TYPES")
        if captured["response_contract"] is not None:
            _response_facts(captured["response_contract"])
        elif captured["response_facts_acknowledged"]:
            raise ValueError("PROVIDER_CAPTURE_ACK_WITHOUT_FACTS")
        if captured["response_facts_acknowledged"] and (
            wire is None
            or wire.get("response_observed") is not True
            or wire.get("headers_socket_write_completed") is not True
            or wire.get("send_lease_acknowledged") is not True
            or wire.get("wire_completion_state") != "HTTP_BODY_READ_COMPLETE"
        ):
            raise ValueError("PROVIDER_CAPTURE_WIRE_ACK_CONTRADICTION")
        events = captured["events"]
        if (
            type(events) is not list
            or len(events) > 64
            or any(
                type(event) is not dict or type(event.get("event")) is not str for event in events
            )
        ):
            raise ValueError("PROVIDER_CAPTURE_EVENTS")
        accepted = [event for event in events if event["event"] == "ROLE_ACCEPTED"]
        if len(accepted) > 1:
            raise ValueError("PROVIDER_CAPTURE_DUPLICATE_ACCEPTANCE")
        for event in accepted:
            if set(event) != {
                "event",
                "role",
                "deadline_disposition",
                "acceptance_state",
                "response_observed",
                "accepted_monotonic",
            } or (
                event["role"] != role
                or event["deadline_disposition"] != "WITHIN_EVALUATION_DEADLINE"
                or event["acceptance_state"] != "ACCEPTED_AT_FINAL_ROLE_BOUNDARY"
                or event["response_observed"] is not True
                or not _finite_number(event["accepted_monotonic"])
            ):
                raise ValueError("PROVIDER_CAPTURE_ACCEPTANCE_FIELDS")
    return value


def read_provider_capture(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
        raise ValueError("PROVIDER_CAPTURE_FILE_UNAVAILABLE")
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("PROVIDER_CAPTURE_INCOMPLETE_BYTES")
    return validate_provider_capture(strict_json_loads(raw))
