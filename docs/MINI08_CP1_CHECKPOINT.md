# MINI08-CP1 — Consolidation candidate and validation HOLD

Research prototype. No real inference, publication, merge or deployment is authorized by this document.

## Baseline and source reconciliation

The integration branch derives from verified `main` commit `601e65ed77630bbad43eec2bcdce17c25ca65349`. Both prior MINI08 worktrees remain untouched. All 24 MINI08.1 and 33 MINI08.2 inventory identities were independently rechecked before copying. MINI08.2 contains nineteen unchanged MINI08.1 copies, five intentionally modified console copies and nine additions; it was not assumed to be a complete overlay without comparison.

The new main includes previously merged FAA-C1 code. Five shared files differ from the frozen MINI07.3 110-source inventory: governance execution, policy and request risk, MCP discovery and tools. These changes originated in main, not this console branch. No protected source is downgraded or changed here.

The proposed additive `evals/manifests/mini08_cp1_console_sources_v1.json` records the 110 current-main files plus the existing `channel_b/invocation_contract_v1.py` import dependency. Every recorded source was compared with its exact baseline Git blob. This does not activate an FAA profile or change the default local contract. The original manifest and original `run_local_governance_demo.py` remain byte-identical. The console worker alone reads the new inventory and rejects mismatches; it never automatically repins sources.

## Material blocker

Current Gateway `_call()` invokes policy through `_evaluate()`. The historical observer recognizes direct Gateway/boundary callers only, so the extra frame is recorded as `policy_other`; it also cannot recover the Gateway request identifier through that extra frame. The existing backend admission validator rejects this with `BACKEND_CAPTURE_OBSERVER_PHASE_INVALID`.

A valid synthetic policy PERMIT, consumed binding and backend response do not override failed primary-evidence admission. The mismatch is not established evidence of an authority bypass. It is a material observation/correlation compatibility gap. It prevents claiming a reproducible current-main verified console checkpoint.

Do not rewrite the old observer, relax the validator to accept `policy_other`, force CLOSED, replay an uncertain attempt, or present earlier successful captures as fresh current-main results. A separately reviewed versioned observational compatibility correction must recognize exact trusted caller relationships and preserve both phase and request-ID correlation. That correction is not implemented by this checkpoint task.

## Existing startup interface — bounded, not a passing current-main demo

Console and MCP worker environments are separate. The existing measured console environment is Windows/Python 3.13.7 with FastAPI 0.129.0, Starlette 0.52.1, Jinja2 3.1.6, Uvicorn 0.34.0 and HTTPX 0.28.1. Console test dependencies are explicit in `requirements-evidence-console-test.txt` (including pytest and jsonschema). The existing worker uses MCP 1.30.0 and LangGraph 1.2.15. Do not upgrade an accepted environment implicitly.

The following trusted-operator interface is preserved for diagnostic reproduction. It is not a claim that current-main fresh demonstrations pass:

```powershell
$worker = Read-Host "Existing verified MCP worker Python"
$executions = Read-Host "NEW private synthetic execution directory outside the checkout"
$analyses = Read-Host "NEW private mock analysis directory outside all input and execution roots"
$port = Read-Host "Available loopback port"
python -B scripts/serve_evidence_console.py --catalog docs/examples/evidence_console_empty_catalog_v1.json --port $port --enable-synthetic-e2e --worker-python $worker --execution-root $executions --advisor-mode mock --advisor-output-root $analyses
```

An empty catalog is accepted only with explicit synthetic execution opt-in. Default read-only startup still requires a nonempty operator catalog. Historical manifests identify captured bytes; supplying a catalog pin does not establish human authentication or new authority.

On a failed or uncertain observation the controller must hold. Refreshing GET pages cannot retry or close it. Keep every failure and investigate before another operational attempt. Independent synthetic test fixtures may use separate new roots to characterize different cases; that is not operational recovery or a general exactly-once guarantee.

## Claude preflight and payload previews

The [API preflight](MINI08_CP1_CLAUDE_API_PREFLIGHT.md) documents official contracts and the separate future authorization gate. Current code is mock-only; supplying a key cannot activate real HTTP. No authenticated Models request, credit query or paid inference is performed.

```powershell
$catalog = Read-Host "Absolute local catalog for three independently pinned preserved synthetic observations"
$previews = Read-Host "NEW private preview directory outside the checkout and all evidence roots"
python -B scripts/preview_evidence_advisor.py --catalog $catalog --output-root $previews
```

Previews are explicitly tied to preserved observations, not new current-main execution. They contain fixed enum/count/hash facts and source aliases; no raw request, arguments, logs, result rows or private filesystem paths are submitted. Projection and mock wire-body digests are distinct. Actual Sonnet identity, credits, verified rates, token ceilings and maximum real cost remain UNKNOWN. A future model/configuration change requires a new exact wire preview and approval. Matching citations resolve references, not narrative truth.

## Verification disclosure

The private CP1 evidence package records commands, JUnit, source identities, failures, preservation results and selected previews. New counts are reported per selection; overlapping tests are never summed as independent samples. Prior MINI08.2 354-PASS and separate 37-PASS results remain historical evidence for their original baseline only.

Unmodified core-plus-console `mypy src` currently reports 160 errors in five optional console files. This diagnostic is preserved; the optional prototype has not acquired strict typing certification. No blanket ignore, CI suppression, historical test rewrite or false green result is introduced. CI/publication integration remains unresolved with the checkpoint HOLD.

No new console checkpoint commit, staging or push is permitted after the failed validation gate. No PR, tag, force push or merge is created. Existing main, historical acceptance, original dirty work and evidence remain intact.

```text
MINI08_CHECKPOINT: CHECKPOINT_HOLD
EVIDENCE_ADVISOR: MOCK_ONLY
REAL_ANTHROPIC_EXECUTION: NOT_AUTHORIZED
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED
USASPENDING_INTEGRATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
FAA_FULL_CONTRACT: BLOCKED
HOLDOUT: RESERVED_UNEXECUTED_NOT_ADJUDICATED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

Stop after diagnosis and documentary preflight. No new compatibility-remediation phase is automatically started.
