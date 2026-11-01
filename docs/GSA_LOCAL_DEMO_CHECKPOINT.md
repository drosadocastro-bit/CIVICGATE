# GSA local governance and integrated A2 checkpoint

Scope: reviewed research-prototype source and reproducible offline synthetic tests.
This checkpoint does not authorize live providers, USAspending requests, deployment, governmental decisions or writes.

## Included source

The publication explicitly selects versioned R3/R3.1/R3.2 capture admission and composition dependencies, the accepted R4 budget/provider dependencies they require, relevant R3.2 tests, and the MINI07.1/07.2 demonstration assertions.
The existing Channel A Gateway, deterministic policy, ExecutionBoundary and production adapter remain unchanged.

MINI07.1 already exercised LangGraph A2. MINI07.2 additionally persists the actual node-entry history, compiled-graph invocation, original request and separate planner/MCP proposal, correlated with policy, binding, backend, result and SQLite records.

The runner exposes fixed synthetic selections only. See the [offline guide](../evals/README.md) and [source inventory](../evals/manifests/gsa_local_demo_checkpoint_v1.json).
The [verification receipt](../evals/manifests/gsa_local_demo_validation_v1.json) records the executed selections separately. Counts overlap and must not be summed as independent semantic samples.

## Publication-copy adaptations

Original evidence and source candidates remain in local custody. This publication uses reviewed copies:

- Machine-specific source-root literals were replaced with bounded runtime guard configuration created exclusively by the trusted runner.
- Guard and restart helper reject missing, duplicate, unsupported or overlapping source/copy configuration before project imports.
- Output must be outside the repository; source imports occur only from the verified pinned copy.
- Compact demo code was formatted; unused budget references were renamed without removing creation or changing assertions.
- The delayed pytest import is explicitly retained after guard installation.
- README reproduction uses checked-in scripts and an existing verified environment rather than private ZIPs or personal filesystem paths.

The accepted R4 attempt_budget_v2.py bytes remain pinned to:
32a2ad4d49b5ea7715c5d5e7adc34e8b46be3d9a2224a0fed7288b6104d2d31a.

A first new portability run reported 10 PASS / 1 FAIL because a case-sensitive environment filter omitted Windows SYSTEMROOT before a socket probe.
The corrected known-key lookup retained every guard assertion. That failed run and the initial lint/format findings remain preserved privately; later success does not erase them.

## Evidence and interpretation

Each new run records commands, stdout/stderr, JUnit, source identities, primary traces, SQLite data and a run manifest.
The integrated scenarios are PERMIT, DENY and deterministic REVIEW_REQUIRED despite permissive synthetic Judge advice.
All four tools are discovered; only find_federal_awards is invoked by these three demonstration cases.

Binding issuance and consumption, adapter entry, MockTransport attempt, response validation and custody are separate observations.
The saved pre-close summary, returned close ACK and actual database fence are retained separately. CLOSED is documentary custody, not human acceptance.
Synthetic protocol labels do not establish effective Granite/Luna identity.

No datasets, holdout, human adjudication/acceptance records, credential stores, raw logs, databases or private archives are published.
The source inventory establishes byte identity, not authenticated human origin or execution authority.

## Validation boundaries

The measured environment is Windows/Python 3.13.7, MCP 1.30.0, LangGraph 1.2.15 and HTTPX 0.28.1.
Other platforms/model quality are not certified by these runs. Existing CI and historical A1/A2/J3 results retain their own scope.
The default repository pytest configuration does not discover all evals selections; use the guarded runner for the recorded evaluation checks.
Python guards are cooperative local-process controls, not OS isolation, power-loss resistance or distributed exactly-once execution.

Historical protocol documents retain their original statuses and limits. Neither this checkpoint nor a passing synthetic test creates new authority.
FastAPI, Evidence Console and frontend development are not implemented here.

## Retained gates

- LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
- EVAL002_EXECUTION_AUTHORIZATION: HOLD
- USASPENDING_INTEGRATION: HOLD
- P2_02_DURABLE_STOP: PARTIAL
- FAA_FULL_CONTRACT: BLOCKED
- FAA planned definitions: 54 BLOCKED/SKIP, zero executed as a full compatible FAA contract
- PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
- Effective real Granite/Luna identities: UNKNOWN
- Judge calibration: NOT_YET_MEASURED
- Independent golden-reference acceptance: PENDING

A merge, deployment, live operation or subsequent frontend phase requires its own human decision.
