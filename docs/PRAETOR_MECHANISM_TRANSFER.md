# PRAETOR mechanism transfer

Read-only reference: `D:\Preator_MCP`, HEAD `34b0c4272cc7d02bdbcbc60d5406346cd65f9a04`, inspected September 17, 2026. Existing dirty files were present before this task. No PRAETOR file was modified, no commands ran its experiments, and no historical artifact was copied into CivicGate.

The evidence motivating transfer is observed implementation structure and explicit failure contracts, not transferred empirical validation. CivicGate is a new implementation in Python. Each mechanism needs its own tests here.

| PRAETOR mechanism / observed file | Why it existed / evidence for reuse | CivicGate implementation and differences | New evidence required |
| --- | --- | --- | --- |
| Strict schemas: `src/schema.ts`, `src/adapters/adapterValidation.ts` | Bounded records and provenance fields constrain input and adapter shape | Pydantic input models and projected USAspending responses; no maintenance/NEXRAD types | Malformed fields, excessive limits, unknown fields, finite amounts |
| Tool gate: `src/runtime/toolGateway.ts` | Gateway checks session access before executing an action | One deterministic policy issuer and four public read tools; no submit/persist actions | Zero adapter calls on denial; direct MCP parity |
| Agent K: `src/safety/agentKPreAction.ts` | Detects overreach, mismatch and retry pressure | Reimplemented advisory signals; only policy grants/denies; process-local denial counter | Repeated denial, conflict, authority pressure |
| Hybrid judge: `src/research/liveModelEvaluationV61.ts` | Separates semantic observation from governance and preserves hard failures | Independent provider interfaces; unavailable judge becomes review; no historical scoring or model result imported | Contradictory signals, failed judge, schema failure; future real-model evaluation |
| Provenance gate: `src/adapters/adapterValidation.ts` | Source metadata required at data boundaries | Public source origin, retrieval timestamp and query/response fingerprints; explicit synthetic provenance | Missing/invalid provenance, count mismatch, duplicate/conflicting source rows |
| Audit: `src/runtime/traceRecorder.ts` | Ordered inspectable runtime events and explicit storage errors | Local redacted JSONL and bounded memory window; no archive/freeze claims | Event ordering, shared IDs, write failure, redaction |
| Explicit adapter failure / bounded execution | Validation rejects malformed upstream data | Fixed-origin HTTP adapter, bounded attempts and bytes; no silent synthetic substitution | Timeout, HTTP errors, invalid JSON, oversize responses |
| Credential separation / container hardening | Separation prevents model/platform credentials becoming application authority | No inbound HTTP auth needed for local stdio; model secret never sent to USAspending; non-root image | Header inspection and container smoke; remote auth out of scope |

Credential separation and container hardening were reconsidered as design concepts; the inspected reference checkout did not provide the HTTP hardening variant previously discussed. No claim is made that its current HEAD contains that variant.

**Intentionally not ported:** G2 freeze machinery, G3/G3B adaptive runtime and artifacts, amendment chains, NEXRAD fixtures, research archives, historical claims, experiment results, old evaluation conclusions, adaptive authority and governmental write paths. No PRAETOR test count, freeze status or performance result appears as validation of CivicGate.
