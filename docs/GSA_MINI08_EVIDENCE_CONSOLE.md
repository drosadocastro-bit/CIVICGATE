# MINI08.0 — Local read-only Evidence Console

Status: development candidate for human review. No commit, push or deployment is authorized by this package.

## Purpose

The console displays existing, genuine offline synthetic captures from the MINI07.3 checkpoint. It is a separate passive FastAPI application with local Jinja2 templates, CSS and a small presentation-only JavaScript tab controller. It neither imports nor exposes the Gateway, policy, MCP client, model providers, execution controls or an AI Evidence Advisor.

The starting commit is 7fde24a23bf27c96c30ddec474095adc9f7f4be4, tree 52669840ae16425b03481e0b00cc44dad9febf09. The active checkpoint PR and other worktrees are outside this implementation.

## Start locally

Use a separate console Python environment with the versions in requirements-evidence-console.txt. These dependencies must not be overlaid onto an accepted MCP environment. The measured console environment uses Windows/Python 3.13.7, FastAPI 0.129.0, Starlette 0.52.1, Jinja2 3.1.6, Uvicorn 0.34.0 and HTTPX 0.28.1. No dependency installation was performed for this task. MCP is not imported by this console; its installed version in another environment is not execution evidence.

Prepare a private JSON catalog outside the repository. It has exact fields version=1 and runs, with one to eight explicitly selected captures. Every run entry has id, root (an absolute local directory) and manifest_sha256. Do not add credentials or forwarded identity claims. Unknown fields, duplicate keys, invalid versions and excessive size are rejected.

Example structure below is non-operational until an operator supplies an existing local directory and its previously preserved manifest identity:

~~~json
{
  "version": 1,
  "runs": [
    {
      "id": "mini072",
      "root": "<ABSOLUTE_LOCAL_SYNTHETIC_CAPTURE_DIRECTORY>",
      "manifest_sha256": "d15b2aa14074f66b1fdabf08364ebcbdfeb9333096a323d155cb06d5b73ffde2"
    }
  ]
}
~~~

From the repository root:

~~~powershell
$catalog = Read-Host "Absolute path to the private evidence catalog"
python -B scripts/serve_evidence_console.py --catalog $catalog --port 8765
~~~

Open http://127.0.0.1:8765. Stop with Ctrl+C. The entrypoint has no host override and binds 127.0.0.1 only, disables proxy-header trust and limits simultaneous connections. Do not expose it through a proxy, public interface or shared untrusted host. Loopback/Host/Origin checks are not independent human authentication.

The task's private catalog references the genuine final MINI07.3 MINI072 and MINI071 captures. Their manifest pins were verified against the already committed MINI07.3 validation receipt, rather than taking a new candidate-computed digest as authorization:

| Capture | Manifest files | RUN_SHA256_MANIFEST.json SHA-256 |
| --- | ---: | --- |
| MINI07.2 | 206 | d15b2aa14074f66b1fdabf08364ebcbdfeb9333096a323d155cb06d5b73ffde2 |
| MINI07.1 | 188 | 5985d9918aa931050bcebbbfd996e1e0698fb766db3571edb127cf6338b16669 |

These identities identify evidence; they do not grant execution authority or authenticate a reviewer. Private catalog paths and raw captures are excluded from source publication.

## Read interfaces

Only HTTP GET is accepted, including for static resources. Other methods receive 405 before evidence access. Host must be a single localhost/127.0.0.1 value, the direct peer must be loopback, and cross-origin/cross-site requests are rejected. Forwarded identity headers grant nothing.

| Route | Purpose |
| --- | --- |
| / | Available configured captures and supported policy distributions |
| /runs/{id} | Observation ledger |
| /runs/{id}/observations/{observation_id} | Timeline, decision, binding, result, custody and source inspectors |
| /api/runs | Sanitized configured-run summaries |
| /api/runs/{id} | Sanitized observation index |
| /api/runs/{id}/observations/{observation_id} | Sanitized allowlisted evidence view |
| /health | Non-authorizing read-only service status |
| /assets/... | Installed local CSS, tab JavaScript and icon |

There is no arbitrary path parameter, file download endpoint, directory browser, upload, execution, retry, rollback, acceptance, provider or custody-clearing route. Swagger/OpenAPI endpoints are disabled. No third-party frontend resources, CDN, analytics, remote fonts or network data loading are used.

## Evidence mapping

Read EVIDENCE_CONSOLE_READ_CONTRACT.md from the private MINI07.2 package before altering these mappings. Its verified SHA-256 is e89c720d3dd5d2ae16a2049d00fa0028b9105b66e78e2ae1e2583397c1ca87f9. It remains unchanged.

