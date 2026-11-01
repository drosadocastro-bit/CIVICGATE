# EVAL-002B-R3 — Capture and numeric admission contract v1

PROPOSED_FOR_INDEPENDENT_REVIEW. Offline evaluation only. No human acceptance.

This additive candidate composes the unchanged R1 wire transport/shared budget
and accepted R4 role/MCP custody controls with three documentary corrections.
It changes no production policy, Gateway, ExecutionBinding, prompts or tools.

1. Capture closure requires bounded strict complete JSONL streams and a valid
   observer seal. The validator reconciles audit request/proposal/policy, issued
   and consumed bindings, typed query/schema/facts hashes, one dispatch, one
   HTTP attempt, paired component completions, indexes and timestamp order.
   Missing, empty-when-required, duplicate, malformed or mismatched primary
   evidence is UNKNOWN/incomplete and cannot close OPEN. Genuine sealed
   pre-dispatch DENY/REVIEW has zero backend records and remains supported.
2. Worker/supervisor structures are admitted before use. Rejected worker objects
   are discarded, never dereferenced later or interpreted as zero activity.
   Supervisor receipts and other independently validated channels remain known.
   Provider receipt Host/path/length correlate with the actual owned endpoint
   and wire facts; tuple server views are serialized, acknowledged and reread.
   Final snapshot/summary/STOP-write failures remain explicit incomplete custody.
3. Both outer provider JSON and inner typed content use a shared strict loader:
   duplicate-key rejection, constant rejection, finite parse_float, and iterative
   recursive-container finite checks. Exponent overflow is rejected before
   successful proposal admission. Ordinary finite numbers retain Python JSON
   semantics, including finite underflow. Decoder recursion overflow becomes a
   structured parse failure. These checks are not monetary-domain certification.

Raw observed response, acknowledged response facts, typed parsing, telemetry and
final role acceptance remain separate. No uncertain reservation is refunded or
automatically retried. Missing backend capture never proves absence of execution.
Capture admission is local consistency, not human authentication or independent
remote attestation. Legacy dispatch/HTTP rows have no request/observation IDs;
they are linked through available audit/binding/query/HTTP/timestamp evidence,
without inventing missing fields. Hostile local mutation/admin, power-loss, OS
isolation, hard real-time/preemption and distributed exactly-once are not proven.

The summary is written before the sole possible safe fence-close transaction.
Its saved fence-close field is a pre-closure fact; verify actual closure from
the coordinator and returned ACK. An ACK loss remains unknown, never an implicit
retry authorization. P2_02_DURABLE_STOP remains PARTIAL, including the inability
to create durable quarantine when no initial OPEN write can succeed.
