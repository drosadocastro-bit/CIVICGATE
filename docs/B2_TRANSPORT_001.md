# B2-TRANSPORT-001 — Dual-Channel Transport & Trust Amendment

Status: **PROPOSED — Pending Human Approval**.

This amendment proposes one governance core with two transport profiles: Channel A,
trusted stdio MCP, and Channel B, authenticated MCP Streamable HTTP. The profiles
share governance code and contracts, not live Gateway or ExecutionBoundary objects.
This documentary checkpoint does not approve the amendment or authorize HTTP
implementation, installation, cloud probes, deployment, recovery trials or MLflow writes.

| Checkpoint field | Value |
| --- | --- |
| Document date | 2026-10-15 |
| Historical tested baseline, as reported | `82862cd5e258867163a3caf83066a01de24cdbb9` |
| Remote `main` verified before branch creation | `82862cd5e258867163a3caf83066a01de24cdbb9` |
| Commits after the historical baseline at that check | None |
| Documentary branch | `docs/b2-transport-001` |
| SDK contract | `mcp==1.30.0`; no dependency change |
| Decision authority | Human approval, recorded separately against an exact revision |

The companion [B0 and B1 evidence record](B2_TRANSPORT_001_REPORTED_EVIDENCE.md)
separates reported external results from source inspection. Neither portability
nor synthetic evaluation establishes remote transport readiness.

## Existing boundary and proposed amendment

The existing [Channel A ownership contract](CHANNEL_A_SECURITY_R1.md) and
[A1 execution boundary](CHANNEL_A1_EXECUTION_BOUNDARY.md) remain in force.
`BoundedMCPServer` is stdio-only: its supported SSE and Streamable HTTP entry
points reject use, stdio runner ownership is permanent, and a second SDK session
cannot take over. These are enforced boundaries, not configuration switches.
`BoundedMCPServer` remains unchanged.

If approved for later implementation, this amendment would add a separately
constructed `StreamableHTTPGatewayApp`. It must not import, wrap, subclass or
modify `BoundedMCPServer`. Channel B must use the MCP Streamable HTTP protocol,
including bounded discovery and tool invocation, rather than treating four
ordinary HTTP routes as proof of MCP compatibility. Protocol compatibility and
security under SDK 1.30.0 require later local evidence.

There is one source of governance semantics: the existing schemas, deterministic
policy, Gateway path and ExecutionBoundary. No copied policy engine, alternate
authority issuer, HTTP shortcut or channel-specific weakening is proposed.
Every tool invocation enters that channel's `gateway.call()`.

## Transport profiles and ownership

| Property | Channel A | Proposed Channel B |
| --- | --- | --- |
| Transport | Trusted local stdio MCP | Authenticated MCP Streamable HTTP |
| Adapter | Existing `BoundedMCPServer` | Separate `StreamableHTTPGatewayApp` |
| Runtime boundary | Own Gateway and ExecutionBoundary | Own Gateway and ExecutionBoundary, separate from A |
| Owner | One trusted local owner and SDK session | One HTTP adapter owner per Gateway, bound at startup |
| Identity | Trusted host composition; SDK object identity is not human authentication | Verified caller identity plus server-owned session context |
| State | Existing instance-local state | Separate instance state with the proposed durable recovery gate |

The initial B profile is deliberately bounded to one approved authenticated
principal/trust domain per app process. Another principal/trust domain requires
a separately authorized instance; cross-principal multiplexing is not included.
Multiple sessions of that principal must remain isolated. A session identifier
alone is never identity or authority. Broader multi-principal operation would
require an additional reviewed isolation contract.

Each B process constructs its own Gateway, ExecutionBoundary, denial counter
and owner binding. `_claim_mcp_owner()` attaches the HTTP adapter once at startup.
It cannot attach to Channel A's Gateway. Authenticated request context must bind
principal, session, request, channel and instance identity to the internal
invocation and its evidence; callers cannot supply or replace trusted bindings.
No authority envelope is transferred between sessions, instances or channels.

Source inspection shows that `Gateway.call()` serializes calls with the async
`_lock`. `_mcp_owner_lock` protects owner attachment only. Neither lock supplies
authentication, session isolation, durable containment or cross-process
serialization. The current Gateway has no authenticated remote-session contract;
B must demonstrate that contract before any cloud deployment. Conservative
instance-wide containment may hold all sessions of the approved principal; a new
session cannot be used to escape it.

## Authentication, authorization and app identity

These responsibilities remain distinct:

| Layer | Proposed responsibility | Evidence status for the target App |
| --- | --- | --- |
| Ingress TLS | Approved TLS termination and protected upstream path | DOCUMENTED_ONLY; not verified here |
| Caller authentication (authN) | Verify OAuth2 bearer credentials at the HTTP boundary against an approved issuer, audience and validity policy; reject missing or invalid credentials before Gateway access | DOCUMENTED_ONLY; implementation not authorized |
| App access control | Admit only the approved caller principal/trust domain and bind sessions server-side | UNKNOWN |
| Execution authorization (authZ) | Existing deterministic policy and exact single-use ExecutionBoundary checks on every invocation | Existing local core; HTTP integration unimplemented |
| App identity | Separately scoped service principal for approved platform resources | Auto-provisioning is a reported design assumption; actual identity and grants UNKNOWN |

