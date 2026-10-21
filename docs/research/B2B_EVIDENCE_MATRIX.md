# B2b evidence matrix

Prepared 2026-10-21. Historical observations below were read from preserved reports; they were not rerun unless explicitly identified as a checkpoint run. Original source report paths, sizes and SHA-256 are in the [inventory](B2B_CANDIDATE_INVENTORY.json). Private reports and raw logs are intentionally not published. Their digests anchor documentary identity, not independent reviewer approval.

| Phase | Evidence class | Observation retained | Boundary / current status |
| --- | --- | --- | --- |
| A1/A2 and R1 | Historical local synthetic / real stdio | A1 binding and R1 intent/argument checks; original A2 570 PASS / 2 FAIL / 1 SKIP is a distinct historical contract | The two original J3 freeze-identity failures are not rewritten by later successful integration CI |
| B1 | Reported cloud evaluation | Preserved 7 scenarios × 4 criteria: 18 PASS, 8 N/A, 1 intentional FAIL, 1 intentional UNKNOWN | Observability is not authority; no new evaluation performed |
| B2a | Historical local HTTP + synthetic backend | Original verification: 2075 PASS / 0 FAIL / 1 SKIP; later source baseline includes subsequent work | Local authorization, identity and recovery tests do not certify distributed/cloud readiness |
| B2b Phase 1 | Synthetic ledger protocol | Append-only history validation, source-bound domain, acknowledged intent and HOLD | Synthetic SQL model does not verify PostgreSQL engine durability |
| Phase 1.1–1.2 | Historical real PostgreSQL | Phase 1.2 full run 2336 PASS / 2 FAIL / 1 SKIP; G2 and broad G1 each observe one send where zero was asserted | Both genuine failures remain FAIL; zero released results does not imply zero sends |
| Phase 1.3 initial | Historical local synthetic | Original report: 2352 PASS / 119 SKIP, with real engine unavailable | Keep this earlier availability result distinct from the later authorized real-engine addendum |
| Phase 1.3 real-engine addendum | Historical PostgreSQL 17.11 / psycopg 3.3.6 | Initial full run 2467 PASS / 3 FAIL / 1 SKIP; corrected disposable permission setup 2468 PASS / 2 FAIL / 1 SKIP; 132 distinct new cases pass | Setup failure preserved; G1/G2 unchanged. No power-loss, failover or general exactly-once proof |
| Phase 1.4 / P0 | Documentary proposals | B2b-NC and B2b-FR contract separation; external admission/trust prerequisites | PROPOSED_FOR_HUMAN_REVIEW; no new policy authority or cloud deployment |
| P0.1 | Historical pure synthetic assessment | 96 PASS; assessment cannot issue a binding or dispatch | Reproduced as part of the current selected Windows run |
| P0.2 | Historical loopback HTTP / synthetic identities | 70 PASS; finite host-enrolled callers, stateless transport and unchanged Gateway | Current Windows coverage; Linux rerun unavailable without Git in cached image |
| P0.3 | Historical separate SDK 2.3 environment | 91 PASS including six cross-version cases; original routing/header and setup failures retained | Global MCP pin remains 1.30.0; not a migration approval |
| P0.4 | Historical synthetic resource / protocol | 58 PASS; single-caller isolation characterized; baseline shared-capacity starvation and two-caller saturation retained | Complete unknown-outcome custody remained UNKNOWN at this phase |
| P0.5 | Historical durable client experiment | 42 PASS; raw late HeaderMismatch assertion 0 PASS / 1 FAIL (two effects instead of one) | Guarded HOLD blocks automatic repeat; no general exactly-once guarantee |
| FAA-001 | Synthetic real-Gateway + MockTransport | 42 characterization PASS; two required-property assertions FAIL | Legacy top-tier payload and attribution gap remain; both FAIL reobserved in checkpoint |
| FAA-002 | Standalone synthetic model | 172 contract PASS and five integration-blocker PASS | A passing blocker characterization is not working FAA Gateway integration |
| FAA-C1 separate integration | Uncommitted candidate, separate worktree | Inventory includes five shared-module edits and associated sources/tests | EXCLUDE from checkpoint; no shared-contract amendment imported |
| MVP-001 | Evidence unavailable in inspected source set | No independently identified phase-specific artifact | UNKNOWN; no invented results |
| MVP-002 | Historical Windows / Linux 3.11 synthetic | 50 runtime + 13 packaging tests; 63 distinct cases, executed in two environments | Repeated platforms are not 126 independent cases. Checkpoint includes runtime slice only |
| MVP-003 | Historical local package audit | 89 instrumented HTTP assertions, 28 execution-disabled calls, zero observed dispatch/connect; tracked suite 2078 PASS / 1 SKIP | Local package audit, not live endpoint verification |
| MVP-004 Gate 2 | Historical Linux package preparation | 121 configured-host assertions, 63 prior regressions, 11 declared-command assertions; 14 files (13 source + manifest) | Separate overlapping runs. No cloud operation performed by package preparation |
| App creation / deployment | Human/Genie-reported cloud operation | Original package and later source snapshots were reported deployed under separate authorization | This checkpoint did not repeat cloud control-plane inspection, startup, shutdown or runtime verification |
| 005B / 005D + corrigendum | Local bytes vs cloud-reported hashes | Original comparison 12 MATCH / 1 MISMATCH against truncated human input; additive correction 13 MATCH | Original MISMATCH retained. Cloud measurements are Genie-reported, not remeasured by Codex |
| 006A / 006B / 006C | Synthetic client + reported live HTTP | 006A 56 synthetic PASS. Reported health HTTP 403 at 2026-10-20T02:55:39Z; stop verification reported at 02:57:36Z; stopped-log access 503 preserved | initialize, tools/list and tools/call not run in that failed live smoke; original layer attribution unresolved |
| 006D | Historical synthetic diagnostics | 74 PASS; bounded redacted signature classification and immediate STOP | No raw body or credentials published; synthetic rejection is not a live MCP rejection |
| 006E / R1 | Local independent reconciliation of Genie report | 13 paths / 86695 bytes matched second-snapshot reported hashes; manifest reported absent from snapshot | Exact local ZIP differs as a container from extracted files; no claim of cloud ZIP equality or loaded runtime code |
| 006F | Participant-reported diagnostic result | ROOT_CAUSE_NARROWED: Host rejection signature strongly supported | Original 006F response/log artifact not independently available in inspected reports; incoming Host/proxy trust UNKNOWN |
| 006G | Historical local differential/security | 359 observer tests; combined scope 552 PASS including prior suites | Host decision preserved; fingerprint potentially guessable; cloud deployment HOLD |
| 006H | Historical Linux 3.11 / local processes | 607 PASS / 0 FAIL / 0 SKIP: 359 + 56 + 74 + 63 prior cases + 55 custody cases | Subsumes 006G totals. Local capability/IPC behavior is not cloud identity, log ACL or durable cross-worker custody |
| 006I | User-supplied Genie report; local bytes verified | [Addendum](B2B_MVP_006I_LOG_ACCESS_AND_CUSTODY_ADDENDUM.md): access control PARTIAL, effective readers UNKNOWN, private custody PROPOSED_ONLY, worker attribution UNKNOWN; prior uncaptured logs reported lost | Source now available; no independent cloud remeasurement. Calendar date absent from supplied observation times. Deployment HOLD |

