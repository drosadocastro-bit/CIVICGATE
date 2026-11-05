# WRITE-01 — governed synthetic review-state mutation

Status: candidate for human technical review, local synthetic research only.
This document does not record human acceptance or operational activation.

## Baseline and preservation

The isolated branch is `codex/write01-synthetic-review`, based on main commit
`ea59646fdfe54d8ce954b8917979a8370ad27bef`, tree
`4c25cc3c2cd9f049e36b6075014c2e00121e4ec2`. The baseline GitHub Actions run
[41881616962](https://github.com/drosadocastro-bit/CIVICGATE/actions/runs/41881616962)
completed successfully across its five jobs. That is baseline evidence, not CI
certification of these uncommitted additions.

All 425 baseline tracked files, including the 61 accepted MINI09 files and their
four manifests, remain unchanged. Original oracle decisions, DATA01-026 and FAA
false-PERMIT captures, R02.1's unapplied patch, R02.2's known legacy-route risk,
the reserved holdout and earlier failures are not rewritten or relabeled.
No dependencies, production source, original tests, prompts, README, Console,
global MCP registry or historical manifests are edited.

The immutable 40-record dataset is
[awards_v1.json](../evals/data01/awards_v1.json), 31,704 bytes, SHA-256
`7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d`.
Its embedded `review_status` remains original source metadata. Mutable state
belongs to an explicitly initialized, separate SQLite database.

## Architecture and exact authority boundary

The original policy and ExecutionBoundary support `PUBLIC_SPENDING_RESEARCH`;
their four-tool registry cannot honestly grant WRITE authority. The original
InvocationContract only replaces FIND's schema. WRITE-01 therefore adds a narrow
experimental authority namespace under `evals/write01/`. It does not disguise
a write as FIND, change the original policy, or claim that the unchanged READ
policy authorized the new action.

The new [authority](../evals/write01/authority_v1.py) reuses CIVICGATE's immutable
`AuthorityEnvelope`, `ExecutionBinding`, `PolicyEvaluation` and `PolicyResult`
types, existing prohibited-request tripwires, exact canonical JSON/schema
identities, object ownership, bounded expiry and consume-before-dispatch checks.
Its deterministic policy version is `civicgate-write01-synthetic-v1`. This is
new, explicitly scoped authorization logic requiring review, not an established
production capability or a replacement general governance framework.

The trusted host constructs the exact approval and selects this server before
discovery. The agent receives only an initialized MCP session. Approval binds
the original request, exact effective tool/arguments, dataset digest, owner,
store and approval reference. The MCP payload cannot provide an approval object,
owner, profile, database path, server selector or fallback endpoint. References
and hashes document identity; they do not authenticate a human or grant authority.
The demonstration approvals are explicitly synthetic host fixtures authorized
for this experiment, not manufactured human operational decisions.

The path is:

1. Trusted host configures one dedicated WRITE-01 stdio owner.
2. MCP lists bounded metadata; discovery grants no permission.
3. A deterministic fixture proposes a typed operation and original request.
4. The new Gateway reads verified current state and evaluates deterministic
   target, transition, version, schema, tripwire and exact host-approval rules.
5. PERMIT issues a fresh retained binding in the exact synthetic operation scope.
6. SQLite durably reserves OPEN intent; Gateway independently reads it back.
7. Gateway actually consumes the owned envelope before entering its adapter.
8. SQLite records one adapter-attempt marker, then commits state and evidence.
9. Gateway reconciles receipt, bound operation and actual state, then verifies
   the separate close acknowledgement against durable SQLite closure.
10. A typed response distinguishes policy, execution, verification and custody.

The fixture Judge reports `IN_SCOPE`, confidence 0.99. It cannot compensate for
missing host approval or a deterministic denial. No Granite, Luna, Claude or
other real model is constructed or evaluated. The driver is a deterministic
proposer using actual MCP SDK 1.30.0 stdio/JSON-RPC, not a new LangGraph workflow.
Existing A2 paths are covered separately by unchanged regressions.

## Versioned public contract

[contract_v1.py](../evals/write01/contract_v1.py) defines strict frozen input
models, with extra fields rejected. This separate server exposes exactly two
operations; it does not append a fifth tool to any original READ server.

| Operation | Capability | Inputs / behavior |
| --- | --- | --- |
| `update_synthetic_award_review` | Synthetic review-state WRITE | `user_request` and typed `query`: synthetic `award_id`, strict `expected_version`, `proposed_status`, bounded `reviewer_note`, `idempotency_key` |
| `get_synthetic_award_review_v1` | Explicit versioned overlay READ | `user_request` and `query.award_id`, with its own exact host approval and READ binding |

Only `UNREVIEWED` version 0 → `PENDING_REVIEW` version 1 is implemented. The
second state means a local review is pending; it is not a procurement decision,
approval of an award, payment, eligibility or authorization to act externally.
There are no arbitrary field updates, compensating writes, resets or deletes.

The note is bounded to 1,000 characters / 4,000 UTF-8 bytes and restricted
control characters. It is inert exact data, not interpreted as another request,
prompt, code or authority. A malicious instruction inside an explicitly approved
note cannot change the bound action. There is no note-rendering UI here; a future
display must escape its text. No current Console migration is claimed.

Original request text is captured separately from the proposed arguments. It
must match the host-approved intake exactly. This is a trusted local-host
boundary, not authenticated remote user intent or general natural-language
understanding. Existing hard-denial tripwires remain an additional restriction.

The server reuses original stdio/session ownership and metadata-contract
serialization. It pins handler/metadata/schema identities and verifies them
before discovery/call. It prohibits HTTP/SSE routes and contains no legacy
fallback. Original READ and FAA contexts retain their four tools and behavior;
they receive no new WRITE permissions.

## SQLite schema and transaction semantics

Authoritative schema SQL is in
[store_v1.py](../evals/write01/store_v1.py). Logical tables:

| Table | Contents / constraints |
| --- | --- |
| `metadata` | Exact store version, store ID and immutable dataset SHA-256 |
| `review_state` | Exactly the 40 known synthetic award IDs; supported status and version |
| `intents` | Unique operation ID and idempotency key, exact operation JSON/digest, binding digest, OPEN/CLOSED, durable attempt marker, receipt JSON/digest |
| `notes` | Append-only note for the committed operation, target and resulting version |

A unique partial index prevents two OPEN operations for the same target.
The store opens only existing explicitly initialized databases with SQLite
`mode=rw`, foreign keys and `synchronous=FULL`. Missing/corrupt/inconsistent stores
fail closed; normal startup never silently creates a replacement. Dataset and
stored state/evidence associations are revalidated on every operation.

OPEN reservation and one-attempt marking precede the mutation transaction. Inside
one `BEGIN IMMEDIATE` transaction, the adapter rechecks expected version/state,
updates status, increments version, appends the note and records the committed
idempotency outcome with exact before/after evidence and binding association.
A failure before commit leaves none of those mutation effects partially applied.
The earlier reservation/attempt remains as evidence and prevents retry.

Duplicate keys are rejected, not automatically re-dispatched or refunded.
Receipt inspection is read-only. A duplicate on another still-unreviewed target
may encounter PERMIT/issuance before atomic reservation refusal; it has zero
consumption and zero adapter dispatch. Do not describe every duplicate as a
preflight DENY with zero issuance.

Close acknowledgement is a separate documentary operation. A committed change
with lost or inconsistent acknowledgement is withheld as UNKNOWN; actual durable
state may be OPEN or CLOSED. Gateway records known COMMITTED separately when its
receipt/state verification completed. A returned CLOSED string alone is not
accepted: exact operation/receipt identities and stored CLOSED must reconcile.
`custody_at_commit=OPEN` and the later `close_ack` describe different moments.
CLOSED does not mean human acceptance or that the client received a response.

Any uncertainty stops that Gateway owner. A persisted unresolved target remains
blocked across new owners, keys and process restarts; no automatic recovery is
provided. If the first durable write fails completely, dispatch is blocked but
no universal persistent quarantine can be claimed. Durable STOP remains PARTIAL.
An operator must investigate uncertain outcomes; this prototype does not grant
reset, retry or manual recovery authority.

## Evidence and reproduction

Use the already provisioned worker environment (Windows / Python 3.13.7,
MCP 1.30.0). No installation, secret, external service or live API is required:

```powershell
python -B scripts/run_write01_synthetic_v1.py --execute-synthetic --evidence-root <NEW_PRIVATE_DIRECTORY>
```

The [runner](../scripts/run_write01_synthetic_v1.py) refuses existing output paths,
pins copies of required sources, reuses the original versioned offline guard,
and runs only the named WRITE-01 tests. The worker additionally installs the
existing fixture network/dataset guards. This is cooperative Python protection,
not OS-level network isolation or hostile-code containment.

The fresh private package includes exact commands, dependency/source identities,
JUnit, stdout/stderr, three demonstration directories, actual MCP initialize/list/
call responses, append-only Gateway events, SQLite files/readbacks, before/after
receipts, guard facts and an evidence inventory. An additional authorized overlay
READ follows the PERMIT WRITE; these two MCP calls are reported separately.

| Core scenario | Expected and observed outcome |
| --- | --- |
| PERMIT | Exact host-approved transition; WRITE binding issued/consumed 1/1, one adapter attempt, one atomic commit, state 0→1, one note, verified CLOSED documentary custody |
| DENY | Proposed `AWARD_CONTRACT` status prohibited; zero binding, adapter entry or mutation |
| REVIEW_REQUIRED | Missing affirmative exact host approval despite permissive synthetic Judge; zero binding, adapter entry or mutation |

Fault/adversarial tests cover stale versions, unknown targets, forbidden
transitions, exact/cross-record duplicate keys, copied/foreign/read/replayed/expired
bindings, modified query/notes/intake, injected owner/profile/approval fields,
direct calls to legacy MCP, missing startup store without fallback, concurrent
SQLite reservation, process exits/restart, lock/corruption, precommit rollback,
commit/ACK loss, false OPEN/CLOSED acknowledgements, wrong receipt identity,
malformed receipt types, audit failures and read-only overlay preservation.

The candidate manifest supplies the final source identities. Counts and raw
results remain in the private delivery package; source identity alone is not
execution evidence. Assistant review roles use the same environment and are not
independent human or organizational acceptance.

## Results and preserved development findings

Fresh final WRITE selection: **142 PASS / 0 FAIL / 0 SKIP**, including all three
real MCP demonstrations and the negative controls. Ruff and formatting pass;
strict Mypy checks `src` plus the new implementation/runner (77 source files).

| Separately rerun unchanged selection | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: |
| Original A1/A2/MCP | 221 | 0 | 0 |
| R3.2 | 373 | 0 | 0 |
| Console/Advisor | 441 | 0 | 9 |
| R02.1 additive baseline/disposition overlay | 90 | 0 | 0 |
| R02.1 isolated unapplied proposal | 24 | 0 | 0 |
| R02.2 characterization | 171 | 0 | 0 |
| R02.3 host topology | 89 | 0 | 0 |

Selections overlap and must not be summed. Console skips retain their explicit
local catalog/HTTP prerequisites; three separate fresh worker captures passed
primary readback. R02.2 passing its characterization does not resolve its known
legacy bypass. The original DATA01-026 failure is not reclassified by the additive
disposition overlay. No full historical suite or new remote CI result is claimed.

Preserved development evidence includes 103 PASS / 21 FAIL in the initial
integrated selection, an independent 67 PASS / 1 FAIL Judge-NONE reproduction,
and 1 PASS / 4 FAIL custody/type probes. The initial integrated failures exposed
misclassification of the advisory `NONE` sentinel and unsupported SDK internal
metadata serialization. The independent probes exposed acceptance of false or
mismatched close ACKs and unhandled malformed receipt types. All were corrected
only in new candidate files, with unchanged negative expectations. Earlier
127-PASS and 136-PASS runs remain separate snapshots, not final identities.
Initial lint/type diagnostics and a failed patch-context application are also
preserved in the private preparation record; none changed historical source.

## Remaining limits and retained holds

- One synthetic transition and explicitly authorized overlay READ only; no
  general service-WRITE framework, compensation, Console migration or full FAA
  query contract. The 54 FAA full-contract definitions remain BLOCKED/SKIP.
- Two-process SQLite tests establish bounded local contention behavior; they do
  not certify distributed exactly-once, power-loss recovery, hostile local
  administrator resistance, filesystem rollback resistance or OS isolation.
- A new host with filesystem/Python control is trusted and can violate the
  composition assumptions. An agent given another client/owner independently is
  outside the tested topology. Hashes are not authentication.
- No live providers, external agency writes, real USAspending reads, semantic
  model quality, calibration or human benchmark acceptance is established.
- Approval loss and protocol-response loss are not automatic retry authority.
  No server/client fallback or retry loop is implemented.

```yaml
SYNTHETIC_WRITE01: CANDIDATE_FOR_HUMAN_REVIEW
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
USASPENDING_INTEGRATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
FAA_FULL_CONTRACT: BLOCKED
MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

No staging, commit, push, merge, cloud operation or operational acceptance is
part of this delivery. Stop after local implementation, evaluation and review.
