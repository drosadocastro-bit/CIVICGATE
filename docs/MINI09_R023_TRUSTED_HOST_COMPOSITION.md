# MINI09-R02.3 — trusted host composition and legacy route isolation

Status: `FAA_HOST_COMPOSITION_READY_FOR_HUMAN_REVIEW`, limited to the demonstrated
local synthetic MCP topology. This is not human acceptance, production activation,
Console migration, host isolation or permission for live execution.

## Baseline and additive scope

- Branch: `codex/mini09-eval-r02-data01`.
- HEAD: `fdf91d288eba9160dedc4c83b8a0ff339da14857`.
- Tree: `b87dad4e0421ec8afd6e37e425a2337b337e96b5`.
- The 364 original tracked files, 21 MINI09 V1 files, 14 R02.1 files and 17 R02.2
  files remain byte-identical to their earlier inventories. Git tree identity
  alone does not identify these untracked candidates; separate manifests do.
- This task adds a host composition, versioned evidence wiring, three test files,
  one case matrix, a runner, this report and an identity manifest. No production
  Gateway, policy, registry, schemas, Console or original evaluation is edited.

The [R02.2 contract proposal](FAA_FY2026_PR_READ_v1_PROPOSAL.md) remains unchanged.
`FAA_FY2026_PR_READ_v1` means FAA awarding subtier under DOT, inclusive FY2026
2025-10-01 through 2026-09-30, PR place of performance, prime contracts,
explicit A/B/C/D, page 1 and a limit of 1–20. Date semantics remain
`AWARD_DATE_SYNTHETIC_ONLY`; optional recipient means an exact fictional name.
Current host templates require the full ordered A/B/C/D set. No new-awards-only,
transaction, live-response, total-spending or general natural-language contract
is introduced. The 54 historical full-FAA definitions remain BLOCKED/SKIP.

## The boundary that changed

R02.2 could demonstrate a strict server but also select a separate legacy owner
in its test host. That was correctly insufficient to claim agent containment.
R02.3 fixes the launch capability **before discovery and planning**, then hands
the planner/agent an already initialized governed transport. Launch parameters,
server factories, URLs and legacy clients are not agent-facing tools.

[TrustedFaaLaunchOwner](../evals/proposals/r023/host_v1.py) binds the immutable
intake, strict schema, fixed stdio module, executable, arguments, clean worker
environment and exact configuration. Its process-local capability must be the
same object owned by that host; copying matching fields/hashes does not acquire
the launch. The capability is consumed once. Finish, failure and re-entry do
not reset it or create a legacy owner. Hashes record integrity, not independent
human authentication or policy authority.

`HostSelectedFaaComposition.from_gateway()` accepts the existing strict FAA
Gateway/contract and reuses R02.2's actual server and scope gate. The worker has
no owner selector, legacy launch branch, URL route or automatic fallback. The
server's original SDK-session ownership and stdio-only restrictions remain.
All four tool names are still discovered: the isolation is not name hiding.
GET, RECIPIENT and SUMMARY calls reach the same strict gate and are refused;
aliases and extra routing fields are rejected before backend dispatch.
Protocol metadata is neither trusted intake nor a profile selector. Ignoring a
metadata claim does not authorize a different operation: the original request,
strict typed query and host selection must still match before policy can PERMIT.

The [versioned worker](../evals/proposals/r023/observation_v1.py) records the
actual module, source SHA, PID, intake and selected schema before discovery.
It reuses original LangGraph A2, MCP SDK, deterministic policy, ExecutionBoundary,
observer, R02.2 adapter/capture validator and SQLite coordinator. Reusing helpers
may transitively import legacy code; no legacy route is registered, offered or
invoked by this FAA worker. Import availability is not tool authority.

There are four distinct lifecycle controls:

1. Host launch capability: one consumption, no transport/endpoint substitution.
2. Original server: one stdio start and one owned SDK session object.
3. Evaluation worker: one Gateway invocation per observation, with a synchronous
   admission flag set before awaiting the original Gateway. Repeated calls are
   refused before a second policy/binding/backend action.
4. Original ExecutionBinding: exact effective invocation and single consumption.

MCP 1.30.0 can accept another initialize message on the same pipe. That does not
select a new Gateway or establish another trusted context. The tests separately
observe successful protocol reinitialization and refusal of the subsequent
reused invocation. No SDK behavior or global policy is changed to simplify this.

## Tested topology and its limits