## Critical preserved identities

These original bytes were independently rehashed during this checkpoint, without rewriting their content:

| Private artifact | SHA-256 |
| --- | --- |
| Phase 1.2 G2 observation, 7367 bytes | `656393a581c13a5ffc197d45e5128a55f587a45f46b2a221c87abfff741ace82` |
| Phase 1.2 broad G1 observation, 7147 bytes | `af649b9038e3b20c6f7384880e66504aff36e0b8ed5cf1f973cb696f5a67a381` |
| Phase 1.3 real-engine addendum, 11420 bytes | `1a2954efd3203e88ae298cf56c2300dd862c5834d5a17ac2e28485299dbc9eee` |
| Original Gate 2 ZIP, 31789 bytes | `fcbe5c2b2b1b0be22660702fd30ed544367be02d617f11ba9be95cec68d79e69` |
| Gate 2 earlier inventory, 3403 bytes | `4c364c4a67da3738b59196ab866fafc9e68d2508adf44d2c2b4284b8b59e9f8b` |
| Gate 2 embedded manifest, 3980 bytes | `8ad643cef0e0e183f594fc062e0019f3692ae155b68a94ee977c54502b3ae75f` |

Current checkpoint commands, measured outcomes and raw-log identities are recorded in [verification](B2B_VERIFICATION_2026-10-21.json). Raw logs stay in private custody because they include local paths. No test total here is a calibrated model-accuracy statistic or a new scientific freeze.
