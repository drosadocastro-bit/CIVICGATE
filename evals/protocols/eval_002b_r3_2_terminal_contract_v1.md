# EVAL-002B-R3.2 / Mini04 — terminal attempt evidence contract v1

Status: offline development candidate; acceptance HOLD. This is an additive
evaluation-level reconciliation contract, not a production schema, policy,
retry permission, authority grant or scientific amendment.

## Pinned producer and scope

The contractual reference is `src/civicgate/adapters/usaspending.py`, SHA-256
`56540259e73c98f3253cae67288a6900190354d042dd6fb6209d2cc302f14816`.
Its `AttemptRecord` declarations and `model_dump` are at lines26–58;
configuration bounds at153–172; retry-after parsing at174–191; attempt
production and retry branches at193–422. The original producer remains unchanged.

The R3.1 starting validator is `backend_capture_admission_v2.py`, SHA-256
`df76a72c03a21a197442342e2d9126c28d610ce5cc644eae9a13b9d0010bf1a8`.
R3.2 retains its independent-envelope, request/binding, policy, timestamp,
receipt and capture reconciliation. Only versioned evaluation successors are
permitted. Gateway, production adapter, policy, bindings, provider transport,
shared parser, budget and SQLite implementation are protected references.

`AttemptRecord` is an annotated frozen dataclass. Those annotations do not
validate dictionaries parsed from an audit file. Admission must check the
actual record before using its fields or claiming coherent evidence.

## Complete shape and field matrix

`model_dump()` emits exactly the eleven keys below. Every key is required,
including nullable keys. An absent key is not an explicit valid null. Additional
keys are unsupported by this pinned record shape. No coercion or silent default
is permitted: `42` must not become a class name, `true` must not become ordinal1,
and an unknown retry literal must not become `NONE`.

| Field | Representation and nullability | Domain / relationship |
| --- | --- | --- |
| `attempt` | Exact integer; boolean excluded; non-null | Positive ordinal, no greater than `max_attempts`. Current harness requires exactly1. |
| `max_attempts` | Exact integer; boolean excluded; non-null | Production configuration accepts1–3. Current harness requires exactly1 and one terminal attempt record; this contract does not increase either. |
| `elapsed_ms` | JSON number: integer or float, boolean excluded; non-null | Finite and nonnegative, preserving existing `_duration` validation. No new upper deadline or arbitrary numeric cap is invented. |
| `dispatch_state` | Exact string; non-null | Producer declares `DISPATCH_ATTEMPTED`, `REQUEST_CONFIRMED`, `DISPATCH_UNKNOWN`. Actual pinned branches use confirmed when a response exists, unknown otherwise. Domain membership does not establish a coherent received state. |
| `response_state` | Exact string; non-null | `NO_RESPONSE`, `RESPONSE_RECEIVED`, `TRANSPORT_ERROR`. A received header/status may coexist with a later transport error. |
| `exception_type` | Explicit null or string | Successful terminal HTTP completion has null. Coherent error branches record `type(exc).__name__`. Numbers, booleans, arrays and objects are invalid; class names are not whitelisted or coerced. |
| `status_code` | Explicit null or exact integer, boolean excluded | No response means null; a received response has a bound status. Preserve the existing100–599 received-status bounds and agreement with the HTTP component. |
| `response_received` | Exact boolean; non-null | Reflects `response is not None`; it does not prove the response body completed. Binding consumption and transport entry alone do not prove reception. |
| `retry_after_seconds` | Explicit null or JSON number, boolean excluded | Numeric values must be finite and nonnegative. Success emits null; error branches can preserve nullable header-derived metadata. No new arbitrary upper cap. |
| `retry_decision` | Exact string; non-null | Declared domain `NONE`, `RETRY_ALLOWED`, `RETRY_BLOCKED`. Validate state/capacity after validating this domain. |
| `retry_reason` | Exact string; non-null | The producer annotates this as a string, not a production Literal enum. Reconcile the actual producer reasons and state; do not normalize unknown or contradictory values into success. |

The strict shared JSON reader remains responsible for rejecting nonfinite
numbers in the input representation. Field validation also preserves finite
number checks and exact boolean/integer separation. The record's number fields
are JSON numbers, not an invented float-only wire contract.

## Producer state matrix

These relationships derive from the pinned constructors and branches, not
fixture IDs, test mode names or expected outputs.

| Terminal HTTP path | Dispatch / response / status | Exception and retry tuple | Cross-channel interpretation |
| --- | --- | --- | --- |
| Completed HTTP read and JSON decode | `REQUEST_CONFIRMED` / `RESPONSE_RECEIVED` /200; received=true | exception=null; retry_after=null; `NONE` / `success` | Terminal HTTP success. Later adapter shape validation or post-result validation can still fail. |
| Timeout before response | `DISPATCH_UNKNOWN` / `TRANSPORT_ERROR` /null; received=false | Exception class; `RETRY_BLOCKED` / `timeout` at max1 | Unknown delivery/result; preserve the attempt, consumed work and OPEN. HTTP and adapter exception names can differ. |
| Timeout after response | `REQUEST_CONFIRMED` / `TRANSPORT_ERROR` /bound status; received=true | Exception class; `RETRY_BLOCKED` / `timeout` at max1 | Reception is established, completion is not. Do not relabel this as no dispatch. |
| Request/stream error | Confirmed if response exists, unknown otherwise; `TRANSPORT_ERROR` | Exception class; retry_after=null; `RETRY_BLOCKED` / `network error` at max1 | Received HTTP200 headers can precede a body-read failure. |
| Retryable upstream status | `REQUEST_CONFIRMED` / `RESPONSE_RECEIVED` /429 or5xx; received=true | `AdapterError`; nullable Retry-After; ALLOWED only if ordinal<maximum, otherwise BLOCKED; `retryable upstream status` | General producer branch. Its existence does not expand this harness or remove the legacy HTTP status admission restrictions. |
| Other in-stream AdapterError | Confirmed/received with a bound response, otherwise unknown/no-response | Error class; `NONE`; lowercased error code | Producer examples are `not_found`, `upstream_rejected`, `malformed_response`, `response_too_large`. Do not conflate this layer with the HTTP handler's exception class. |
| Retry budget exhausted | Retains the previous attempt's observed transport facts | Previous pending retry becomes `RETRY_BLOCKED` / `retry budget exhausted` | No new attempt is appended for a retry prevented before transport entry. This general producer branch is not evidence of retry authority in the max1 harness. |

