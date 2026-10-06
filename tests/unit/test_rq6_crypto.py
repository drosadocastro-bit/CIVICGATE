from copy import deepcopy
from decimal import Decimal
from hashlib import sha256 as hashlib_sha256
from unittest.mock import patch

import pytest

from civicgate.rq6 import crypto
from civicgate.rq6.core import RQ6Error, decode_exact, exact_json, sha256

# Explicit synthetic material, never entropy generation or a real evidence selector.
SEED = "01" * 32
NONCE = "02" * 32


def bundle_metadata():
    return {
        "canonical_encoding_version": crypto.ENCODING_VERSION,
        "protocol_id": "SYNTHETIC-PROTOCOL",
        "amendment_id": "SYNTHETIC-AMENDMENT",
        "package_id": "SYNTHETIC-PACKAGE",
        "frozen_manifest_sha256": "a" * 64,
        "private_manifest_position": 1,
    }


def assignment(selector):
    return {
        **bundle_metadata(),
        "algorithm_version": crypto.ALGORITHM_VERSION,
        "source_slot_selector": selector,
    }


def synthetic_mapping():
    metadata = bundle_metadata()
    aliases = crypto.ordered_aliases(SEED, [assignment("synthetic-slot")])
    return {
        **metadata,
        "algorithm_version": crypto.ALGORITHM_VERSION,
        "source_artifact_sha256": "b" * 64,
        "exact_source_slot_selectors": ["synthetic-slot"],
        "complete_required_repeat_selectors": ["synthetic-r1", "synthetic-r2", "synthetic-r3"],
        "bundle_review_id": crypto.opaque_bundle_id(SEED, metadata),
        "bundle_seed": SEED,
        "commitment_nonce": NONCE,
        "aliases": aliases,
        "source_identity_bindings": {"SIDE_1": "synthetic-source"},
        "reviewer_access_policy_sha256": "c" * 64,
    }


def card_material():
    mapping = synthetic_mapping()
    common = {
        key: mapping[key]
        for key in ("canonical_encoding_version", "protocol_id", "amendment_id", "package_id")
    }
    unit_metadata = {
        **common,
        "bundle_review_id": mapping["bundle_review_id"],
        "exact_source_slot_selector": "synthetic-slot",
        "repeat_number": 1,
    }
    unit_id = crypto.opaque_unit_id(SEED, unit_metadata)
    output = {
        "classification": "SYNTHETIC_CLASS",
        "flags": ["SYNTHETIC_FLAG", "SYNTHETIC_FLAG"],
        "confidence": Decimal("0.9600"),
        "rationale": "Exact synthetic é rationale\n",
    }
    reference = {"classification": "SYNTHETIC_CLASS", "flags": []}
    context = {
        "user_request": "Synthetic request",
        "proposed_tool": "synthetic_tool",
        "proposed_arguments": {"amount": Decimal("1.00")},
    }
    payload = {
        "schema_version": crypto.CARD_VERSION,
        **{key: common[key] for key in ("protocol_id", "amendment_id", "package_id")},
        "bundle_review_id": mapping["bundle_review_id"],
        "reviewer_unit_id": unit_id,
        "observation_sequence_within_bundle": 1,
        "blind_alias": "SIDE_1",
        **context,
        "frozen_neutral_reference": reference,
        "stored_output": output,
        "mapping_commitment_sha256": crypto.mapping_commitment(mapping),
    }
    preimage = {
        **common,
        "bundle_review_id": mapping["bundle_review_id"],
        "reviewer_unit_id": unit_id,
        "source_artifact_sha256": "b" * 64,
        "raw_output_slice_sha256": sha256(exact_json(output)),
        "exact_selector": "synthetic-r1",
        "context_sha256": sha256(exact_json(context)),
        "neutral_reference_sha256": sha256(exact_json(reference)),
        "mapping_commitment_sha256": payload["mapping_commitment_sha256"],
        "independent_unit_nonce": "03" * 32,
    }
    return payload, preimage


