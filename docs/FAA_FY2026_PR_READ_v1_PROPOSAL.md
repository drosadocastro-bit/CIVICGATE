# FAA_FY2026_PR_READ_v1 — synthetic local contract proposal

Status: `PROPOSED_FOR_HUMAN_REVIEW_NOT_OPERATIONAL_AUTHORIZATION`.
No existing Channel A contract, schema, policy or authority object is replaced.
This document defines a dedicated synthetic READ owner, not Service WRITE.

## Intent and scope

Original natural request, retained exactly:
`Find FY2026 FAA awards with a place of performance in Puerto Rico.`

The host-selected scope means FAA-awarded prime contract records whose fictional
DATA-01 award_date falls in FY2026 and whose place-of-performance state is PR.
DOT is the parent department; FAA is its operating administration/subagency.
DOT-wide records and FAA-funded records awarded by another agency are not
substitutes. There is no geographic widening, alias-to-DOT rewriting or fallback.

Date semantics are explicitly **AWARD_DATE_SYNTHETIC_ONLY**, inclusive
2025-10-01 through 2026-09-30. This does not establish live USAspending overlap,
transaction, new_awards_only or fiscal-year spending semantics. The 54 historical
full-FAA definitions remain BLOCKED/SKIP and are not replaced by this prototype.

## Versioned input contract

The [strict frozen model](../evals/proposals/r022/faa_contract_v1.py) and its
[exact generated schema](../evals/proposals/r022/FAA_FY2026_PR_READ_v1.schema.json)
reject extra fields. Every fixed scope field must be supplied; omission never
selects legacy behavior.

| Field | Required value or bound |
| --- | --- |
| profile_id | FAA_FY2026_PR_READ_v1 |
| awarding_agency | Federal Aviation Administration |
| agency_type / agency_tier | awarding / subtier |
| agency_toptier_name | Department of Transportation |
| fiscal_year | 2026 |
| start_date / end_date | 2025-10-01 / 2026-09-30 |
| date_semantics | AWARD_DATE_SYNTHETIC_ONLY |
| state_code | PR, place of performance, not recipient location |
| award_types | Nonempty unique subset of A/B/C/D in the typed model |
| page | 1 |
| limit | Strict integer 1–20 |
| subawards | Explicit false; prime awards only |
| recipient_name | Optional exact fictional name filter; null/omitted means none |

The current stdio intake deliberately supports only the full ordered A/B/C/D
set. Model-level subset support is unit-tested, but the current request templates
do not express subsets and therefore reject them before server startup. No
subset end-to-end capability is claimed. Optional recipient matching is exact
inside this fixture; recipient_search_text does not establish live API search
or legal-entity resolution semantics.

The complete normalized query is fixed in trusted intake before planning. A
planner cannot change limit, recipient, types, dates, geography, agency role/tier,
parent or profile after this capture. No extra filter is appended after binding.
The renderer serializes the same scope to the fixed read endpoint's USA-shaped
POST body. POST does not grant modification authority; the only adapter is an
exact MockTransport synthetic READ adapter with one attempt and no live mode.

## Trusted intake and supported text

[TrustedFaaIntake](../evals/proposals/r022/stdio_v1.py) stores immutable original
text and canonical expected query JSON. It admits exact bounded templates:

- `Find public awards for agency "Federal Aviation Administration" in Puerto Rico during FY2026.`
- The corresponding `Show {limit} public awards ...` form, with matching count.
- The corresponding exact quoted `for recipient "..."` form.
- The original natural request quoted above, preserved verbatim.

The existing policy may still return REVIEW_REQUIRED for the natural request;
the prototype does not rewrite it into the canonical template or override that
decision. DOT-wide, funding-only, ambiguous, missing, contradictory or unsupported
host context is rejected rather than inferred. Exact text/hash comparison provides
integrity within a trusted local host boundary, not independently authenticated
human identity or intent. This is not a general natural-language parser.

## Placement and authority

The dedicated owner is selected by trusted application startup, before planner
execution. MCP fields and model outputs cannot select or replace its contract,
session or transport. A fixed InvocationContract reuses the original per-instance
registry/schema and ExecutionBoundary mechanisms. The original global TOOLS,
Gateway policy and legacy optional argument behavior are unchanged.

The dedicated stdio composition reuses BoundedMCPServer ownership and
BoundedToolDiscovery with the selected registry. It retains four discovery names:
FIND uses the new strict schema; GET, RECIPIENT and SUMMARY retain descriptive
legacy schemas but are explicitly unavailable in this query-only owner. Their
calls reach the same scoped admission gate and are rejected without binding or
backend action. Discovery is not permission to execute.

Missing or malformed FIND fields are SDK/schema rejections. Request/query
mismatch or unsupported tools are host-profile admission rejections. Neither
is fabricated into a deterministic Gateway DENY/REVIEW or an authority receipt.
Valid admitted FIND reaches the unchanged deterministic policy, which remains
the sole source of PERMIT/ExecutionBinding. Initial policy, binding issuance,
actual consumption, adapter entry, MockTransport attempt and final verification
remain distinct observations.

InvocationContract alone is insufficient: it changes FIND only. Without scoped
ingress, SUMMARY can still reach its legacy Search path. The dedicated owner
therefore has no silent fallback for any of the other three names. Direct
in-process Gateway calls also pass the scope gate, although hostile arbitrary
Python inside the trusted host is outside the guarantee.

## Response contract

The [additive adapter](../evals/proposals/r022/faa_adapter_v1.py) reuses exact
monetary parsing, provenance and existing response-outcome types. It requires
FAA awarding subtier under DOT, PR performance, FY2026 dates, permitted award
types and complete source attribution. Funding fields are reported separately
and cannot establish FAA awarding status. Missing/contradictory attribution,
false empty pages, malformed bodies or mismatched projections withhold results.
The immutable 40-record fixture is hash-pinned; independent SQL answers provide
a separate functional reference. Fixture completeness validation is not a claim
of exhaustive real-world history or live upstream completeness.

One HTTP 200 response may still fail validation after an authorized read. That
preserves the original PERMIT and dispatch evidence, withholds the result and
retains the appropriate REVIEW/ERROR/UNKNOWN and OPEN/STOP custody states.
Timeout or an MCP error is never permission for automatic retry or fallback.
Verified empty results are allowed only after valid authorization and matching
fixture scope; an empty toptier FAA result is not accepted as a subtier answer.

## Options and remaining decision

| Option | Assessment |
| --- | --- |
| A: distinct FAA-specific tool/contract | A versioned contract is implemented experimentally. A fifth/differently named tool would also require versioned client/discovery changes; it is not added here. |
| B: server-selected scope | Smallest demonstrated composition: trusted profile/intake, versioned FIND schema, same existing authority, explicit rejection of other tools in that owner. |
| C: continued review | Required for unsupported/natural/ambiguous intentions. C alone does not fix a matching FAA literal on an unscoped legacy owner. |

Recommend the **A contract + B trusted owner**, retaining C where unsupported.
This preserves legacy compatibility by keeping its owner separate and unchanged.
It does not certify global containment: if the same agent can choose or reach
the separate legacy owner, the original FAA false-PERMIT route remains. Trusted
application routing must exclude that route for FAA-scoped sessions before any
end-to-end containment claim. No automatic cross-owner failover is supported.

## Activation boundaries

Human technical review of exact code, profile, routing and evidence is pending.
There is no production/Console migration, live model, USAspending request,
Databricks deployment, WRITE, commit or publication. The local prototype is not
live API compatibility, model quality, calibration, exactly-once or OS isolation
certification. All operational HOLD states and durable STOP PARTIAL remain.
