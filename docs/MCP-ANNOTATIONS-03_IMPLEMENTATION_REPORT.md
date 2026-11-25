# MCP-ANNOTATIONS-03 — Versioned Metadata Correction and Audit Report

**Status:** Post-submission research update, prepared for controlled publication on November 25, 2026. This public document is a privacy-redacted summary of the locally reviewed implementation report. It is not a new live experiment, a government security authorization, or a claim of deployment.

## Why this update exists

A third-party MCP directory/static-analysis review raised questions about annotation completeness and tool-test detection. The subsequent CivicGate internal investigations separated three distinct claims:

1. **Presence:** MCP-ANNOTATIONS-01 observed all four metadata hints in 22 serialized SDK tool registrations across six profiles; the selected offline regression reported 487 PASS, 0 FAIL, 0 SKIP.
2. **Semantics:** MCP-ANNOTATIONS-02 identified 16 closed/non-executing profile registrations advertising openWorldHint=true, and one synthetic WRITE-01 state transition advertising destructiveHint=false despite replacing the current review status and version. These findings depend on the stated application-state interpretation of the MCP hints, and are not claims of a security bypass or loss of history.
3. **Correction:** MCP-ANNOTATIONS-03 produced an opt-in trusted-host metadata successor, MCP_TOOL_METADATA_V2, with a reproducible before/after SDK discovery view. It does not change the frozen v1 registrations or execution contracts.

The external scanner's scoring/detection logic was not independently reproduced. This correction targets metadata truthfulness, not a numerical trust grade.

## Implementation and security boundary

Source: [metadata_v2.py](../src/civicgate/mcp/metadata_v2.py).
Focused tests: [test_metadata_v2.py](../tests/mcp/test_metadata_v2.py).
Test-only synthetic stdio fixture: [metadata_v2_stdio_fixture.py](../tests/mcp/metadata_v2_stdio_fixture.py).

A trusted host explicitly calls install_metadata_v2 on an already-constructed, supported owner **before** serving requests. The installer only decorates the existing MCP SDK tools/list request handler. It first executes the original listing under the original request context, verifies the complete legacy listing and annotations, deep-copies the result, then changes the selected public hints. The result-level _meta includes the contract identifier and host-determined profile. It does not register a new tool, replace call_tool, alter Gateway policy, modify approval bindings, or open a new WRITE route.

Host input does not control its own profile classification. Closed fixture profiles require the expected owner, transport, and mock-provider composition. Unknown types, altered dependencies, unsupported SDK versions, duplicate or late installations, and mismatched original annotations fail closed. This implementation relies on MCP SDK 1.30.0 internals and requires a new review if that dependency changes.

**Important compatibility limit:** The historical v1 decorators, direct internal server.list_tools calls, and SDK internal tool cache remain unchanged. Only the explicitly opt-in, SDK-serialized discovery response carries metadata v2. Existing executable defaults are not automatically migrated or corrected by the presence of the new module. Static scanners that inspect v1 source annotations rather than actual opted-in wire listings may continue to report historical values.

## 22-registration semantic matrix

Hint tuple order: readOnlyHint / destructiveHint / idempotentHint / openWorldHint.

| Profile | Tools | Legacy tuple | Opt-in metadata v2 tuple | Changes |
| --- | --- | --- | --- | --- |
| primary-stdio | four public READ tools | T/F/F/T | T/F/F/T | none |
| b2a-http (closed fixtures) | four READ tools | T/F/F/T | T/F/F/F | openWorldHint ×4 |
| faa-c1-http (closed fixtures) | four READ tools | T/F/F/T | T/F/F/F | openWorldHint ×4 |
| cloud-discovery (execution disabled) | four discovery-only READ tools | T/F/F/T | T/F/F/F | openWorldHint ×4 |
| r022-faa-stdio (closed fixtures) | four READ tools | T/F/F/T | T/F/F/F | openWorldHint ×4 |
| write01-stdio | update_synthetic_award_review | F/F/F/F | F/T/F/F | destructiveHint ×1 |
| write01-stdio | get_synthetic_award_review_v1 | T/F/T/F | T/F/T/F | none |

These represent **22 (profile, tool) registrations, six distinct tool names and 17 changed hint fields**, not 22 independently implemented tools. The complete, privacy-redacted per-registration projection is in [MCP-ANNOTATIONS-03_METADATA_MATRIX.json](MCP-ANNOTATIONS-03_METADATA_MATRIX.json).

