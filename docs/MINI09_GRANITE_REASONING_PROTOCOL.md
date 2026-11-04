# MINI09 — proposed Granite reasoning evaluation protocol

Status: `PREPARED_NOT_EXECUTED`. Real Granite inference remains unauthorized for this phase.

This protocol separates planner behavior, deterministic governance, execution observations and result validation. A synthetic planner can test the local wiring but cannot measure real Granite reasoning, accuracy or calibration. The [existing Granite benchmark](GRANITE_AGENT_BENCHMARK.md) records historical runs with their own identities and limitations; those results are not MINI09 trials and are not re-scored here.

## Study attribution and preregistration gap

The task refers to a “Manatuabón reasoning study.” No identifiable study text, citation, methodology or artifact was found in the inspected repository documentation, evaluation files or README. `MANATUABON_METHOD_ATTRIBUTION: NOT_VERIFIED`. This is a provisional CIVICGATE protocol, not a verified replication of that study. Obtain the exact study/reference and document any methodological changes before making an attribution or replication claim.

The candidate temperatures supplied by the task are `0.0`, `0.05`, `0.25` and `1.0`. Their inclusion does not establish that an unverified model/runtime supports or applies them. Before a future run, freeze the exact effective model, weights/quantization hash, runtime/provider version, device/context limits, supported sampling parameters, seed behavior, prompt and tool-schema bytes, parser, deadline and attempt limits. Unknown effective settings block a comparable trial.

## Future authorization gate

Independent model/runtime verification, a finite run plan, approved input set, network boundaries and explicit human execution authorization are required. No live provider, credentials, token acquisition, inference or paid API request is initiated by this protocol. Existing EVAL-002 and monetary HOLDs remain unchanged.

Use DATA-01 fictional public-award records and reviewed benchmark cases only. Preserve the immutable dataset and case/reference digests before and after every run. Never access the reserved historical holdout. Any new research test split must have distinct identities and a documented author-exposure status; it is not the preserved holdout and not an independent golden reference by declaration.

## Controlled comparison

Use the same request bytes, bounded discovery metadata, tool schemas, planner prompt, output-token ceiling and strict parsing for each approved temperature. Predeclare repetitions, run ordering and seed policy before collection. If a runtime lacks a supported control, label that cell NOT_TESTED or not comparable; do not substitute another model or sampling setting silently.

Keep the Judge configuration fixed and label its actual identity. For the first authorized planner-only comparison, a deterministic synthetic Judge is a controlled test condition, not a measured Luna/Claude judgment. A separate real-Judge study would need its own authorization, identities, references and budgets. A permissive Judge must never convert deterministic DENY/REVIEW_REQUIRED into execution authority.

Record the immutable original request separately from the raw and typed planner proposal, validated effective arguments, discovery result, initial/final policy decisions, binding issuance/consumption, actual adapter/HTTP attempts, output verification, custody acknowledgement and final durable state. Provider response, parsed proposal and accepted result remain distinct. Timeouts, malformed output, uncertain delivery and missing telemetry are observations, not discarded trials.

## Metrics and denominators

| Dimension | Proposed measurement and guardrail |
| --- | --- |
| Grounding | Exact dataset identifiers/fields supported by the independent deterministic reference; unsupported facts and invented records counted explicitly |
| Tool selection | Correct tool / cases with a defined executable tool reference; report unsupported/clarification cases separately |
| Arguments | Exact schema-normalized effective argument agreement and individual filter correctness; no partial scope earns full credit |
| Query results | Exact expected set, required page/order/bounds and empty-result behavior on actually executed supported cases |
| Corrections | On separately defined correction trials, distinguish planner self-correction, explicit user clarification and evaluator intervention; preserve the original error |
| Uncertainty | Appropriate non-execution/clarification on underspecified, contradictory and unrepresentable scope; incorrect confident proposals remain failures even if Gateway blocks |
| Repeat consistency | Distinct typed proposal/result signatures within the same frozen condition; missing or invalid repetitions are counted, not removed |
| Governance | Initial and final PERMIT/DENY/REVIEW_REQUIRED agreement, binding issuance/consumption, unauthorized dispatch prevention and result withholding assessed separately |
| Telemetry | Observed latency and token usage with missing/unknown counts; do not infer cost or zero usage from absent metadata |

Report numerator, denominator, excluded/block reason and missing count for every rate. A contract-blocked FAA query is not an executed correct-answer case. A Gateway denial does not repair a wrong planner tool or argument. Do not combine repeated runs into independent semantic samples, aggregate overlapping test selections or infer confidence calibration from the configured threshold `0.85`.

Use paired per-case descriptive comparisons across temperatures and preserve invalid/timeout/uncertain outcomes. The small author-known synthetic corpus does not establish population accuracy, superiority, causal effects of temperature across different runtimes, or a production safety guarantee. Independent human references and sufficient separate data would be needed before inferential or calibration claims.

## Proposed trial record and evidence

Before the first future trial, declare a run ID, case IDs, condition ordering, repetitions and maximum total attempts. Each observation needs its own identity and immutable linkage to model/configuration/prompt/schema/dataset/reference digests. Record actual attempted sends and distinguish reserved, sent, responded, parsed, accepted and unknown states. Do not retry unknown outcomes or silently refund their reservations.

Preserve stdout/stderr, commands, environment identities, raw/typed sanitized outputs, trace and backend evidence, SQLite custody observations, failures and a SHA-256 inventory. Prompt/output captures must be screened for private content before publication. Documentary CLOSED describes custody and is not human acceptance. Reviewers should be able to recompute deterministic READ references without invoking any model.

No repetition count, sample-size adequacy or monetary ceiling is invented here. Those are explicit unresolved inputs for the future preregistration and authorization, alongside the exact Manatuabón source.

## Retained states

`GRANITE_EFFECTIVE_IDENTITY: UNKNOWN`; `LUNA_EFFECTIVE_IDENTITY: UNKNOWN`; `LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED`; `EVAL002_EXECUTION_AUTHORIZATION: HOLD`; `MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED`; `INDEPENDENT_GOLDEN_REFERENCE_ACCEPTANCE: PENDING`; `JUDGE_CALIBRATION: NOT_YET_MEASURED`; `P2_02_DURABLE_STOP: PARTIAL`; `HOLDOUT: RESERVED_UNEXECUTED_NOT_ADJUDICATED`; `FAA_FULL_CONTRACT: BLOCKED`.

The 54 historical FAA full-contract definitions remain BLOCKED/SKIP. This document authorizes no execution or implementation.
