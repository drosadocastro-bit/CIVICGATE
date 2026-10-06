"""Pure Amendment 001 commitment primitives; callers supply all secret material."""

from __future__ import annotations

import hmac
import json
import math
import re
from collections.abc import Iterable
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256 as hashlib_sha256
from typing import Any

from civicgate.rq6.core import RQ6Error, exact_json, require, sha256

ENCODING_VERSION = "civicgate-rq6-canonical-json-v1"
ALGORITHM_VERSION = "civicgate-rq6-bundle-alias-v1"
CARD_VERSION = "judge-repeat-reviewer-card-amendment-001-v1"
DOMAINS = {
    "mapping": b"civicgate/rq6/amendment-001/mapping/v1",
    "alias_assignment": b"civicgate/rq6/amendment-001/alias-assignment/v1",
    "opaque_bundle_id": b"civicgate/rq6/amendment-001/bundle-id/v1",
    "opaque_unit_id": b"civicgate/rq6/amendment-001/unit-id/v1",
    "source_link": b"civicgate/rq6/amendment-001/source-link/v1",
}
_COMMON = ("canonical_encoding_version", "protocol_id", "amendment_id", "package_id")
ASSIGNMENT_FIELDS = (
    *_COMMON,
    "algorithm_version",
    "frozen_manifest_sha256",
    "private_manifest_position",
    "source_slot_selector",
)
BUNDLE_ID_FIELDS = (*_COMMON, "frozen_manifest_sha256", "private_manifest_position")
UNIT_ID_FIELDS = (*_COMMON, "bundle_review_id", "exact_source_slot_selector", "repeat_number")
MAPPING_FIELDS = (
    *_COMMON,
    "algorithm_version",
    "frozen_manifest_sha256",
    "private_manifest_position",
    "source_artifact_sha256",
    "exact_source_slot_selectors",
    "complete_required_repeat_selectors",
    "bundle_review_id",
    "bundle_seed",
    "commitment_nonce",
    "aliases",
    "source_identity_bindings",
    "reviewer_access_policy_sha256",
)
SOURCE_LINK_FIELDS = (
    *_COMMON,
    "bundle_review_id",
    "reviewer_unit_id",
    "source_artifact_sha256",
    "raw_output_slice_sha256",
    "exact_selector",
    "context_sha256",
    "neutral_reference_sha256",
    "payload_sha256",
    "mapping_commitment_sha256",
    "independent_unit_nonce",
)
CARD_FIELDS = (
    "schema_version",
    "protocol_id",
    "amendment_id",
    "package_id",
    "bundle_review_id",
    "reviewer_unit_id",
    "observation_sequence_within_bundle",
    "blind_alias",
    "user_request",
    "proposed_tool",
    "proposed_arguments",
    "frozen_neutral_reference",
    "stored_output",
    "mapping_commitment_sha256",
    "source_link_commitment_sha256",
)
_FIELD_SETS = {
    "mapping": MAPPING_FIELDS,
    "alias_assignment": ASSIGNMENT_FIELDS,
    "opaque_bundle_id": BUNDLE_ID_FIELDS,
    "opaque_unit_id": UNIT_ID_FIELDS,
    "source_link": SOURCE_LINK_FIELDS,
}
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _metadata(value: Any, active: set[int]) -> None:
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        require(value >= 0, "NEGATIVE_METADATA_INTEGER")
        return
    require(type(value) in (list, dict), "UNSUPPORTED_COMMITMENT_METADATA_TYPE")
    require(id(value) not in active, "CYCLIC_METADATA")
    active.add(id(value))
    if type(value) is dict:
        require(all(type(k) is str for k in value), "NONSTRING_OBJECT_KEY")
        for item in value.values():
            _metadata(item, active)
    else:
        for item in value:
            _metadata(item, active)
    active.remove(id(value))


def canonical_json(value: Any) -> bytes:
    """Exact locked metadata encoding; floating-point/Decimal evidence is excluded."""
    _metadata(value, set())
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except UnicodeError as exc:
        raise RQ6Error("INVALID_UNICODE_METADATA") from exc


def _digest_string(value: Any) -> None:
    require(type(value) is str and _HEX.fullmatch(value) is not None, "INVALID_HEX_DIGEST")


def _seed(value: str | bytes) -> bytes:
    if type(value) is str:
        _digest_string(value)
        return bytes.fromhex(value)
    require(type(value) is bytes and len(value) == 32, "INVALID_SEED")
    assert isinstance(value, bytes)
    return value


