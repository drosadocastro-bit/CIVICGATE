# Provider-Specific Configuration Under a Shared Experimental Contract

Status: prospective identity decision resolved; offline implementation for review.
No live execution or publication authorized.
Source baseline: `32b1760326c44972d526f38008173078582bbbf3`.

## KEY DECISION

“CivicGate freezes shared experimental semantics independently from provider-native transport configuration. Provider-specific parameters may differ when required by the external API, but those differences must be declared before execution and may not alter the semantic contract, fixture corpus, scoring, evidence rules, retry policy, or authority boundary.”

APIs expose different parameter names and semantics. Forcing byte-identical
payloads would create invalid requests; silently hiding differences would
overstate comparability. Explicit profiles preserve operational validity and
auditability: **same experiment != identical provider request payload**.

## Shared instrument and provider profiles

`scripts/run_j3_experiment.py` owns the shared execution loop, failure policy,
accounting, exclusive per-observation journals and future execution seals.
`SharedExperimentSpec` identifies the common invariants. Immutable provider
profiles reuse the exact versioned `Profile` definitions from
`run_profiled_judge_benchmark.py`; the `j2-luna` key identifies a transport
profile, not the legacy J2 execution protocol.

| Setting | AnthropicJudgeProfile (`j3-sonnet`) | OpenAIJudgeProfile (`j2-luna`) |
| --- | --- | --- |
| Model | `claude-sonnet-5` | `gpt-5.6-luna` |
| Protocol | `anthropic_messages` | `openai_compatible` |
| Endpoint | `https://api.anthropic.com/v1/messages` | `https://api.openai.com/v1/chat/completions` |
| Owned credential name | `CIVICGATE_ANTHROPIC_JUDGE_API_KEY` | `CIVICGATE_OPENAI_JUDGE_API_KEY` |
| Native token control | `max_tokens=512` | `max_completion_tokens=512` |
| Timeout | 30 seconds | 30 seconds |
| Sampling | Historical omissions preserved | `temperature`, `top_p`, `reasoning_effort` omitted |
| Response format | Historical Messages envelope | `response_format={"type":"json_object"}` |

OpenAI never sends `max_tokens`. Neither profile reads the generic
`CIVICGATE_JUDGE_API_KEY` or the other provider's binding. Any generic-key
behavior in production/demo paths is separate; there is no experimental alias.
Tests resolve ownership using a synthetic SecretProvider; no real credential
lookup is needed to plan or validate the instrument.

## Native observation and shared taxonomy

`scripts/judge_experiment_observers.py` implements bounded native observers.
Anthropic delegates structural observation to the unchanged J3-AMEND-001
observer. OpenAI retains its own native envelope, finish reason and usage,
then applies the same bounded structural wire evidence rules. It does not
construct a fictitious Anthropic response. Unknown fields stay null.

| Native observation | Completion state | Result category |
| --- | --- | --- |
| Anthropic `end_turn` / OpenAI `stop`, valid wire | COMPLETE | TYPED_VALID |
| Complete text, parseable JSON, invalid wire | COMPLETE | PARSEABLE_BUT_WIRE_INVALID |
| Complete text, malformed semantic JSON | COMPLETE | MALFORMED_SEMANTIC_JSON |
| Anthropic `max_tokens` / OpenAI `length` | INCOMPLETE | INCOMPLETE_MAX_TOKENS |
| Anthropic `refusal` / OpenAI nonempty `message.refusal` or `content_filter` | REFUSED | PROVIDER_REFUSAL |
| Other/missing native stop, missing content or incompatible envelope | UNKNOWN or COMPLETE with unusable content | RESPONSE_NOT_VALIDATED |

The length mapping is fixed before live observation. Length takes precedence
if accompanied by a refusal marker, matching the historical incomplete path.
Partial, refused or unknown-stop text is never semantically parsed. The existing
OpenAI production parser does not enforce completion itself; the experimental
transport gates completion before delivering the unchanged bytes to the real
LiveJudgeProvider. No production parser, prompt, schema or policy is changed.

Structural evidence includes parse state, wire state, bounded error locations
and type codes, rationale length, native stop, returned model and exposed usage.
At most 64 fields/errors are retained; overflow is a fatal evidence limitation.
Invalid rationale text, raw envelopes, hidden reasoning and provider error
messages are not retained. Individually valid fields of an invalid object keep
the historical EXPLORATORY / NON-AUTHORITATIVE / NOT A JUDGESIGNAL labels and
never enter canonical scoring. Existing wire coercions are preserved, with no
additional repair or post-hoc conversion.

Fatal categories remain FREEZE_OR_INSTRUMENT_MISMATCH,
REQUEST_BOUNDARY_VIOLATION, RETURNED_MODEL_MISMATCH,
CALL_ACCOUNTING_VIOLATION, EVIDENCE_WRITE_FAILURE, OBSERVER_EVIDENCE_FAILURE,
PROVIDER_HTTP_FAILURE, TRANSPORT_FAILURE, RESPONSE_SIZE_BOUND and
UNEXPECTED_INSTRUMENT_FAILURE. Any HTTP rejection or transport failure stops
the run without retry. Nonvalidated semantic observations advance once, even
after three consecutive failures. Fatality and semantic result are separate.

