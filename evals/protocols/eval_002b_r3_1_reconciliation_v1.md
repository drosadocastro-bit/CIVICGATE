# EVAL-002B-R3.1 — bounded cross-channel reconciliation

Status: candidate for independent technical review. Acceptance remains HOLD.
Only synthetic local observations are in scope. No new execution authority.

## Independent reference and admission order

The client-observed typed `Envelope` is supplied to
`backend_capture_admission_v2.validate_backend_capture(expected_envelope=...)`
by `eval_002b_composition_v3`. It is the original `result.outcome.envelope`,
not a reconstruction from the audit record being admitted. Any completed
invocation without this reference is unverified; absent evidence is not coherence.
An observation with no governance activity may have no envelope.

The original invocation, typed arguments, deterministic policy, observer,
ExecutionBinding identity/consumption, timestamps, adapter entry and HTTP
request-shape checks from R3 remain. The new checks reconcile the completed
audit response with the actual observed envelope, each dispatch label with
that envelope, terminal reception facts with dispatch, and adapter termination
with observed result/error semantics. Fixture names, IDs and backend mode are
not used to decide the new consistency rules.

## State matrix derived from pinned adapter and Gateway

| State | HTTP finish and terminal facts | Adapter finish | Observed envelope | Admission / custody |
| --- | --- | --- | --- | --- |
| Successful read | HTTP200; response received; REQUEST_CONFIRMED / RESPONSE_RECEIVED | No error | OK, RESULT_VERIFIED, result | Admit; eligible for existing safe-close checks |
| Parsing failure after HTTP200 | HTTP200; received; confirmed; terminal HTTP exception may be null | Adapter exception | ERROR, FAILED_VALIDATION, no result | Admit complete failure; OPEN |
| Post-result validation failure | HTTP200; received; confirmed | May return without exception | ERROR, FAILED_VALIDATION, no result | Admit complete failure; OPEN |
| Timeout before response | No status; HTTP exception matches terminal exception; received=false; DISPATCH_UNKNOWN / TRANSPORT_ERROR | Adapter exception may differ from HTTP exception | ERROR, RESULT_UNKNOWN, no result | Admit complete uncertainty; OPEN |
| Pre-dispatch DENY/REVIEW | No backend rows, no attempts, NOT_DISPATCHED / NO_RESPONSE | No adapter rows | Held; no tool execution | Admit held capture; legitimate CLOSED |
| Adapter exception plus successful result | Successful HTTP/terminal facts | Non-null exception of any name | Successful verified result | Reject ADAPTER_TERMINATION_CONTRADICTION; OPEN |
| Audit dispatch differs from observed envelope | Audit may have two agreeing but wrong labels | Any | Independent dispatch reference differs | Reject DISPATCH_STATE_CONTRADICTION; OPEN |
| Received response with unknown/not-dispatched terminal label | received=true disagrees with terminal dispatch | Any | Even agreement of audit labels is insufficient | Reject receipt contradiction; OPEN |
| Client envelope lost | Execution may be recorded in other channels | Any | Independently observed reference absent | Reject OBSERVED_ENVELOPE_REQUIRED; reported counts retained, verified counts unknown; OPEN |

All rejection codes have the `BACKEND_CAPTURE_` prefix. Existing R3 validations
may reject malformed captures earlier. An exception name is not an intent or
causality oracle. HTTP success is not necessarily adapter/result success.
Binding consumption or HTTP entry alone never establishes response reception.

## Documentary effects and invariants

The composition records `backend_capture_admission` separately from
`observed_envelope`. A/B are injected after the synthetic response was observed.
Rejection sets `primary_projection_verified=false` and prevents close ACK;
it does not retract or rewrite the original observed result or Gateway decision.
Verified backend counts become null for rejected evidence; separately labeled
reported counts, primary capture bytes, consumed bindings and accounting remain.
No refund, retry, redispatch or capture repair is performed.

The saved summary precedes the close transaction. Final CLOSED/OPEN evidence
comes from read-only SQLite plus returned ACK and, for CLOSED, the exact saved
summary hash. A separate process calls only `ensure_recoverable()`, never
begin/reserve/dispatch, and compares SQL and capture identities before/after.

## Versioning, tests and limitations

Original R1/R2/R3/R4 and production files are immutable references. New tests
explicitly import the R3.1 successors. Original R3 tests remain a separate
baseline. Derivative tests update only the new independent-envelope interface
and strengthen lost-response expectations. Both JSON layers are exercised
through the R3.1 composition using owned synthetic provider responses.

This is a cooperative local evidence-consistency contract. Backend legacy rows
lack request/observation IDs; retained attribution uses the single bound
invocation, exact query, observer and timestamps. Hashes and typed equality do
not authenticate a hostile process or an independently trusted human.
No OS isolation, preemption, exactly-once, power-loss durability, live-provider
security, monetary readiness, semantic accuracy or human acceptance is claimed.
P2_02_DURABLE_STOP remains PARTIAL; live transport and execution remain on HOLD.