def _selector(value: Any) -> None:
    require(
        (type(value) is str and bool(value)) or (type(value) is dict and bool(value)),
        "INVALID_SOURCE_SELECTOR",
    )
    canonical_json(value)


def _selectors(value: Any) -> None:
    require(type(value) is list and bool(value), "INVALID_SELECTOR_LIST")
    for selector in value:
        _selector(selector)
    encoded = [canonical_json(selector) for selector in value]
    require(len(encoded) == len(set(encoded)), "DUPLICATE_SOURCE_SELECTOR")


def _validate(operation: str, payload: Any) -> None:
    require(
        type(payload) is dict and set(payload) == set(_FIELD_SETS[operation]),
        "COMMITMENT_FIELD_MISMATCH",
    )
    canonical_json(payload)
    require(
        payload["canonical_encoding_version"] == ENCODING_VERSION,
        "CANONICAL_ENCODING_VERSION_MISMATCH",
    )
    for field in ("protocol_id", "amendment_id", "package_id"):
        require(type(payload[field]) is str and bool(payload[field]), "INVALID_IDENTIFIER")
    if "algorithm_version" in payload:
        require(payload["algorithm_version"] == ALGORITHM_VERSION, "ALGORITHM_VERSION_MISMATCH")
    for field, value in payload.items():
        if field.endswith("_sha256") or field in (
            "bundle_review_id",
            "reviewer_unit_id",
            "bundle_seed",
            "commitment_nonce",
            "independent_unit_nonce",
        ):
            _digest_string(value)
        if field in ("private_manifest_position", "repeat_number"):
            require(type(value) is int and value > 0, "INVALID_POSITION")
        if field in ("source_slot_selector", "exact_source_slot_selector", "exact_selector"):
            _selector(value)
    if operation == "mapping":
        slots = payload["exact_source_slot_selectors"]
        _selectors(slots)
        _selectors(payload["complete_required_repeat_selectors"])
        aliases = payload["aliases"]
        bindings = payload["source_identity_bindings"]
        require(
            type(aliases) is dict and set(aliases) == {f"SIDE_{i + 1}" for i in range(len(slots))},
            "INVALID_ALIAS_COVERAGE",
        )
        require(
            {canonical_json(v) for v in aliases.values()} == {canonical_json(v) for v in slots},
            "ALIAS_SOURCE_MISMATCH",
        )
        require(
            type(bindings) is dict
            and set(bindings) == set(aliases)
            and all(type(v) is str and bool(v) for v in bindings.values()),
            "INVALID_IDENTITY_BINDINGS",
        )


def frame(domain: str | bytes, payload: dict[str, Any]) -> bytes:
    """Frame an explicitly declared operation; unknown domains/fields stop."""
    if type(domain) is str and domain in DOMAINS:
        operation = domain
    else:
        try:
            encoded = domain.encode("ascii") if type(domain) is str else domain
        except UnicodeError as exc:
            raise RQ6Error("UNKNOWN_COMMITMENT_DOMAIN") from exc
        require(encoded in DOMAINS.values(), "UNKNOWN_COMMITMENT_DOMAIN")
        operation = next(key for key, value in DOMAINS.items() if value == encoded)
    _validate(operation, payload)
    return DOMAINS[operation] + b"\0" + canonical_json(payload)


def _hmac(seed: bytes, operation: str, metadata: dict[str, Any]) -> bytes:
    return hmac.new(seed, frame(operation, metadata), hashlib_sha256).digest()


def ordered_aliases(
    seed: str | bytes, assignment_preimages: list[dict[str, Any]]
) -> dict[str, Any]:
    require(type(assignment_preimages) is list and bool(assignment_preimages), "EMPTY_SOURCE_SLOTS")
    key = _seed(seed)
    selectors: list[bytes] = []
    rows: list[tuple[bytes, Any]] = []
    bundle_metadata: bytes | None = None
    for preimage in assignment_preimages:
        _validate("alias_assignment", preimage)
        current = canonical_json({k: v for k, v in preimage.items() if k != "source_slot_selector"})
        require(bundle_metadata is None or current == bundle_metadata, "MIXED_BUNDLE_ASSIGNMENTS")
        bundle_metadata = current
        selectors.append(canonical_json(preimage["source_slot_selector"]))
        digest = _hmac(key, "alias_assignment", preimage)
        require(type(digest) is bytes and len(digest) == 32, "INVALID_HMAC_RESULT")
        rows.append((digest, deepcopy(preimage["source_slot_selector"])))
    require(len(set(selectors)) == len(selectors), "DUPLICATE_SOURCE_SELECTOR")
    require(len({row[0] for row in rows}) == len(rows), "ALIAS_DIGEST_TIE")
    return {f"SIDE_{i + 1}": row[1] for i, row in enumerate(sorted(rows, key=lambda row: row[0]))}