The synthetic agent has one host-provisioned private stdio connection. It can
propose tools/arguments or directly issue MCP calls on that connection. It has
no Python/shell execution tool, filesystem/configuration editor, transport
factory, endpoint selector, legacy client or host reset operation. Direct SDK
fault injections intentionally exercise more than the planner normally exposes.

The test host separately composes one legacy compatibility control; that client
is never passed to the FAA agent, A2 transport or FAA launcher. This control is
authorized only as a synthetic test under this task, not an operational authority
receipt. No production authentication system is invented.

HTTP/SSE startup and route requests are refused by the actual host/server methods.
No HTTP application or listener is provided to the agent. Protocol metadata
claiming an HTTP endpoint remains metadata on the existing stdio pipe; it does
not cause a connection there. These tests are not a port scan or evidence of
network-wide isolation. An agent independently given another MCP client, the
existing unmodified Console, arbitrary Python/process control or access to a
compromised host is outside this topology and is not contained by this prototype.
Integrating this selection into an operational host/Console requires separate
review and authorization; this task does not silently migrate either.

## Before/after bypass matrix

| Attempt | R02.2 observation/limitation | R02.3 observation |
| --- | --- | --- |
| Legacy FAA FIND query without profile | Separate unscoped owner could PERMIT an empty toptier result although the FAA reference has 16 records | R023-019 sends that query to the actual fixed FAA pipe: SDK rejection, no binding or backend |
| Original or other registered tool | InvocationContract alone left SUMMARY's legacy Search path available | R023-016–018 reach the same strict owner and are refused |
| Alias/path-like tool name | Hiding names alone was insufficient as a proposed boundary | R023-020–021 are real direct MCP calls and return tool errors |
| Missing/changed profile, parent, role, tier, dates, geography or original text | Strict R02.2 gate already refused these inside its owner | R023-005–015 retain refusal on the host-fixed target |
| Client owner/profile/transport/endpoint fields | A selectable host route was the outstanding concern | R023-022–024 reject extra invocation fields without policy or dispatch |
| Metadata claims LEGACY or an alternate endpoint/session | Not a tested host-fixed topology | R023-025–026 execute only the exact strict FAA query and return 16 records, with the same observed strict schema/worker |
| Reused launch, copied capability, changed config or target | No agent-bound launch capability was demonstrated | Unit/adversarial controls reject reuse, coherent clones, target mutation and alternate transports |
| Same pipe replay / protocol reinitialize | Server session ownership alone does not prohibit protocol reinitialize | R023-027–028 retain the strict owner and reject a second invocation; no new binding or backend |
| Failed initialization | Fallback containment was not demonstrated | R023-029 deliberately removes only its new synthetic config after launch reservation; worker fails before MCP initialization, with no fallback, policy or dispatch |
| Separate legacy host | Known FAA false PERMIT must remain preserved | R023-LEGACY-CONTROL still PERMITs its empty result; it is explicitly outside the FAA agent's routes, not relabeled semantic success |

Unknown/unsupported intentions receive REVIEW_REQUIRED or a stricter documented
SDK/host refusal. The natural FAA request in R023-004 still returns
REVIEW_REQUIRED / REQUEST_INTENT_UNRESOLVED despite synthetic IN_SCOPE at 0.99.
The host does not rewrite it to force PERMIT. A refusal at SDK/host admission is
not fabricated into a deterministic DENY or a human decision.

## Fresh execution and custody evidence

The final selection is `mini09-r023-20261104/all-final-02/`, outside the repository.
It contains commands, pinned copies, guard facts, JUnit, logs, actual MCP inputs
and responses, worker selection, observer phases, raw MockTransport bytes,
fingerprints, functional references, SQLite snapshots and a SHA-256 inventory.

There are 32 FAA observations plus one separately composed legacy control.
Five cases traverse actual A2 transitions; direct SDK cases test the planner
bypass boundary. The failed-startup case never initializes MCP. All providers
are deterministic fixtures, including the reused `r022-synthetic` Judge;
Granite and Luna are not invoked. All backend activity is HTTPX MockTransport.

Across the selection: 32 primary logical MCP calls and 34 actual SDK tool calls.
The extra two calls are explicit adversarial replays, not automatic retries.
The strict cases have 33 raw SDK send records. The separate legacy call is
supported by its original client counter/input/result rather than the new raw
send ledger; these evidence channels are not represented as identical.
There are nine binding issuances, nine actual consumptions, nine adapter entries
and nine MockTransport attempts: eight in strict FAA cases and one in the separate
legacy control. SQLite preserves nine CLOSED fences and 24 OPEN fences.
No provider attempt or send lease is created; no uncertain reservation is refunded.

