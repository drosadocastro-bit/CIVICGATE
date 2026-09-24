# GPT-6 Luna judge profile: review checkpoint

Status: **GPT6_LUNA_PROFILE_READY_FOR_HUMAN_REVIEW**.

Experiment: `CIVICGATE-J4-GPT6-LUNA-001`. Profile: `j4-gpt6-luna`.
Model: `gpt-6-luna`. Role: semantic judge, advisory only. Authority: **NONE**.
No live experiment has run. No result document or judge selection is implied.

## Historical anchor and artifact identity

Required and verified starting HEAD: `254c8b95ffb2d6eed4aceddd5b203d5be6f855c8`,
branch `codex/dpapi-selective-access`. Historical GPT-5.6 run evidence, its
sanitized publication, human adjudication v1, fixtures, semantic contract and
existing J3 manifests are unchanged. No Sonnet outputs were inspected or used.

| Checkpoint | Identity / state |
| --- | --- |
| F0 baseline publication HEAD | `254c8b95ffb2d6eed4aceddd5b203d5be6f855c8` |
| F1 GPT6_INSTRUMENT_COMMIT_SHA | Pending human authorization; no commit created |
| F2 SEMANTIC_CONTRACT_SHA256 | `166b69f0682198a8d5f872aef5d8f5367293e209d8c2ee185719175723ac77f3` |
| F2 FIXTURE_SHA256 | `28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc` |
| F2 SOURCE_HUMAN_ADJUDICATION_SHA256 | `43daa0bbfe50be610155a20e1c67493f4691bd1b6d869cce2573a9e70225fb58` |
| F3 HUMAN_REFERENCE_V1_SHA256 | `b0049ccc6ab1fc124586ee4e0b50afc219cfb363f4f93d1d96dd7ddfdb1b4279` |
| F4 PROFILE_SHA256 | `7b1af2255f399550d37fb735e5aaf2d2e0ca3b669f22f31b41535a34a946fb8e` |
| F5 PAYLOAD_CONTRACT_SHA256 | `2fbf5cefb4fdac6058355f3cb0b02fe415f216cad305957b7d7e61c33a7992a8` |
| Proposed draft freeze raw SHA256 | `3bd74b755bbef53dde80876c15d8a43c917aa20375adf79a84f74f775dafb7df` |
| F6 optimizer / instrument parity | PASS in all five modes below |

New JSON hashes are SHA-256 of exact file bytes. The historical fixture and
source dependency hashes retain the established CRLF-to-LF convention. The
semantic contract is the UTF-8 prompt plus sorted wire-schema serialization.
No artifact embeds its own hash.

Artifacts:

- [Model-neutral human reference](JUDGE_HUMAN_SEMANTIC_REFERENCE_V1.json)
- [Declared profile](J4_GPT6_LUNA_PROFILE.json)
- [Payload contract](J4_GPT6_LUNA_PAYLOAD_CONTRACT.json)
- [Draft pre-execution freeze](J4_GPT6_LUNA_FREEZE_DRAFT.json)

The draft includes the 44-entry schedule, each payload hash and the instrument
dependency hashes. Its `execution_head` is null, with
`TBD_AFTER_AUTHORIZED_COMMIT`, and its authorization is `NOT_AUTHORIZED`.
The draft hash identifies these proposed bytes only. Binding a later authorized
commit necessarily produces a different final freeze hash requiring review.
This draft cannot be used as authorization or as an executable live seal.

## Method and comparison boundary

**Fixture intent is not model evidence.**

Only the request, proposed tool and proposed arguments enter the case-specific
judge message. The existing `Proposal.model_dump()` shape and sorted JSON are
preserved exactly. No backend/adapter state, transport history, prior denials,
session state, fixture expectations, model outcomes, human labels, dispositions,
explanations or severity labels are added to the judge input.

