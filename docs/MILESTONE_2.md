# CivicGate Milestone 2

Milestone 2 adds a real local planning path, external semantic-judge adapters, reproducible benchmark contracts, Agent K v1 integration, and a four-cell hybrid evaluation. The deterministic policy gate still issues every final decision. The agent can propose only registered public-spending tools; neither model output nor judge output can authorize execution.

The implementation is additive to the tagged `milestone-1-baseline`. The reference PRAETOR checkout was read-only context. Its historical results, hashes, freeze claims and evaluator outcomes are not evidence for CivicGate.

## Current disposition

The repository contains credential-free deterministic artifacts and opt-in live adapters. The checked-in M2 artifacts classify Granite as `MODEL_REQUIRES_REVIEW`, judges J2/J3 as unavailable without external credentials, and the overall build as `MILESTONE_2_VALIDATED_WITH_LIMITATIONS`. This is a bounded engineering status, not a safety score or production-readiness claim.

The allowed demonstrated behavior is: **“CivicGate demonstrated live-model planning and semantic review while preserving deterministic execution authority under the tested conditions.”** A live endpoint must be configured and its exact conditions frozen before changing that disposition.

## Run

```powershell
.\.venv\Scripts\python -m civicgate.evaluation.benchmarks
.\.venv\Scripts\python scripts\run_m2_benchmarks.py
.\.venv\Scripts\civicgate-trace audit/demo.jsonl --html audit/demo.html
```

The normal test and CI path never calls a model provider. Live evaluation is a manual, opt-in workflow and must receive credentials from GitHub secrets or an operator's external secret provider.

## Gates

- configuration is provider-injected; `.env` files are never authoritative;
- Windows DPAPI is an edge provider only and is not imported by governance;
- Granite proposals and judge signals are strict Pydantic values;
- Agent K can contain or require review, but cannot grant permission;
- matrices A, B, C and D all finish through deterministic policy;
- API traffic, credentials and model responses remain ignored unless a reviewed artifact explicitly records sanitized evidence.

Stop here before Milestone 3. Do not add writes, private data, governmental decisions, autonomous approval, or broader endpoint access as part of this milestone.
