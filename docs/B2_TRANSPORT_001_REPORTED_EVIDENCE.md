# B2-TRANSPORT-001 B0 and B1 reported evidence

Record date: 2026-10-15. Related amendment:
[B2-TRANSPORT-001](B2_TRANSPORT_001.md), **PROPOSED — Pending Human Approval**.

This is an additive record of reported results and their limits. B0/B1 values
below come from the human-supplied checkpoint request; they were not rerun or
independently read from Databricks/MLflow during this documentary task. Source
inspection and Git identity checks are recorded separately. No historical
evaluation artifact, trace, assessment, tag or freeze is modified.

## Evidence classification

| Label | Meaning here |
| --- | --- |
| VERIFIED_SOURCE | Direct read of repository source at the stated Git revision; not a runtime test |
| VERIFIED_GIT | Direct Git/GitHub identity or permission observation for this checkpoint |
| REPORTED_VERIFIED | A verification reported by the human or attributed to Genie, not independently repeated here |
| DOCUMENTED_ONLY | Proposed or described platform behavior without a target-App demonstration |
| UNKNOWN | Evidence is absent or does not establish the claim |

The literal B1 outcome labels PASS, N/A, FAIL and UNKNOWN are assessment outcomes,
not substitutes for these provenance classifications.

## Git baseline and checkpoint preflight

| Item | Observation |
| --- | --- |
| Repository | `drosadocastro-bit/CIVICGATE` |
| Historical tested baseline supplied by the human | `82862cd5e258867163a3caf83066a01de24cdbb9` |
| Remote `refs/heads/main` before branch creation | `82862cd5e258867163a3caf83066a01de24cdbb9` — VERIFIED_GIT |
| Post-baseline changes at that check | None; current main and the reported historical SHA are identical |
| Checkpoint base | Clean separate clone of that exact remote main; not the pre-existing dirty checkout |
| Dedicated branch | `docs/b2-transport-001`, absent remotely before creation |
| Repository write access | GitHub reported push permission — VERIFIED_GIT |

The initial local checkout had seven uncommitted paths. Work stopped before
mutation; the human then explicitly authorized a separate clean checkout.
Those changes were not stashed, reset, copied into this branch or edited.
Equality with the reported baseline verifies Git identity; it does not rerun or
independently substantiate the historical portability/evaluation results.

## B0 Databricks Serverless portability

| Reported item | Value and limit |
| --- | --- |
| Outcome | Serverless portability verified — REPORTED_VERIFIED |
| Initial checks | 12 |
| Closure checks | 7 |
| Reported baseline SHA | `82862cd5e258867163a3caf83066a01de24cdbb9` |
| Scope | The reported Serverless environment and checks only |
| Raw per-check evidence in this checkpoint | Not supplied; check identities and individual receipts are not reconstructed |

The counts remain separate phases, not an invented 19-case independent benchmark.
B0 does not establish authenticated HTTP behavior, remote-session isolation,
durable recovery, Databricks Apps permissions, App runtime compatibility or App
egress. It is not production approval.

## B1 synthetic MLflow evaluation

| Reported item | Value |
| --- | --- |
| Traces | 7 |
| Assessments | 28 |
| PASS | 18 |
| N/A | 8 |
| FAIL | 1, intentional |
| UNKNOWN | 1, intentional |
| Experiment ID | `2769275036588554` |
| Run ID | `a13bff535fdd43de865509899e4eb5cd` |
| Readback | Confirmed by Genie, as reported by the human — REPORTED_VERIFIED |

