# B2a local MCP Streamable HTTP prototype

Scope: **LOCAL SYNTHETIC PROTOTYPE / HUMAN REVIEW**. No Channel B operational
readiness or B2b/B2c authorization is asserted. See the additive
[human declaration](B2A_LOCAL_APPROVAL.md) and the unchanged
[amendment](B2_TRANSPORT_001.md).

## Composition and identity

`civicgate.mcp.http_app.StreamableHTTPGatewayApp` is a separate ASGI composition
root. It constructs a private Gateway, ExecutionBoundary, denial counter,
single-attempt USAspending adapter, synthetic judge, and durable local journal.
It accepts only `httpx.MockTransport`; this slice cannot select a real provider.
It does not import, wrap, subclass, or modify `BoundedMCPServer`.

Actual MCP initialize, initialized notification, discovery, tool invocation and
session deletion use the pinned **mcp==1.30.0** SDK. There is one `/mcp` endpoint,
not four REST routes. The four transport wrappers use the existing `TOOLS`
models and `Envelope`, call the existing `Gateway.call`, and seal the unchanged
`BoundedToolDiscovery`. The HTTP/stdio public tool metadata and schemas are
compared exactly in a real-client test. No policy or ExecutionBoundary source
is changed. Wrapper declarations repeat only transport registration, not policy.

The caller presents a short-lived synthetic JWT signed outside the app by an
ephemeral Ed25519 test issuer. The verifier receives only the public key and
pins EdDSA, issuer, exact audience, principal and invocation scope. It requires
integer issued/not-before/expiry times, a maximum five-minute lifetime, and a
bounded credential identifier. No arbitrary bearer string or identity header
is accepted as identity. The configured synthetic service identity is separate
from the authenticated caller and grants no execution authority.

One configured principal/trust domain is allowed per instance. Each SDK session
is additionally bound to the exact verified credential that opened it. Token
renewal requires a new session. Every request is reauthenticated; queued calls
and pre-dispatch journaling recheck expiry. Server-generated request IDs,
verified identity, SDK session ID, stable instance and process generation are
recorded separately. Credentials and reusable authority envelopes are not
persisted. Context is obtained from the current SDK request, not inherited from
the session's first task or caller-supplied metadata.

## Transport bounds and lifecycle

- Only `127.0.0.1`, the explicitly configured Host/port and matching Origin
  (if present) are accepted. No forwarded identity/proxy headers are trusted.
- Body limit: 64 KiB, including chunked bodies; body receipt deadline: five
  seconds. Header bounds: 64 fields / 16 KiB aggregate / 8 KiB per field.
- At most 16 concurrent HTTP requests and 16 SDK sessions; SDK idle timeout is
  60 seconds. Credential-bound admission expires within five minutes.
- Duplicate JSON keys, JSON batches, extra tool parameters, unregistered tools,
  mutated registrations and schemas fail closed. The SDK checks protocol versions.
- `initialize` must precede `notifications/initialized`, which must precede
  tool access. A local gate enforces this even though SDK 1.30.0 accepted an
  early tool call in the characterization test. The raw failure is retained.
- MCP POST returns JSON. Standalone GET/SSE streams return 405, as allowed for a
  server that offers no standalone stream. Resumption/Last-Event-ID is disabled;
  DELETE closes sessions. No legacy SSE endpoint or reset endpoint is exposed.

