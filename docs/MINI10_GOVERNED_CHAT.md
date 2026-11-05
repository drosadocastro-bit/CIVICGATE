# MINI10 Governed Chat — local synthetic MVP

Status: isolated development candidate; human review pending.

MINI10 adds one optional Chat surface to the existing Evidence Console. It does
not add a new authority mechanism. The trusted local host fixes the READ owner,
planner fixture, MCP stdio route, Gateway, and synthetic backend before the
browser can submit a request.

## Execution contract

```text
prompt POST
  → durable immutable prompt record
  → isolated guarded worker copy
  → LangGraph A2: intake → discovery → planner → gateway → result
  → MCP SDK stdio / JSON-RPC
  → deterministic Gateway policy
  → single-use ExecutionBinding when and only when PERMIT
  → synthetic read adapter / MockTransport
  → manifest-verified evidence and documentary custody
```

The browser submits only `{"prompt": "..."}` and a UUIDv4 idempotency header.
It cannot supply a tool, arguments, owner, profile, model, approval, Gateway,
WRITE operation, or fallback. The original UTF-8 request and SHA-256 are
persisted before the worker thread starts. Each turn admits one bounded proposal
and at most one governed MCP invocation. A lost or unknown outcome is never
automatically retried.

The active MVP owner is `CHANNEL_A_LOCAL_READ_V1`. The strict FAA owner and the
WRITE-01 owner are separate compositions and are not imported or exposed by
Chat. There is no fallback to a legacy or weaker Gateway. FAA intents that the
active contract cannot represent remain `REVIEW_REQUIRED` with no binding or
backend dispatch.

## Interface

The optional `/chat` view displays:

- immutable request digest;
- selected MCP tool and canonical arguments;
- deterministic `PERMIT`, `DENY`, or `REVIEW_REQUIRED` disposition and reasons;
- binding issuance and consumption counts;
- synthetic backend attempt count;
- result verification state and released/withheld result;
- observed A2 stage-entry deltas; and
- a link to the admitted Evidence Console observation.

GET pages and status polling do not execute tools. Refresh first reconciles
existing turns; an unresolved `HOLD` or `UNKNOWN` turn blocks a new submission.
`COMPLETE` means the evidence passed local admission. SQLite `CLOSED` means
documentary custody, not human acceptance.

## Reproduction

Use a Python 3.11 environment containing the repository's pinned MCP and
LangGraph dependencies plus `requirements-evidence-console-test.txt`. Choose a
fresh absolute output directory outside the checkout and any historical
evidence root.

```powershell
$worker = '<python-3.11-environment>\Scripts\python.exe'
$output = '<fresh-absolute-chat-evidence-directory>'

& $worker scripts/serve_evidence_console.py `
  --catalog '<bounded-catalog.json>' `
  --port 8765 `
  --enable-synthetic-chat `
  --worker-python $worker `
  --chat-output-root $output `
  --chat-deadline-seconds 90 `
  --chat-max-turns 4
```

Open `http://127.0.0.1:8765/chat`. The server binds to loopback only. The
catalog may contain zero runs only when a synthetic mode is explicitly enabled.
Its shape remains `{"version": 1, "runs": [...]}`.

## Benchmark scope

`tests/fixtures/mini10_chat_benchmark_v1.json` declares eight cases:

| Case | Boundary | Expected observation |
| --- | --- | --- |
| CHAT-001 | compatible public READ | PERMIT; binding 1/1; backend 1 |
| CHAT-002 | FAA/DOT scope not representable | REVIEW_REQUIRED; 0/0; backend 0 |
| CHAT-003 | named-agency argument mismatch | REVIEW_REQUIRED; 0/0; backend 0 |
| CHAT-004 | prohibited consequential request | DENY; 0/0; backend 0 |
| CHAT-005 | authority-bypass instruction | DENY; 0/0; backend 0 |
| CHAT-006 | prompt injection in supplied text | DENY; 0/0; backend 0 |
| CHAT-007 | planner timeout | PLANNING_FAILED before MCP invocation |
| CHAT-008 | malformed planner output | PLANNING_FAILED before MCP invocation |

The first six are deterministic fixtures, not samples of Granite reasoning.
Timeout and malformed-output tests measure orchestration safety, not policy
accuracy. Tool selection, argument equality, intent preservation, policy,
binding, backend, timing, evidence, and custody are reported as separate facts;
they are not combined into an “agent accuracy” score.

## Optional Granite preparation

`LocalGraniteChatConfig` can prepare the existing OpenAI-compatible
`GranitePlanner` for a separately reviewed local experiment. It requires:

- a host-supplied numeric loopback URL with explicit port and `/v1` base path;
- a non-empty exact model ID;
- a 1–30 second timeout;
- one HTTP attempt, no redirect, proxy, retry, or provider fallback;
- strict `Proposal` parsing; and
- an exact match between requested and provider-reported model strings.

Provider-reported strings do not authenticate a runtime or model artifact. The
synthetic Chat composition does not construct this adapter. Effective Granite
identity and genuine inference remain unverified until a separately authorized
loopback observation establishes them.

### Read-only local inventory observed 2026-11-05

No inference was performed. LM Studio processes and CLI build `ff50809` were
present, with 15 locally catalogued models including `granite-4.2-8b`,
`ibm/granite-3.1-8b`, and `ibm/granite-4-h-tiny`. Ollama `0.40.14` listed
`granite3.3:latest`; its local manifest digest was
`fd429f23b90980ed1bef53b990894e7b0199331f6ae90c5650240a7d5b70f1f7`.
No matching configured listener, Chat composition, response model identity, or
runtime artifact attestation was observed. Therefore
`GRANITE_EFFECTIVE_IDENTITY` remains `UNKNOWN_NOT_ACTIVATED`; model names in a
local catalogue are availability candidates, not proof of the model that would
answer a future request.

## Retained boundaries

- synthetic local data only; no USAspending request;
- no real Granite, Luna, Claude, or paid-provider inference;
- no Chat-to-WRITE operation;
- no recursive planning, memory, multi-tool loop, retry, or fallback;
- no strict FAA contract execution and no widening from FAA to DOT;
- deterministic policy remains the sole authority issuer;
- durable STOP remains `PARTIAL`;
- the 54 historical FAA full-contract definitions remain `BLOCKED/SKIP`;
- all operational HOLD states remain unchanged; and
- no production, hostile-host, power-loss, or exactly-once certification.

Capability does not create authority. This candidate requires human review and
does not authorize publication, live execution, or deployment.
