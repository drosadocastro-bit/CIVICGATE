# Local governance checkpoint: offline evaluation

This publication contains only the explicit dependencies and tests for the local synthetic governance demonstration.
It preserves the versioned R3/R3.1/R3.2 implementations. It does not redistribute datasets, human adjudications, acceptance records, private captures, historical ZIPs or live-provider configuration.

## Reproduce

From the repository root in an existing verified development environment:

    python -B scripts/run_local_governance_demo.py --execute-synthetic

This executes MINI07.2's PERMIT, DENY and REVIEW_REQUIRED through actual LangGraph A2, MCP stdio, deterministic Gateway and synthetic backend.
The runner accepts only fixed offline selections. It creates a new pinned copy and private evidence outside the repository. Existing source pins are checked before execution.
No credential, provider URL, model or write-capability option exists.

Use --suite mini071, a2, r32, r32-ab, r32-terminal, budget or portability for the separately documented regression selections.
Use --evidence-root with an external directory if the default system temporary location is unsuitable. Overlap with the source repository fails closed.

## Evidence and limits

Each run preserves command/environment, stdout/stderr, JUnit, primary captures, SQLite data and a SHA-256 run manifest.
The public source manifest binds the exact checkpoint code; hashes establish identity, not human authentication or execution permission.
Actual graph history, original request and planner proposal, policy, binding consumption, backend observations and result validation remain separate.
Pre-close summary, returned close ACK and actual SQLite state must not be collapsed into one field. CLOSED means documentary custody.

The trusted runner writes a bounded private guard-config.json before dispatching pytest. Both the guard and restart helper require it and reject overlapping source/copy roots. The configuration is runtime data, not a new authority source.
Python/process guards are not OS isolation, power-loss certification or distributed exactly-once guarantees.

The full FAA contract remains BLOCKED; all 54 planned definitions remain BLOCKED/SKIP.
Live provider transport is NOT_AUTHORIZED. EVAL-002 and USAspending integration remain HOLD. P2-02 remains PARTIAL.
Real Granite/Luna identities and Judge calibration are unestablished. No holdout is included or accessed.

## Historical contracts

The included protocol files retain their historical statuses and claims. This checkpoint does not rewrite those records or transform private technical review into independent human/scientific acceptance.
See ../docs/GSA_LOCAL_DEMO_CHECKPOINT.md for the publication inventory, newly executed selections and remaining limitations.