| Display | Primary source and comparison |
| --- | --- |
| Capture, budget and observation identifiers | Operator catalog, enclosing capture, synthetic-http-worker-config.json, returned summary and SQLite meta/fence |
| Original request / proposal | Audit proposal; actual a2-orchestration-result.json and a2-mcp-client-input.json where available; SHA-256 and explicit scope comparisons |
| Five graph transitions | a2-events.jsonl node entries versus actual returned visited_nodes; original request and gateway-node proposal checked |
| Initial policy / final disposition | audit.jsonl policy row separately from completed response and returned observed envelope |
| Judge advisory signal / invocation | Audit Judge object versus coordinator attempts and matching synthetic server receipt; hard DENY has no Judge call |
| Binding issued / consumed | governance-observations.jsonl integrity, request/tool identity, matching binding and ordered issue/consume records |
| Adapter / MockTransport | dispatch.jsonl, http-attempts.jsonl, components.jsonl, completed attempts, counters and observed response |
| Result / provenance | Completed observed envelope, allowlisted structured result and provenance; RESULT_VERIFIED distinct from metadata correlation |
| Actual durable state | coordinator.sqlite opened mode=ro, immutable=1; query_only and trusted_schema controls; exact database/snapshot/summary binding |
| Saved summary / returned ACK | Exact synthetic-observation-summary.json versus SQLite summary hash; returned-summary.json kept separate |
| Restart record | preservation-and-restart.json and restart-result.json; no new recovery or admission is performed |
| Source references | Configured run manifest, unique relative paths, exact sizes and SHA-256; no raw-file access |

The old console-evidence-projection.json and verified demo card are not treated as self-authenticating truth. The reader derives bounded views from manifest-pinned primary channels and reconciles supported relationships. This is a documentary reader with explicitly tested comparisons, not a replacement for the complete R3.2 validator, deterministic policy engine or historical human acceptance.

MINI07.1 has no saved detailed node history. Its graph is UNKNOWN and its aggregate view is PARTIAL, while supported policy, binding, dispatch and custody facts remain visible. A missing channel never becomes a zero counter, a manufactured timeline or assumed CLOSED state.

## Interpretation and security

- VERIFIED describes the stated local comparisons; it is not human authentication, semantic correctness, production certification or authority.
- Policy authorization, binding consumption, adapter entry, HTTP attempt, observed response and accepted result remain separate.
- The exact initial PERMIT and authorized read remain facts if final disposition later requires review. The interface says “before execution” only when supported absence and zero binding/dispatch facts agree.
- A Judge object is not proof of invocation. Recorded confidence is uncalibrated; synthetic protocol names do not establish effective real Granite/Luna identity.
- CLOSED is documentary custody, not human acceptance. Saved pre-close field, returned close ACK and actual SQLite state are displayed separately.
- Every request rechecks the configured manifest and file hashes. Limits include 1 MiB manifest, 1,000 files, 8 MiB per file, 64 MiB total, bounded rows and JSON nesting. No live filesystem-wide search is performed.
- Unsafe paths, traversal, duplicate entries/keys, non-finite JSON, symlinks and Windows reparse points are rejected. SQLite sidecars/inconsistent or malformed captures fail closed for unsupported claims.
- Captured text is untrusted. Only selected fields are emitted; credentials, URLs and private paths are redacted; templates autoescape. No raw headers, logs, configuration files or arbitrary JSON keys are served.
- Hostile local administrators, malicious replacement races, OS isolation, power-loss guarantees and distributed exactly-once execution are not certified. Evidence must be under trusted local custody and quiescent while inspected.
- Reads and refreshes do not run an evaluation, open a new observation, reserve budget, consume a binding, invoke MCP or modify custody. Byte hashes and SQLite contents are compared before and after the documented checks.

## Isolated tests

Use the separate console environment, with source on PYTHONPATH and automatic third-party pytest plugins disabled. Run the evidence-console selection with --confcutdir=tests/evidence_console so the production MCP fixture conftest is not loaded. Redirect JUnit, temporary files and logs to a fresh private evidence directory outside the checkout. Set CIVICGATE_CONSOLE_TEST_CATALOG only for the explicit genuine-capture preservation check; without it, that one local check is reported SKIP.

~~~powershell
$env:PYTHONPATH = "src"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -B -m pytest --confcutdir=tests/evidence_console -p no:cacheprovider tests/evidence_console
~~~

The source tests use documentary fixtures, including malformed, missing and contradictory records. They do not create actual governance evidence or demonstrate new Gateway executions. Genuine-capture checks and browser screenshots are recorded separately in the task's private evidence package. Historical 54 FAA definitions remain BLOCKED/SKIP and are not counted as new passes.

## Proposed next UI improvements (not implemented)

1. Human-reviewed field-to-source drill-down with scoped comparison explanations, without raw file downloads.
2. Accessible filtering across larger configured catalogs and explicit comparison of captures.
3. Versioned read-model export and authenticated shared-host design only after a separate threat and authorization review.

No AI Evidence Advisor, provider controls, WRITE capability, public deployment or new execution phase is implemented.

## Retained gates

~~~yaml
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
USASPENDING_INTEGRATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
FAA_FULL_CONTRACT: BLOCKED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
~~~
