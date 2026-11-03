# MINI08-CP1.1 — Versioned Gateway observer compatibility

Local synthetic integration candidate. Human review required. No staging, commit, push, merge, paid provider or deployment authorization.

## Two independent causes

The baseline is main commit `601e65ed77630bbad43eec2bcdce17c25ca65349`. The Gateway now calls deterministic `policy.evaluate` through its `_evaluate` method. V2 recognized only direct `_call` or `ExecutionBoundary.evaluate` callers. The extra frame caused `policy_other`, and its immediate frame had no `request_id`. The backend validator correctly rejected those captures instead of permitting an unsupported CLOSED fence.

The 59 restart failures were a different integration problem. The historical restart helper requires a `pinned-copy` working directory beside `execution/guard-config.json`, with a disjoint protected source root. CP1's direct regression invocation did not supply that layout. Adding only the required layout makes the unchanged helper run and retain an unresolved OPEN fence; it does not repair V2's phase error. A separate frozen-V2 composition with the correct layout confirms that distinction.

## Minimal versioned correction

- `governance_observer_v3.py` retains the original profiling lifecycle, event limits, target set, binding serialization and flush/custody behavior.
- The target set remains exactly the actual policy function, binding issuance and binding consumption. The wrapper supplies context; it is not another event and cannot duplicate a policy return.
- The resolver recognizes only exact code objects: direct Gateway `_call`, or the single known `_evaluate` wrapper whose parent is exact `_call`. Wrapper and outer frame must refer to the same Gateway instance; wrapper and policy frame must contain the same evaluated facts object. There is no arbitrary stack search or caller-supplied phase/identity.
- Phase comes from actual outer-call state and evaluated facts. Preflight, binding issuance, binding consumption and post-result evaluation remain separate. The evaluated post-result facts may legitimately be a replacement object relative to the outer frame's original facts.
- The request identifier is read from the genuine corresponding Gateway frame. Observation correlation remains the observer's selected observation ID; invocation and request hashes remain bound by the unchanged validator.
- Unrecognized shapes still yield `policy_other`/unknown correlation and fail strict admission. Nothing authorizes a tool or forces a result/fence.

The legacy V2 import path is now an explicit compatibility facade exporting the V3 implementation and version. New records say `CIVICGATE-EVAL-GOVERNANCE-OBSERVER-V3`; they are never relabeled V2. Original V2 bytes remain exact in `governance_observer_v2_reference.py`, Git history and the untouched prior worktrees. Its SHA-256 is `0e71f86c8a70a110f9db18d00c8429e98890433deaac21199f27a4d9989add94`.

No Gateway, deterministic policy, ExecutionBinding, production transport, admission validator or original R3.2 test was changed.

## Versioned source and harness wiring

The old 110- and CP1 111-source manifests and V1 runners are preserved. The new `mini08_cp11_console_sources_v1.json` pins 113 files: the current-main source set, V3, the explicit V2 facade and exact V2 reference. `run_console_synthetic_demo_v2.py` validates those pins and their historical manifest links; the console controller selects this V2 worker. No automatic repinning or fallback occurs.

`run_cp11_regressions.py` copies only the explicit pinned sources into a fresh external `pinned-copy`, creates sibling `execution/guard-config.json` and invokes the unchanged guard with stripped environment. It never weakens the restart helper. The A1/A2/MCP selection also verifies six explicit unchanged main test pins needed for its complete selection.

Existing console tests retain their assertions. Two test loader paths now select the actual V2 worker. The historical CP1 inventory check receives its genuine 111-file context with exact frozen V2 bytes; its original 111-file/five-change assertions remain intact. Separate new tests validate current 113-file identity and tamper rejection. Historical context is not presented as current execution.

## Reproduce the synthetic regressions

Use the existing compatible MCP 1.30.0 / LangGraph 1.2.15 worker environment; this task installs or upgrades nothing. Evidence roots must be outside and disjoint from the checkout. Each command creates a new versioned capture and preserves failures.

```powershell
python -B scripts/run_cp11_regressions.py --suite r32 --evidence-root <private-evidence-parent>
python -B scripts/run_cp11_regressions.py --suite a2 --evidence-root <private-evidence-parent>
```

