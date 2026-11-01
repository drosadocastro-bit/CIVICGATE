# EVAL-002B-R1 — Offline transport admission contract v1

Status: PROPOSED_FOR_HUMAN_TECHNICAL_REVIEW. No activation authority.

This additive evaluation candidate preserves the accepted R4 budget, bounded
provider and composition byte-for-byte. It reuses their parsers, prompts,
deadlines, receipt and OPEN/STOP semantics. Production governance is unchanged.

The order is: durable OPEN → exact role context → atomic attempt and synthetic
liability reservation → IN_FLIGHT ACK → nonconsuming admission check → owned
loopback connection → one-use durable send-lease ACK → final monotonic send
check → one fixed HTTP/1.1 header block and exact bounded body → incremental
read → strict response facts ACK → inherited typed parse/telemetry/custody and
final deadline guard. Only the deterministic Gateway may authorize tool execution.

The judge context additionally requires the shared MCP state to be ADMITTED and
its normalized effective invocation digest to match the requested operation.
Current-run worker capability joining is explicit; restart does not restore an
unresolved OPEN capability or authorize redispatch.

HTTPX 0.28.1, HTTPCore 1.0.9 and h11 0.16.0 installed Python-source trees are
pinned. The direct HTTPCore HTTP/1.1 connection has an owned socket stream and
no pool, retry, proxy, redirect, TLS or alternate client. Logical Granite/OpenAI
origins are protocol labels only: the sole actual destination is an active
in-process owned server at an ephemeral 127.0.0.1 port. Synthetic routing is
declared at construction, never a fallback from a live attempt. Provider headers
and synthetic Authorization material are not forwarded to the fixture.

The stream verifies the exact first-header bytes and bounded body sequence.
Its lease ACK is necessary before emission. A lost ACK remains UNKNOWN even if
SQLite committed consumption; it cannot be reused. Socket writes/TCP segments
are not separate HTTP requests. Reservations, header-emission attempts, server
header/body receipts, responses and typed acceptances are separate facts.

Responses retain at most 200000 body bytes incrementally; header parsing is
bounded to 16384 bytes plus a possible parser-read chunk of 8192. Kernel/socket
buffers are outside that retention claim. Nonidentity content encoding is
unsupported. HTTP status/raw body identity are distinct from contract success.
Admission requires exact returned model label, exactly one terminal stop choice,
no refusal/action, strict JSON without duplicates/nonfinite values, original
Proposal or JudgeSignal schema, and consistent nonnegative integer usage.
Missing usage remains UNKNOWN and blocks final role acceptance. Reported usage
is neither authenticated billing nor an independently verified monetary limit.

The cost seam defaults BLOCKED. Offline transactions use explicitly nonmonetary
synthetic upper-bound units, with no refunds for uncertain/no-send reservations.
No prices or billable token ceilings are invented. Even caller-populated monetary
fields cannot activate a real destination in this candidate.

The composition exercises original local MCP stdio, LangGraph, Gateway and
ExecutionBinding; backend HTTP remains exact MockTransport. It reconciles
worker/supervisor captures with request hashes, consumed leases and acknowledged
response facts. Missing captures remain UNKNOWN, preserving other known audit
channels. Safe closure rejects incomplete custody, any STOP attempt, unknown or
failed result validation and incomplete primary evidence.

Limits: cooperative Python/SQLite/Windows process boundary; no hostile-local-code
or administrator protection, OS isolation, hard real-time/preemption, power-loss,
distributed exactly-once or live-provider compatibility certification. A failure
before initial OPEN ACK blocks dispatch but cannot establish durable quarantine
when every initial write fails. The accepted P2 durable STOP classification
remains PARTIAL. Observation IDs and fixture capabilities are not human authority.
