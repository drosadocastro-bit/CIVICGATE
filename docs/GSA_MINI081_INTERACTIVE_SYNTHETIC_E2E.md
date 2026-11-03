# MINI08.1 — Interactive synthetic end-to-end console

Development candidate for human review. No commit, push, merge, production deployment or API-backed execution is authorized.

## Architecture

CIVICGATE is an API-integrated MCP governance architecture. Synthetic E2E is a local test composition, not a claim that the architecture is inherently offline.

The new explicit POST traverses actual FastAPI, compiled LangGraph A2, MCP SDK stdio/JSON-RPC, Gateway, deterministic policy, ExecutionBinding when permitted, synthetic backend, primary evidence and SQLite custody.

The controller selects one original MINI07.2 input. It does not supply a policy verdict, issue a binding or replace the policy engine. The unchanged existing test checks the actual outcome and independently observed channels before a capture can be displayed as complete.

API-backed E2E is a separately authorized future composition. The Evidence Advisor is a separate future analytical capability. Neither is activated by MINI08.1.

## Start locally

Preserve the MINI08.0 worktree/server and historical evidence. The new worktree is independent. The measured session keeps the old read-only server on 8765 and uses another available loopback port for interactive testing.

Use the existing separate console environment from requirements-evidence-console.txt. The worker must use the existing compatible MCP environment; startup checks require MCP 1.30.0 and LangGraph 1.2.15. No dependency installation or accepted-environment upgrade is required.

Default startup remains read-only. Synthetic execution requires explicit --enable-synthetic-e2e, --worker-python and --execution-root configuration. No HTTP parameter can select a provider or execution target.

~~~powershell
$catalog = Read-Host "Absolute path to the preserved local evidence catalog"
$worker = Read-Host "Absolute path to the existing MCP 1.30.0 worker Python"
$output = Read-Host "Absolute path for a NEW private execution directory"
$port = Read-Host "Available local TCP port"
python -B scripts/serve_evidence_console.py --catalog $catalog --port $port --enable-synthetic-e2e --worker-python $worker --execution-root $output --deadline-seconds 90 --max-jobs 8
~~~

Open the local /demonstrations page. Select a scenario, press Run Demonstration once, wait for completion and inspect the fresh evidence link. GET polling and refresh never start a demonstration.

The output root must be new, local, disjoint from the repository and all historical input directories. Existing roots, reparse points and overlaps are rejected. Do not select a new root to bypass unresolved execution; investigate uncertainty first.

The launcher binds 127.0.0.1, disables proxy-header trust and exposes no host override. Graceful shutdown records active uncertainty best-effort, attempts cleanup of the task-owned subtree and never redispatches or refunds. OS preemption, abrupt host termination and power-loss cleanup are not certified.

## HTTP contract

MINI08.0 read-only evidence routes remain available. Interactive routes exist only with explicit trusted startup configuration.

| Method / path | Contract |
| --- | --- |
| GET /demonstrations | Scenario form; local CSRF nonce and SameSiteStrict HttpOnly cookie |
| GET /api/demo/capabilities | Synthetic mode, concurrency, deadline, remaining count and HOLD state |
| POST /api/demo/executions | Exactly one scenario and an idempotency key; returns job acknowledgement |
| GET /api/demo/executions | Sanitized request list; no scheduling or writes |
| GET /api/demo/executions/{id} | Sanitized status of an existing request |
| Existing GET /runs/{id} and observation routes | Manifest-bound historical and successfully admitted fresh evidence |
| Existing GET /api/runs routes | Read-only sanitized evidence access, suitable for separately reviewed analytical clients |

There is one exact POST path, no trailing-slash redirect, form fallback, reset, retry, recovery or alternative execution endpoint.

~~~json
{"scenario":"permit"}
~~~

Allowed values are permit, deny and review. Unknown fields, URLs, tools, arguments, model IDs, provider names, credentials, targets and query overrides are rejected. Bodies are limited to 256 bytes and a two-second read deadline, with duplicate-key and non-finite JSON rejection.

The POST requires a single nonempty same-origin Origin header, matching server-issued X-CivicGate-CSRF header and cookie, application/json, and a single canonical UUID4 Idempotency-Key. Invalid Host/Origin, cross-site requests and malformed or duplicated required headers fail before scheduling.

The idempotency key only deduplicates an execution request. It is not human identity or authority. A duplicate key with the same scenario returns the existing job without redispatch; another scenario using the same key is a conflict.

Responses allowlist id, scenario, status, created_at_utc, started_at_utc, completed_at_utc, error_code, run_id, observation_id and evidence_url. The API never returns local paths, command lines, raw logs, credentials, cookies or CSRF values.

Status is RESERVED, RUNNING, COMPLETE, HOLD or UNKNOWN. COMPLETE means the current process observed the required acknowledgement and accepted the evidence before its deadline. It is not human approval or a production authority receipt.

