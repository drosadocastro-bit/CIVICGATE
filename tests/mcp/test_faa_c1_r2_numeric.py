"""Raw-byte oracles specified independently of the FAA numeric helper.

No precision-sensitive literal is first encoded as a Python float. The expected
canonical amount and fingerprint prefix are explicit test contract constants.
"""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext

import pytest

from civicgate.channel_b.faa_adapter_v1 import FaaResponseOutcome
from civicgate.channel_b.faa_money_v1 import amount_text, response_fingerprint
from civicgate.channel_b.faa_profile_v1 import (
    AwardRowV1,
    FaaScopeV1,
    parse_response_bytes,
    validate_synthetic_page,
)
from civicgate.models.responses import Envelope
from tests.mcp.test_faa_c1 import Capture, body, query

RAW_TEMPLATE = (
    b'{"spending_level":"awards","limit":20,"results":[{"internal_id":1,'
    b'"generated_internal_id":"SYNTHETIC-R2","Award ID":"SYNTHETIC-R2",'
    b'"Recipient Name":"Synthetic Recipient","Award Amount":AMOUNT,'
    b'"Awarding Agency":"Department of Transportation",'
    b'"Awarding Sub Agency":"Federal Aviation Administration",'
    b'"Funding Agency":"Department of Transportation",'
    b'"Funding Sub Agency":"Federal Highway Administration"}],'
    b'"page_metadata":{"page":1,"hasNext":false}}'
)


def raw_amount(token: str) -> bytes:
    return RAW_TEMPLATE.replace(b"AMOUNT", token.encode("ascii"))


def independent_fingerprint(raw: bytes, expected: str) -> str:
    # Test-owned oracle: the only decimal in this fixed response is Award Amount.
    obj = json.loads(raw, parse_float=Decimal)
    obj["results"][0]["Award Amount"] = expected
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(b"FAA-C1-MONEY-v1\n" + canonical.encode("utf-8")).hexdigest()


ACCEPTED = [
    ("9007199254740993.01", "9007199254740993.01"),
    ("9007199254740994.00", "9007199254740994"),
    ("9007199254740993", "9007199254740993"),
    ("123.45", "123.45"),
    ("0.01", "0.01"),
    ("0.10", "0.1"),
    ("1000000.99", "1000000.99"),
    ("-123.45", "-123.45"),
    ("0", "0"),
    ("-0.000", "0"),
    ("1e0", "1"),
    ("1.2300e+2", "123"),
    ("1e-12", "0.000000000001"),
    ("-1e-12", "-0.000000000001"),
    ("999999999999999999999999.999999999999", "999999999999999999999999.999999999999"),
    ("-999999999999999999999999.999999999999", "-999999999999999999999999.999999999999"),
    ('"123.45"', "123.45"),  # Preserved explicit numeric-string fixture compatibility.
    ('"9007199254740993.01"', "9007199254740993.01"),
    ("1.0000000000000000000000000000000000000", "1"),
    ("0e38", "0"),
]


@pytest.mark.parametrize("token,expected", ACCEPTED)
async def test_exact_raw_decimal_typed_value_publication_and_fingerprint(token, expected):
    raw = raw_amount(token)
    c = Capture(raw=raw)
    result = await c.call()
    assert result.verification_state == "RESULT_VERIFIED"
    assert result.decision == "PERMIT" and result.attempt_count == len(c.requests) == 1
    assert result.result["records"][0]["award_amount"] == expected
    wire = json.loads(result.model_dump_json())
    assert type(wire["result"]["records"][0]["award_amount"]) is str
    assert wire["result"]["records"][0]["award_amount"] == expected
    assert Envelope.model_validate(wire).result == result.result
    value = validate_synthetic_page(
        FaaScopeV1.model_validate(query()),
        raw,
        result.provenance,
        status_code=200,
        content_type="application/json",
    )
    assert type(value.records[0].award_amount) is Decimal
    assert value.records[0].award_amount == Decimal(expected)
    assert value.raw_response_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.provenance.response_fingerprint == independent_fingerprint(raw, expected)
    assert (
        next(e for e in c.trace.events if e["stage"] == "policy")["policy"]["decision"] == "PERMIT"
    )
    assert c.trace.events[-1]["pre_dispatch_verification"] == "PASS"


async def test_cr_f01_distinct_raw_values_do_not_collapse():
    results = [await Capture(raw=raw_amount(token)).call() for token, _ in ACCEPTED[:2]]
    assert all(r.verification_state == "RESULT_VERIFIED" for r in results)
    assert len({r.result["records"][0]["award_amount"] for r in results}) == 2
    assert len({r.provenance.response_fingerprint for r in results}) == 2


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (["1", "1.0", "1.00", "1e0", '"1.00"'], "1"),
        (["0", "-0", "0.00", "-0e+12", '"-0.00"'], "0"),
        (["0.10", "0.1", "1e-1", '"0.100"'], "0.1"),
    ],
)
async def test_intentional_value_equivalence_retains_distinct_raw_identity(tokens, expected):
    values = [await Capture(raw=raw_amount(t)).call() for t in tokens]
    assert {r.result["records"][0]["award_amount"] for r in values} == {expected}
    assert len({r.provenance.response_fingerprint for r in values}) == 1
    assert len({hashlib.sha256(raw_amount(t)).hexdigest() for t in tokens}) == len(tokens)


