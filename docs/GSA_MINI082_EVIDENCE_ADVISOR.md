# MINI08.2 — Selected-evidence Advisor

Local research candidate for human review. External analysis, billing, production use and publication remain unauthorized. MINI08.1 and all historical sources are preserved separately.

## Implemented boundary

The optional service reads one explicitly selected observation through the existing `EvidenceStore`. That reader rehashes the operator-pinned manifest and listed files, reconciles the available policy, binding, backend and custody channels, and opens SQLite read-only/immutable. Missing or contradictory projected facts remain PARTIAL or UNKNOWN. Manifest-corrupt, byte-mismatched or unavailable selections fail without provider analysis; validly pinned partial records may still be analyzed with their uncertainty preserved.

The path is:

`Manual Analyze Evidence → strict local POST → EvidenceStore → allowlisted projection → mock Anthropic Messages adapter → report validation → citation reconciliation → local analysis record → UI`

It is separate from:

`Run Demonstration → LangGraph A2 → MCP stdio → deterministic Gateway → synthetic backend`

The Advisor imports no Gateway, policy, binding issuer or MCP execution client. Granite remains the planner interface; Luna remains advisory Judge. The Advisor cannot invoke tools, alter policy, consume bindings, change the evidence, close an execution fence, approve a result or authorize any action.

## Start

Use the existing console Python environment documented in `requirements-evidence-console.txt`; no new package or SDK is required. The trusted startup argument permits only `off` (default) or `mock`. The mock identity is explicitly `synthetic-claude-advisor-v1`, not a guessed Anthropic model ID.

```powershell
$catalog = Read-Host "Absolute path to an operator-verified synthetic evidence catalog"
$analyses = Read-Host "Absolute path to a NEW private advisor output directory"
$port = Read-Host "Available loopback TCP port"
python -B scripts/serve_evidence_console.py --catalog $catalog --port $port --advisor-mode mock --advisor-output-root $analyses --advisor-max-jobs 8
```

To compose with the existing explicit synthetic demonstration mode, add MINI08.1's `--enable-synthetic-e2e`, `--worker-python`, `--execution-root`, `--deadline-seconds` and `--max-jobs` options. The advisor and demonstration output directories must be disjoint from each other, the repository and every historical input root. Only the demonstration worker needs MCP 1.30.0 / LangGraph 1.2.15. No external provider mode is available from the CLI or HTTP requests.

Open an observation and press **Analyze Evidence** once. Loading a page, viewing a report, polling, refreshing or expanding a citation never starts another analysis. Provider errors display FAILED without fabricated findings or automatic retry. Restart does not automatically recover jobs or refund uncertain reservations. Existing output directories are rejected.

## Data selection and references

Outbound JSON has exact top-level keys `version`, `observation_id`, `integrity`, `facts`, `sources`, `limitations`. The observation uses alias `obs-1`; source aliases are `S001` etc.; fixed fact aliases are `F001` etc. Sources contain byte size and SHA-256. Actual observation IDs, private paths and artifact filenames stay local.

The 25 fixed fact slots include evidence integrity; policy state/initial/final disposition; Judge state/call/synthetic/classification; binding state/counts/verification; backend state/counts/dispatch/response/absence; result state/verification; custody state/OPEN-or-CLOSED/ACK/restart/summary digest. Only supported enums, bounded integers, booleans, validated hashes or null may occupy these slots. Null means UNKNOWN.

Original user requests, planner arguments, model rationale, logs, raw HTTP messages, result rows, credentials, arbitrary instructions and personal information are not selected. No evidence directory is uploaded. The only configured transport is `httpx.MockTransport`; no evidence is sent externally in this candidate.

Local source aliases bind exact relative path, byte size and digest from the selected manifest inventory. The service rechecks the original selection after analysis and before publishing COMPLETE. Any change blocks the session. The new sanitized request digest records identity; it is not independent trusted provenance.

Prompt text says evidence is untrusted data and grants no tool permissions. This is defense in depth, not proof that a future model is immune to prompt injection. Selection excludes freeform evidence before it reaches the adapter. Provider output is untrusted, bounded, schema-checked, rejected for supported sensitive/path/markup patterns and rendered using text-only DOM operations. Pattern checks are not a universal secret detector.

## Structured report contract

The static shape is `advisor_report_v1.schema.json`; the executable schema and additional dynamic reference checks are `validate_report()` in `evidence_advisor_v1.py`. No MCP or authority schema is changed.

Top-level exact fields:

| Field | Contract |
| --- | --- |
| `version` | Integer 1 |
| `summary` | Nonempty sanitized text, at most 1,500 characters |
| `findings` | 1–12 typed findings |
| `limitations` | 1–10 sanitized strings, each at most 500 characters |

Each finding requires exact fields `id`, `category`, `severity`, `kind`, `observation_id`, `fact_ids`, `source_ids`, `explanation`, `uncertainty`, `investigation`.

- IDs are unique `A001`-style references.
- Category is `DECISION_CONSISTENCY`, `BINDING_INTEGRITY`, `EXECUTION_EVIDENCE`, `CUSTODY`, `EVIDENCE_GAP` or `SCOPE_LIMITATION`.
- Severity is `INFO`, `LOW`, `MEDIUM` or `HIGH`.
- Provider-claimed kind is `OBSERVED_FACT`, `MODEL_INFERENCE` or `UNKNOWN`.
- Observation must be the selected `obs-1` alias. Every finding must cite actual fact and source IDs; the cited source set must exactly match the sources associated with those facts. An observed-fact claim cannot cite null fact values.
- Explanation and uncertainty are required sanitized text; investigation is sanitized text or null. The 1,500-character limit applies to each.