The final disk journal deliberately records EVIDENCE_CANDIDATE separately from process-observed COMPLETE. Existing execution roots are not automatically restored. A lost response or uncertain custody is not automatically retried.

## Execution and custody

1. Verify explicit configuration and worker package identities.
2. Acknowledge an exclusive durable request reservation before dispatch. Permit one active request and a finite configured count.
3. Preserve one absolute monotonic deadline from submission through custody and final acceptance. Check each pre-dispatch ACK and immediately before starting either subprocess.
4. Verify and copy the original 110 pinned MINI07.3 sources. Do not modify their manifests, Gateway, providers, schemas or authority contracts.
5. Execute exactly one original test node: test_mini072_demo_v1.py::test_local_synthetic_demo[scenario], using the existing guard, stripped environment and compatible worker interpreter.
6. Collect real graph, MCP, policy, binding, adapter, MockTransport, result, SQLite and restart observations.
7. Require one actual JUnit PASS, unchanged source identities, supported guard evidence, a new manifest and primary reconciliation by the console reader.
8. Publish sanitized identifiers and the evidence link. Missing, contradictory, expired or unacknowledged evidence remains HOLD/UNKNOWN, with reservations retained and new work blocked.

The original guard records a blocked local socket setup probe in this environment. That denial is preserved as enforcement evidence. Unexpected denied public DNS/connect attempts cannot be ignored as a clean admission.

Request, capture, budget run, observation and Gateway request identities are distinct and fresh. Historical MINI07 records are never presented as newly executed.

## Display rules

- Preserve the original request separately from the planner and effective proposal.
- Display only observed graph history and discovered tool identities.
- Keep initial deterministic authorization separate from final disposition and Judge advice.
- Separate binding issuance/consumption, adapter entry, MockTransport attempt, observed response and verified result.
- PERMIT expects one actual issued/consumed binding and synthetic backend invocation. DENY and REVIEW require supported zero-dispatch facts.
- The review scenario may record synthetic IN_SCOPE at 0.99 while deterministic policy retains REVIEW_REQUIRED.
- SQLite CLOSED is documentary custody, not human acceptance. Saved pre-close summary, returned ACK and actual database state remain separate.
- A newly generated manifest identifies captured bytes; it is not independent external endorsement or execution authority.
- GET reads and refreshes do not alter budgets, bindings, SQLite, hashes or custody.

## Future API integration points — unchanged

| Boundary | Existing interface | Separately authorized future work |
| --- | --- | --- |
| Planner to A2 | AgentModel.propose -> Proposal; existing GranitePlanner | Verified provider/model identity, transport admission, costs and telemetry |
| Judge to Gateway | JudgeModel.assess / JudgeProvider -> JudgeSignal; existing LiveJudgeProvider | Advisory provider configuration and verified responses, never binding authority |
| A2 to MCP | GovernedMCPTransport and existing reserved transport | Preserve intake, exact proposal and one governed invocation |
| Backend | Existing Gateway, ExecutionBoundary and read-only adapter | Authorized endpoint/scope and provenance; no argument rewrite after authorization |
| Evidence analysis | Sanitized GET evidence views | Separate analytical adapter, potentially Anthropic, without execution capability |

Synthetic adapters are selected only by the trusted local test composition. Production governance and provider-neutral interfaces remain unchanged. No synthetic fallback for a failed real provider, or real fallback for a failed synthetic provider, is implemented.

No Evidence Advisor is implemented. An advisor must never issue bindings, change policy, execute tools, refund reservations or modify historical evidence.

## Verification and limitations

The private review package records executed commands, JUnit, logs, fresh SQLite, trace identities, source hashes and manifests. It separates counting-double ingress tests, actual TCP HTTP tests, browser-initiated executions, historical results and technical review. Overlapping counts must not be added as independent samples.

Controls cover three fresh scenarios, repeated unique executions, duplicate-request suppression, provider restrictions, CSRF/Origin, bounds, deadlines, failed custody, GET non-mutation, missing/malformed evidence and prior MINI08.0 behavior. Actual results and all failed development runs are preserved in the private report.

This is a trusted-local-host prototype. Loopback and CSRF do not authenticate a human, isolate hostile local code, establish universal persistence, guarantee exactly-once execution or certify production readiness.

No effective real model identities, model quality, judge calibration, live USAspending compatibility or complete OS network isolation are established.

## Retained gates

~~~text
SYNTHETIC_E2E: AUTHORIZED_FOR_LOCAL_TESTING
EXTERNAL_PROVIDER_EXECUTION: NOT_AUTHORIZED
LIVE_PROVIDER_TRANSPORT: HOLD
USASPENDING_INTEGRATION: HOLD
EVAL002_EXECUTION_AUTHORIZATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
~~~

The 54 full FAA definitions remain BLOCKED/SKIP. No cloud, holdout, production writes, commits, pushes or merges. Stop after review.