def _opaque(
    seed: str | bytes, metadata: dict[str, Any], operation: str, existing_ids: Iterable[str]
) -> str:
    _validate(operation, metadata)
    value = _hmac(_seed(seed), operation, metadata)
    require(type(value) is bytes and len(value) == 32, "INVALID_HMAC_RESULT")
    opaque = value.hex()
    existing = tuple(existing_ids)
    for prior in existing:
        _digest_string(prior)
    require(opaque not in existing, "OPAQUE_ID_COLLISION")
    return opaque


def opaque_bundle_id(
    seed: str | bytes, metadata: dict[str, Any], *, existing_ids: Iterable[str] = ()
) -> str:
    return _opaque(seed, metadata, "opaque_bundle_id", existing_ids)


def opaque_unit_id(
    seed: str | bytes, metadata: dict[str, Any], *, existing_ids: Iterable[str] = ()
) -> str:
    return _opaque(seed, metadata, "opaque_unit_id", existing_ids)


def mapping_commitment(mapping: dict[str, Any]) -> str:
    return sha256(frame("mapping", mapping))


def source_link_commitment(preimage: dict[str, Any]) -> str:
    return sha256(frame("source_link", preimage))


def verify_mapping_assignment(
    mapping: dict[str, Any],
    *,
    used_seeds: Iterable[str] = (),
    used_nonces: Iterable[str] = (),
    existing_ids: Iterable[str] = (),
) -> bool:
    """Reproduce assignment and IDs; custody supplies prior-bundle collision context."""
    _validate("mapping", mapping)
    used = tuple(used_seeds) + tuple(used_nonces)
    for previous in used:
        _digest_string(previous)
    require(
        mapping["bundle_seed"] not in used
        and mapping["commitment_nonce"] not in used
        and mapping["bundle_seed"] != mapping["commitment_nonce"],
        "REUSED_SECRET_MATERIAL",
    )
    base = {key: mapping[key] for key in BUNDLE_ID_FIELDS}
    require(
        opaque_bundle_id(mapping["bundle_seed"], base, existing_ids=existing_ids)
        == mapping["bundle_review_id"],
        "BUNDLE_ID_DERIVATION_MISMATCH",
    )
    assignments = [
        {
            **base,
            "algorithm_version": mapping["algorithm_version"],
            "source_slot_selector": selector,
        }
        for selector in mapping["exact_source_slot_selectors"]
    ]
    require(
        ordered_aliases(mapping["bundle_seed"], assignments) == mapping["aliases"],
        "ALIAS_DERIVATION_MISMATCH",
    )
    return True


def verify_mapping_commitment(
    mapping: dict[str, Any],
    expected: str,
    *,
    used_seeds: Iterable[str] = (),
    used_nonces: Iterable[str] = (),
    existing_ids: Iterable[str] = (),
) -> bool:
    _digest_string(expected)
    verify_mapping_assignment(
        mapping, used_seeds=used_seeds, used_nonces=used_nonces, existing_ids=existing_ids
    )
    require(
        hmac.compare_digest(mapping_commitment(mapping), expected), "MAPPING_COMMITMENT_MISMATCH"
    )
    return True


def verify_source_link(
    preimage: dict[str, Any],
    expected: str,
    *,
    card: dict[str, Any] | None = None,
    used_nonces: Iterable[str] = (),
) -> bool:
    _digest_string(expected)
    require(type(preimage) is dict, "COMMITMENT_FIELD_MISMATCH")
    value = dict(preimage)
    has_final_hash = "final_card_sha256" in value
    final_hash = value.pop("final_card_sha256", None)
    require(hmac.compare_digest(source_link_commitment(value), expected), "SOURCE_LINK_MISMATCH")
    used = tuple(used_nonces)
    for nonce in used:
        _digest_string(nonce)
    require(value["independent_unit_nonce"] not in used, "REUSED_SECRET_MATERIAL")
    if has_final_hash:
        _digest_string(final_hash)
    if card is not None:
        require(type(card) is dict, "CARD_FIELD_MISMATCH")
        projection = deepcopy(card)
        require(
            projection.pop("source_link_commitment_sha256", None) == expected,
            "CARD_SOURCE_LINK_MISMATCH",
        )
        _card(projection)
        require(sha256(exact_json(projection)) == value["payload_sha256"], "CARD_PAYLOAD_MISMATCH")
        if final_hash is not None:
            require(sha256(exact_json(card)) == final_hash, "FINAL_CARD_HASH_MISMATCH")
    return True