The successful HTTP constructor is at247–267. Timeout and request-error
constructors are at270–352. AdapterError constructors and retry-budget rewrites
are at353–416; a pre-entry exhaustion rewrite also appears at208–224.

### Required success and retry consistency

A coherent terminal success tuple requires null exception, `NONE`, `success`,
null Retry-After, confirmed received HTTP200 and `RESPONSE_RECEIVED`. Any
incompatible exception name rejects; the rule is not a blacklist of Mini03's
three names. A valid enum such as `RETRY_BLOCKED` can still contradict success.

`RETRY_ALLOWED` cannot coexist with exhausted `attempt == max_attempts` and
cannot label a completed success. The current harness has attempt=max_attempts=1,
so it never admits an allowed retry. This context restriction does not remove
the `RETRY_ALLOWED` value from the general production adapter's declared domain.
Neither `retry_decision` nor the envelope's separate `retry_class` issues an
ExecutionBinding, dispatch authority or permission to repeat an observation.

Error-path exception class names remain strings in context. No generic rule
requires terminal, HTTP and adapter names to be identical. Preserve the existing
explicit equality where the HTTP component actually recorded the originating
exception, while retaining legitimate exceptions that arise later in the stack.

### Separation of successful reception from later errors

The synthetic HTTP component finishes when its handler returns a response.
It can therefore report HTTP200/error=null before the response stream later
raises `ReadError` or `ReadTimeout`. The production adapter explicitly supports
that received-response transport-error path. A tests-only stream control may
exercise it without modifying production or creating a new authority channel.
Execution and evidence for that control must be reported separately; this
document alone is not a claim that it passed.

Do not require exception=null solely because the HTTP component had no error.
Select terminal success using the complete terminal relationship. Conversely,
do not require an HTTP exception merely because the overall envelope is ERROR.

The existing malformed-backend control is valid JSON with an invalid typed
response shape. `_request()` completed successfully; later validation at
474–493,518–528 or542–553 raises AdapterError while retaining the original
null/`NONE`/`success` terminal HTTP record. The global result is withheld and
OPEN remains, but that complete failure capture is coherent and admissible.

Raw invalid JSON inside `_request()` is a distinct producer limitation: it
appends a success record before `json.loads`, then appends an AdapterError record
when decoding fails. This can create two records for one ordinal even at max1.
The inherited one-record capture rule rejects that shape. Mini04 must not
silently relax cardinality or modify the producer to make such an optional
control pass; characterize the limitation separately if exercised.

## Evidence admission and fail-closed effect

New terminal shape/type/domain and semantic checks operate before projection
verification and the existing safe-close decision. Rejection must have a stable,
payload-free reason and no secondary exception from malformed field values.
Missing evidence or an unsupported combination is not established coherence.

Contradictory or invalid terminal capture must leave
`primary_projection_verified=false`, the durable observation OPEN, no close ACK,
and no close hash/time. A fresh process checks only `ensure_recoverable()` and
must remain blocked for the unresolved observation; it never begins/reserves or
dispatches another observation to test recovery.

The independently observed envelope and delivered synthetic result remain
historical facts. Evidence rejection after execution does not retract delivery
or relabel it as never executed. Preserve known consumption and raw reported
counts while keeping unverified aggregate counts unknown. Attempts, bindings,
leases, reservations and response facts must not be refunded, retried,
redispatched, reset or repaired by evidence admission.

Complete coherent error/unknown captures remain admissible evidence while their
result/validation state keeps OPEN. Pre-dispatch DENY and REVIEW have no attempt
record, no binding consumption or backend dispatch, and retain legitimate held
closures. Their labels must not be converted to PERMIT.

## Coverage, provenance and limits

Mini03's six C/D variants are historical defect evidence, not security acceptance.
Mini04 requires new full-path C/D and controls on the successor, A/B regressions,
nearby justified terminal-contract negatives, and preservation of the original
incomplete-capture, malformed-worker and nonfinite JSON fixes. Test imports and
source hashes must identify the successor rather than silently exercise R3.1.
The resulting evidence report records what ran, what was only hashed and any
unexecuted or unsupported positive path. Overlapping suites are not summed.

This contract was coauthored by an AI collaborator through read-only producer
analysis and additive documentation. It grants no human acceptance. Python
guards are cooperative process controls, not OS isolation; no hostile-host
authenticity, power-loss durability, preemption or exactly-once is certified.

ACCEPTANCE: HOLD
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED
GRANITE_EFFECTIVE_IDENTITY: UNKNOWN
LUNA_EFFECTIVE_IDENTITY: UNKNOWN
EVAL002_EXECUTION_AUTHORIZATION: HOLD
JUDGE_CALIBRATION: NOT_YET_MEASURED
INDEPENDENT_GOLDEN_REFERENCE_ACCEPTANCE: PENDING
P2_02_DURABLE_STOP: PARTIAL
HOLDOUT: RESERVED_UNEXECUTED_NOT_ADJUDICATED
DATABRICKS_NATIVE_PORT: OUT_OF_SCOPE
