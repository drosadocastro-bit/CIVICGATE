# B2a local verification record — 2026-10-15

Status: **LOCAL PROTOTYPE / HUMAN REVIEW; READINESS STOPPED**.

Approved base: `4cc2a6baaa83349201db41a2b2fd0375aad439bd`.
Tested implementation: `999a935cb40c1dd430707a347d7fd964f810cc5b`.
Branch: `feat/b2a-streamable-http`.
Worktree: `D:\CIVICGATE-b2a-local`.

The [approval record](B2A_LOCAL_APPROVAL.md) quotes the user's bounded current-chat
declaration. The [prototype contract](B2A_LOCAL_PROTOTYPE.md) describes design,
reproduction and limitations. No independent reviewer or implementation approval
is claimed. No merge or deployment is authorized by these results.

## Verification results

Commands below were run from the isolated worktree with
`.\.venv\Scripts\python.exe`. All backend calls and credentials in the new tests
are synthetic. Real loopback HTTP and the real MCP client/server SDK are used.

| Command/check | Result | Evidence and limit |
| --- | --- | --- |
| `-m pytest -q --tb=short --junitxml=.../b2a-full-suite-final.xml` | PASS: 2075 passed, 1 skipped | Exit 0; 322.85 seconds; two existing malformed-fixture warnings retained in local JUnit/log |
| `-m pytest tests/adversarial/test_a1_execution_boundary.py::test_transport_failure_preserves_permit_dispatch_and_unknown_result tests/mcp/test_b2a_http.py tests/mcp/test_b2a_recovery.py -q --tb=short` | PASS: 48 | Existing failing Channel A test plus all 47 B2a cases, after correcting default-limit handling |
| `-m ruff check .` | PASS | Exit 0 |
| `-m ruff format --check .` | PASS | Exit 0 |
| `-m mypy src` | PASS | 54 source files; exit 0 |
| `-m pip check` | PASS | No broken requirements |
| `-m pip_audit --local --format json --output .../b2a-dependency-audit-after.json` | PASS with coverage limitation | No known vulnerabilities reported in audited packages; local unpublished `civicgate` skipped |
| `git diff --check` | PASS | Whitespace integrity; not runtime validation |
| Approved-source preservation | PASS | stdio server, discovery, policy, ExecutionBoundary, request/response schemas, SDK declaration and B2 amendment/evidence unchanged |
| Seven original uncommitted paths | PASS | All seven SHA-256 hashes and sizes match the before snapshot; original HEAD and status retained |
| Cloud / MLflow / production | NOT RUN | No such operations authorized or performed |
| Production/distributed durability and TLS | NOT VERIFIED | Blocks readiness; local process-crash evidence does not certify these properties |

The complete suite includes 100 existing Channel A MCP cases (including stdio
subprocess tests), 47 new B2a cases, and existing ExecutionBoundary adversarial
tests, without changing their expectations.

## B2a acceptance evidence

| Requirement | Demonstrated observation |
| --- | --- |
| True MCP transport | SDK ClientSession over real loopback HTTP; initialize/list/call/delete; all four tools invoked |
| Exact discovery contracts | All four public tool definitions equal stdio definitions; extra tools, wrapper/schema drift and bad/extra input fields rejected |
| Authentication | Missing/arbitrary/unsigned/wrong-signature/expired/wrong issuer/audience/principal/scope/not-before credentials rejected before Gateway |
| Identity separation | Client identity headers cannot replace verified principal or service identity |
| Session isolation | Separate credential-bound SDK sessions; foreign credentials/session IDs and cross-instance use denied |
| Concurrency | Four concurrent session calls serialize without interleaved begin/finish records; distinct request/session contexts retained |
| Request bounds | Host/Origin, body limit, duplicate JSON keys, batch messages, unsupported protocol version and admission limits rejected |
| MCP lifecycle | Tool call before initialized notification blocked by explicit HTTP gate; no dispatch |
| Tripwire DENY | Zero dispatch; deterministic policy retained |
| Pre-dispatch REVIEW | No binding and zero dispatch; semantic-unavailable case held |
| Post-dispatch REVIEW | Initial PERMIT, issued/consumed verified binding, one read, final `RECIPIENT_IDENTITY_UNCONFIRMED`; phases remain separate |
| Binding protections | Mutation, expiry after durable intent, foreign boundary, consumed replay and expired authenticated context all stop dispatch; baseline tests cover issuance ownership |
| Pre-dispatch durability | An independent SQLite connection sees committed intent before entering synthetic transport; injected begin/policy/intent write errors yield zero dispatch |
| Post-dispatch failure | Failed final journal write yields an error/HOLD, one observed dispatch, no second call |
| Durable containment | Two tripwire denials persist through fresh sessions and clean process-generation restart; policy containment remains active |
| Actual process crash | Child process exits after begin, after durable intent, during dispatch and before finish; replacement journal refuses admission in HOLD |
| Unknown outcomes | Timeout, network failure, partial response and cancellation preserve HOLD; one backend attempt, no automatic retry |
| Recovery integrity | Missing, empty, truncated or inconsistent stores fail closed; wrong domain/instance rejected |
| Cross-process ownership | Simultaneous owner refused while child holds the OS lock; clean release permits reopening |
| Channel separation | HTTP Gateway rejects a stdio attachment and stdio Gateway rejects another owner; HTTP tools require actual authenticated HTTP context |