Successful strict reads return 16 records, a bounded first five, or a legitimate
empty exact-recipient result. IDs, exact amounts and pagination agree with the
unchanged SQL oracle for the selected fixture scopes. Wrong attribution preserves
the initial PERMIT and authorized read, then withholds the result with
FAILED_VALIDATION and OPEN/STOP. SDK errors are received responses but have no
governed envelope; the unchanged coordinator conservatively keeps their custody
OPEN/CLIENT_RECEIPT_UNKNOWN. They are not described as lost network responses.

Startup refusal has no observer seal or Gateway projection. Its
`primary_projection_verified` is false, `server_selected_profile` is null, and
the requested host profile is recorded separately. The startup refusal is checked
against the preserved configuration identity, actual worker error, absence of
initialization/calls and OPEN/STOP state. No synthetic policy or acceptance is
created to fill the missing projection.

For initialized observations, R02.2's unchanged capture validator reconciles the
actual request, selected schema, binding, attempt, bytes, provenance and client
projection before any close. Host selection and target are checked independently.
CLOSED means documentary custody, not human acceptance, model quality or FAA
semantic correctness; the separate legacy control can also close under its old
contract. No automatic retry, failover, reset or recovery path is introduced.

## Results, failures and preservation

| Executed selection | PASS | FAIL | SKIP |
| --- | ---: | ---: | ---: |
| Final R02.3: 56 unit/adversarial controls + 33 full-path characterizations | 89 | 0 | 0 |
| Original A1/A2/MCP | 221 | 0 | 0 |
| Original R3.2 | 373 | 0 | 0 |
| Console/Advisor | 441 | 0 | 9 |

Counts overlap. The separate 37-PASS host and 19-PASS independent selections are
subsets, not additional semantic samples. The Console skips retain their explicit
local catalog/HTTP prerequisites; three guarded worker captures were freshly
verified separately. No complete-repository suite or new CI run is claimed.
Ruff/format pass on six new Python files. `mypy src` passes for 70 unchanged
production files, not as certification of the evaluation prototype's typing.

Development `all-development-01` remains 88 PASS / 1 FAIL. Its genuine failure
was `ValueError: R3_CAPTURE_FILE_UNAVAILABLE`: the new collector attempted to read
an audit file that the deliberately failed startup never created. The worker had
already refused initialization without dispatch. The correction permits absent
files only for that exact startup-fault case with an observed error; malformed,
symlinked or missing normal captures still fail. The original validator was not
changed. An early hypothesis about None iteration was disproven by the traceback.

The new runner was also corrected after static review to require zero SKIP before
writing a READY disposition. No actual false READY from skipped tests was observed.
`all-final-01` preserves 89 PASS before the explicit requested-profile versus
observed-server-profile metadata clarification; final evidence uses the exact
current identities in `all-final-02`. Earlier failures and manifests are untouched.

Separate assistant agents performed host tests, adversarial review and primary
readback in the same environment. This is technical cross-checking, not independent
human or organizational acceptance. The SQL oracle is independently implemented,
not an accepted human golden reference. This is a disclosed non-blind engineering
evaluation aware of prior incidental R1 exposure. The reserved EVAL holdout is not
read, executed, adjudicated or used; previous metadata exposure remains historical.

## Reproduction and remaining decisions

Use the already provisioned worker environment, MCP 1.30.0 / LangGraph 1.2.15 on
Windows/Python 3.13.7, with a new private destination outside the repository:

```powershell
python -B scripts/run_r023_host_v1.py --execute-synthetic --selection all --evidence-root <NEW_PRIVATE_DIRECTORY>
```

The runner refuses an existing output directory. No install or live credential
is required. The [candidate manifest](../evals/manifests/mini09_r023_candidate_v1.json)
identifies every new file; a private delivery receipt identifies the manifest,
primary evidence, preservation checks and retained development failures.

Human review must decide whether to accept this exact bounded prototype and,
separately, whether to integrate the fixed host selection into an application.
No global policy change or legacy removal is proposed. Future use must preserve
the same no-alternate-client/launcher assumptions or establish a stronger boundary.
Arbitrary host processes, filesystem attackers, power loss, distributed exactly-once,
universal persistent quarantine and real model/API behavior remain unverified.

```yaml
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
USASPENDING_INTEGRATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
FAA_FULL_CONTRACT: BLOCKED
SERVICE_WRITE: NOT_IMPLEMENTED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

No staging, commit, push, merge, cloud operation or operational acceptance is
performed by this task. Stop after this isolated validation and human review.
