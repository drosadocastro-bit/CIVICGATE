# J3 multi-provider offline readiness

Baseline: `a8bbb28aaf058395f5f9f99f81feccdfe28aadc1`, branch `main`.
This update implements the approved provider plumbing offline. It is not live
interoperability evidence, a benchmark result, or authorization to run J3.
Status: **J3_MULTI_PROVIDER_OFFLINE_READY** for the tested offline scope only.

## Resolved offline

### Explicit credential routing

The configured provider determines protocol, endpoint, model and secret selection.
Credential contents never select a provider. `RuntimeSettings` and the pinned J2
runner share the following routing:

| Judge provider | Protocol | Base URL | Model for this experiment | Judge secret precedence |
| --- | --- | --- | --- | --- |
| `openai_compatible` | `openai_compatible` | `https://api.openai.com/v1` | `gpt-5.6-luna` | `CIVICGATE_OPENAI_JUDGE_API_KEY`, then `CIVICGATE_JUDGE_API_KEY`, then existing legacy `CIVICGATE_MODEL_API_KEY` |
| `anthropic` | `anthropic_messages` | `https://api.anthropic.com` | `claude-sonnet-5` | `CIVICGATE_ANTHROPIC_JUDGE_API_KEY` only |

Anthropic without its specific secret raises `ConfigurationError` before provider
construction. An OpenAI key or generic key cannot satisfy it. Conversely, an
Anthropic key does not satisfy OpenAI. Tests use in-memory synthetic providers;
no real DPAPI values are read for this work.

Explicit Anthropic configuration cannot inherit a legacy URL, switch to the OpenAI
protocol/origin, or be overwritten by `CIVICGATE_PROVIDER=openai_compatible`.
Such contradictions fail closed. Anthropic runtime configuration is direct-only:
the root URL is required, with optional trailing slash, and `/v1` is rejected to
prevent `/v1/v1/messages`. Custom Anthropic proxies require a separate reviewed
configuration design. Existing valid OpenAI-compatible routes remain supported;
an Anthropic origin or protocol cannot be used with OpenAI credential routing.

The secret store implementation is unchanged. Its interactive `set` command already
supports both names without putting values on the command line:

```powershell
.\.venv\Scripts\python.exe scripts/dpapi_secret.py set CIVICGATE_OPENAI_JUDGE_API_KEY
.\.venv\Scripts\python.exe scripts/dpapi_secret.py set CIVICGATE_ANTHROPIC_JUDGE_API_KEY
```

These are manual storage instructions, not commands executed by this task. No key
was migrated, overwritten or deleted. Use the existing external Windows-user DPAPI
store as the explicitly supplied `SecretProvider`; setting non-secret environment
configuration does not make the default environment secret provider read DPAPI.
For example, `config.providers(configuration, WindowsDPAPIStore(default_store_path()))`
constructs providers using that store. Model calls still require separate authorization.
The local CLI's existing `check` command exposes a masked prefix/suffix; it was neither
used nor modified here. Use `set`, not that preview, for the intended storage workflow.

### Exact Sonnet 5 request profile

Only `anthropic_messages` + `https://api.anthropic.com` + `claude-sonnet-5` selects
the compatibility profile. The payload contains exactly `model`, `max_tokens=512`,
`system`, and `messages`. Sampling fields (`temperature`, `top_p`, `top_k`) are
absent, not null. No thinking configuration, effort, output repair, fallback model,
or parameter-change retry was added. The first future smoke retains 512 tokens.

The system prompt, wire schema, taxonomy and serialized request/proposal are the
same as J2. The provider syntax differs, not the semantic instructions. Luna still
sends `max_completion_tokens=512`, JSON response format and its unchanged messages;
it sends no `max_tokens`, sampling or reasoning-effort fields. Other OpenAI-compatible
profiles retain their parameters. Other Anthropic model/route profiles retain their
existing sampling and stop behavior; they do not inherit the Sonnet-specific changes.

