# CivicGate Milestone 3 Plan: Execution-State Receipts

Status: **staged implementation slice implemented and covered; full M3 adoption gate remains open.** Receipt schema, attempt metadata and stateful fixture work are implemented within the scope below and exercised by `tests/adversarial/test_receipts.py` plus the `five-hundred-then-success` and `timeout-then-changed-snapshot` cases in `tests/fixtures/adversarial.json`. Default HTTPX still cannot prove wire-level dispatch for every timeout, so the model records that uncertainty explicitly rather than claiming a full send guarantee. Reviewed by Claude (gap analysis), Nova (threat-model refinement), and Luna (implementation-feasibility review against the current code).

## Origin

This plan responds to Mansoor, Phadke & Rana, *"Verified Tool Calls Improve LLM Agent Reliability Under Non-Atomic Failures"* (arXiv:2608.02645, Jul 2026), which observes that real tool calls are not atomic — timeouts after dispatch, delayed visibility, and partial state updates make binary success/failure signals unreliable — and proposes postcondition verification, verify-before-retry, and idempotency keys as a general-purpose wrapper.

CivicGate did not adopt this paper's design. CivicGate independently built a structural separation between authorization, execution, and verified result before this paper was read (see below). The paper is used here as an external adversarial lens on an existing invariant, to find boundary cases the invariant does not yet name — not as a spec to import wholesale.

## What CivicGate already does (verified against the current implementation)

| Concept | Existing mechanism |
|---|---|
| Authorization state | `Envelope.decision: PERMIT \| DENY \| REVIEW_REQUIRED`. **Correction:** this is the *initial* pre-dispatch decision; the final envelope decision may still escalate through the existing post-execution path described below. It is not issued once and frozen. |
| Execution occurred | `Envelope.tool_executed: bool`, set `True` immediately before the adapter dispatch call in `mcp/tools.py`. **This means "the gateway initiated adapter execution," not "the request reached the provider."** It must not be treated as a stand-in for `dispatch_state` below. |
| Verified result | `Envelope.status: OK` reached only after schema revalidation, provenance/record-count consistency, and source-type match |
| Partial result signal | `Provenance.truncated: bool` |
| Conflicting source detection | duplicate `generated_internal_id` check in `adapters/usaspending.py::search()`, already covered by `tests/adversarial/test_boundaries.py:82` |
| Retry loop | `adapters/usaspending.py::_request()` — 3 fixed attempts, fixed 0.2/0.4s backoff, retries `TIMEOUT`/`NETWORK_ERROR`/429/5xx only |
| Post-dispatch authorization escalation | `decision` already escalates to `REVIEW_REQUIRED` after dispatch, in `mcp/tools.py`, along three paths: ambiguous recipient/identity resolution, `AdapterError` with code `CONFLICTING_SOURCE_RESULTS`/`PROVENANCE_UNAVAILABLE`, and a catch-all for `ValidationError`/`ValueError`/`TypeError`/`KeyError`/`AttributeError` at the gateway's own revalidation boundary (`review_reason="ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"`). Documented in `ARCHITECTURE.md`. |

The paper's core thesis — authorization state ≠ execution state ≠ verified result state — is already structurally true in CivicGate. This plan makes the execution/result side of that separation explicit and adds a transport-uncertainty state it currently lacks.

## Governing invariant (binding on this design)

> `Envelope.decision` may escalate after dispatch only when post-execution evidence changes the *resolvability* of the request — scope ambiguity, identity ambiguity, provenance incompleteness or conflict, or data-integrity failure that bears on the governed outcome. Transport failure and unknown execution outcome are execution/result-state concerns and must not be mislabeled as authorization failure.

Two lanes, kept separate:

```
LANE A — request/evidence resolvability (touches decision)
PERMIT → post-fetch ambiguity or integrity issue → REVIEW_REQUIRED

LANE B — execution mechanics (does not touch decision)
PERMIT → dispatch → timeout / no response / verification outcome
       → RESULT_VERIFIED | RESULT_UNKNOWN | FAILED_VALIDATION
       → next_action: NONE | RETRY_ALLOWED | RETRY_BLOCKED | HUMAN_REVIEW_REQUIRED | STOP
```

**Correction on `FAILED_VALIDATION` (Luna):** the current code does not have one uniform "malformed infrastructure output" outcome. There are two distinct paths, and the plan must keep them distinct rather than collapsing both into `PERMIT + FAILED_VALIDATION + STOP`:

- **Adapter-side schema failure** (the adapter's own Pydantic model fails to validate the upstream response, or the upstream returns a non-JSON content type) raises `AdapterError("MALFORMED_RESPONSE")`. This is caught in `mcp/tools.py`'s `except AdapterError` block, which leaves the pre-existing decision unchanged (normally `PERMIT`, since this branch only runs when the pre-dispatch decision already was `PERMIT`) and sets `status="ERROR"` — this is the Lane B, `FAILED_VALIDATION`-equivalent case.
- **A record-count mismatch** (`batch.provenance.records_returned != len(batch.records)`) raises `AdapterError("PROVENANCE_UNAVAILABLE")` — caught by the *same* `except AdapterError` block as above, which then checks `exc.code in {"CONFLICTING_SOURCE_RESULTS", "PROVENANCE_UNAVAILABLE"}` and escalates `decision` to `REVIEW_REQUIRED` with `review_reason="PROVENANCE_UNAVAILABLE"`. This is Lane A, and it is a *different* code path and a different `review_reason` string than the one below — both currently resolve to `REVIEW_REQUIRED`, but by distinct routes that a future implementation must not conflate.
- **Gateway-boundary revalidation failure** (the gateway's own `DataBatch.model_validate()` re-check fails, or a field access like `row["award_amount"]` raises `KeyError`) is caught by a *separate* except clause (`ValidationError`/`ValueError`/`TypeError`/`KeyError`/`AttributeError`) that always escalates `decision` to `REVIEW_REQUIRED` via `review_reason="ADAPTER_SCHEMA_OR_PROVENANCE_INVALID"` — this is also Lane A, via yet another route.

All three must be named explicitly and kept distinct in the eventual state design; a single `FAILED_VALIDATION` label, or treating the record-count and schema-revalidation cases as one path, would erase distinctions the code already makes on purpose.

**Explicit non-goal:** post-dispatch escalation must not become a catch-all. `timeout → REVIEW_REQUIRED`, `network error → REVIEW_REQUIRED`, `5xx → REVIEW_REQUIRED` would re-merge governance ambiguity with infrastructure failure and destroy the distinction this plan exists to create.

## State axes

```
authorization_state:  PERMIT | DENY | REVIEW_REQUIRED          (unchanged, Lane A)
dispatch_state:        NOT_DISPATCHED | DISPATCH_ATTEMPTED | REQUEST_CONFIRMED | DISPATCH_UNKNOWN
response_state:        NO_RESPONSE | RESPONSE_RECEIVED | TRANSPORT_ERROR
verification_state:    UNVERIFIED | RESULT_VERIFIED | RESULT_UNKNOWN | FAILED_VALIDATION
validation_lane:       NONE | LANE_A_RESOLVABILITY | LANE_B_EXECUTION
validation_reason:     NONE | MALFORMED_RESPONSE | PROVENANCE_UNAVAILABLE | ADAPTER_SCHEMA_OR_PROVENANCE_INVALID
next_action:           NONE | RETRY_ALLOWED | RETRY_BLOCKED | HUMAN_REVIEW_REQUIRED | STOP
```

**Dispatch decision (resolved for implementation):** `tool_executed=True` means only that the gateway entered adapter execution. It never upgrades `dispatch_state`. `NOT_DISPATCHED` is certain when policy holds the call before the adapter. `DISPATCH_ATTEMPTED` is an intermediate observation emitted when `_request()` enters the configured transport boundary; once that attempt finishes without confirmation, its terminal state is `DISPATCH_UNKNOWN`. `DISPATCH_ATTEMPTED` is a client-side observation, not proof that bytes left the process. `REQUEST_CONFIRMED` is reserved for a response whose headers were observed, or an explicitly instrumented transport event that confirms handoff. `DISPATCH_UNKNOWN` covers an attempted call with no response and no send acknowledgement. A real `ConnectTimeout` and a timeout before response headers therefore remain `DISPATCH_UNKNOWN`; the client cannot prove "never left" versus "left but produced no response" from the default HTTPX exception alone. A `ReadTimeout` after response headers is `REQUEST_CONFIRMED` plus `TRANSPORT_ERROR`. For `httpx.MockTransport`, handler entry proves only that the request crossed the mock boundary; a custom response stream can confirm headers or raise during body iteration, but neither simulates a real network send. The implementation must preserve `DISPATCH_UNKNOWN` instead of inferring provider-side truth. A retry budget that is exhausted before an attempt enters the transport boundary appends no attempt record at all — nothing was dispatched — and instead marks the preceding attempt's pending retry as `RETRY_BLOCKED` with reason `retry budget exhausted`.

### Implementation constraints on the `Envelope` model (Luna)

`Envelope` is a `StrictModel` (`extra="forbid"`, defined once on the shared `StrictModel` base in `models/requests.py`; the `Envelope` class itself starts in `models/responses.py`). The new axes above must be added as explicit fields, not inferred from existing ones:

- `decision`, `status`, and `tool_executed` stay unchanged — additive only.
- New fields need defaults so existing constructors (tests, fixtures) don't break.
- Every return path in `Gateway._call` must set them before returning — a field that's sometimes populated and sometimes left at a stale default is worse than not having it.
- This changes the MCP response shape. Document it: a client validating the JSON against a closed schema may need updating.

**Attempt-history decision:** keep the full bounded history trace-first, with a compact summary in the MCP envelope. Each trace attempt record contains `attempt`, `max_attempts`, elapsed time, `dispatch_state`, `response_state`, exception class or HTTP status, `response_received`, parsed `retry_after_seconds` when present, the retry decision, and the reason for allowing or blocking the next attempt. The envelope carries only the bounded summary needed by a caller (`attempt_count`, `retry_class`, final `next_action`, and the current final-state axes); `request_id` is the trace lookup key and the trace records are redacted like existing events. This keeps the normal response small while preserving an auditable `5xx → 200` or `timeout → retry → 200` trajectory. A client that needs per-attempt reasoning must request the trace; the tradeoff is explicit rather than silently exposing transport history in every MCP response.

## Retry safety is not `READ_ONLY ⇒ SAFE_TO_RETRY`

Read-only means no mutation of authoritative application state. It does not mean effect-free. USAspending-relevant operational effects that a blind retry can still cause or be affected by:

- API quota / billable request consumption
- rate-limit escalation or provider-side anti-abuse throttling
- cache mutation or cache warming
- **temporal drift between retries** — a timed-out request retried against a data source that has since changed can return a result from a different effective snapshot than the original attempt would have; pagination across retries can mix snapshots
- repeated access triggering provider-side protections

**Cross-doc note:** `SECURITY.md` currently states *"Read-only POST searches are safe to retry."* That line predates this analysis and describes the code's current retry trigger conditions accurately, but not its operational-effect exposure. It should be revised to the `CONDITIONALLY_SAFE` framing below if and when this plan is adopted — not before, since adopting the language without the mechanism would overstate what the code currently does.

`retry_class` is a **proposed**, deterministic, non-LLM contract — not a description of current behavior:

```
retry_class: SAFE | CONDITIONALLY_SAFE | UNSAFE | UNKNOWN
```

Target framing for current USAspending reads: `semantic side effects = NONE`, `resource side effects = POSSIBLE` → `retry_class = CONDITIONALLY_SAFE`.

**Gap between this contract and the current adapter (Luna, verified against `usaspending.py::_request`, line 78):**

- Retry count is fixed at 3 attempts; not configurable or exposed to the caller.
- Backoff is fixed (`0.2 * 2**attempt` → 0.2s, 0.4s), not derived from any response.
- `Retry-After` is never read from the response headers — a 429 gets the same fixed backoff as any other retryable error.
- The attempt number is not surfaced outside the loop.
- There is no global elapsed-time or rate-limit budget across attempts — only the existing per-attempt 20s `asyncio.timeout`.
- `query_hash` is computed once per call but never used in the retry decision itself.
- `httpx.TimeoutException` collapses `ConnectTimeout`, `ReadTimeout`, and other timeout subtypes into one `AdapterError("TIMEOUT")` — no distinction between "never left the process" and "sent but no response."
- After the final attempt (`attempt == 2`), a retryable `AdapterError` is still raised with `retryable=True` set, even though no further retry will actually happen — the flag no longer means what it says at that point.

**Conclusion: `retry_class` cannot simply be added to the envelope at the end.** The boundary between `_request()` and `Gateway` needs to carry attempt-level metadata first — at minimum: current attempt and max, exception class or HTTP status, whether a response was received at all, `Retry-After` value if present, elapsed time, and the reason the next attempt was allowed or blocked. `retry_class` is computed from that metadata; it is not a label bolted onto the final result.

**Attempt-metadata boundary decision:** introduce a typed internal `RequestOutcome` for successful calls and attach the same bounded `AttemptRecord[]` plus query fingerprint to `AdapterError` for failed calls. `_request()` returns `RequestOutcome(raw, query_fingerprint, attempts)` instead of a bare two-tuple; each public adapter method wraps a successful `DataBatch` in a private `AdapterCall(batch, outcome)` so the history cannot be discarded before it reaches `Gateway`. Adapter-side validation errors raised after `_request()` returns (including `MALFORMED_RESPONSE` and `CONFLICTING_SOURCE_RESULTS`) reuse that outcome's attempts and fingerprint when they become `AdapterError`. On exhaustion, `_request()` raises an `AdapterError` carrying the attempt records and fingerprint. `Gateway` normalizes the adapter result, writes the full records to the trace, derives the envelope summary, and never copies response bodies or arbitrary headers into either surface. A legacy alternate adapter that still returns a bare `DataBatch` is accepted during migration but must mark attempt metadata unavailable (`attempt_metadata_available=false`, `retry_class=UNKNOWN`) rather than inventing an empty successful history. Each `AttemptRecord` has `attempt`, `max_attempts`, `elapsed_ms`, `dispatch_state`, `response_state`, `exception_type`, `status_code`, `response_received`, `retry_after_seconds`, `retry_decision` and `retry_reason`.

`Retry-After` is parsed from any received retryable HTTP response (at least 429 and any configured 5xx class), normalized to seconds, bounded by the call-level retry budget and recorded even when it blocks the next attempt. The existing three-attempt limit remains the initial experiment default, but the budget and the reason for exhaustion are explicit metadata rather than hidden control flow. The existing `Error.retryable` flag is redefined at the gateway boundary to mean "another retry is currently allowed"; it is `False` after the final attempt, while the attempt history preserves that the underlying error class was normally retryable. This removes the current `retryable=True`-after-exhaustion ambiguity without pretending the old adapter already has these signals.

For this first slice, the call-level budget is **60.6 seconds**: three existing 20-second attempt ceilings plus the existing 0.2/0.4-second backoff allowance. It is an explicit baseline derived from the current loop, not a provider SLA; later calibration belongs to the experiment rather than this implementation gate.

## Idempotency: recorded, not guaranteed

`request_id` is always assigned and always reaches the audit trace, regardless of outcome. `query_fingerprint` is weaker than that: it is computed at the start of every `_request()` call, but it only reaches `Provenance` — and therefore the trace — when a `DataBatch` is actually constructed, i.e. on a successful adapter call. On a transport error, timeout, or malformed response, `_request()` raises before returning the fingerprint to the caller, and it is silently discarded. So the identity that is "replay-comparable" today is real only for successful calls; a transport-failed, timed-out, or malformed call currently leaves no fingerprint in the trace at all. This is the same gap the attempt-metadata decision above addresses — recording per-attempt identity, not just per-successful-call identity, is part of what closing that gap means.

That gap is intentionally not closed by adding write-capable idempotency machinery in this milestone: idempotency *keys* (in the paper's sense — a token a downstream system honors to reject duplicate mutations) only earn their complexity once there is a mutation to protect against duplicating. CivicGate has none. Building that machinery now would be scope creep against the milestone boundary already stated in `AUTHORITY_MODEL.md` and `MILESTONE_2.md`: *"Stop here before Milestone 3. Do not add writes..."* This plan does not add writes. It only makes read execution-state explicit.

## Validation experiment

**Fixture-extension decision:** keep the JSON declarative and add an optional `transport_factory` key plus an `observed_receipt` expectation block. A test-only Python registry keyed by factory name supplies the `httpx.MockTransport` or custom `AsyncByteStream`; `evaluate.py` constructs that transport once per fixture case so its closure persists across all attempts, then records only observable receipt fields. Existing cases with no factory continue to use `fixture_adapter()`. This extends the existing evaluator rather than creating a second harness, and keeps executable behavior out of the JSON.

The first factories are `five_hundred_then_success`, which returns a 500 followed by a valid 200, and `timeout_then_changed_snapshot`, which raises during the first response stream and returns a different valid body on the retry. They are exercised by the `five-hundred-then-success` and `timeout-then-changed-snapshot` fixture cases (category `non_atomic_failure`) and by `tests/adversarial/test_receipts.py`, which also covers timeout exhaustion, `Retry-After` recording, the three `FAILED_VALIDATION` routes, the legacy bare-`DataBatch` adapter path, and `NOT_DISPATCHED` for held calls. The latter's `observed_receipt` checks only the attempt trajectory (first attempt unknown, second response observed and verified); the hidden fact that the second body differs from an unobserved first snapshot is retained as simulation metadata and is never scored as a CivicGate-observable failure. The registry covers the mid-stream failure case through `timeout_then_changed_snapshot`; repeated-timeout exhaustion is covered inline in `test_receipts.py` with a handler that always raises. Neither imports test transports into production code.

Fixture-by-fixture viability (Luna, verified against the current adapter):

| Case | Status |
|---|---|
| timeout-before-dispatch | Approximable via `MockTransport` raising `ConnectTimeout`, but the runtime cannot actually prove the request was never sent. Synthetic approximation, not a true negative. |
| timeout-after-dispatch | Viable — an `AsyncByteStream` raising `ReadTimeout` during `aiter_bytes()`. Collapses to `TIMEOUT` in the current adapter. |
| response-after-client-timeout | **Not observable as written.** A response arriving after CivicGate has already given up cannot enter CivicGate's own result. Approximate instead as "first attempt times out, second attempt receives a response." |
| HTTP 200 + invalid schema | Directly viable; resolves to `MALFORMED_RESPONSE` today. |
| truncated response | Two distinct meanings need separating: `hasNext=true` → `Provenance.truncated=True` (a known, intentional signal) vs. a JSON body cut off mid-stream, which needs a broken stream/invalid body and produces a different error class entirely. |
| `records_returned` mismatch | **Cannot be produced from an HTTP response alone** — `_batch()` computes `records_returned=len(records)` internally, so the two can never disagree from outside. Requires a broken/double adapter or injection at the gateway boundary. |
| duplicate source ID | Directly viable; already covered by `tests/adversarial/test_boundaries.py:82`. |
| 429 + `Retry-After` | Viable to send the header in a mock response; the current code ignores it and applies fixed backoff regardless. |
| 5xx then success | Directly viable — confirmed a counter-based `MockTransport` handler can return 500 then 200 within one call. |
| repeated timeout exhaustion | Viable; ends today after 3 attempts with `TIMEOUT`. |
| timeout → retry → response differs from first snapshot | Viable with a stateful handler that changes the response body per attempt. **But** if the first attempt timed out, CivicGate never observed the first snapshot's content — so "different from the first snapshot" only exists as the fixture author's hidden knowledge, not as something CivicGate itself could ever detect. |

**Oracle-leakage correction, self-applied (Luna):** the document's own OMR definition (below) requires the oracle to use only evidence CivicGate could actually observe. The two unobservable cases in the table above — `response-after-client-timeout` and `timeout → retry → response differs from first snapshot` — describe things CivicGate structurally cannot observe. They are useful for testing that CivicGate preserves `RESULT_UNKNOWN` for the timed-out attempt and records a verified second response without claiming that the two snapshots were identical, but they must never be scored as if CivicGate should have detected the hidden difference. The experiment design has to separate "what the fixture simulates happening" from "what CivicGate's receipt is allowed to claim it knows" — conflating the two would violate the oracle-leakage rule this same document sets out below.

### Metrics

**Outcome Misclassification Rate.** The oracle must only use evidence CivicGate could actually observe — never the fixture's hidden ground truth about what happened at the provider.

```
OMR = |{cases where observed classification ≠ CivicGate-observable ground-truth class}| / |non-atomic-failure fixtures|
```

**Unsafe Retry Rate.** Retries performed when the retry policy's own observable state did not justify another attempt.

**Ambiguity Preservation Rate.** Whether CivicGate correctly preserved `RESULT_UNKNOWN` rather than collapsing it to a false `FAILED` or false `RESULT_VERIFIED` when the available evidence could not distinguish success from failure.

## Adoption gate

This becomes an architecture change only if the experiment shows all of:

1. current `ERROR` semantics collapse materially different execution states;
2. richer receipts reduce that misclassification;
3. retry policy becomes more faithful without materially weakening availability;
4. deterministic authority remains untouched (Lane A/Lane B separation holds under adversarial fixtures);
5. provenance and replay remain intact;
6. added complexity is proportional to the measured benefit.

If `OMR = 0` under realistic read fixtures, or the richer state machine adds complexity with no behavioral difference, the documented conclusion is: *interesting paper, not currently justified for CivicGate* — and it is not adopted. That is a valid outcome of this experiment, not a failure of it.

## Implemented pre-implementation design decisions

The five feasibility blockers were resolved as design decisions and are now implemented in the staged first slice described below. Two gaps found during independent revalidation are also closed: the retry-budget-exhaustion branch is now regression-tested directly (`tests/adversarial/test_receipts.py::test_retry_budget_exhaustion_blocks_next_attempt_without_fake_record`, which forces the exact `remaining <= 0` branch deterministically rather than relying on real timing, since real timing cannot reliably distinguish it from the separate, always-correct in-handler backoff-budget check), and per-attempt records are now persisted into `artifacts/evaluation.json` (via `scripts/evaluate.py`) rather than only being checked transiently during the harness run and then discarded.

1. **Dispatch observability.** Use `NOT_DISPATCHED` when policy prevents adapter entry, `DISPATCH_ATTEMPTED` as the intermediate event when `_request()` enters the transport boundary, `REQUEST_CONFIRMED` only after response headers or an explicit transport handoff event, and terminal `DISPATCH_UNKNOWN` when an attempt ends without either signal. Default HTTPX cannot prove that a `ConnectTimeout` never left the process, and a mock handler invocation is not a real network send. The receipt must preserve that uncertainty instead of choosing between "never sent" and "sent with no response" without evidence.

2. **Attempt history.** Store bounded per-attempt records in the redacted trace and put only `attempt_count`, `retry_class`, final axes and `next_action` in the MCP envelope. `request_id` is the lookup key. This gives clients a useful final receipt without inflating every response, while operators can still explain a multi-attempt trajectory from the trace. The client-visible tradeoff is intentional: per-attempt transport detail requires a trace read.

3. **Metadata boundary.** `_request()` returns a typed `RequestOutcome`; each public adapter method carries it alongside the `DataBatch` in a private `AdapterCall`, while post-response adapter errors and exhausted retries carry the same records on `AdapterError`. `Gateway` normalizes that result and records the attempts before applying its own revalidation. The records carry attempt/max, elapsed time, dispatch and response observations, exception/status, `Retry-After`, retry decision and reason. `Retry-After` is parsed and budgeted when present. `Error.retryable` means another retry is currently allowed, so it is false after exhaustion even when the underlying class is normally retryable; a legacy adapter without attempt metadata is marked unavailable and receives `retry_class=UNKNOWN`.

4. **Fixture extension.** `evaluate.py` accepts optional JSON `transport_factory` and `observed_receipt` fields. A test-only registry creates stateful `MockTransport` handlers or failing response streams; the same adapter instance is retained for every attempt in a case. The first factories cover 500-then-success and timeout-then-changed-snapshot. Hidden snapshot differences remain simulation metadata and never become an oracle assertion.

5. **Validation state.** Keep `verification_state=FAILED_VALIDATION` as the broad state, but require `validation_lane` and `validation_reason` whenever it appears. `MALFORMED_RESPONSE` maps to `LANE_B_EXECUTION`; `PROVENANCE_UNAVAILABLE` for record-count mismatch and `ADAPTER_SCHEMA_OR_PROVENANCE_INVALID` for gateway revalidation map to `LANE_A_RESOLVABILITY`. This preserves the authorization/execution split while keeping the existing error codes and review paths visible in the receipt.

The staged first slice implements the receipt model, attempt metadata, trace summary and stateful fixture registry. Wire-level send confirmation remains an explicit limitation of the default transport; any future transport instrumentation may upgrade `DISPATCH_UNKNOWN` to `REQUEST_CONFIRMED`, but implementation must not infer that upgrade from `tool_executed` or an exception name alone.

## Attribution

Direction reviewed by Claude (code-level gap analysis against the paper), Nova (threat-model refinement — operational vs. data effects, oracle-leakage correction on OMR, the Lane A/Lane B invariant correcting an earlier overstated "authorization is frozen post-dispatch" claim), and Luna (implementation-feasibility review against the current code — corrected inaccurate claims, identified the attempt-history gap, and scoped the fixture/harness work accurately). The staged first implementation slice described here is now implemented; the five decisions remain the binding scope for this slice, and the broader adoption gate remains open.