The WRITE update moves a fictional award's current review state from UNREVIEWED/version 0 to PENDING_REVIEW/version 1 and appends a note. It retains before/after evidence; no historical-data deletion or government-system change is asserted. The change to destructiveHint=true conservatively describes its non-additive effect. WRITE idempotentHint=false remains unchanged: duplicate suppression and one-use binding do not grant permission for arbitrary retries. Read-only values retain their conservative historical interpretation, including audit and custody effects.

A hint is descriptive metadata, not an authorization or integrity guarantee.

## Recorded validation (local reviewed candidate)

The following are distinct recorded selections from the local isolated Windows / Python 3.13.14 review environment, not tests performed by this publication action. Overlapping suites **must not be summed**:

| Selection | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: |
| Broader core, final | 2,798 | 0 | 1 |
| Focused successor semantics and transport | 30 | 0 | 0 |
| Fresh reproduction of previous 487-case selection | 487 | 0 | 0 |
| Host71 offline contracts / mock transport | 48 | 0 | 0 |

Ruff check and formatting, scoped new-module mypy, pip dependency consistency, and final patch validation were reported passing. Earlier red/repair test failures were retained in the private review package, including environment recovery and an SDK _meta alias serialization repair. These totals do not establish Linux, Python 3.11/3.12, production runtime, a live model, live government backend, external-scanner score, or complete security certification. CI results on each publication PR are separate measurements.

The original 526 tracked files were preserved in the isolated candidate. The 13 historical WRITE-01 files matched their pinned SHA-256 manifest; the publicly reproducible freeze reference remains [write01_candidate_v1.json](../evals/manifests/write01_candidate_v1.json). The local review package separately retains original logs, SDK captures and diagnostics. Private machine paths and raw local capture locations are intentionally omitted from this publication.

## Reproduction, scope and rollback

The versioned feature is not activated by simply importing or installing this repository. A trusted host selects its existing owner, then may opt in before transport startup:

    from civicgate.mcp.metadata_v2 import install_metadata_v2
    view = install_metadata_v2(existing_authorized_owner)
    assert view.contract_id == "MCP_TOOL_METADATA_V2"

R022 additionally requires the existing, already-bound synthetic Gateway supplied explicitly as the gateway parameter. The exact supported owner compositions and constraints are enforced by the module; this example grants no deployment or backend permission.

To return to the legacy discovery view, create a fresh authorized process/session using the original owner **without** installing the v2 projection. Never reset historical custody, replay an uncertain WRITE, or modify evidence to force a rollback. Returning to v1 also restores its documented metadata limitations.

## Remaining questions

- The MCP readOnlyHint meaning relative to all audit/log/custody effects is not fully resolved by this experiment; the implementation uses an explicitly bounded application-state interpretation.
- Closed-world classification is asserted only for the specific supported synthetic or no-execution compositions, not arbitrary future fixtures.
- The view does not protect against malicious code inside the trusted Python process or independently certify upstream model/tool behavior.
- No production deployment or new public API use was part of this review.
- Frozen historical v1 metadata remains visible to direct-source analyzers, which is a deliberate evidence-preservation tradeoff.

**Publication principle:** Metadata must describe observed behavior; it does not create execution authority. Deterministic policy decides, and the Gateway enforces. Agent K observes.

## Publication CI compatibility note — November 25, 2026

The initial GitHub Actions Linux/Python 3.11 and 3.12 checks on the publication branches revealed a source-typing traversal issue: static imports of optional, frozen evaluation modules inside metadata_v2.py caused mypy to check three historical evals files, finding 14 unrelated pre-existing type errors there. The original local MCP-ANNOTATIONS-03 candidate had been tested with scoped mypy follow-imports=skip on the new module rather than the complete CI import graph.

A minimal publication compatibility amendment changes only metadata_v2.py to load those optional evaluation modules through importlib.import_module with fixed module names. Exact owner-type checks, trusted-host restrictions, tool-call behavior, public annotation values, authorization policy, and frozen evaluation files remain unchanged. This amended metadata_v2.py has a different source hash than the locally reviewed candidate; it is not presented as byte-identical to that original. The local test suite results above remain historical, and the independent GitHub PR CI runs determine whether the amended publication candidate is accepted. No test assertions or project-wide mypy configuration were weakened.
