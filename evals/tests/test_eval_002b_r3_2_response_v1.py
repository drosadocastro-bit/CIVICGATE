# Additive R3.2 derivative of evals/tests/test_eval_002b_r3_1_response_v1.py; SHA-256 97028750fcf558abf5412b65da3e86c0bd9a23e98a087cb6272ea0521a09f6cf
# Additive R3.1 regression derivative; original SHA-256: 34e4cb4b391ff58de15cf090a9e0ef6baca025df082837e172201ff85d53910e
"""R3 finite JSON response admission; only owned synthetic HTTP fixtures.

Run from an isolated source-pinned copy. These tests establish parser/admission
behavior, never real provider quality, pricing, execution, or human acceptance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from evals.harness.bounded_provider_v3 import BoundedProviderError
from evals.harness.live_attempt_budget_v1 import LiveAttemptBudget
from evals.harness.live_provider_candidate_v2 import (
    SYNTHETIC_PLANNER_MODEL,
    build_synthetic_http_providers,
)
from evals.harness.monetary_admission_v1 import SyntheticLiabilityPolicy
from evals.harness.provider_response_admission_v2 import evaluate_response, strict_json_loads
from evals.harness.synthetic_http_server_v1 import SyntheticHTTPServer, SyntheticReply

FACT_KEYS = {
    "http_status",
    "body_sha256",
    "body_bytes",
    "returned_model",
    "model_identity",
    "completion",
    "refusal",
    "usage",
    "typed_schema",
    "contract",
    "errors",
}
NONFINITE_TOKENS = (
    "NaN",
    "Infinity",
    "-Infinity",
    "+Infinity",
    "1e999",
    "-1e999",
    "1.7976931348623159e308",
    "-1.7976931348623159e308",
)
FINITE_TOKENS = (
    "0",
    "-0.0",
    "1.25",
    "-17.5",
    "1e308",
    "-1e308",
    "1.7976931348623157e308",
    "2.2250738585072014e-308",
    "5e-324",
    "1e-999",
    "0e999",
    "1234567890123456789012345678901234567890",
)


def _model(role: str) -> str:
    return SYNTHETIC_PLANNER_MODEL if role == "planner" else "gpt-5.6-luna"


def _content(role: str) -> str:
    if role == "planner":
        return '{"tool":"find_federal_awards","arguments":{}}'
    return (
        '{"classification":"IN_SCOPE","confidence":0.99,'
        '"flags":[],"rationale":"Owned synthetic fixture only."}'
    )


def _body(role: str = "planner", content: str | None = None) -> dict[str, Any]:
    return {
        "model": _model(role),
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": _content(role) if content is None else content},
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    }


def _evaluate(raw: bytes, role: str = "planner") -> dict[str, Any]:
    facts = evaluate_response(200, raw, requested_model=_model(role), role=role)
    assert set(facts) == FACT_KEYS
    assert facts["http_status"] == 200
    assert facts["body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert facts["body_bytes"] == len(raw)
    return facts


def _nested(token: str, location: str) -> str:
    if location == "direct":
        return token
    if location == "array":
        return '[0,{"deeper":[null,' + token + "]}]"
    return '{"deeper":{"values":[true,{"value":' + token + "}]}}"


@pytest.mark.parametrize("token", FINITE_TOKENS)
@pytest.mark.parametrize("encoded", [False, True], ids=["text", "bytes"])
def test_strict_loader_preserves_finite_python_json_values(token: str, encoded: bool) -> None:
    raw = '{"nested":[{"value":' + token + '}],"text":"NaN Infinity 1e999"}'
    source = raw.encode() if encoded else raw
    decoded = strict_json_loads(source)
    expected = json.loads(source)
    assert decoded == expected
    value = decoded["nested"][0]["value"]
    expected_value = expected["nested"][0]["value"]
    assert type(value) is type(expected_value)
    if type(value) is float:
        assert math.isfinite(value)
        assert math.copysign(1.0, value) == math.copysign(1.0, expected_value)


@pytest.mark.parametrize("role", ["planner", "judge"])
@pytest.mark.parametrize("token", FINITE_TOKENS)
def test_outer_finite_metadata_preserves_successful_contract(role: str, token: str) -> None:
    body = _body(role)
    body["synthetic_metadata"] = "REPLACE_FINITE_NUMBER"
    raw = json.dumps(body).replace('"REPLACE_FINITE_NUMBER"', _nested(token, "object")).encode()
    facts = _evaluate(raw, role)
    assert facts["contract"] == "PASS" and facts["typed_schema"] == "PASS"
    assert facts["errors"] == []


@pytest.mark.parametrize("token", FINITE_TOKENS)
def test_nested_finite_planner_arguments_reach_unchanged_typed_validation(token: str) -> None:
    content = (
        '{"tool":"find_federal_awards","arguments":{"nested":' + _nested(token, "array") + "}}"
    )
    facts = _evaluate(json.dumps(_body(content=content)).encode())
    assert facts["contract"] == "PASS" and facts["typed_schema"] == "PASS"
    assert facts["errors"] == []


@pytest.mark.parametrize("token", ["0", "-0.0", "0.99", "1", "5e-324", "1e-999", "0e999"])
def test_finite_judge_confidence_stays_admissible(token: str) -> None:
    content = _content("judge").replace("0.99", token)
    facts = _evaluate(json.dumps(_body("judge", content)).encode(), "judge")
    assert facts["contract"] == "PASS" and facts["typed_schema"] == "PASS"
    assert facts["errors"] == []


@pytest.mark.parametrize("role", ["planner", "judge"])
@pytest.mark.parametrize("location", ["direct", "array", "object"])
@pytest.mark.parametrize("token", NONFINITE_TOKENS)
def test_nonfinite_outer_values_fail_before_contract_fields(
    role: str, location: str, token: str
) -> None:
    body = _body(role)
    body["ignored_metadata"] = "REPLACE_NONFINITE_NUMBER"
    raw = json.dumps(body).replace('"REPLACE_NONFINITE_NUMBER"', _nested(token, location)).encode()
    facts = _evaluate(raw, role)
    assert facts["contract"] == "FAIL"
    assert facts["model_identity"] == "MISSING"
    assert facts["usage"] == "UNKNOWN" and facts["typed_schema"] == "NOT_PARSED"
    assert facts["errors"] == ["INVALID_OR_AMBIGUOUS_RESPONSE_JSON"]


@pytest.mark.parametrize("location", ["direct", "array", "object"])
@pytest.mark.parametrize("token", NONFINITE_TOKENS)
def test_nonfinite_nested_planner_arguments_fail_the_typed_contract(
    location: str, token: str
) -> None:
    content = (
        '{"tool":"find_federal_awards","arguments":{"nested":' + _nested(token, location) + "}}"
    )
    facts = _evaluate(json.dumps(_body(content=content)).encode())
    assert facts["contract"] == "FAIL" and facts["typed_schema"] == "FAIL"
    assert facts["model_identity"] == "MATCH" and facts["usage"] == "KNOWN"
    assert facts["completion"] == "COMPLETE"
    assert facts["errors"] == ["TYPED_RESPONSE_SCHEMA_REJECTED"]


@pytest.mark.parametrize("token", NONFINITE_TOKENS)
def test_nonfinite_judge_confidence_fails_the_typed_contract(token: str) -> None:
    content = _content("judge").replace("0.99", token)
    facts = _evaluate(json.dumps(_body("judge", content)).encode(), "judge")
    assert facts["contract"] == "FAIL" and facts["typed_schema"] == "FAIL"
    assert facts["errors"] == ["TYPED_RESPONSE_SCHEMA_REJECTED"]


@pytest.mark.parametrize(
    "raw", [b'{"a":1,"a":2}', b'{"a":[{"b":1,"b":2}]}', b"\xff", b"not-json", b""]
)
@pytest.mark.parametrize("role", ["planner", "judge"])
def test_malformed_ambiguous_outer_json_retains_structured_failure(raw: bytes, role: str) -> None:
    facts = _evaluate(raw, role)
    assert facts["contract"] == "FAIL" and facts["typed_schema"] == "NOT_PARSED"
    assert facts["errors"] == ["INVALID_OR_AMBIGUOUS_RESPONSE_JSON"]


@pytest.mark.parametrize(
    "content", ["not-json", "[]", "{}", '{"x":1,"x":2}', '{"x":[{"y":1,"y":2}]}']
)
@pytest.mark.parametrize("role", ["planner", "judge"])
def test_malformed_ambiguous_typed_json_retains_structured_failure(content: str, role: str) -> None:
    facts = _evaluate(json.dumps(_body(role, content)).encode(), role)
    assert facts["contract"] == "FAIL" and facts["typed_schema"] == "FAIL"
    assert facts["errors"] == ["TYPED_RESPONSE_SCHEMA_REJECTED"]


@pytest.mark.parametrize("role", ["planner", "judge"])
@pytest.mark.parametrize("layer", ["outer", "typed"])
def test_decoder_depth_overflow_is_structured_failure(
    tmp_path: Path, role: str, layer: str
) -> None:
    deep = _decoder_overflow_fixture(tmp_path)
    raw = deep.encode() if layer == "outer" else json.dumps(_body(role, deep)).encode()
    assert len(raw) < 200_000
    facts = _evaluate(raw, role)
    assert facts["contract"] == "FAIL"
    assert facts["typed_schema"] == ("NOT_PARSED" if layer == "outer" else "FAIL")
    assert facts["errors"] == [
        "INVALID_OR_AMBIGUOUS_RESPONSE_JSON"
        if layer == "outer"
        else "TYPED_RESPONSE_SCHEMA_REJECTED"
    ]


def _decoder_overflow_fixture(tmp_path: Path) -> str:
    """Prove the fixture reaches this decoder's limit before testing admission.

    The Python recursion limit alone did not predict the native JSON decoder's
    limit in the first copied run. Keep that failure and measure this fixture
    against the actual decoder, within the existing response byte ceiling.
    """
    recursion_limit = sys.getrecursionlimit()
    depth = max(10_000, recursion_limit + 100)
    assert depth <= 90_000, f"Fixture exceeds bounded range: recursion_limit={recursion_limit}"
    deep = "[" * depth + "0" + "]" * depth
    decoder_overflow = False
    try:
        json.loads(deep)
    except RecursionError:
        decoder_overflow = True
    metadata = {
        "python_recursion_limit": recursion_limit,
        "fixture_depth": depth,
        "fixture_bytes": len(deep.encode()),
        "fixture_sha256": hashlib.sha256(deep.encode()).hexdigest(),
        "native_decoder_recursion_error": decoder_overflow,
    }
    with (tmp_path / "decoder-depth-fixture.json").open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, indent=2, sort_keys=True)
        stream.write("\n")
    assert decoder_overflow, metadata
    return deep


def test_public_loader_normalizes_decoder_depth_overflow(tmp_path: Path) -> None:
    deep = _decoder_overflow_fixture(tmp_path)
    with pytest.raises(ValueError, match="JSON_NESTING_EXCEEDS_DECODER_LIMIT"):
        strict_json_loads(deep)


@contextmanager
def _owned_network_only(origins: set[tuple[str, int]]) -> Iterator[list[dict[str, Any]]]:
    """A cooperative Python socket guard around already owned fixture servers."""
    events: list[dict[str, Any]] = []
    connect, connect_ex, resolve = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def permitted(address: Any) -> bool:
        return isinstance(address, tuple) and len(address) >= 2 and address[:2] in origins

    def guarded_connect(sock: Any, address: Any) -> Any:
        allowed = permitted(address)
        events.append({"event": "connect", "address": str(address), "allowed": allowed})
        if not allowed:
            raise PermissionError("R3_NON_OWNED_SOCKET_DENIED")
        return connect(sock, address)

    def guarded_connect_ex(sock: Any, address: Any) -> Any:
        if not permitted(address):
            raise PermissionError("R3_NON_OWNED_SOCKET_DENIED")
        return connect_ex(sock, address)

    def guarded_resolve(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        if (host, int(port)) not in origins:
            raise PermissionError("R3_NON_OWNED_DNS_DENIED")
        return resolve(host, port, *args, **kwargs)

    def no_datagrams(*_args: Any, **_kwargs: Any) -> Any:
        raise PermissionError("R3_DATAGRAM_DENIED")

    with (
        patch.object(socket.socket, "connect", guarded_connect),
        patch.object(socket.socket, "connect_ex", guarded_connect_ex),
        patch.object(socket, "getaddrinfo", guarded_resolve),
        patch.object(socket.socket, "sendto", no_datagrams),
    ):
        yield events


@pytest.mark.parametrize("layer", ["outer", "typed"])
@pytest.mark.parametrize("token", ["1e999", "-1e999"])
def test_owned_socket_nonfinite_response_is_observed_acknowledged_and_never_accepted(
    tmp_path: Path, layer: str, token: str
) -> None:
    async def exercise() -> None:
        if layer == "typed":
            content = (
                '{"tool":"find_federal_awards","arguments":{"nested":[{"value":' + token + "}]}}"
            )
            raw = json.dumps(_body(content=content)).encode()
        else:
            body = _body()
            body["ignored_metadata"] = "REPLACE_NONFINITE_NUMBER"
            raw = (
                json.dumps(body)
                .replace('"REPLACE_NONFINITE_NUMBER"', _nested(token, "array"))
                .encode()
            )
        async with (
            SyntheticHTTPServer(SyntheticReply(body=raw)) as planner,
            SyntheticHTTPServer() as judge,
        ):
            budget = LiveAttemptBudget.create(
                tmp_path / "response.sqlite",
                "EVAL002B_R3_FINITE_RESPONSE",
                liability_policy=SyntheticLiabilityPolicy(
                    total_limit_units=10,
                    per_attempt_upper_bound_units={"planner": 1, "judge": 1},
                ),
            )
            bound = build_synthetic_http_providers(
                budget, "R3_RESPONSE_OBSERVATION", planner.endpoint, judge.endpoint
            )
            with _owned_network_only(
                {("127.0.0.1", planner.endpoint.port), ("127.0.0.1", judge.endpoint.port)}
            ) as network:
                with pytest.raises(BoundedProviderError, match="RESPONSE_CONTRACT_NOT_ADMITTED"):
                    await bound.planner.propose("Owned synthetic finite-response test only.")
            snapshot = budget.snapshot()
            delegate = bound.planner_transport.response_delegate
            assert planner.connection_count == planner.request_count == 1
            assert judge.connection_count == judge.request_count == 0
            assert snapshot["counts"] == {"planner": 1, "judge": 0}
            assert snapshot["stopped"] is True
            assert bound.planner_transport.acceptance is None
            assert delegate.facts_acknowledged is True
            assert delegate.facts is not None
            assert delegate.facts["contract"] == "FAIL"
            assert delegate.facts["body_sha256"] == hashlib.sha256(raw).hexdigest()
            assert len(snapshot["response_facts"]) == 1
            assert all(event["allowed"] for event in network)
            assert delegate.wire is not None
            evidence = {
                "layer": layer,
                "token": token,
                "network": network,
                "server_receipts": [dict(row) for row in planner.receipts],
                "wire_facts": dict(delegate.wire.facts),
                "response_facts": delegate.facts,
                "budget": snapshot,
            }
            with (tmp_path / "owned-socket-response.json").open("x", encoding="utf-8") as stream:
                json.dump(evidence, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
            await bound.planner_transport.aclose()
            await bound.judge_transport.aclose()

    asyncio.run(exercise())