This is a manual synthetic credential resource boundary, **not** a complete
OAuth authorization server, IdP integration or production authentication design.
Loopback HTTP provides no production TLS. It is unsuitable for remote exposure.
The transport reference used was the
[2025-11-25 MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
with runtime behavior checked against the installed 1.30.0 SDK rather than a
newer draft or an unpinned SDK.

## Durable evidence and containment

`provision_local_store` explicitly creates a new synthetic store once; app
startup never calls it. Replacement processes must use the same provisioned
path and stable trust-domain/instance configuration. A missing or unreadable
store, wrong domain, concurrent owner or invalid history refuses startup.
Provisioning another empty store is not a supported recovery operation.

The local SQLite store uses rollback journaling (`DELETE`) and `synchronous=EXTRA`.
A lifetime OS file lock prevents concurrent owners of the same store. Events
are append-only through the implementation and SQLite triggers, hash chained,
and checked on recovery. Startup bounds the store to 32 MiB / 10,000 events;
capacity exhaustion stops execution rather than rotating away evidence.

Within Gateway's existing serialization lock, the optional journal seam records:

1. Request admission and server-owned identity context (`begin`).
2. Initial deterministic decision and whether a binding was issued (`policy`).
3. Exact non-authorizing binding digests, policy/schema/context identities,
   containment count, code HEAD and source-tree hash (`intent`). The transaction
   commits before returning from this seam.
4. The existing ExecutionBoundary immediately revalidates expiry, arguments,
   schema, policy context and object ownership, consumes the binding, and
   dispatches checked arguments with no inserted callback after consumption.
5. Observed attempts, verification/consumption, pre/post phase, final decision,
   errors, containment count and HOLD disposition (`finish`).

HEAD is checked against the local Git checkout, and a digest of actual package
sources plus `pyproject.toml` distinguishes an edited tree from its base commit.
Digests are evidence, never reconstructible authority. All envelopes remain
process-local and single-use. A new process constructs a new ExecutionBoundary.

Pre-dispatch write failure means zero dispatch. Any incomplete request or
unclean process generation causes recovery HOLD. A missing final outcome,
unknown dispatch, absent attempt evidence or interrupted response also causes
HOLD. The HTTP adapter permits only one attempt; there is no automatic logical
retry, failover, release, or recovery replay. A completed known HTTP error is
recorded without pretending success. The existing deterministic policy remains
the sole decision issuer; HOLD affects execution/recovery and next action.

Denial counts survive clean shutdown and restart. New sessions do not clear
containment. `Gateway._lock` only serializes calls; `_mcp_owner_lock` only guards
attachment. Authentication, durable recovery and process exclusion are separate.
Channel A uses no journal by default and retains its existing attempt limit.

## Local verification and reproduction

Use a dedicated local environment, from this worktree:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest tests/mcp/test_b2a_http.py tests/mcp/test_b2a_recovery.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

The tests start and stop real loopback HTTP servers and MCP clients, with
ephemeral synthetic signing keys. Crash fixtures exit child processes at
specific durable-write/dispatch boundaries. Nothing launches a persistent
service or contacts cloud systems. Existing dev dependencies are used;
`pyproject.toml` is unchanged. PyJWT/cryptography/Starlette/uvicorn are already
dependencies of the pinned MCP SDK.

See [verification evidence](B2A_LOCAL_VERIFICATION.md) for exact results,
preserved failures, environment and source commit.

## Gaps and readiness stop

**Readiness remains STOPPED.** Local process-crash tests do not establish
power-loss durability, filesystem/controller flush guarantees, distributed
storage, malicious OS administrator resistance, rollback-proof evidence,
cross-host exclusion, production TLS or cloud identity behavior. SQLite and
its owner file must stay together on a trusted local filesystem. An operator
with filesystem/code control can replace state; this is not a sandbox against
that operator. No production ACL or filesystem attestation was performed.

No exactly-once claim is made. An acknowledged intent proves only intent; a
crash between intent and outcome deliberately loses availability in HOLD.
No human-authorized release workflow is implemented. A held store requires a
separately reviewed decision; do not delete/reprovision it to manufacture clearance.

The source digest identifies files at startup, not a signed runtime attestation;
changing code or configuration while running is outside the trusted-host model.
Unix locking is implemented but this run verifies Windows only. No Linux,
container, cloud or production test is claimed. The current full dependency
resolution is recorded, not a reproducible transitive lockfile.

MLflow remains future observability only. No MLflow record, Databricks App,
cloud token, real provider request, FAA information, production system or
deployment is involved. B0/B1 historical records and the two amendment files
remain unchanged. Builder evidence is not independent review or human approval
of the implementation.