### KEY DECISION: prospective returned-model identity

“Requested model identity is configuration; returned model identity is evidence. Future provider-neutral J3 executions require the returned model identifier to be explicitly observable and equal to the frozen expected model. Missing identity is an observer-evidence failure; conflicting identity is a returned-model mismatch.”

This human-approved rule applies to both profiles and every future execution
of the provider-neutral runner. An explicitly observable expected ID permits
continued evaluation. A different safely extracted ID causes
RETURNED_MODEL_MISMATCH; an absent, null, structurally unavailable or unsafe
identifier causes OBSERVER_EVIDENCE_FAILURE. Neither case permits a subsequent
dispatch, retry, fallback or repair. Results are journaled before stopping.
Requested model, endpoint, profile, prior responses and surrounding metadata
cannot substitute for returned identity. Existing HTTP rejection, transport
and response-size failures retain their established fatal causes; the identity
rule does not invent an observed assessment when no usable response was received.

Historical J3-AMEND-001 allowed absent returned_model to remain unknown unless
an exposed model mismatch occurred. This stricter prospective rule is an
execution-instrument decision, not a reinterpretation of historical evidence.
Sonnet Run 002 observed `claude-sonnet-5` in all 44 provider responses. Its
recorded outcome would therefore be unchanged, but counterfactual equivalence
is not claimed for a hypothetical response with missing model identity.

“The provider-neutral runner is mechanically stricter than historical J3-AMEND-001 when returned-model metadata is absent. This prospective identity-evidence rule does not modify Sonnet Run 002, whose 44 responses all exposed the expected model identifier.”

The planned comparison remains PRACTICAL_PROVIDER_COMPATIBLE_JUDGE_COMPARISON.
No historical runner, manifest, report or forensic finding is retroactively amended.

## Evidence order and freeze boundary

The same 35 primary cases and 9 repeats run in the same order. Before dispatch,
an exclusive start journal contains run_id, sequence, id, phase, observation,
prior_http_count, expected_request_ordinal and utc_start. The runner verifies
`prior_http_count == sequence - 1` and
`expected_request_ordinal == prior_http_count + 1 == sequence`, then arms one
dispatch. The result must be persisted before the next start. At most 44 HTTP
requests can be dispatched. All retry layers use one attempt / zero retries.
An exclusive run-start marker prevents resuming a stopped run.

Future seals pin HEAD, canonical plans and raw dependency hashes, including
this decision record, both new modules and the tests. Sealing requires every
dependency to match its committed content. The current uncommitted draft is
not a live-execution baseline. No authorization arises from a passing offline
test or from creating an offline plan. A new human-authorized smoke and frozen
execution preflight remain separate work.

The direct runner calls only the real judge adapter and deterministic J1
reference for comparison. It never calls the legacy `_run` or `_preflight`,
Gateway, policy, Agent K, Protocol 66, tool dispatch or USAspending. Tests fail
on attempts to enter those boundaries. Imports of historical scoring helpers
are inert. The legacy scripts remain unchanged and describe historical J2
and J3 runs under their original execution rules.

## COMPARABILITY LIMITATION

“Provider-specific configurations limit strict model-to-model causal comparability.”

Anthropic Run 002 used `max_tokens=512`; the Luna profile uses
`max_completion_tokens=512`. Equal numbers do **not** establish equal visible
output budgets, reasoning-token allocations, internal inference behavior,
sampling behavior or token accounting. Provider default sampling, response
envelopes, stop/finish reasons, usage reporting, hidden reasoning
implementations and transport stacks may differ.

The comparison is **PRACTICAL_PROVIDER_COMPATIBLE_JUDGE_COMPARISON**,
not CONTROLLED_IDENTICAL_INFERENCE_COMPARISON.

The controlled variables are the semantic judge contract, `_JudgeSignalWire`,
fixtures, order, primary and repeat schedules, evidence contract, journal
semantics, retry count, failure handling, typed-validation rules, scoring,
comparison metrics, no repair, no Gateway execution and no downstream policy
authority. The prompt/schema contract hash remains
`166b69f0682198a8d5f872aef5d8f5367293e209d8c2ee185719175723ac77f3`;
the fixture hash remains
`28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc`.

Report component metrics: transport outcomes, parse/wire validity, native
completion, typed-assessment coverage, J1 agreement on valid primary cases,
injection-fixture classification, repeat stability, exposed usage and latency.
There is no winner score. J1 agreement is agreement with an engineering
reference, not human ground truth; schema validity does not prove semantic
correctness. Provider-native usage remains explicit, with unavailable values
null rather than inferred as zero or equated across providers.

## Historical scope and offline proof

Sonnet Run 002 (`j3-amend001-sonnet-20260921T160919667859Z`) and its evidence
remain immutable. These findings remain scoped exclusively to that run:

“Transport success did not imply contract-valid semantic output.”

“A completed governed execution can remain partially semantically unevaluable without compromising the integrity of the experiment.”

The new tests use synthetic responses only. They compare Anthropic structural
evidence, normalized results and canonical metrics against J3-AMEND-001, then
run identical mechanical cases for Luna. They do not replay or reproduce any
historical Sonnet semantic output. Fresh implementation evidence belongs in
its own external evidence directory, never in a historical experiment folder.
