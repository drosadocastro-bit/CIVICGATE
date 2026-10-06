"""Add-only RQ6 custody storage. Callers supply an authorized destination explicitly."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from civicgate.rq6.core import ArtifactSnapshot, decode_exact, require, sha256

Verifier = Callable[[ArtifactSnapshot], None]


def _safe_path(path: Path) -> Path:
    absolute = path.absolute()
    require(absolute.resolve() == absolute, "CUSTODY_PATH_REDIRECTION")
    return absolute


def build_artifact(kind: str, payload: dict[str, Any]) -> ArtifactSnapshot:
    from civicgate.rq6.schemas import validate_artifact

    validate_artifact(kind, payload)
    return ArtifactSnapshot.build(kind, payload)


class ArtifactStore:
    """Content addressed files, exclusive creation and revalidation on every read.

    This is custody, not a release operation or authorization issuer. There is no
    default destination and constructing the store performs no filesystem writes.
    Existing evidence can be consumed as-is with a pinned hash, never regenerated.
    """

    def __init__(self, root: Path, verifier: Verifier) -> None:
        self.root = _safe_path(root)
        self.verifier = verifier
        self._records: dict[str, tuple[str, Path]] = {}

    def persist(self, artifact: ArtifactSnapshot) -> ArtifactSnapshot:
        self.verifier(artifact)
        require(sha256(artifact.payload_bytes) == artifact.sha256, "ARTIFACT_HASH_MISMATCH")
        destination = self.root / "objects" / f"{artifact.sha256}.json"
        _safe_path(destination)
        if artifact.sha256 in self._records:
            previous = self.get(artifact.sha256)
            require(previous == artifact, "IMMUTABLE_ARTIFACT_CONFLICT")
            return previous
        destination.parent.mkdir(parents=True, exist_ok=True)
        _safe_path(destination)
        require(not destination.is_symlink(), "SYMLINK_ARTIFACT")
        # A preexisting object is accepted only byte-for-byte, never overwritten.
        if destination.exists():
            require(destination.read_bytes() == artifact.payload_bytes, "ARTIFACT_HASH_MISMATCH")
        else:
            with destination.open("xb") as stream:
                stream.write(artifact.payload_bytes)
                stream.flush()
                os.fsync(stream.fileno())
        self._records[artifact.sha256] = (artifact.kind, destination)
        return self.get(artifact.sha256)

    def consume(self, kind: str, path: Path, expected_sha256: str) -> ArtifactSnapshot:
        _safe_path(path)
        raw = path.read_bytes()
        require(sha256(raw) == expected_sha256, "ARTIFACT_HASH_MISMATCH")
        artifact = ArtifactSnapshot(kind, raw, expected_sha256)
        self.verifier(artifact)
        previous = self._records.get(expected_sha256)
        require(
            previous is None or previous == (kind, path.resolve()),
            "IMMUTABLE_REGISTRATION_CONFLICT",
        )
        self._records[expected_sha256] = (kind, path.resolve())
        return artifact

    def get(self, digest: str) -> ArtifactSnapshot:
        artifact = self.read_raw(digest)
        self.verifier(artifact)
        return artifact

    def read_raw(self, digest: str) -> ArtifactSnapshot:
        """Rehash physical custody without recursively invoking contextual validators."""
        require(digest in self._records, "UNKNOWN_ARTIFACT")
        kind, path = self._records[digest]
        _safe_path(path)
        require(not path.is_symlink(), "SYMLINK_ARTIFACT")
        raw = path.read_bytes()
        require(sha256(raw) == digest, "PERSISTED_ARTIFACT_MUTATION")
        artifact = ArtifactSnapshot(kind, raw, digest)
        return artifact


class EventLedger:
    """Each event is a separately immutable record with an exact predecessor hash."""

    def __init__(
        self,
        root: Path,
        binding: Mapping[str, str],
        verifier: Verifier,
        *,
        expected_count: int = 0,
        expected_tip: str | None = None,
    ) -> None:
        self.root = _safe_path(root)
        self.binding = dict(binding)
        self.verifier = verifier
        require(type(expected_count) is int and expected_count >= 0, "INVALID_LEDGER_EXPECTATION")
        require((expected_count == 0) == (expected_tip is None), "INVALID_LEDGER_EXPECTATION")
        self._expected_count, self._expected_tip = expected_count, expected_tip

    def verify(self) -> tuple[ArtifactSnapshot, ...]:
        events: list[ArtifactSnapshot] = []
        _safe_path(self.root)
        previous: str | None = None
        for sequence, path in enumerate(sorted(self.root.glob("*.json")), start=1):
            require(path.name == f"{sequence:06d}.json", "LEDGER_SEQUENCE_GAP")
            _safe_path(path)
            require(not path.is_symlink(), "SYMLINK_ARTIFACT")
            raw = path.read_bytes()
            record = ArtifactSnapshot("bundle_event_ledger", raw, sha256(raw))
            self.verifier(record)
            data = record.data()
            require(
                all(data.get(key) == value for key, value in self.binding.items()),
                "LEDGER_CROSS_BUNDLE",
            )
            require(data["event_sequence"] == sequence, "LEDGER_SEQUENCE_GAP")
            require(data["previous_event_sha256"] == previous, "LEDGER_CHAIN_BROKEN")
            previous = record.sha256
            events.append(record)
        require(
            len(events) == self._expected_count and previous == self._expected_tip,
            "LEDGER_TRUNCATION_OR_REWRITE",
        )
        self._check_order(events)
        return tuple(events)

    @staticmethod
    def _check_order(events: list[ArtifactSnapshot]) -> None:
        normal = [
            "ALIAS_COMMITMENT_FIXED",
            *[
                event
                for _ in range(3)
                for event in ("UNIT_RELEASED", "HUMAN_RECEIPT_FIXED", "UNIT_CLOSURE_VERIFIED")
            ],
            "BUNDLE_MAPPING_REVEALED",
            "MECHANICAL_COMPARISON_RECORDED",
            "RATIONALE_ASSESSMENT_FIXED",
            "BUNDLE_CHARACTERIZATION_FIXED",
            "BUNDLE_CLOSURE_VERIFIED",
        ]
        limitation = False
        terminal = False
        normal_index = 0
        for event in events:
            require(not terminal, "LEDGER_EVENT_AFTER_TERMINAL")
            kind = event.data()["event_type"]
            if kind == "EVIDENCE_LIMITATION_RECORDED":
                limitation = True
            elif limitation:
                require(kind == "BUNDLE_CLOSURE_VERIFIED", "LEDGER_LIMITATION_NOT_TERMINAL")
                terminal = True
            else:
                require(
                    normal_index < len(normal) and kind == normal[normal_index],
                    "LEDGER_EVENT_ORDER",
                )
                normal_index += 1
                terminal = normal_index == len(normal)

    def append(self, payload: dict[str, Any]) -> ArtifactSnapshot:
        existing = self.verify()
        require(payload.get("event_sequence") == len(existing) + 1, "LEDGER_SEQUENCE_GAP")
        require(
            payload.get("previous_event_sha256") == (existing[-1].sha256 if existing else None),
            "LEDGER_CHAIN_BROKEN",
        )
        require(
            all(payload.get(key) == value for key, value in self.binding.items()),
            "LEDGER_CROSS_BUNDLE",
        )
        record = build_artifact("bundle_event_ledger", payload)
        self.verifier(record)
        self._check_order([*existing, record])
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{len(existing) + 1:06d}.json"
        with path.open("xb") as stream:
            stream.write(record.payload_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        require(path.read_bytes() == record.payload_bytes, "LEDGER_WRITE_VERIFICATION_FAILED")
        self._expected_count += 1
        self._expected_tip = record.sha256
        require(self.verify()[-1] == record, "LEDGER_WRITE_VERIFICATION_FAILED")
        return record


def historical_leakage_status(
    receipt_bytes: bytes,
    expected_sha256: str,
    original_schema_validator: Callable[[dict[str, Any]], None],
) -> str:
    """Schema-aware primary history: absence is neither retroactive PASS nor FAIL."""
    require(sha256(receipt_bytes) == expected_sha256, "HISTORICAL_RECEIPT_HASH_MISMATCH")
    data = decode_exact(receipt_bytes)
    require(type(data) is dict, "INVALID_HISTORICAL_RECEIPT")
    original_schema_validator(data)
    if "leakage_validation" not in data:
        return "FIELD_NOT_PRESENT_IN_HISTORICAL_SCHEMA"
    require(data["leakage_validation"] == "PASS", "HISTORICAL_LEAKAGE_FAILURE")
    return "PASS"
