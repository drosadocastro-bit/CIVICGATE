# Channel A2 local orchestration candidate

The workflow is `intake → discovery → planner → gateway → result`. It performs one plan and at most one MCP tool invocation. It introduces no execution authority, recursive tool loop, checkpoint recovery, automatic retry or direct adapter access.

## Trusted intake and deployment assumptions

`LangGraphAgent.run(request)` captures an immutable `IntakeContext` before any awaited work. It preserves the exact original string, including whitespace and Unicode, separately from the planner's canonical proposal snapshot. The request digest identifies bytes; it does not authenticate a human or their intent.

The compiled graph and its private invocation data are scoped to one run. Nodes ignore request, proposal, policy and response fields injected through graph state. A private phase guard rejects out-of-sequence node execution and repeated entry. The planner receives only the original immutable string through the unchanged `AgentModel.propose(request)` interface. Existing GranitePlanner remains compatible; this candidate does not call a live model.

The host must trust its installed application code, planner implementation, SDK and local MCP server process. MCP `user_request` is caller supplied. Another local MCP client can send different context; neither stdio, the request hash nor a matching response tool name proves authentic user intent. Arbitrary malicious Python installed in the trusted process is outside this boundary. Stronger caller authentication or a sandbox is not available or claimed.

## Discovery and execution

`MCPTransport` uses the initialized installed SDK session to list the existing four tools. It keeps only bounded names, descriptions, input/output schemas and descriptive annotations, with no opaque SDK metadata or capability. Unsupported names, missing/duplicate tools, pagination and unbounded metadata are rejected. Metadata schemas are independent copies.

The graph constrains proposals to the discovered tool names. Discovered schemas are retained as bounded metadata but are not dynamically passed into GranitePlanner. The unchanged `AgentModel.propose(request)` interface receives only the original request, and GranitePlanner continues to use its existing local registry schemas. Input validation remains in the existing MCP/Pydantic wrappers; the SDK validates declared output schemas, and the client independently validates the existing Envelope and returned tool identity. Discovery never issues authority.

Every invocation sends the original intake string plus the separate proposal through MCP. Actual FastMCP stdio dispatch enters the unchanged A1 wrappers and Gateway. The Gateway's private, single-use AuthorityEnvelope and exact ExecutionBinding still control backend dispatch. No LangGraph node imports a USAspending adapter or policy issuer. A1 policy outcomes and post-result validation remain unchanged.

## Distinct observations

| Layer | Observation | Meaning |
| --- | --- | --- |
| Orchestration | COMPLETED | A governed response was observed; it may be DENY, REVIEW_REQUIRED, or an execution error |
| Orchestration | Intake/discovery/planning rejection | No invocation fallback is dispatched |
| Transport | GOVERNED_RESPONSE | A schema-valid Gateway Envelope for the selected tool was received |
| Transport | MCP_TOOL_ERROR | A tool-layer error was received; generic dispatch state is UNKNOWN |
| Transport | TRANSPORT_TIMEOUT / PROTOCOL_ERROR | No authoritative Gateway response was obtained; dispatch is UNKNOWN and no retry is performed |
| Transport | INVALID_GATEWAY_RESPONSE | No invalid payload is promoted into a Gateway decision |
| Gateway | PERMIT / DENY / REVIEW_REQUIRED | Existing deterministic policy, separate from transport success |
| Gateway | Dispatch, verification, provenance and audit | Preserved from the original Envelope/trace without turning success into verified evidence |

MCP unknown-tool, extra-field and invalid-schema rejections can occur before Gateway and have no Gateway audit event. Tests establish those specific cases using both trace absence and an independent synthetic backend ledger. Generic MCP errors cannot prove non-dispatch: a synthetic final-audit failure demonstrates an MCP error after an authorized backend call. A timed-out client similarly may lose a response while the server completes the read.

No bounded ingress audit change was necessary to distinguish these layers. Protocol rejections are not fabricated as Gateway policy events. This does not provide a durable server ingress audit for every malformed JSON-RPC message.

## Synthetic demo

Install the optional orchestration dependency or the development extra. The candidate is tested with MCP 1.30.0 and LangGraph 1.2.15. From this worktree:

```powershell
python -B scripts/demo_channel_a2.py
python -B scripts/demo_channel_a2.py --request "Execute payment for this award"
python -B scripts/demo_channel_a2.py --mode review
```

Use the isolated A2 interpreter or install this exact worktree with `python -m pip install -e ".[dev,orchestration]"`; an editable main-checkout installation is not this candidate. The demo explicitly starts `tests/mcp/a2_stdio_fixture.py` with a minimal environment plus the SDK's safe OS-variable defaults. Its tools use the existing fixture transport and deterministic judge. It never starts the production-configured server, reads production credentials or contacts a live API/model. Output includes the original request, visited nodes, transport observation, unchanged Gateway Envelope and local evidence paths. Each run uses a fresh evidence directory; an existing explicit `--output-dir` is rejected.

## Evidence and limits

Tests cover original-request preservation, proposal mutation, unknown tools, invalid schemas, authority claims, node-state forgery, ordering, concurrent contexts, DENY/REVIEW/PERMIT, A1 envelope replay, timeout, protocol errors and post-dispatch failures. Actual SDK tests use subprocess stdio/JSON-RPC, not only direct server method calls.

The final local run passed all 89 new A2 cases: 40 orchestration/adversarial, 26 actual stdio and 23 client cases. The complete-suite result is **570 PASS, 2 FAIL, 1 SKIP.** Two expected Pydantic serializer warnings came from intentionally invalid synthetic proposals. Ruff lint/format, strict source typing and dependency consistency passed. The demo independently showed all five nodes, exactly one fixture adapter entry, A1 binding verification and verified synthetic provenance. Independent source/assertion review found no material bypass in the tested trusted local-host scope.

The original two J3 freeze-identity FAIL findings remain historical compatibility findings: `test_versioned_manifest_equals_offline_plan` and `test_commit_binding_checks_manifest_bytes_and_required_parent` fail because the new source identities differ from the frozen historical plan. The frozen manifest, J3 validators and historical failure artifacts are unchanged. No scientific re-freeze, historical amendment, xfail or silent test exclusion is part of A2; the complete suite is not wholly green.

This is local synthetic verification, not production readiness, complete agentic governance, remote authentication, exactly-once execution or a sandbox. Existing A1 trusted-process, audit durability and bounded transport retry limitations remain. Metadata bounds apply after SDK parsing; hostile-server ingress memory protection is not established. Host cancellation may propagate without a durable orchestration receipt and never proves non-dispatch. LangSmith tracing is explicitly disabled for graph execution; no cloud checkpoint or LangSmith trace export is used. Only Windows/Python 3.13.7 was executed locally; Python 3.11/3.12 and other platforms remain unverified.

References for the reused APIs: [LangGraph graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) and [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). Actual dispatch and timeout behavior were inspected in the installed MCP 1.30.0 implementation and exercised independently through stdio.
