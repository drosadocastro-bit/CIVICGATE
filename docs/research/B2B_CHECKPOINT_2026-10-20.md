# B2b research checkpoint — 2026-10-20

Prepared and verified on **2026-10-21**. The filename retains the requested checkpoint label; it is not a backdated observation.

**Local research checkpoint. Human publication review pending. Channel B cloud deployment HOLD.** No production readiness, new authority, automatic failover, HELM or PROMETHEUS integration is established.

## Scope and provenance

The checkpoint starts at verified remote main `360f30df8a4cb371233f1ef2b9e4e25b3ec08384`, on the separate branch `research/b2b-checkpoint-20261020`. The source research checkout remains at `ad4a53a42912b7fefdff2ad082dc71722cbe4662`. Its uncommitted artifacts are identified by bytes and SHA-256, not attributed to that Git commit as if already committed.

The [candidate inventory](B2B_CANDIDATE_INVENTORY.json) accounts for **115 source-qualified files**: 22 INCLUDE, 58 EXCLUDE, and 35 PRIVATE_EVIDENCE_ONLY. It covers the 96 research candidates and 19 separate FAA-C1 integration candidates; identical paths in different checkouts remain separately identified. Included artifacts are byte-identical copies. Original reports remain private and unchanged; these documents are newly authored summaries.

006I is **deferred by explicit human instruction while its original evidence is located**. It is excluded from this checkpoint's verified history. An absent source is not a passing log-access or custody result.

## One governance core, separate execution compositions

- **Channel A:** existing local MCP stdio, fixed four-tool discovery, R1 deterministic policy and Gateway-side AuthorityEnvelope/ExecutionBinding. Discovery does not grant execution. Process-local authorization is single use; a caller-supplied `user_request` is not cryptographically authenticated human intent.
- **B2a:** the existing, separate local Streamable HTTP prototype uses explicitly enrolled synthetic identities and local durable custody. Its preserved approval and verification records describe local scope, not cloud authorization.
- **Channel B research:** additive PostgreSQL ledger, transport checkpoints, cooperative receiver and stateless composition experiments. No new checkpoint module is wired into Channel A or B2a. The included MVP-002 cloud-smoke composition can serve health and four-tool metadata, but contains no execution-enabling switch, Gateway, adapter, journal or authority issuer.

The four tool identities remain `find_federal_awards`, `get_federal_award`, `resolve_federal_recipient`, and `summarize_federal_spending`. The default shared schema, policy, Gateway, ExecutionBoundary, transport entrypoints, dependency declaration and README are unchanged.

Initial authorization and final disposition remain separate facts. Pre-dispatch REVIEW_REQUIRED issues no binding and makes no backend dispatch. Post-dispatch REVIEW_REQUIRED may follow an initially permitted, correctly bound read; it does not erase that authorized dispatch. Output validation and audit recording do not authorize another action.

## Research conclusions

The ledger can record acknowledged intent and retain uncertainty, but a local check cannot cancel a request already delegated to a non-cooperative external API. The genuine G1/G2 failures remain failures. B2b-NC denotes that non-cooperative execution contract; B2b-FR denotes the separate fencing-aware receiver research track. Both labels belong to Channel B.

Cooperative receiver effects can be fenced only under the tested same-primary, same-transaction and trusted-publisher assumptions. This does not establish cross-API exactly-once execution, power-loss safety or zero sends after physical ownership loss.

P0.1–P0.5 distinguish evidence assessment, identity isolation, SDK compatibility, resource limits and durable client HOLD. The late HeaderMismatch counterexample preserves a duplicate effect under unguarded SDK recovery. No automatic recovery, retry or channel failover is approved.

FAA award selection needs explicit awarding/subtier scope and response attribution. The included candidate model passes isolated tests, while two unchanged legacy-Gateway counterexamples remain FAIL. The separate FAA-C1 shared-interface integration is deliberately excluded, not represented as an integrated feature here.

Cloud package hashes can reconcile source snapshots. They cannot establish the running process's loaded code, authenticated caller identity or live MCP behavior. The historical health 403 stopped the smoke before initialize/list/call. The reported 006F Host signature narrows the hypothesis; actual incoming Host and proxy trust remain UNKNOWN. The 006G/006H local observer and custody results do not establish cloud log access.

## Evaluation and mission

See the [evidence matrix](B2B_EVIDENCE_MATRIX.md), [runnable experiment index](B2B_EXPERIMENT_INDEX.md), [open blockers](B2B_OPEN_RISKS_AND_BLOCKERS.md), and [next-phase plan](B2B_NEXT_PHASE_PLAN.md). Counts from repeated or overlapping suites must not be added as independent trials.

The existing [GSA alignment document](../GSA_ALIGNMENT.md) is the historical design reference: public USAspending research, bounded MCP tools, explicit governance outcomes, reproducible evaluation and a judge-facing demonstration. FAA public awards provide a concrete mission-oriented example; synthetic records here contain no internal FAA data. Returned-page amounts are not total FAA spending.

The dual-channel demonstration remains an objective. A local-only submission option is **participant-reported Office Hours guidance from Danny**, not a newly verified published organizer rule or competition approval. This checkpoint does not certify submission eligibility or invent deliverables beyond the preserved project reference.

## Publication boundary

The repository is public. On 2026-10-21 GitHub reported `main` without an enabled branch-protection rule or applicable branch rules; the human prohibition on modifying main still applies. Baseline [CI run 39098258140](https://github.com/drosadocastro-bit/CIVICGATE/actions/runs/39098258140) succeeded for the exact base. That is not CI for these new local commits.

Only local commits are authorized now. Push of the exact commits, PR creation, merge and any cloud action require their separately applicable human authorization. This checkpoint changes none of the historical approval states.