Valid citations establish resolvable identity and associations. They do not prove that the narrative follows from the evidence. Public `semantic_verification` remains `NOT_ESTABLISHED`; `reference_validation` is `RESOLVED_NOT_SEMANTIC_VERIFICATION`. The interface presents provider-claimed kinds without promoting them to deterministic findings or human decisions. CLOSED is documentary custody, never human acceptance.

## HTTP and local custody

`create_app(..., advisor=None)` keeps the Advisor disabled by default. When explicitly configured:

| Method | Route | Behavior |
| --- | --- | --- |
| GET | Existing observation page | Show optional action; issue same-origin local CSRF token, no analysis |
| GET | `/api/advisor/capabilities` | Sanitized mode/capacity/status, no reservation |
| POST | `/api/advisor/analyses` | Exact selected `run_id` and `observation_id`; no prompt/model/URL/tool override |
| GET | `/api/advisor/analyses/{id}` | Existing sanitized status/report only |

POST requires a direct loopback client, approved local Host, one nonempty same-origin Origin, one CSRF header matching the HttpOnly SameSiteStrict cookie, one canonical UUID4 idempotency key and one JSON Content-Type. The legacy cookie name remains `civicgate_demo_csrf`; the nonce is shared by the two distinct local actions. Bodies are limited to 512 bytes and two seconds, reject duplicate JSON keys and non-finite values, and permit only the exact selection fields. Query overrides and alternate mutation paths are rejected.

The service permits one active analysis and a bounded session count. Duplicate keys for the same selection return the original job; conflicting keys reject. An exclusive flushed reservation is acknowledged before the mock call. Failed/uncertain writes, provider failures, deadline expiry and changed evidence block further analysis. Reservations are not automatically refunded. Records contain sanitized metadata, source mapping and validated report, without raw evidence duplication or credentials. Final disk records say ANALYSIS_CANDIDATE; process-observed COMPLETE is not a production receipt.

Output roots are fresh, local and disjoint; symlink/reparse ancestors are rejected. This is a trusted local-host composition, not protection from hostile code under the same user, arbitrary local filesystem races, power loss or a cross-process exactly-once system. Provider cost counters are process-local, not a durable billing ledger.

## Messages adapter and future external gate

The candidate prepares the Messages wire shape using HTTPX and no additional dependency. It targets `POST https://api.anthropic.com/v1/messages`, with explicit API version `2023-06-01`, model, system text, messages and maximum output tokens. It supplies no tools, streaming, cache configuration or fallback. The historical version choice must be rechecked before any future external admission.

Official contract references: [Messages](https://platform.claude.com/docs/en/api/messages/create), [API versions](https://platform.claude.com/docs/en/api/versioning), [errors](https://platform.claude.com/docs/en/api/errors). These are documentary references; no operational Messages request was made. No advertised Sonnet model identifier or pricing is assumed.

Defaults in mock mode: output maximum 2,048 tokens, input payload 32,768 bytes, response 65,536 bytes, absolute adapter deadline 10 seconds, at most eight requests. Per-request/session synthetic dollar reservations default to zero; optional Decimal mock costs exercise exhaustion and concurrency. They are synthetic arithmetic, not Anthropic prices or a real monetary cap.

One reserved mock client attempt runs without redirects, proxy environment, HTTP/2, retry or fallback. The adapter incrementally caps the body and rejects late responses, non-200 status, model mismatch, incomplete/refused/tool-use responses, malformed JSON and output-token violations. Missing usage remains null. HTTP 200 and parseable JSON alone are insufficient.

`SecretProvider` is the existing credential boundary accepted by the adapter interface. Real/unspecified transports are rejected **before secret lookup**. No Anthropic secret was read or created; no DPAPI record, environment file or provider credential configuration was changed. Keys do not appear in the HTML, JavaScript, records or source.

To enable external analysis later, Danny must separately authorize and review:

1. Exact Sonnet API/model identity and compatible API version, with a separately reviewed live transport admission path. This candidate deliberately contains no usable live switch.
2. Exact sanitized payload/digest and permitted data fields, including external disclosure and retention terms.
3. A credential source explicitly supplied at the trusted process edge using `SecretProvider` or a reviewed environment source; no key in a file committed to Git or browser request.
4. Verified pricing, billable token ceilings, a real per-request/session monetary cap and treatment of unknown usage/delivery; mock costs cannot satisfy this gate.
5. No-retry/redirect/proxy/fallback, connection/cancellation accounting, actual provider identity/usage and redaction checks on the live stack.
6. Explicit paid-request authorization and separately preserved live test evidence. Planner/Judge execution remains independently unauthorized.

## Verification and retained limits

The private MINI08.2 review report records each actual test selection, source hashes, commands, raw stdout/stderr/JUnit, browser evidence, real local HTTP mock analyses and preservation checks. Counts from overlapping selections must not be added as semantic samples. Earlier failed preparation runs remain versioned. Full repository/scientific regression and real-model quality or calibration are not claimed by this UI task.

The 54 full FAA definitions remain BLOCKED/SKIP. No holdout was semantically inspected, executed or adjudicated. No real provider, USAspending, Databricks or cloud request was made. No source, policy or ExecutionBinding contract was changed outside the isolated console candidate.

```text
EVIDENCE_ADVISOR_PROVIDER: MOCK_ONLY
REAL_ANTHROPIC_EXECUTION: NOT_AUTHORIZED
MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED
EXTERNAL_PROVIDER_EXECUTION: NOT_AUTHORIZED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
USASPENDING_INTEGRATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

Stop for human review. No commit, push, merge, deployment or automatic next phase.
