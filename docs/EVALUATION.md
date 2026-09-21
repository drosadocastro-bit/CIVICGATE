# Evaluation

The committed artifacts report observations from this CivicGate build, not production assurance. `scripts/evaluate.py` replays explicit synthetic fixtures and writes component metrics to `artifacts/evaluation.json`. `pytest` adds independent policy, adapter, audit, adversarial and real MCP protocol checks. Live public API observations are in `artifacts/live-smoke.json` and are not included in synthetic success rates.

## Method

Each fixture records request, proposed tool, arguments, expected disposition/status, observed envelope, semantic availability, K signals and elapsed time. Case matches are functional expectations, not an aggregate safety score. Invalid inputs are included intentionally; schema validity reports the submitted population rather than pretending every input should pass. Well-formedness means envelope validation, not factual truth.

Metrics are separate: tool selection, schema validity, valid request success, provenance completeness, out-of-scope denial, ambiguity escalation, deterministic consistency, malformed-response containment, judge agreement, K detection, latency and response well-formedness. Each ratio includes numerator, denominator and scope. Mock tool selection is measured only on the three prescribed demo prompts. Judge agreement with an independent semantic reference is **not measured**, because no real model is configured. No synthetic result is presented as real-model accuracy.

Unavailable or invalid judge outputs remain failures. If execution is blocked, the component outcome is `SEMANTIC_FAILURE / GOVERNANCE_HELD`. Lexical and mock classifiers share implementation assumptions; they are not independent raters. Contradictory-signal tests deliberately make the judge permissive to verify non-overridable denial.

## Coverage

- Valid recipient/date, agency/location, known award and bounded aggregate.
- Nonexistent award, empty result, ambiguous recipient and broad query.
- Invalid/reversed/overlong dates, excessive limit, extra authority fields, path injection.
- Malformed source schema, invalid JSON, HTML, oversized response, timeout, network/HTTP failure, identifier mismatch and conflicting rows.
- Private records, governmental decisions, unknown/hidden tools, bypass, repeated denial.
- Missing provenance, unavailable/invalid judge, low confidence, consequential interpretation, Agent K conflict and contradictory judge/policy.
- Audit ordering/redaction/storage failure and agent import boundaries.
- MCP initialize/list/call, four output schemas, missing judge fail-closed, invalid and unknown calls.

## Evidence limits

Offline tests exercise HTTP through explicit mock transports. They do not measure API uptime. Latencies in evaluation.json are fixture execution, not real service benchmarks. The live smoke verifies three API contracts with a small sample on one date; it is not a load test or proof of long-term stability. API data can change, so hashes and record counts are timestamped observations.

Local Python version and platform are recorded in the report. The Windows/Ubuntu Python 3.11/3.12 CI matrix is defined but cannot be marked passed before actual GitHub execution. Docker runtime status is recorded in BUILD_REPORT.md. Dependency audit is a point-in-time advisory lookup; CivicGate itself is a local unpublished package and is skipped by the package database.

Before broader use, independently label diverse natural-language prompts, evaluate the configured agent and judge, measure live latency/error distributions, validate recipient identity workflows, and exercise the CI/container matrix. Do not expand domains or add write capability as part of that validation.

Milestone 2 adds [the Granite benchmark](GRANITE_AGENT_BENCHMARK.md), [judge benchmark](JUDGE_BENCHMARK.md), [hybrid matrix](HYBRID_EVALUATION.md), and [adversarial expansion](ADVERSARIAL_EVALUATION_M2.md). Their JSON artifacts deliberately retain `NOT_RUN_*` and `BLOCKED_*` states when exact live conditions or credentials are absent.

## Open design finding: literal NONE flag

Status: **OPEN_DESIGN_FINDING**. In the recorded-signal replay, an available `JudgeSignal` with `classification="IN_SCOPE"`, `confidence=0.96` and `flags=["NONE"]` was review-relevant. Policy currently tests whether the flag list is non-empty, rather than whether it contains a substantive risk flag. The observed reference-to-replay effect was `PERMIT` → `REVIEW_REQUIRED / BLOCKED` before adapter execution.

This is historical integration behavior, **preserved, not corrected**. A dedicated characterization test records the current result without endorsing it. It does not establish that the desired future result should be `PERMIT`, and is not classified here as a security vulnerability. Design review is required before any semantic change; historical J2 evidence must not be rewritten.

See [offline recorded-signal replay](J2_SIGNAL_REPLAY.md) for the input contract, bounded historical summary and research method. The replay provider remains evaluation-only; policy, Agent K and Gateway production semantics are unchanged.