def _card(payload: Any) -> None:
    expected = set(CARD_FIELDS) - {"source_link_commitment_sha256"}
    require(type(payload) is dict and set(payload) == expected, "CARD_FIELD_MISMATCH")
    require(payload["schema_version"] == CARD_VERSION, "CARD_SCHEMA_VERSION_MISMATCH")
    for field in ("protocol_id", "amendment_id", "package_id", "user_request", "proposed_tool"):
        require(type(payload[field]) is str, "INVALID_CARD_TEXT")
    require(type(payload["proposed_arguments"]) is dict, "INVALID_ARGUMENTS")
    require(
        type(payload["observation_sequence_within_bundle"]) is int
        and payload["observation_sequence_within_bundle"] > 0,
        "INVALID_POSITION",
    )
    require(
        type(payload["blind_alias"]) is str
        and re.fullmatch(r"SIDE_[1-9][0-9]*", payload["blind_alias"]) is not None,
        "INVALID_BLIND_ALIAS",
    )
    for field in ("bundle_review_id", "reviewer_unit_id", "mapping_commitment_sha256"):
        _digest_string(payload[field])
    reference = payload["frozen_neutral_reference"]
    output = payload["stored_output"]
    require(
        type(reference) is dict and set(reference) == {"classification", "flags"},
        "REFERENCE_FIELD_MISMATCH",
    )
    require(
        type(output) is dict
        and set(output) == {"classification", "confidence", "flags", "rationale"},
        "OUTPUT_FIELD_MISMATCH",
    )
    for item in (reference, output):
        require(
            type(item["classification"]) is str and bool(item["classification"]),
            "INVALID_CLASSIFICATION",
        )
        require(
            type(item["flags"]) is list
            and all(type(flag) is str and bool(flag) for flag in item["flags"]),
            "INVALID_FLAGS",
        )
    require(type(output["rationale"]) is str, "INVALID_RATIONALE")
    require(
        type(output["confidence"]) in (int, float) or isinstance(output["confidence"], Decimal),
        "INVALID_CONFIDENCE",
    )
    confidence = output["confidence"]
    require(not isinstance(confidence, Decimal) or confidence.is_finite(), "INVALID_CONFIDENCE")
    require(type(confidence) is not float or math.isfinite(confidence), "INVALID_CONFIDENCE")
    require(0 <= output["confidence"] <= 1, "INVALID_CONFIDENCE")
    exact_json(payload)


def build_card(
    card_payload: dict[str, Any], source_preimage: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a payload then its final bytes without putting the final hash in itself."""
    payload = deepcopy(card_payload)
    require(type(payload) is dict and type(source_preimage) is dict, "CARD_FIELD_MISMATCH")
    has_existing = "source_link_commitment_sha256" in payload
    existing = payload.pop("source_link_commitment_sha256", None)
    if has_existing:
        _digest_string(existing)
    _card(payload)
    preimage = deepcopy(source_preimage)
    expected = set(SOURCE_LINK_FIELDS)
    require(set(preimage) in (expected, expected - {"payload_sha256"}), "COMMITMENT_FIELD_MISMATCH")
    payload_hash = sha256(exact_json(payload))
    require(
        "payload_sha256" not in preimage or preimage["payload_sha256"] == payload_hash,
        "CARD_PAYLOAD_MISMATCH",
    )
    preimage["payload_sha256"] = payload_hash
    for field in (
        "protocol_id",
        "amendment_id",
        "package_id",
        "bundle_review_id",
        "reviewer_unit_id",
        "mapping_commitment_sha256",
    ):
        require(preimage[field] == payload[field], "CARD_SOURCE_BINDING_MISMATCH")
    commitment = source_link_commitment(preimage)
    require(existing is None or existing == commitment, "CARD_SOURCE_LINK_MISMATCH")
    payload["source_link_commitment_sha256"] = commitment
    sidecar = {**preimage, "final_card_sha256": sha256(exact_json(payload))}
    return payload, sidecar