Run console tests in the separate optional FastAPI environment with `--confcutdir=tests/evidence_console`, private JUnit/temp/log locations, and explicit local fixture catalogs. Both synthetic worker environment variable names used by the historical tests must identify the verified worker Python. Do not mix optional FastAPI dependencies into an accepted MCP environment implicitly.

For the console's explicit synthetic mode, use the documented `serve_evidence_console.py` interface and an empty synthetic catalog or independently verified preserved catalog. Its controller now selects the CP1.1 worker. Mock Advisor analysis is a separate manual action and cannot invoke MCP. No HTTP request can select a provider, target, tool, contract, script or source inventory.

## Actual verification

Selections overlap and are not independent semantic samples:

| Selection | Result |
| --- | --- |
| Original six-file R3.2 selection | 373 PASS / 0 FAIL / 0 SKIP |
| A1/A2/MCP selection including original 89 A2 cases | 221 PASS / 0 FAIL / 0 SKIP |
| Complete console/Advisor selection | 381 PASS / 0 FAIL / 0 SKIP |
| Focused observer controls and unchanged backend tests | 81 PASS / 0 FAIL (15 new, 66 original) |
| Separate technical review probes | 11 PASS / 0 FAIL / 0 SKIP |

The console selection includes three fresh actual LangGraph/MCP/Gateway observations and real loopback HTTP tests, with synthetic providers and MockTransport. PERMIT issued/consumed one binding and entered the adapter/MockTransport once. DENY and REVIEW_REQUIRED issued/consumed none and have verified absent dispatch. Three fresh accepted primary projections have actual CLOSED SQLite custody and separately returned ACKs. CLOSED is documentary custody, not human acceptance.

Before/after captures preserve identical policy/execution facts for PERMIT, DENY, REVIEW_REQUIRED and post-dispatch review. The first preflight probe can be REVIEW_REQUIRED while Judge advice is not yet available; later issuance can be PERMIT. A subsequent result-validation review is another actual policy evaluation. The earlier authorized read is not rewritten as unauthorized, and first probe, initial authorization and final disposition are not conflated.

All prior CP1 failures and unsuccessful development runs remain preserved. A first complete console run had 380 PASS / 1 FAIL because its deadline test still loaded the intentionally frozen V1 worker. Only its worker selection was corrected; no assertion was removed. The final selection above is a separate recorded run.

Commands, stdout/stderr, JUnit, source identities, event mapping, exact source diff, SQLite snapshots/restart receipts, preservation checks and independent review remain in the private CP1.1 evidence package. The previous CP1 package is unchanged.

## Mypy classification and limits

Strict `mypy src` still reports 160 diagnostics in five optional console files. They predate this observer repair and match the MINI08 source debt; the controller change is one worker-routing line. No new error was introduced, globally ignored or hidden by module exclusion.

| Category | Count | Interpretation |
| --- | ---: | --- |
| Untyped definitions/calls/decorators and generic annotations | 117 | Incomplete static coverage |
| Optional/Any mapping access and custom runtime guard narrowing | 30 | Data-contract assurance gap; retain runtime negative tests, do not assume all false positives |
| Any returned from an annotated boundary | 4 | Return contract not statically established |
| FastAPI imports absent from MCP worker environment | 4 | Environment separation; console uses its own installed optional dependencies |
| Windows/POSIX symbol typing | 2 | Platform portability typing |
| Reused local-variable inference | 3 | Static int/string/Decimal inference conflicts |

No runtime safety defect is established solely by those diagnostics, and none is dismissed as universally harmless. They remain unresolved and separate from restored synthetic observer compatibility. No production, hostile-host, power-loss, OS isolation, hard real-time, exactly-once, live-provider, model-quality or calibration guarantee is granted.

```text
INTEGRATION: RESTORED_SYNTHETIC_CANDIDATE_PENDING_HUMAN_REVIEW
CHECKPOINT_PUBLICATION: HOLD
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
REAL_ANTHROPIC_EXECUTION: NOT_AUTHORIZED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
USASPENDING_INTEGRATION: HOLD
MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED
P2_02_DURABLE_STOP: PARTIAL
HOLDOUT: RESERVED_UNEXECUTED_NOT_ADJUDICATED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

Stop after repair and validation. Do not resume commit, push, merge, paid validation or deployment automatically.