def test_canonical_encoding_preserves_unicode_arrays_and_control_escapes():
    assert crypto.canonical_json({"z": [2, 1], "é": "e\u0301\n\x00/", "a": True}) == (
        b'{"a":true,"z":[2,1],"\xc3\xa9":"e\xcc\x81\\n\\u0000/"}'
    )
    assert crypto.canonical_json("é") != crypto.canonical_json("e\u0301")


@pytest.mark.parametrize("value", [1.0, Decimal("1"), -1, {1: "x"}, (1,), b"x", "\ud800"])
def test_rejects_noncanonical_metadata(value):
    with pytest.raises(RQ6Error):
        crypto.canonical_json(value)


def test_cyclic_metadata_stops():
    value = []
    value.append(value)
    with pytest.raises(RQ6Error, match="CYCLIC_METADATA"):
        crypto.canonical_json(value)


def test_domain_frame_and_id_known_vector():
    metadata = bundle_metadata()
    expected = (
        b"civicgate/rq6/amendment-001/bundle-id/v1\0"
        b'{"amendment_id":"SYNTHETIC-AMENDMENT","canonical_encoding_version":'
        b'"civicgate-rq6-canonical-json-v1","frozen_manifest_sha256":'
        b'"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"package_id":"SYNTHETIC-PACKAGE","private_manifest_position":1,'
        b'"protocol_id":"SYNTHETIC-PROTOCOL"}'
    )
    assert crypto.frame("opaque_bundle_id", metadata) == expected
    # Independent standard-library HMAC against an exact literal frame.
    import hmac

    assert (
        crypto.opaque_bundle_id(SEED, metadata)
        == hmac.new(bytes.fromhex(SEED), expected, hashlib_sha256).hexdigest()
    )


@pytest.mark.parametrize("domain", ["unknown", "mapping\0", "é"])
def test_unknown_or_double_framed_domains_stop(domain):
    with pytest.raises(RQ6Error, match="UNKNOWN_COMMITMENT_DOMAIN"):
        crypto.frame(domain, bundle_metadata())


def test_preimage_field_types_and_coverage_are_strict():
    for invalid in [
        {**bundle_metadata(), "extra": "x"},
        {key: value for key, value in bundle_metadata().items() if key != "package_id"},
        {**bundle_metadata(), "private_manifest_position": True},
        {**bundle_metadata(), "frozen_manifest_sha256": "A" * 64},
    ]:
        with pytest.raises(RQ6Error):
            crypto.opaque_bundle_id(SEED, invalid)
    for seed in ["AA" * 32, b"short", "0" * 63]:
        with pytest.raises(RQ6Error):
            crypto.opaque_bundle_id(seed, bundle_metadata())


def test_alias_order_is_digest_byte_order_not_input_or_lexical_order():
    preimages = [assignment("first-slot"), assignment("second-slot")]
    with patch.object(crypto, "_hmac", side_effect=[b"\xff" * 32, b"\x00" * 32]):
        assert crypto.ordered_aliases(SEED, preimages) == {
            "SIDE_1": "second-slot",
            "SIDE_2": "first-slot",
        }
    with patch.object(crypto, "_hmac", return_value=b"\x00" * 32):
        with pytest.raises(RQ6Error, match="ALIAS_DIGEST_TIE"):
            crypto.ordered_aliases(SEED, preimages)
    with pytest.raises(RQ6Error, match="DUPLICATE_SOURCE_SELECTOR"):
        crypto.ordered_aliases(SEED, [preimages[0], preimages[0]])


def test_opaque_collision_is_checked_without_retry_or_reassignment():
    with patch.object(crypto, "_hmac", return_value=b"\xab" * 32):
        with pytest.raises(RQ6Error, match="OPAQUE_ID_COLLISION"):
            crypto.opaque_bundle_id(SEED, bundle_metadata(), existing_ids=["ab" * 32])