REJECTED = [
    "1e24",
    "-1e24",
    "1e-13",
    "1e39",
    "1e-39",
    "0e39",
    "123456789012345678901234567890123456789",
    "1.00000000000000000000000000000000000000",
    "1e" + "0" * 94 + "1",
    "9" * 97,
    "NaN",
    "Infinity",
    "-Infinity",
    "null",
    "true",
    "false",
    "[]",
    "{}",
    '"NaN"',
    '"Infinity"',
    '"amount"',
    '""',
    '" 1"',
    '"1 "',
    '"+1"',
    '"01"',
    '"1_000"',
    '"1,00"',
    '"\\u0661"',
    '"1e39"',
    "01",
    "+1",
    "1.",
    ".1",
    "1e",
    "--1",
]


@pytest.mark.parametrize("token", REJECTED)
async def test_invalid_or_excessive_money_withheld_after_original_permit(token):
    c = Capture(raw=raw_amount(token))
    result = await c.call()
    assert result.result is None and result.provenance is None
    assert result.verification_state == "FAILED_VALIDATION"
    assert result.decision == "REVIEW_REQUIRED" and result.tool_executed
    assert result.dispatch_state == "REQUEST_CONFIRMED" and result.attempt_count == 1
    assert len(c.requests) == 1 and result.next_action != "RETRY_ALLOWED"
    assert not any(e.retryable for e in result.errors)
    policy = next(e for e in c.trace.events if e["stage"] == "policy")
    assert policy["policy"]["decision"] == "PERMIT" and policy["binding_issued"]


@pytest.mark.parametrize(
    "raw",
    [
        raw_amount("1").replace(b'"Award Amount":1', b'"Award Amount":1,"Award Amount":2'),
        raw_amount("1")[:-1],
        b"\xff",
        b"{" + b"[" * 1100,
        raw_amount("1").replace(b'"page":1', b'"page":1,"page":1'),
    ],
)
async def test_malformed_and_duplicate_bytes_never_verify(raw):
    c = Capture(raw=raw)
    result = await c.call()
    assert result.result is None and result.verification_state == "FAILED_VALIDATION"
    assert len(c.requests) == result.attempt_count == 1


@pytest.mark.parametrize("precision", [2, 6, 28, 80])
async def test_host_decimal_context_cannot_round_valid_amounts(precision):
    with localcontext() as context:
        context.prec = precision
        context.traps[Inexact] = True
        result = await Capture(raw=raw_amount("9007199254740993.01")).call()
        assert result.result["records"][0]["award_amount"] == "9007199254740993.01"


@pytest.mark.parametrize("value", [1.0, True, None, Decimal("NaN"), Decimal("Infinity")])
def test_already_lossy_or_nonfinite_typed_input_is_rejected(value):
    obj = body()["results"][0] | {"Award Amount": value}
    with pytest.raises(ValueError):
        AwardRowV1.model_validate(obj)


@pytest.mark.parametrize(
    "damage", ["float", "raw-object", "raw-bytes", "publication", "fingerprint", "missing-bytes"]
)
async def test_gateway_reparses_original_bytes_and_checks_all_projections(damage):
    c = Capture(raw=raw_amount("9007199254740993.01"))
    original = c.adapter.find_faa

    async def corrupt(args):
        call = await original(args)
        assert type(call.outcome) is FaaResponseOutcome
        assert call.outcome.raw_response_bytes == raw_amount("9007199254740993.01")
        if damage == "float":
            call.outcome.raw["results"][0]["Award Amount"] = float("9007199254740993.01")
        elif damage == "raw-object":
            call.outcome.raw["results"][0]["Award Amount"] = Decimal("9007199254740994")
        elif damage == "raw-bytes":
            call = replace(call, outcome=replace(call.outcome, raw_response_bytes=raw_amount("2")))
        elif damage == "publication":
            call.batch.records[0]["award_amount"] = "9007199254740994"
        elif damage == "fingerprint":
            call.batch.provenance.response_fingerprint = "0" * 64
        else:
            call = replace(call, outcome=replace(call.outcome, raw_response_bytes=b""))
        return call

    c.adapter.find_faa = corrupt
    result = await c.call()
    assert result.result is None and result.verification_state == "FAILED_VALIDATION"
    assert len(c.requests) == result.attempt_count == 1


async def test_coherently_rehashed_collapsed_projection_cannot_replace_original_bytes():
    c = Capture(raw=raw_amount("9007199254740993.01"))
    original = c.adapter.find_faa

    async def corrupt(args):
        call = await original(args)
        call.outcome.raw["results"][0]["Award Amount"] = Decimal("9007199254740994")
        call.batch.records[0]["award_amount"] = "9007199254740994"
        call.provenance.response_fingerprint = response_fingerprint(call.outcome.raw)
        return call

    c.adapter.find_faa = corrupt
    result = await c.call()
    assert result.result is None and result.verification_state == "FAILED_VALIDATION"


def test_json_decimal_is_never_a_float_and_canonical_output_is_locale_independent():
    obj = parse_response_bytes(raw_amount("9007199254740993.01"))
    assert type(obj["results"][0]["Award Amount"]) is Decimal
    assert amount_text(obj["results"][0]["Award Amount"]) == "9007199254740993.01"


@pytest.mark.parametrize("precision", [1, 5, 28])
def test_canonicalization_is_exact_and_idempotent_for_independent_decimal_grid(precision):
    # Independent integer/string oracle; no production normalizer computes expectations.
    with localcontext() as context:
        context.prec = precision
        for integer in [0, 1, 9, 12345, 9007199254740993]:
            for fraction in ["01", "10", "99", "000001", "123456789012"]:
                for sign in ["", "-"]:
                    token = f"{sign}{integer}.{fraction}"
                    expected = token.rstrip("0").rstrip(".")
                    assert amount_text(Decimal(token)) == expected
                    assert amount_text(amount_text(Decimal(token))) == expected
