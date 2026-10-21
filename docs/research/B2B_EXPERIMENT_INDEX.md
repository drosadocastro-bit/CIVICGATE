# B2b curated experiment index

Prepared 2026-10-21. **Local/synthetic research only; cloud HOLD.**

The [full inventory](B2B_CANDIDATE_INVENTORY.json) is the exhaustive decision list, including all excluded/private candidates, exact source-qualified paths, byte sizes, SHA-256, imports, reproduction requirements and public-safety disposition. `needed_for_reproducibility` refers to this curated slice, not to reproducing every historical experiment.

## Included groups and dependencies

| Group | Files | Demonstrated scope | Important limits |
| --- | ---: | --- | --- |
| PostgreSQL ledger/history/transport guard/cooperative receiver | 10 | Pure replay and synthetic SQL/session/effect models; source identity checks | Includes explicit migration text but does not apply it. No PostgreSQL driver, server or credentials supplied. SQLite simulation is not engine proof. |
| P0.1 | 2 | Pure admission-evidence assessment with trusted synthetic verifier | Cannot issue binding, reserve an operational attempt or dispatch |
| P0.2 | 2 | Real loopback stateless MCP, finite synthetic enrollment, unchanged Gateway/journal | Requires Git checkout, PyJWT/cryptography and SDK 1.30.0; no production JWT/JWKS or cloud identity claim |
| FAA-001 / FAA-002 | 5 | Legacy characterization, two failing required properties, standalone scope/attribution model and integration blockers | Not FAA-C1 integration; no real USAspending request |
| MVP-002 runtime slice | 3 | Stateless health/discovery and explicit execution-disabled calls | Package builder, deployment entrypoint, lock/manifest and cloud-target configuration intentionally excluded |

No imported file replaces an existing base path. None is registered in the CLI or imported by the unchanged Channel A/B2a entrypoints. Experimental ledger modules have operational-looking interfaces but require explicit trusted composition; they are not production enablement. Test keys/credentials are generated synthetically for local scope, never read from operator stores.

## Reproduce from the checkpoint root

Use a clean disposable test environment and the unchanged project dependency declaration. Measured package versions are in [verification](B2B_VERIFICATION_2026-10-21.json); MCP is exactly 1.30.0. Include pytest, pytest-asyncio, PyJWT, cryptography, and Git for the complete selected run. Ruff and Mypy are needed only for static checks. This checkpoint does not add an environment lock or claim arbitrary future dependency versions are equivalent.

On PowerShell, set `$env:PYTHONDONTWRITEBYTECODE='1'` and `$env:PYTHONPATH='src;.'`. On Linux use `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.`. Run the exact argument arrays in the verification JSON from the repository root; place caches/scratch outside preserved evidence. Mypy also requires `MYPYPATH=src`.

Selected tests:

```text
python -B -m pytest -q -p no:cacheprovider tests/mcp/test_b2b_postgres_ledger.py tests/unit/test_postgres_history.py tests/unit/test_postgres_transport_guard_v1.py tests/unit/test_fencing_receiver_experiment_v1.py tests/adversarial/test_b2b_p01_admission.py tests/mcp/test_b2b_p02_stateless.py experiments/b2b_faa_001/test_contract_characterization.py experiments/b2b_faa_002/test_contract_v1.py experiments/b2b_faa_002/test_integration_blockers.py experiments/b2b_mvp_002/test_smoke.py
```

Separate unchanged required-property failures (expected exit 1; **0 PASS / 2 FAIL**, not xfail):

```text
python -B -m pytest -q -p no:cacheprovider experiments/b2b_faa_001/contract_gap_counterexample.py
```

The cached Linux/Python 3.11 image used network isolation, no published ports, read-only source/root filesystem and disposable scratch. It has no Git. The supported Linux command excludes `tests/mcp/test_b2b_postgres_ledger.py` and `tests/mcp/test_b2b_p02_stateless.py` and passes 558 cases. The complete Windows run passes 682; these overlap. Initial Linux collection failure is retained in verification. No stubs, rewritten tests or invented Git revision were used to conceal the missing dependency.

Existing A1/discovery/A2 stdio/orchestration/B2a HTTP/recovery checks pass 192 cases on Windows. Ruff/format pass for 21 selected Python files; strict Mypy passes for nine implementation/helper modules. The complete repository suite is not claimed rerun. Warnings and all raw-output digests are preserved.

## Deliberate exclusions

- Original private reports and cloud measurement inventories: preserved unchanged; only new summaries and digest references published.
- 006A/006D/006G/006H original diagnostic dependency chain: workspace-specific host metadata and private context; no rewritten diagnostic client shipped.
- SDK 2.3 P0.3–P0.5 candidates: complete separate-environment reproduction is outside this minimal SDK 1.30 checkpoint; HeaderMismatch failures remain documented.
- Real PostgreSQL harness and local receiver integration tests: not silently represented as exercised by synthetic tests.
- FAA-C1 integration worktree: five shared-module edits and dependencies remain separate, requiring their own review.
- Cloud deployment builders/entrypoints/locks: the approved Gate 2 ZIP remains untouched; this branch is not a replacement deployment package.
- 006I: explicitly deferred pending its original evidence.

The complete exact included-file list is the 22 rows marked `INCLUDE` in the inventory; the 93 other rows retain their individual exclusion rationale.