def test_mapping_commitment_detects_tampering_and_reproduces_derivation():
    mapping = synthetic_mapping()
    commitment = crypto.mapping_commitment(mapping)
    assert crypto.verify_mapping_commitment(mapping, commitment)
    changed = {**mapping, "commitment_nonce": "04" * 32}
    with pytest.raises(RQ6Error, match="MAPPING_COMMITMENT_MISMATCH"):
        crypto.verify_mapping_commitment(changed, commitment)
    changed = {**mapping, "bundle_review_id": "d" * 64}
    with pytest.raises(RQ6Error, match="BUNDLE_ID_DERIVATION_MISMATCH"):
        crypto.verify_mapping_commitment(changed, crypto.mapping_commitment(changed))
    with pytest.raises(RQ6Error, match="REUSED_SECRET_MATERIAL"):
        crypto.verify_mapping_commitment(mapping, commitment, used_nonces=[NONCE])


def test_build_card_has_no_hash_cycle_and_keeps_exact_source_values():
    payload, preimage = card_material()
    originals = deepcopy((payload, preimage))
    card, sidecar = crypto.build_card(payload, preimage)
    assert (payload, preimage) == originals
    assert card["stored_output"] == payload["stored_output"]
    assert b"0.9600" in exact_json(card) and b"1.00" in exact_json(card)
    assert set(sidecar) == set(crypto.SOURCE_LINK_FIELDS) | {"final_card_sha256"}
    assert sidecar["payload_sha256"] == sha256(exact_json(payload))
    assert sidecar["final_card_sha256"] == sha256(exact_json(card))
    assert "final_card_sha256" not in card
    assert crypto.verify_source_link(sidecar, card["source_link_commitment_sha256"], card=card)
    with pytest.raises(RQ6Error, match="COMMITMENT_FIELD_MISMATCH"):
        crypto.source_link_commitment(sidecar)
    changed = deepcopy(card)
    changed["stored_output"]["rationale"] += "changed"
    with pytest.raises(RQ6Error, match="CARD_PAYLOAD_MISMATCH"):
        crypto.verify_source_link(sidecar, card["source_link_commitment_sha256"], card=changed)
    with pytest.raises(RQ6Error, match="REUSED_SECRET_MATERIAL"):
        crypto.verify_source_link(
            sidecar,
            card["source_link_commitment_sha256"],
            used_nonces=[preimage["independent_unit_nonce"]],
        )


def test_card_binding_and_field_injection_stop():
    payload, preimage = card_material()
    with pytest.raises(RQ6Error, match="CARD_SOURCE_BINDING_MISMATCH"):
        crypto.build_card(payload, {**preimage, "reviewer_unit_id": "f" * 64})
    with pytest.raises(RQ6Error, match="CARD_FIELD_MISMATCH"):
        crypto.build_card({**payload, "source_model": "synthetic-source"}, preimage)
    with pytest.raises(RQ6Error, match="OUTPUT_FIELD_MISMATCH"):
        crypto.build_card(
            {**payload, "stored_output": {**payload["stored_output"], "coding": "x"}}, preimage
        )
    with pytest.raises(RQ6Error, match="COMMITMENT_FIELD_MISMATCH"):
        crypto.build_card(payload, {**preimage, "future_selector": "x"})


def test_card_preserves_parsed_confidence_exponent_lexeme():
    payload, preimage = card_material()
    payload["stored_output"]["confidence"] = decode_exact(b"9e-1")
    card, _ = crypto.build_card(payload, preimage)
    assert b'"confidence":9e-1' in exact_json(card)


def test_explicit_null_digest_is_not_treated_as_omitted():
    payload, preimage = card_material()
    card, sidecar = crypto.build_card(payload, preimage)
    with pytest.raises(RQ6Error, match="INVALID_HEX_DIGEST"):
        crypto.build_card({**payload, "source_link_commitment_sha256": None}, preimage)
    with pytest.raises(RQ6Error, match="INVALID_HEX_DIGEST"):
        crypto.verify_source_link(
            {**sidecar, "final_card_sha256": None}, card["source_link_commitment_sha256"]
        )