The model ID and route were established during the preceding documentation review:
[Sonnet migration guide](https://platform.claude.com/docs/en/models/sonnet-5/migration-guide)
and [API overview](https://platform.claude.com/docs/en/api/overview). No provider-documentation
or model-discovery network calls were made in this offline implementation pass.

### Content extraction and strict completion

Anthropic extraction validates a list of object blocks, visits them in order and
selects only `type="text"`. It never reads, parses, records or exposes the payloads
of thinking/reasoning blocks. Exactly one nonempty string text block is required.
Missing text, malformed blocks and multiple text blocks produce
`MALFORMED_PROVIDER_RESPONSE`. Multiple blocks are deliberately not concatenated:
no documented JSON assembly rule has been established for this contract. There is
no separator invention, fragment repair or selection of a favorable answer.

For the exact Sonnet profile, completion is checked before schema parsing:

| `stop_reason` | Result |
| --- | --- |
| `end_turn` | Eligible for strict wire parsing; not automatic success |
| `max_tokens` | `PROVIDER_RESPONSE_INCOMPLETE` |
| `refusal` | `PROVIDER_REFUSAL` |
| Missing, null or any other value | `MALFORMED_PROVIDER_RESPONSE` |

Classification and confidence remain mandatory. Invalid enum values, out-of-range
confidence, invalid flags and extra internal fields fail validation. `available` and
`provider` cannot be supplied by the model. A valid runtime Anthropic signal gets
`available=True` and `provider="anthropic"` internally. Literal `flags=["NONE"]`
is preserved; its **OPEN_DESIGN_FINDING** remains unfixed.

### Protocol-neutral observation

`observe_judge_response` in the existing benchmark module accepts an explicit protocol
and requested model. It exposes requested/returned models, HTTP status, sanitized request
ID, `finish_or_stop_reason`, content presence, JSON/schema validation and observed usage.
It retains distinct raw `finish_reason` and `stop_reason` fields, with the inapplicable
one null. Anthropic `end_turn` is not renamed to OpenAI `stop`.

`wire_validation` and `response_validation` are separate. Anthropic non-completion
fails response validation before wire parsing; `wire_validation=NOT_EVALUABLE` then
records that no schema assessment was attempted. OpenAI's existing schema observation
is preserved, while neutral response validity also requires its normal complete stop.
Returned model metadata cannot alter a signal or authority decision. Missing token
counts remain null; totals and reasoning usage are not estimated. Thinking, rationale,
raw responses, error messages, credentials and complete headers are not retained.

The J2 transport uses a compatibility projection of the neutral observer, retaining
its exact previous evidence keys, values and scoring inputs. It remains pinned to
Luna's endpoint and request guards. This task prepares J3 observation, not a selectable
44-call J3 runner or a new live freeze. Shared J2 credential routing adds the new
OpenAI-specific name while preserving both approved older names.

## Comparability and historical evidence

The 35 fixtures, their order, repeat/injection sets, shared prompt/schema, taxonomy,
status rules, scoring denominators and repeat-consistency rules are unchanged.
Disagreement-analysis and recorded-signal replay methods are unchanged. J2 historical
files remain immutable. The script and relevant source fingerprints necessarily change
with this implementation; this does not retroactively update the old freeze or certify
a future one. Prior readiness findings and packet artifacts remain preserved outside Git.

Policy, Agent K and Gateway authority code are unchanged. No fixture was relabeled.
Tests cover the credential boundary before construction, exact payload isolation,
thinking-first responses, strict wire errors, incomplete/refused results and neutral
observation. Green offline checks establish only those tested integration properties.

## Still pending

- Provisioning/confirming the actual Anthropic-specific DPAPI credential and account access.
- Explicit authorization and successful one-call live smoke, using the actual provider,
  zero automatic retries, the existing synthetic pattern and the unchanged 512-token limit.
- A separately reviewed J3 execution guard and live instrument freeze after that smoke.
- Separate authorization for the 44-call J3 benchmark.
- J3 disagreement analysis and recorded-signal replay based on actual J3 evidence.
- Independent human adjudication and approval of its proposed rubric before labeling.

No live smoke, full live benchmark, freeze, provider call or USAspending call was made.

## Preserved human-review packet

The existing local-only 35-case packet is preserved, not regenerated. It contains
exact requests/proposals, neutral case numbers, tool context and the proposed rubric.
It excludes J1/J2/J3 labels, model confidence/flags and expected fixture outcomes.
The organizer mapping remains separate. Danny remains exposed/unblinded because he
has seen J2; no independent reviewer or human labels were invented. Human tool context
is not added to the model prompt, and the two review conditions remain distinguished.

## Offline verification

- Provider-routing and Sonnet tests independently: **78 passed**.
- Full suite: **287 passed, 1 skipped** (non-Windows contract test on Windows).
- Ruff lint, format (85 files), strict mypy (33 source files), and diff-check: passed.
- Fixture evaluation: **35/35**; deterministic M2 benchmarks: passed.
- J2 method function bodies and original OpenAI observation logic are unchanged;
  historical prompt/schema, fixture bytes, schedule and scoring rules still match.
- Regenerated deterministic artifacts match after excluding runtime timestamps,
  generated request IDs and latency. Decisions, reasons, counts and disagreements match.
- Historical evidence, blinded packet and encrypted secret-store hashes are unchanged.

No files are staged, committed or pushed. The required checks regenerated the already
modified deterministic artifacts; unrelated local work remains preserved. There were
zero external calls, no secret-value reads and no live J3 execution in this pass.

## Versioned follow-up

The offline results above describe the preserved pre-smoke checkpoint. The first
subsequent authorized live call passed; see [the sanitized smoke record](J3_SONNET_SMOKE.md).
Commit `a5cdb8b12983c498ddf86a7425c62f03417bf029` preserves the exact six smoke files.
The next commit prepares [the J3 benchmark freeze](J3_BENCHMARK_FREEZE.md) and an explicit
profile runner. The historical packet and first observation remain unchanged. The
44-call live benchmark, disagreement analysis, replay and independent human adjudication
remain unperformed and require their respective authorization/review gates.
