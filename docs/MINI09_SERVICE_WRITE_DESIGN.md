# MINI09 — future synthetic review-state WRITE design

Status: `DESIGN_ONLY_NOT_IMPLEMENTED_NOT_AUTHORIZED`.

This specification prepares a future local research phase. MINI09 implements READ evaluation only. No review-state mutation tool, endpoint, handler, database migration or WRITE authority is added by this document.

The proposed user request is: “Mark synthetic award SYN-FAA-PR-026 as pending review and attach a reviewer note.” The identifier refers exclusively to the fictional DATA-01 dataset. No real award, FAA system or USAspending record would be changed.

## Existing boundary and necessary approval

At the inspected baseline `fdf91d288eba9160dedc4c83b8a0ff339da14857`, the [four MCP tools](../src/civicgate/models/requests.py) represent public reads. [Deterministic policy](../src/civicgate/governance/policy.py) and [ExecutionBoundary](../src/civicgate/governance/execution.py) use `PUBLIC_SPENDING_RESEARCH`. Their present authority is not authority to modify review state. A matching digest, synthetic planner proposal, favorable Judge signal or documentary CLOSED state cannot confer WRITE permission.

A future phase needs explicit human approval of a versioned mutable capability, strict input/output schemas, deterministic authorization rules, identity assumptions, trusted composition and pre-dispatch binding coverage. It must reuse the existing authority mechanism rather than create a second issuer. The feasibility of that minimal extension remains unverified. No present tool is silently repurposed and no change to the fixed four-tool registry is proposed for MINI09.

## Separate data stores

The source dataset remains immutable and independently hash-pinned. Its embedded initial `review_status` is source metadata, not the live mutable state. A separate local SQLite store would overlay review state using the pair `(dataset_sha256, synthetic_award_id)` as its target identity. An unknown award, mismatched dataset or contradictory source identity must be rejected before mutation.

Proposed logical records, not an implemented schema:

| Record | Required content |
| --- | --- |
| Review state | Dataset digest, synthetic award ID, status, bounded reviewer note, monotonically increasing version, last committed operation ID |
| Operation | Unique operation ID, idempotency key, canonical request digest, expected version, explicit authorization reference, exact binding identity, outcome |
| Evidence | Before/after state and digests, actual committed version, operation correlation, result and custody acknowledgements |

For a never-reviewed award, the future contract must explicitly define the starting state and version; absence must not be guessed to mean “approved” or “pending.” Notes need a bounded length, no executable interpretation and output escaping in any display. A local owner boundary does not independently authenticate a remote reviewer or protect against a hostile administrator.

## Proposed operation contract

The exact effective operation must be fixed before deterministic evaluation: dataset identity, award ID, requested status, exact note bytes or their unambiguous canonical encoding, expected version, idempotency key, operation identity and approved scope. The future binding must cover these effective values and the applicable schema and policy decision. Mutable state may not be substituted after authorization. A read binding must fail for this operation.

The future authorization must distinguish permission to update synthetic review state from any governmental decision. `pending_review` is a local workflow annotation, not an award determination. Model content remains advisory. Missing authorization, invalid schema, unsupported status transitions, absent current-state evidence or unresolved custody must fail closed.

## Atomic commit and idempotency

A proposed transaction would:

1. Confirm acknowledged durable intent and the exact already-consumed pre-dispatch authorization before entering the handler. Failure to acknowledge intent prevents dispatch.
2. Begin a bounded SQLite transaction and look up the idempotency key and target state under the same transaction.
3. If the key is already committed for the identical canonical operation, return its stored result without another mutation. If it names different content, reject it as an idempotency conflict. This is receipt retrieval, not permission to dispatch an uncertain historical operation again.
4. Verify the immutable dataset reference, target, expected version and permitted transition. Reject stale versions without silently merging or rewriting notes.
5. Write the new review state, increment the version, and record the before/after operation evidence atomically in the same store. Commit before reporting successful mutation.
6. Preserve a separate durable result/custody acknowledgement. A successful state commit followed by failed acknowledgement is not REJECTED or safe to repeat; it is an uncertain receipt requiring investigation.

SQLite lock, corruption, unavailable storage or unconfirmed intent prevents a new mutation. A rollback before commit must leave the old state and version intact. The design must be tested against actual SQLite transaction and process-failure behavior; listing these steps is not proof of power-loss durability or distributed exactly-once execution.

## Conflicts, recovery and rollback

An observed timeout, lost response or process death after dispatch must retain the attempt and block automatic retry. Recovery must inspect the same operation identity, committed state and evidence in read-only mode before deciding whether a commit occurred. Ordinary restart, a new idempotency key or a fresh session must not bypass unresolved custody for that bounded target operation. The exact recovery authority and clearing conditions require a separately reviewed contract.

A corrective rollback after a committed update is a new, explicitly authorized compensating operation with its own expected current version, binding and before/after evidence. It must preserve the original update and note history. Deleting evidence, restoring an old database over a newer state, decrementing versions or editing the immutable source is not an acceptable rollback.

## Required future acceptance tests

| Area | Minimum expected evidence |
| --- | --- |
| Authorization | No WRITE under discovery, model approval, read binding, unknown identity or missing explicit authorization |
| Exact scope | Target/note/status/version/idempotency tampering rejected before mutation; no post-authorization substitution |
| Atomicity | State and operation evidence commit together, or both remain unchanged before commit |
| Concurrency | Two writers using one expected version yield one commit and one version conflict |
| Idempotency | Identical committed request returns the preserved receipt without a second update; altered content under the same key rejects |
| Uncertainty | Crash before intent, during transaction, after commit and before ACK remain distinguishable; no automatic redispatch or refund |
| Recovery | Restart preserves unresolved custody and cannot clear it through ordinary completion or new identifiers |
| Integrity | Dataset hash unchanged; before/after hashes and versions reconcile with durable records |
| Display | Notes remain inert, escaped and bounded; credentials and private paths are not exposed |
| Compatibility | Existing Channel A READ contracts, PERMIT/DENY/REVIEW_REQUIRED, binding semantics and historical evidence unchanged |

No listed acceptance test has been executed for WRITE in MINI09. A future implementation proposal and explicit human authorization are prerequisites.

## Retained limits

`LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED`; `EVAL002_EXECUTION_AUTHORIZATION: HOLD`; `USASPENDING_INTEGRATION: HOLD`; `MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED`; `P2_02_DURABLE_STOP: PARTIAL`; `FAA_FULL_CONTRACT: BLOCKED`; `PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED`.

The 54 historical FAA full-contract definitions remain BLOCKED/SKIP. No model, cloud, holdout or WRITE execution is authorized by this design.
