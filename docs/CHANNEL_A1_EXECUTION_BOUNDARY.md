# Channel A1 execution boundary

Discovery does not imply authority. This candidate reuses the existing four-tool registry, MCP wrappers, deterministic policy, Gateway dispatch and audit trace. It adds no tool, policy authority or orchestration framework.

## Invocation path

1. MCP discovery returns only the registered name, static description, input/output schemas and fixed descriptive hints. Each response owns its metadata copies. Extra wrapper fields and registration changes are rejected.
2. Gateway snapshots the proposal before waiting for its session lock. Tool arguments are validated, and the semantic judge receives a separate copy. Existing deterministic preflight DENY still skips the judge.
3. The execution boundary calls the unchanged ordered policy. DENY and REVIEW_REQUIRED issue no envelope. A PERMIT can issue a private immutable AuthorityEnvelope with an exact ExecutionBinding.
4. The binding identifies the request, tool, canonical effective arguments, schema, fixed PUBLIC_SPENDING_RESEARCH scope, policy decision/facts and server policy context. Hashes describe integrity; the private issuance registry authenticates the exact issued object within this Gateway process.
5. After the pre-execution audit succeeds, Gateway checks and consumes the envelope immediately before backend dispatch. It rejects absent, copied, foreign, changed, expired or consumed authority and changed configuration or schemas. It dispatches validated arguments reconstructed from the checked binding, with no intervening await or external callback.
6. Result validation, clarification, reduction and final audit happen afterward. A post-result REVIEW_REQUIRED cannot grant or retrospectively supply execution authority.

No public invocation API accepts caller approvals, envelopes, policy results or capability claims. Planner-generated claims and matching self-calculated hashes cannot enter the private issuance registry.

## Fit and limits

| Concern | Candidate behavior | Remaining limit |
| --- | --- | --- |
| Discovery | Same four-tool MCP catalog, bounded metadata projection | No dynamic/untrusted tool installation |
| Policy | Existing PERMIT / DENY / REVIEW_REQUIRED rules reused unchanged | Existing semantic calibration and lexical limitations remain |
| Provenance | Exact object retained by the issuing Gateway | Trusted server process; no remote identity or signature claim |
| Execution | Immediate gate on agent, MCP and internal Gateway paths | Arbitrary hostile Python in the server process is outside the boundary |
| Replay | Each issued envelope is consumed once; expiry uses monotonic time | No durable cross-process admission or exactly-once backend guarantee |
| Audit | Actual policy, binding verification, backend attempts and result status remain separate | Final logging cannot undo a public read; audit is not tamper-proof |
| Read retry | Existing bounded adapter transport retry policy retained | One binding authorizes one logical adapter call, which may include transport retries |

The USAspending adapter remains a trusted SDK primitive used by composition code and tests. It is not a second MCP execution entry point. Adding remote transports, untrusted in-process plugins, writable tools or arbitrary backends requires a separate boundary review.

Tests use synthetic judges and fixture transports, including hostile proposals, direct MCP calls, forged/copied envelopes, tool/argument/schema/context changes, expiry, replay, audit failure, transport failure and post-result review. Their evidence supports the tested local boundary; it does not establish production readiness or complete agentic governance.

## Candidate verification

The unchanged base passed 407 tests with one skipped. This candidate adds 58 execution-boundary/adversarial tests and 18 discovery tests; all 76 passed. Ruff lint/format and strict source typing passed. Independent source/assertion review found no material bypass in the supported Gateway/MCP scope.

The complete candidate suite reported 481 passed, two failed and one skipped. Both failures are the historical J3 benchmark freeze checks in `tests/unit/test_profiled_judge_benchmark.py`. Its unchanged manifest pins the old source set. The only difference is `plan.source_sha256`: the three modified and two added A1 source files. All original source hashes from the base still match the frozen manifest. The guard correctly refuses the changed candidate, and the full suite is therefore not green. Neither its manifest, tests nor validator was updated or weakened. The preserved diagnostic and raw test results accompany the external verification report.

Channel B, Databricks, LangGraph orchestration, RQ6 authority/evidence, real admissions and scientific operations remain outside this change. No commit, push or merge is part of this candidate.