An authenticated caller is not automatically permitted to execute a tool. App
access permission and service-principal resource access cannot issue policy
PERMITs, satisfy REVIEW_REQUIRED or override DENY. The service principal must
not be represented as the human caller. Client-provided identity headers or
session IDs are untrusted unless an approved boundary authenticates and binds
them. Tokens and secrets must not enter traces or MLflow evidence.

The concrete identity provider, credential validation, session lifecycle and
least-privilege resource grants remain review inputs for B2a/B2b. No cloud
identity behavior or permission is inferred from successful Serverless work.

## Frozen tools, discovery and execution invariants

The four tools remain exactly:

- `find_federal_awards`
- `get_federal_award`
- `resolve_federal_recipient`
- `summarize_federal_spending`

Channel B must register these tools from the same `TOOLS` schema registry and
seal `BoundedToolDiscovery` over its actual registered wrappers at startup.
Listings and invocations must verify the sealed registration, including names,
input/output schemas, wrapper identities and metadata. Tool inputs remain
`user_request` and `query`; unexpected fields are rejected. Discovery describes
capabilities and never authorizes invocation. Authentication does not relax
registration checks.

The following requirements are non-negotiable in any later implementation:

1. Preserve schemas, the deterministic policy and its ordering, the existing
   Judge/Agent K roles, and `PUBLIC_SPENDING_RESEARCH` scope. Model signals are
   evidence inputs, not execution authority.
2. DENY never reaches the tool adapter. REVIEW_REQUIRED produces a hold and
   cannot be bypassed by caller consent, a transport claim, a service principal,
   an observation score or an alternate channel.
3. Preserve exact bindings for request, tool, canonical effective arguments,
   schema, policy decision/facts and server policy context. Only an envelope
   issued by the channel's own ExecutionBoundary may be consumed there.
4. Reject forged, copied, mutated, expired, foreign and consumed envelopes.
   Successful or failed consumption cannot enable replay. Durable audit records
   and matching hashes cannot reconstruct dispatch authority.
5. Preserve immediate pre-dispatch verification and dispatch of the checked
   arguments without an intervening mutable callback or authority substitution.
6. Isolate authenticated session context, results and bindings across sessions
   and instances. No direct adapter endpoint, shared Gateway between A and B,
   or cross-channel failover may evade the policy path.
7. `DISPATCH_UNKNOWN` means **HOLD**. No automatic logical retry, replay or
   failover may resolve uncertainty by issuing another call. `tool_executed=True`
   does not prove provider receipt, success or a known transport outcome.

One consumed binding currently authorizes one logical adapter call; the baseline
adapter has its own bounded read retry behavior. That existing behavior is not
a new permission to retry an uncertain B operation. B2a must inspect and constrain
the effective attempt policy so any ambiguous dispatch attempt stops further
attempts and enters HOLD. This is a proposed B requirement, not a claim that the
baseline adapter already supplies it or authorization to edit it in this checkpoint.

## Durable evidence and containment

The baseline `_issued` registry and `_denials` counter are in memory. Envelopes
have a default 30-second lifetime and a maximum of 256 outstanding entries per
ExecutionBoundary. New processes lose that state. `Trace` keeps a bounded
in-memory event window and optionally appends JSONL to a file; the source alone
does not establish crash durability or durable recovery coordination.

For proposed B dispatch, evidence must be append-only and durably acknowledged
**before** entering the adapter. The record must identify the authenticated
context without secrets, channel/instance generation, request, exact binding
digests, policy/schema/code revision, containment decision and dispatch intent.
Post-dispatch evidence must record observed attempts, outcome and unresolved
uncertainty separately. An intent record is not proof of an actual send.

Durable recording must integrate with the existing immediate consumption gate:
record the exact candidate binding first, then revalidate and consume immediately
before dispatch. A logging delay cannot extend expiry or permit a changed
binding. Never persist a reusable authority token. Missing evidence or failure
to acknowledge a pre-dispatch write means STOP with zero dispatch. A missing
post-dispatch outcome means HOLD, never assumed success or assumed non-execution.

| Event | Required proposed B behavior |
| --- | --- |
| Reconnect or new session | Reauthenticate and establish a fresh request context; preserve applicable containment and unresolved dispatch holds |
| Process restart | Invalidate all old envelopes; recover durable containment and unresolved intent/outcome records before admitting execution |
| Recovery evidence absent, incomplete or unreadable | Fail closed in HOLD; do not treat an empty in-memory counter as clearance |
| Intent without a conclusive outcome, or `DISPATCH_UNKNOWN` | HOLD pending human review; no automatic retry, replay or channel failover |
| Human-authorized release | Append a separate decision tied to the affected evidence and instance generation; fresh requests require fresh policy evaluation and bindings |

A restart is not an authorized containment reset. Durable containment must cover
the approved principal/trust domain across replacement process generations; it
must not be keyed only to an ephemeral session or instance ID. Its storage,
concurrency and ownership design must prevent two instances from independently
clearing the same unresolved hold. Historical failures remain immutable.

