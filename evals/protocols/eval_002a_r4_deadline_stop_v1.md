# EVAL-002A-R4 — Deadline and durable observation custody

Status: ADDITIVE OFFLINE CANDIDATE; NOT HUMAN ACCEPTANCE OR EXECUTION AUTHORITY.

## Preserved evidence

Provider/composition v1 and v2, budget v1, their tests and reports are historical
inputs, never migration targets. The six R3 failures remain failures. Historical
138 PASS, historical 151 PASS, independent 150 PASS / 1 FAIL, and the isolated
diagnostic 1 PASS are separate overlapping runs. R4 neither sums nor rewrites
them. The original 10 ms assertion remains unchanged in its historical file.

R4 introduces only versioned evaluation modules, tests, this specification,
report and identity inventory. Production policy, prompts, parsing, MCP tool
contracts, Gateway, ExecutionBinding and backend validation remain unchanged.

## Deadline states

1. Begin and acknowledge observation custody before any provider attempt.
2. Capture absolute monotonic role and attempt deadlines. Exact equality is
   expiry. Asyncio cancellation is a cooperative backstop, not the absolute
   acceptance oracle.
3. Reserve/start durably, then check time before delegate entry. A no-send
   reservation remains counted; no refund or fallback transport is available.
4. After delegate return, preserve response-arrival facts and check expiry.
   Check again after body reading, envelope processing and telemetry.
5. Record acknowledged response custody as acceptance pending. Check after its
   ACK: a timely response followed by late local custody is not typed success.
6. Complete unchanged production typed parsing and client-lease teardown.
   Validate both deadlines again, perform required custody reads, then apply
   the final clock guard before publishing the typed role result.

Timeout, late response, late reading, late local typed processing, late custody
ACK and final-boundary expiry have distinct stage evidence. An observed response
can remain RESPONSE_OBSERVED while its final typed result is rejected. A later
local failure never retroactively establishes non-dispatch or refunds a slot.

The durable response record deliberately says acceptance pending. A finite
write/ACK protocol cannot durably certify the timeliness of its own last ACK.
WITHIN_EVALUATION_DEADLINE is therefore a final local acceptance observation,
not a prematurely committed ledger assertion. No blocking I/O, external callback
or awaited cleanup follows that final sampled boundary in the bound role.
Descheduling after the sample is outside this program-level guarantee: no OS
preemption or hard real-time property is established.

## Durable observation state machine

| Prior state | Operation | Required acknowledged facts | Next state |
| --- | --- | --- | --- |
| No current fence | begin_observation | SQLite transaction commits OPEN and current observation capability | OPEN |
| OPEN | provider/MCP reservation, dispatch and terminal receipt | Exact current observation capability and existing admission checks | OPEN |
| OPEN | required STOP/custody failure | STOP acknowledgement may succeed or remain UNKNOWN | OPEN, and optionally stopped=true |
| OPEN | safe current completion | Known terminal receipts, no error/required STOP, verified final evidence, fsynced summary, atomic close transaction | CLOSED with summary hash |
| OPEN or stopped=true | fresh-controller admission/recovery | Unresolved fence or persisted STOP | REJECTED; no new observation |
| CLOSED with safe completion | next distinct observation | Existing budget/recovery checks pass | New OPEN fence |

The private capability joins the current parent/stdio child for resource custody.
It does not authenticate a human, authorize a tool or replace deterministic
policy. A newly attached controller cannot silently adopt an existing OPEN
observation. Terminal provider/MCP rows do not remove its fence.

An unsafe observation is never eligible for automatic closure. There is no API
to reset STOP or clear an unresolved fence on restart. Such recovery would need
a separately specified and verified procedure; this candidate provides none.

## Completion and uncertain acknowledgements

Final evidence is written and fsynced before the sole safe-close transaction.
The transaction records CLOSED plus its summary SHA-256 only after safe current
completion. No fallible evidence write follows that transaction.

Safe completion requires present regular capture files, complete JSONL object
records, one final PASS observer seal with matching version/correlation/counts,
and a typed child-provider report. The planner and any attempted judge must have
final role-acceptance evidence. Empty present capture streams are valid for a
no-dispatch path; missing streams are not evidence of zero events. Missing files,
incomplete JSONL, malformed child reports, or the tested observer-seal
contradictions keep custody incomplete and the fence OPEN. Separately available
raw dispatch/response facts are retained. This validates capture shape and the
observer seal, not arbitrary deletion or rewriting of syntactically valid rows.

An unacknowledged close is reported UNKNOWN. If it failed before commit, OPEN
remains and recovery blocks. If the already-safe close committed but its ACK was
lost, CLOSED refers to the prior established safe completion and exact summary;
it is not automatic clearance of an unresolved STOP. This distinction must be
tested and reported without claiming an ACK or a general exactly-once guarantee.

STOP attempted, STOP acknowledged, response custody acknowledged and final
observation closure acknowledged are separate fields. Failed STOP must never
become NOT_REQUESTED. Missing projection/read evidence remains unavailable,
not zero counters or a recorded success. An invalid backend response preserves
the earlier PERMIT/binding/read while requiring FAILED_VALIDATION and STOP.

## Total-write-failure boundary

After OPEN is acknowledged, failure of every subsequent relevant write leaves
that previously durable fence. Restored storage availability cannot by itself
authorize a new observation. No uncertain operation is automatically replayed.

Before any OPEN commit is acknowledged, storage failure blocks provider and MCP
activity. If no relevant write ever succeeds, persistent quarantine across an
entire process loss cannot be manufactured. That path is BLOCKED with no dispatch;
durable STOP/quarantine is not established. If the commit succeeded but its ACK
was lost, the unadopted OPEN fence blocks the next controller. These are distinct
cases, not a conversion of UNKNOWN to a clean store.

SQLite acknowledgement is tested on local storage, not certified against media
loss, operator tampering, power failure or distributed concurrency. Trusted host
code and fixed budget identity remain assumptions. Python-level network guards,
synthetic fixtures and MockTransport are not OS/native isolation.

## Required gates

Independent negative tests must cover both roles at every success boundary,
late ACK/typed parsing, final-boundary expiry, equality, known response followed
by rejection, and no refund/retry. Separate-process probes must cover terminal
receipt plus failed STOP, final read/projection failure, total writes lost before
and after fence ACK, and safe-close commit/ACK ambiguity.

Only synthetic tools/providers and pinned source copies are used for independent
execution. Model quality, calibration, monetary limits, live transport and real
backend compatibility remain outside this candidate. A separate technical
review of final identities precedes any recommendation for human acceptance.

EVAL002A_HUMAN_ACCEPTANCE: PENDING

LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED

EVAL002_EXECUTION_AUTHORIZATION: HOLD

MONETARY_CAP: UNKNOWN

INDEPENDENT_GOLDEN_REFERENCE_ACCEPTANCE: PENDING

JUDGE_CALIBRATION: NOT_YET_MEASURED