Experiment:
[B1 MLflow experiment 2769275036588554](https://dbc-aae0ba16-8727.cloud.databricks.com/#mlflow/experiments/2769275036588554).

The reported arithmetic is consistent: 18 + 8 + 1 + 1 = 28 assessments. The
intentional FAIL and UNKNOWN remain literal outcomes; intent does not turn them
into PASS. N/A is not PASS. These are synthetic observations, not a measured
real-world success rate, independent proof of every invariant, an HTTP transport
test or deployment/recovery evidence. Individual assessment names, trace
identifiers and causal explanations are not invented from aggregate counts.

### Git provenance gap in persisted metadata

The Git SHA was reportedly verified in preflight, but **was not recorded in
MLflow tags**. Therefore the Git SHA in persisted MLflow metadata is **UNKNOWN**.
The reported preflight baseline is
`82862cd5e258867163a3caf83066a01de24cdbb9`; current Git equality does not repair the
historical metadata gap or prove a persisted run-to-code binding.

Genie's reported readback confirms the reported observation, not a missing SHA
tag. No retroactive tag write, run edit, trace replacement or metadata repair is
authorized. Any later additional evidence must be additive and distinguish
contemporaneous metadata from retrospective attribution.

## Platform claims and boundaries

The retrieved [Evaluación del caso 26 discussion](chatgpt-conversation://6ac4e412-6a3c-83ea-8b61-598f53e5c662)
provides these additional reported observations. It is context, not authority.
Assistant replies were returned as content-reference placeholders and cannot be
treated as readable evidence for additional facts.

| Claim | Scope and status |
| --- | --- |
| Outbound HTTPS to `api.usaspending.gov` returned 200 | Serverless only, REPORTED_VERIFIED; App egress UNKNOWN |
| `httpx` used in connectivity testing | Serverless only, REPORTED_VERIFIED; App availability UNKNOWN |
| `pydantic` 2.x available | Serverless only, REPORTED_VERIFIED; App compatibility UNKNOWN |
| MCP present on Serverless | Reported presence; target App runtime and installed version UNKNOWN |
| Four secret scopes visible | Reported visibility only; read/write grants UNKNOWN; no scope names or values recorded |
| `workspace-access` and `workspace-consume` visible | Reported entitlement observation; App creation permission UNKNOWN |
| TLS reverse proxy and auto-provisioned service principal | DOCUMENTED_ONLY design assumptions; effective App configuration and grants UNKNOWN |
| Databricks App creation/deployment permission | UNKNOWN |
| Databricks App egress | UNKNOWN |
| Durable dispatch journal and containment recovery | Proposed requirements; not demonstrated by B0/B1 |

No App was created, deployed or probed for this checkpoint. No platform claim
above is promoted from a Serverless observation to an App guarantee.

## Baseline source inspection

These facts were inspected at
`82862cd5e258867163a3caf83066a01de24cdbb9` and are VERIFIED_SOURCE:

| Source | Observed contract or limitation |
| --- | --- |
| [MCP server](../src/civicgate/mcp/server.py) | `BoundedMCPServer` rejects SSE/HTTP, prevents stdio re-entry and rejects a second SDK session; four tool wrappers enter Gateway |
| [Gateway](../src/civicgate/mcp/tools.py) | Separate `_denials` and ExecutionBoundary per instance; `_mcp_owner_lock` protects attachment; async `_lock` serializes calls |
| [Discovery](../src/civicgate/mcp/discovery.py) | Four-tool/schema registration snapshot and validation; metadata grants no authority |
| [ExecutionBoundary](../src/civicgate/governance/execution.py) | Private exact-object issuance and single-use consumption; default 30-second lifetime; maximum 256 outstanding envelopes; in-memory registry |
| [Trace](../src/civicgate/audit/trace.py) | Bounded in-memory event window and optional file append; no source evidence of a crash-durable recovery protocol |
| [Dependency declaration](../pyproject.toml) | `mcp==1.30.0`; declaration is not proof of the installed App environment |
| [Channel A security contract](CHANNEL_A_SECURITY_R1.md) | Trusted local ownership, no public reset service, separate adapter retry behavior, historical failures and limitations retained |

These reads do not implement or test Channel B. In particular, current
process-local locks and envelope identity do not prove authenticated cross-session
isolation or restart containment for a future HTTP process.

## Documentary validation and authority

Review of this checkpoint is limited to consistency with inspected source,
preservation of the reported numbers and unknowns, Markdown/link integrity and
an exact docs-only Git diff. There are no code/test edits, dependency installs,
local runtime evaluations, Databricks operations or MLflow writes in this task.
The commit uses `[skip ci]` to avoid automatically running the repository's
installing/evaluating workflows for this documentary publication; no workflow
file is modified and no runtime PASS is claimed.

The commit and PR request human review. They supply neither human approval of
the amendment nor authority to implement, deploy, merge or execute B2a/B2b/B2c.
No signature or approval receipt is fabricated. MLflow remains observability
only, and the original B0/B1 records retain their historical identities and limits.