## Failures retained and corrections

1. Initial type check using the pre-existing environment reported missing
   LangGraph types and Windows-incompatible static analysis of the Unix lock
   branch. A separate environment with the repository's existing dev dependencies
   was created; the platform branch uses `sys.platform` for correct type checking.
   An initial system-package inheritance attempt exposed a LangChain dependency
   conflict. System-package inheritance was disabled before the recorded test runs.
   The original environment and the user's checkout were not edited.
2. First B2a run: **39 passed, 2 failed**. An unquoted recipient name correctly
   triggered pre-dispatch `REQUEST_INTENT_UNRESOLVED`, so the intended post-dispatch
   test did not dispatch. A targeted first correction still failed until the
   already-established labeled JSON-string name grammar was used. Policy was
   never relaxed. Separately, the invalid-version request omitted MCP's `Accept`
   header and got 406 before reaching version validation; the test now supplies
   valid transport headers and checks the intended 400 rejection. Corrected run:
   **41 passed**.
3. Expanded B2a run: **46 passed, 1 failed**. SDK 1.30.0 dispatched a synthetic
   read before `notifications/initialized`. This was a real lifecycle observation,
   not a successful negative test. The HTTP adapter now requires that notification
   before tool access. Subsequent expanded run: **47 passed**.
4. First complete suite on `bc251b10323b2af42acbbc0c2e22edea831b83ca`:
   **2074 passed, 1 failed, 1 skipped**. The default argument captured three attempts
   before an existing Channel A test changed its module-level limit to one. Commit
   `999a935cb40c1dd430707a347d7fd964f810cc5b` restores dynamic default handling;
   Channel B continues to pass an explicit limit of one. The existing test was
   not modified. The 48-case focused rerun passed; the final complete run is
   recorded above separately rather than replacing this failure.
5. Initial dependency audit: **FAIL**, 12 reported entries in `pip 25.2`, representing
   six unique advisory IDs. Only the local environment's installer was updated to
   `pip==26.2.1`, satisfying the existing CI minimum `pip>=26.2`; the SDK and
   `pyproject.toml` were unchanged. The subsequent audit reported no known
   vulnerabilities in audited packages. Both raw audit outputs are retained.

Two Pydantic warnings in the complete suite concern existing deliberately malformed
planner fixtures (integer tool name and non-object arguments). They are recorded,
not suppressed. The skipped test is the existing non-Windows configuration test.

## Environment and evidence delivery

Windows, Python 3.13.7; MCP 1.30.0; httpx 0.28.1; Pydantic 2.14.1;
Starlette 1.8.0; uvicorn 0.54.0; PyJWT 2.15.1; cryptography 50.0.2;
pytest 9.1.1; Ruff 0.17.1; mypy 2.4.0; LangGraph 1.2.15.
Final local installer: pip 26.2.1.

Raw first/final test logs, both JUnit reports, lint/type checks, dependency audits,
before/after protected-file hashes and representative durable event histories are
delivered in this chat's local `outputs/evidence/`. `B2A_EVIDENCE_MANIFEST.json`
records their SHA-256 hashes, source invariants, environment and test totals.
These local evidence files are not uploaded wholesale to GitHub. The PR contains
reproducible tests and this record; remote CI is not claimed. Commits use
`[skip ci]` and no historical evaluation artifacts or workflows are changed.

No readiness promotion: local process restart/locking is demonstrated only under
the documented trusted-filesystem assumptions. Hardware power loss, distributed
storage, administrative rollback, Unix execution, production identity/TLS,
cloud permissions and a human-authorized release workflow remain unverified or
unimplemented. There is no exactly-once assertion and no authority for B2b/B2c.
