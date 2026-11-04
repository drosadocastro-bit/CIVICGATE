"""Derive a review-only patch; apply exclusively inside synthetic pinned copies.

PROPOSED_NOT_APPLIED. This module is not imported by production governance.
Its measured hashes are engineering identities, not operational trust pins.
"""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

BASE_POLICY_SHA256 = "50204b8374528c2f902153d9d1be83c623152d1874a754663bd3d2399549ba24"
POLICY_PATH = "src/civicgate/governance/policy.py"
MODULE_PATH = "src/civicgate/governance/agency_scope_v1.py"
PROPOSAL_PATH = "evals/proposals/r021/agency_scope_v1.py"


def derive_policy(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != BASE_POLICY_SHA256:
        raise ValueError("R021_EXACT_BASE_POLICY_REQUIRED")
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    anchor = b"from civicgate.governance.authority import denied_reasons" + newline
    if raw.count(anchor) != 1:
        raise ValueError("R021_POLICY_IMPORT_ANCHOR_MISMATCH")
    updated = raw.replace(
        anchor,
        b"from civicgate.governance.agency_scope_v1 import agency_scope_reasons" + newline + anchor,
        1,
    )
    anchor = b"    if not facts.bounded:" + newline
    if updated.count(anchor) != 1:
        raise ValueError("R021_POLICY_REVIEW_ANCHOR_MISMATCH")
    addition = newline.join(
        (
            b"    # PROPOSED R02.1: legacy read scope only; no new PERMIT authority.",
            b"    if contract is None:",
            b"        review.extend(agency_scope_reasons(request, facts.tool, facts.arguments_json))",
            b"",
        )
    )
    return updated.replace(anchor, addition + anchor, 1)


def patch_text(root: Path) -> str:
    before = (root / POLICY_PATH).read_bytes()
    after = derive_policy(before)
    module = (root / PROPOSAL_PATH).read_text(encoding="utf-8")
    return "".join(
        difflib.unified_diff(
            before.decode().splitlines(True),
            after.decode().splitlines(True),
            fromfile="a/" + POLICY_PATH,
            tofile="b/" + POLICY_PATH,
        )
    ) + "".join(
        difflib.unified_diff(
            [], module.splitlines(True), fromfile="/dev/null", tofile="b/" + MODULE_PATH
        )
    )


def apply_to_preview(copy: Path, source_root: Path) -> dict:
    copy, source_root = copy.resolve(strict=True), source_root.resolve(strict=True)
    if (
        copy.name != "pinned-copy"
        or not (copy.parent / "execution/guard-config.json").is_file()
        or copy.is_relative_to(source_root)
        or source_root.is_relative_to(copy)
    ):
        raise ValueError("R021_DISJOINT_SYNTHETIC_PREVIEW_REQUIRED")
    original = (copy / POLICY_PATH).read_bytes()
    modified = derive_policy(original)
    module = (copy / PROPOSAL_PATH).read_bytes()
    with (copy / MODULE_PATH).open("xb") as stream:
        stream.write(module)
    (copy / POLICY_PATH).write_bytes(modified)
    return {
        "status": "PROPOSED_PATCH_IN_SYNTHETIC_COPY_ONLY",
        "production_source_modified": False,
        "policy_before_sha256": hashlib.sha256(original).hexdigest(),
        "policy_after_sha256": hashlib.sha256(modified).hexdigest(),
        "new_module_sha256": hashlib.sha256(module).hexdigest(),
        "new_module": MODULE_PATH,
    }
