# Offline recorded-signal replay

Research question: **Given a previously recorded semantic signal, what does CivicGate's deterministic Gateway do with it?**

CivicGate treats model judgment as replayable evidence rather than authority. The evaluation-only [replay instrument](../scripts/replay_recorded_judge_signals.py) introduces a stored typed signal into the real Gateway without calling the model again. Each case receives fresh session state, deterministic policy, Agent K and an explicit synthetic adapter. No production provider configuration, credential access or DPAPI dependency is added.

## Reproduce an offline replay

Activate the repository's virtual environment. Save a reviewed input outside the repository, then run from the repository root:

```console
python scripts/replay_recorded_judge_signals.py --input ../reviewed-signals.json --output ../new-replay-result.json
```

Both paths must resolve outside the repository. The output must not already exist. The input is limited to 200 KB and 100 uniquely identified cases. This small example is **synthetic**, not a historical Luna observation:

```json
{
  "schema_version": "civicgate.recorded-signals.v1",
  "cases": [{
    "id": "synthetic-example",
    "request": "Find public awards in Puerto Rico.",
    "proposal": {
      "tool": "find_federal_awards",
      "arguments": {
        "start_date": "2025-01-01",
        "end_date": "2025-02-01",
        "state_code": "PR"
      }
    },
    "signal": {
      "classification": "IN_SCOPE",
      "confidence": 0.96,
      "flags": [],
      "available": true,
      "provider": "synthetic-example"
    }
  }]
}
```

All five signal fields are required and preserved literally. Extra signal fields, including rationale or provider request metadata, are rejected. Do not include credentials, raw responses or sensitive text in the reviewed input. Native `JudgeSignal` defaults complete the internal type; its rationale default is not reconstructed model content and is excluded from output.

Optional case fields:

- `transport`: `default`, `malformed`, `five_hundred_then_success` or `timeout_then_changed_snapshot`. Only existing mock transports are selectable; no endpoint is accepted. Stateful factories start fresh for each case.
- `expect_preflight_deny`: additionally require judge participation to be skipped. Known unknown-tool, invalid-input and text-tripwire cases are guarded automatically. The real Gateway still decides authorization.
- `reference`: a reviewed `DETERMINISTIC_ENGINEERING_REFERENCE_LANE` observation. Required fields are `decision`, `status`, `policy_reasons` and `adapter_initiated`. Optional fields are `judge_consulted`, `agent_k`, `dispatch_state`, `response_state`, `verification_state` and `next_action`. Missing reference evidence is never invented; absent references or insufficient post-dispatch state yield `NOT_COMPARABLE`.

The tool reports the exact recorded signal, consumed signal summary, policy reasons, Agent K observations, pre-dispatch policy, final states and explicit provider/adapter/transport counters. Input and source hashes identify the execution conditions. Raw provider bodies, rationale and generated request IDs are not recorded. A stopped run retains completed rows, marks uncompleted cases and does not continue through a fallback. Counters are explicitly scoped to completed cases.

## Method and historical result

The completed local J2 replay used **14 offline replays**: seven primary potential-difference cases, three variability observations and four controls. It compared actual offline Gateway behavior with a preserved synthetic engineering reference; it did not resample Luna or replace the original 35-case benchmark results.

| Observed direction | Count |
| --- | ---: |
| Contractive | 10 |
| Neutral | 4 |
| Expansive | 0 |

There were zero external calls and zero adapter initiations in the J2 replay lanes. All **7/7** static potential differences became observed execution-boundary differences: five changed final `PERMIT` to `REVIEW_REQUIRED`; two retained final review but moved it before candidate retrieval. Three denial controls skipped semantic participation entirely.

The taxonomy distinguishes contraction/expansion before dispatch, post-dispatch differences, timing differences with the same final authority, caution-only differences, no difference and non-comparability. Removing adapter permission is contractive even when final review is unchanged. **Contractive does not mean correct or safe.** These selected cases do not supply population rates or an aggregate safety score.

Under these tested conditions, deterministic authority retained ownership, while probabilistic semantic inputs changed review posture and execution boundaries in selected replay cases. No tested recorded semantic signal created new execution authority.

The three variability observations all remained review-blocked. Their reasons and Agent K observations differed, but their final decision and dispatch did not. The exact `IN_SCOPE`, confidence `0.96`, `flags=["NONE"]` representation was review-relevant under the current policy. This is an [open design finding](EVALUATION.md#open-design-finding-literal-none-flag), preserved rather than corrected.

Historical per-case signals, source artifacts, freeze/checkpoint records and private provider metadata remain outside Git. This public tool is derived from that local instrument, with portable reviewed inputs and synthetic regression fixtures. No historical evidence is embedded in its tests. The experiment does not establish semantic correctness, general safety or production readiness.

## Distinctive workflow

```text
probabilistic judgment
        ↓
typed semantic signal
        ↓
deterministic authority
        ↓
PERMIT / DENY / REVIEW_REQUIRED
        ↓
bounded execution (only when permitted)
        ↓
replayable evidence
```

Recorded semantic signals can be reintroduced offline into the deterministic Gateway to measure their effect on review and execution boundaries without resampling the model. This is **a distinctive workflow implemented and evaluated in CivicGate**, not a claim of industry uniqueness or superiority.

Project/design language, not experimental evidence: **Capability does not create authority.**