A Unity Catalog table or Volume-backed append-only log is a candidate storage
choice, not a proven durable design. Atomicity, acknowledgment, access control,
failure behavior and recovery must be specified and demonstrated before B2b.
An offline/local durable-store substitute may be evaluated in separately
authorized B2a work. No exactly-once guarantee is asserted.

## MLflow and platform limits

MLflow is **observability only**. Post-hoc scorers may consume serialized evidence;
they cannot issue authority, reset containment, alter Gateway state or stand in
for the pre-dispatch durable journal. The B1 synthetic experiment and all its
historical records remain unchanged. If later authorized, deployment trials use
a separate experiment namespace such as `CIVICGATE_B2_Deployment_<date>`.
This proposal does not create that experiment or write any tags or assessments.

Databricks App creation/deployment permissions and App egress status are
**UNKNOWN**. Serverless connectivity does not establish App connectivity.
App runtime availability of MCP 1.30.0 and compatible dependencies, service
principal grants and durable-store access also remain UNKNOWN. Neither visible
entitlements nor a reported Serverless test authorizes an App creation probe.

## Proposed phases and approval gates

| Phase | Bounded purpose | Entry and exit requirements |
| --- | --- | --- |
| B2a local prototype | Separately authorized local implementation and synthetic/adversarial verification of authenticated MCP Streamable HTTP | Human approval of the amendment plus explicit implementation scope; demonstrate invariant parity, identity/session isolation, durable failure handling and pinned SDK compatibility without cloud deployment |
| B2b authorization-gated cloud deployment | A separately approved Databricks App trial | Reviewed B2a evidence; explicit cloud authority and budget; verified App permissions, identity grants, egress, runtime and durable storage; no implicit create probe |
| B2c controlled recovery | Bounded restart/reconnect and uncertain-dispatch exercises | Separate human authorization with failure scenarios, evidence capture and stop criteria; demonstrate durable containment and human-controlled release without replay |

Unknown cloud permissions block B2b readiness, not the ability to review this
proposal or later authorize local B2a work. Approval of one phase does not approve
the next. All phases remain unexecuted and unauthorized by this checkpoint.

## Required future acceptance evidence

These are review criteria, not newly implemented tests or reported passes.

| Control | Required observation |
| --- | --- |
| Missing, invalid, expired or wrong-context credentials | Rejected before Gateway; no tool dispatch |
| Authenticated bypass request | DENY and `tool_executed=False` |
| REVIEW_REQUIRED | No authority issuance or adapter dispatch; no caller override |
| Argument, schema or policy-context tampering | Binding/context rejection before dispatch; exact failure retained |
| Foreign session, instance or channel binding | Rejected; no authority, result or context leakage |
| Replay or expiry | Consumed/expired envelope rejected, including after reconnect/restart |
| Discovery mutation or extra tool/input | Fail closed; exactly the four frozen tools and schemas |
| Concurrent authenticated sessions | Serialized Gateway calls with distinct context and no interleaved bindings |
| Failed durable pre-dispatch write | Zero dispatch and preserved failure |
| Crash before/after dispatch with incomplete outcome | Recovery HOLD, no automatic repeated attempt |
| Active containment followed by reconnect/restart | Containment survives operationally or startup remains held |
| `DISPATCH_UNKNOWN` at any attempt | HOLD; no adapter retry, logical retry or cross-channel failover |
| MLflow unavailable or a scorer returns PASS | No alteration of execution authority or recovery state |
| Channel A regression and MCP 1.30.0 parity | Existing stdio contract remains unchanged; actual MCP discovery/call behavior demonstrated separately |

## Reconciliation of the earlier discussion

The referenced discussion is proposal context, not approval or implementation
evidence. Its retrieved assistant turns contain content-reference placeholders,
so they cannot supply missing technical decisions. This checkpoint uses the
explicit current request and inspected baseline to resolve these points:

| Earlier wording | Coherent proposed contract |
| --- | --- |
| Four HTTP routes establish Channel B | Actual MCP Streamable HTTP compatibility is required |
| `_mcp_owner_lock` serializes requests | `_lock` serializes calls; owner attachment uses `_mcp_owner_lock` |
| Restart clears containment and is acceptable | Baseline state loss is a gap; proposed B must recover containment or HOLD |
| Trace JSONL is in-memory only | Trace supports optional file append; crash durability remains unproven |
| One shared Gateway implies authenticated caller isolation | The core does not authenticate sessions; B requires an explicit bounded principal/session contract and evidence |
| Unknown App permission blocks all B2a work | Cloud permission gates B2b; local prototype work still needs separate human authorization |

## Human review decision

**Pending. No approval, signature, implementation or deployment is recorded.**
The requested commit and PR are documentary publication for human review only;
they do not merge the amendment into authority. A future decision must identify
the reviewed Git revision, approved scope, constraints and phase authorizations.
Builder, reviewer and human authority remain distinct. Historical evaluations,
frozen manifests and failed or unknown observations are not rewritten.