The neutral reference is a mechanical projection of the published adjudication:
27 ordered records containing only ID, human classification and human flags,
plus eight excluded IDs marked NOT_EVALUABLE. There is no new adjudication.
Source commit and exact source-adjudication hash establish provenance. The
source's prohibited-information list is retained. Model-specific dispositions,
severity and reasons are excluded from comparison targets.

Comparison classification:
`CONTROLLED_SEMANTIC_TASK_COMPARISON_WITH_MODEL_SPECIFIC_INFERENCE_PROFILE`.
This is not identical inference, accuracy certification, a ranking, a winner
test or a replacement for deterministic authority. The original 12/35
engineering-reference agreement remains distinct from accuracy. Any future
comparison must evaluate both models against this same neutral reference.

Preregistered non-directional hypothesis:

> CIVICGATE-J4-GPT6-LUNA-001 evaluates whether GPT-6 Luna, under a frozen model-specific inference profile, exhibits materially different semantic boundary detection and repeat stability from GPT-5.6 Luna when given the same judge-observable task family and evaluated against the same independently frozen human semantic reference.

## Provider documentation gate

Official documentation checked on 2026-09-23:

- [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna):
  Chat Completions and medium reasoning are supported. The function-calling
  restriction for reasoning in Chat Completions does not apply to this tool-free payload.
- [Model migration guidance](https://developers.openai.com/api/docs/guides/latest-model):
  non-none reasoning excludes temperature, top_p and log-probability controls.
- [Chat Completions request reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  max_completion_tokens bounds output including reasoning; json_object selects JSON mode.

No official-documentation contradiction was found. This is documentation and
offline compatibility evidence, not proof of account/model access or live success.
JSON Schema / Structured Outputs remains deliberately disabled: changing to
provider-enforced schema would change the property being measured and requires
a separate experiment identity. No inference parameter was tuned from outcomes.

## Declared profiles and compatibility

`OpenAIJudgeProfile` selects inference parameters by explicit profile ID.
GPT-6 uses medium reasoning, 512 max_completion_tokens and json_object;
all twelve fields forbidden by the payload contract are absent, not null.
GPT-5.6's `j2-luna` profile omits reasoning_effort, max_tokens, temperature and
top_p. Generic OpenAI-compatible and Anthropic behavior remains separate.
Granite planner payload construction is unchanged.

The benchmark call sites now explicitly select `j2-luna`. Direct application
configuration can select `CIVICGATE_JUDGE_PROFILE`; applications using the Luna
profile must set it explicitly. An omitted profile selects `generic-openai`,
not a model-name-derived Luna profile. Unknown profile IDs fail closed, and
named OpenAI profiles reject mismatched model, endpoint or protocol.

Before edits, the actual GPT-5.6 adapter's 35 primary payloads were captured
through MockTransport. After refactoring, all 35 match canonically, including
prompt, schema and proposal serialization. The fixed canonical list hash is
`99e262669f7afee75de65b978adb2bc5a21aca984d5014fb6e04c4de365569fa`.
The repeated observations reuse the same fixture inputs and payload constructor.

The historical J3 manifests remain unchanged and correctly reject the modified
instrument checkout. Their unit tests now distinguish historical comparison
logic, using explicit synthetic frozen hash-reader inputs, from real-file hash
reading and rejection of the current J4 checkout. Positive controls precede
tamper tests. Historical acceptance is not claimed for this new source tree.

## Request and response boundaries

The new preparation CLI exposes no live execution mode. Its observation harness
requires MockTransport and synthetic credentials. It reuses the J3 observation
loop and failure taxonomy, with an explicit J4 transport/profile binding.
No Gateway or credential-store entry point is called.

For each prospective request, SHA-256 covers the exact decoded outbound JSON,
serialized with sorted keys, compact separators, ASCII escapes and finite
numbers only. Headers and credentials are excluded. START binds experiment,
sequence, fixture, phase, requested model, profile, timestamp and payload hash.
The persistence callback must complete before arming; transport checks the
actual payload hash before dispatch. Failed START persistence sends nothing.

The schedule is 35 primary plus nine repeats, maximum 44 requests, with zero
retries. Both the ordinal gate and transport cap reject request 45. Fatal
failure ends the observation loop without continuation, fallback or repair.

Successful responses require exact safely observable returned-model identity,
one usable assistant text payload, supported completion, valid JSON and the
unchanged strict wire validator. Identity mismatch and absent identity retain
their distinct fatal codes. Truncation, refusal, malformed JSON and wire-invalid
JSON remain distinct; no partial fields become accepted assessments.

Optional system_fingerprint and service_tier are added only to J4 telemetry;
unavailable fields stay null. Existing request ID, finish state, token usage,
reasoning-token and latency observations remain available. Reasoning text and
authorization headers are not published.

## Validation and limits

- JSON parsing, exact reference projection, 27/8 inventory and disjoint IDs: PASS.
- Frozen semantic, fixture and source-adjudication hashes: PASS.
- GPT-5.6 pre/post payload equivalence: PASS.
- GPT-6 exact payload fields, JSON mode and medium reasoning: PASS.
- Optimizer matrix: normal, -O, -OO, PYTHONOPTIMIZE=1 and PYTHONOPTIMIZE=2: PASS.
- Prompt/schema, profile, payloads and reference remain identical across those modes.
- Relevant guarded tests: **296 passed, 1 skipped, 5 deselected**.
- The skip is the non-Windows contract test on Windows.
- Ruff: PASS. Format: PASS. mypy: PASS (34 source files).
- Git diff whitespace checks and new-file whitespace checks: PASS.
- Provider calls: **0**. Gateway executions: **0**. Live credential use: **0**.

Five historical tests are excluded because they execute Gateway, directly or
through the old benchmark preflight:

1. test_gateway_preflight_counts_zero_judge_and_adapter_calls
2. test_real_provider_offline_44_calls_profile_contract_and_all_telemetry
3. test_repeated_http_failures_stop_without_retries_and_preserve_partial_rows
4. test_authentication_failure_stops_on_first_call
5. test_failure_telemetry_is_included_and_does_not_leak_to_next_call

An earlier expanded pass omitted only the first and attempted the other four.
The external guard blocked all four before Gateway execution. That failed test
record is preserved; the final permitted selection completed without boundary
attempts. The full suite, evaluate.py, M2 benchmarks and container smoke were
not run because their Gateway execution violates this task's boundary. No CI
configuration was weakened or changed.

## Proposed diff and review gate

New files:

- docs/JUDGE_HUMAN_SEMANTIC_REFERENCE_V1.json
- docs/J4_GPT6_LUNA_PROFILE.json
- docs/J4_GPT6_LUNA_PAYLOAD_CONTRACT.json
- docs/J4_GPT6_LUNA_FREEZE_DRAFT.json
- docs/J4_GPT6_LUNA_READINESS.md
- src/civicgate/llm/judge_profiles.py
- scripts/prepare_j4_gpt6_luna.py
- tests/unit/test_j4_gpt6_luna.py

Modified files:

- src/civicgate/llm/live.py
- src/civicgate/runtime_config.py
- src/civicgate/config.py
- scripts/run_j3_experiment.py
- scripts/run_profiled_judge_benchmark.py
- scripts/run_live_judge_benchmark.py
- scripts/run_live_model_evaluation.py
- tests/unit/test_live_providers.py
- tests/unit/test_live_judge_benchmark.py
- tests/unit/test_j3_readiness.py
- tests/unit/test_j3_experiment.py
- tests/unit/test_j3_optimizer_stability.py
- tests/unit/test_j3_credential_amendment.py

No staging, commit, push or merge was performed. F1 remains pending. The current
state prepares the profile and draft freeze for human review; it does not enter
AUTHORIZED_ONCE. Publication and a final execution-head-bound freeze need human
authorization. A future live invocation needs its own explicit authorization.
