# J3-AMEND-001 — Full-corpus failure-tolerant observation

Status: **approved for versioning and future separately authorized execution**.
**J3 Run 002: NOT YET AUTHORIZED.** Live Anthropic execution requires separate
explicit human authorization. The version is the Git commit containing this
document and [J3_AMENDMENT_001.json](J3_AMENDMENT_001.json), without a self-embedded SHA.

**J3-AMEND-001 changes observation/completion behavior, not the judge semantic contract.**

## Parent and evidence basis

Parent freeze commit: `40efd42cbf0d7c2006e6b9312fb3490657e72268`.
The original manifest remains [J3_BENCHMARK_FREEZE.json](J3_BENCHMARK_FREEZE.json).

Historical Run 001, `j3-sonnet-20260921T115723065245Z`, remains
**J3_BENCHMARK_RUN_INCOMPLETE**: 22/44 attempted, 12 wire-valid, nine wire-invalid,
one incomplete at `max_tokens`, and zero retries. Three consecutive integration
failures stopped the legacy runner. The **exact validation mechanism is unknown**
for the nine historical wire failures; their values and error details were not retained.

The separate characterization run,
`j3-run001-failure-characterization-20260921T122041026687Z`, made ten new independent
observations: three valid, five wire-invalid and two incomplete. All five *new*
wire failures were `rationale / string_too_long`, exceeding 500 characters.
This does not establish the cause of any historical Run 001 wire failure.
Characterization was classified **MULTIPLE_FAILURE_MECHANISMS**, including output
contract mismatch, token-budget interaction, non-reproduction and historical
observer limitations. One diagnostic observation per case does not establish a
failure probability or causal explanation for changed output.

Neither historical experiment is amended, resumed, replaced or merged here.

## What remains frozen

The new runner imports the existing real `LiveJudgeProvider`, its exact prompt,
`_JudgeSignalWire`, extraction/stop handling and provider profile. It does not
change any production source or the legacy J2/J3 runners.

- Anthropic, `anthropic_messages`, `claude-sonnet-5`.
- `https://api.anthropic.com/v1/messages`.
- Identical `system`/`messages` payloads; `max_tokens=512`; timeout 30 seconds.
- No temperature, top_p, top_k, thinking configuration or reasoning_effort added.
- Identical classification and flag taxonomies, confidence contract,
  `rationale max_length=500`, and strict extra-field prohibition.
- Exact fixture text/order, 35 primary observations, nine repeats, injection set
  and repeat set: **44 scheduled observations, at most 44 HTTP requests**.
- Exactly one request per attempted observation; **zero retries/replacements**.
- No JSON repair, rationale truncation/discard before validation, flag
  normalization, prompt hints or automatic parameter changes.

Unchanged canonical SHA-256 values (CRLF normalized to LF in memory for files):

| Input | Before | After |
|---|---|---|
| Prompt plus wire schema | `166b69f0682198a8d5f872aef5d8f5367293e209d8c2ee185719175723ac77f3` | Same |
| Fixture file | `28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc` | Same |

The manifest also pins parent runtime hashes and new observer/runner/test hashes.
Raw-byte identity of existing files is checked separately; no file normalization
or reinterpretation of historical fingerprints is performed.

## Exact completion-policy amendment

`scripts/run_j3_amendment_001.py` is a separate execution path. It uses the shared
schedule, per-case real-provider assessment and canonical summarizer, but replaces
the legacy consecutive-failure stop with the following predeclared taxonomy.

| Nonfatal observation | Action |
|---|---|
| Parseable semantic JSON fails the wire schema | Persist failure; advance once |
| Malformed semantic JSON | Persist failure; advance once; no repair |
| `max_tokens` incomplete | Persist incomplete; advance once; do not parse partial text |
| Provider refusal | Persist refusal; advance once |
| Other nonvalidated response structure or stop reason | Persist failure; advance once |

These outcomes remain nonvalidated. Consecutive nonfatal failures, including 44
wire failures, do not become successes and do not terminate collection early.

| Fatal condition | Action |
|---|---|
| Freeze, source, schedule or input drift | Stop before next request |
| Wrong requested endpoint/model/payload or credential binding | Reject dispatch |
| Exposed returned model ID differs from the requested model | Record and stop; no canonical assessment acceptance |
| Request count is inconsistent, exceeds budget or differs from one for an attempted call | Stop; never dispatch request 45 |
| Evidence persistence fails | Stop before any subsequent request |
| Structural observer fails, truncates its bounded metadata, or contradicts typed validity | Record available evidence and stop |
| Any HTTP rejection, including 401/403, other 4xx, 429 or 5xx | Record provider failure and stop; no retry |
| Transport error or timeout | Record transport failure and stop; no retry |
| Response exceeds the existing 200,000-byte bound | Stop |
| Unexpected instrument exception or unrecognized state | Stop |

A missing returned model ID stays unknown; it is not fabricated or inferred to
match. Request model/profile are always checked. Explicit different returned IDs
are fatal. HTTP/provider and transport errors are deliberately fatal under this
amendment; failure tolerance applies to the five response/semantic conditions above.

The future execution journal writes an exclusive per-observation start record
before dispatch, then a sanitized result record before advancing. The start record
preserves an in-flight attempt if a later write or process interruption prevents a
result. An exclusive run marker prevents automatic restart. A disk failure may
prevent writing the final report itself; it never authorizes further calls.

Each start record explicitly contains `run_id` from the execution seal,
`sequence`, fixture `id`, `phase`, `observation` (including the repeat index),
`prior_http_count`, `expected_request_ordinal`, and `utc_start`. Before persistence,
accounting must establish `prior_http_count == sequence - 1` and
`expected_request_ordinal = prior_http_count + 1 == sequence`, within the 44-call
budget. The execution persistence boundary captures a fresh ISO-8601 UTC timestamp
immediately before each exclusive start write. A failed start write prevents that
request; a failed result write prevents any subsequent request. Result records
retain their existing shape and pair with start records by sequence in the unique
run directory; no scientific fields or metrics are added.

Run 002 preflight `j3-amend001-run002-preflight-20260921T140546287025Z` was blocked
before execution because the versioned start-journal record did not satisfy the
authorized evidence contract: zero observations, model calls, credential reads
and retries. That evidence remains unchanged. This journal fix supplies no Sonnet
Run 002 result or live authorization; a new execution requires separate approval
after versioning and successful CI.

Amended completion statuses:

- `J3_AMEND_001_RUN_COMPLETE_ALL_ASSESSMENTS_VALID`: all 44 attempted, all valid.
- `J3_AMEND_001_RUN_COMPLETE_WITH_NONVALIDATED_ASSESSMENTS`: all 44 attempted,
  one request each, and at least one nonvalidated observation.
- `J3_AMEND_001_RUN_INCOMPLETE`: fatal condition, missing observations or final
  integrity failure. Missing scheduled rows remain `NOT_ATTEMPTED`.

Both `status` and `completion_classification` use these names. The old summary
label `PARTIAL_PROVIDER_FAILURE` is not used to describe amended schema failures.
The legacy runners and their original status/completion rules remain unchanged.

## Future-only observer amendment

The new observer reuses the separately fingerprinted characterization observer
without modifying it. It records fixture ID, sequence, stop reason, JSON/wire
status, sanitized top-level field names/types, and validation error `loc`, `type`
and `message_code`. No Pydantic error input, context or free-form message is saved.

For an available semantic `rationale` string, it records `rationale_length` in
characters. An overlong rationale's text is never retained, shortened or removed
before validation. When the full wire validates, its bounded semantic fields may
be retained as valid output, with credential-pattern redaction for stored rationale.
No raw provider response or nontext thinking/reasoning block payload is archived.

For a parseable object whose *full wire fails*, classification, confidence and
flags may each be preserved only after validating that present value against its
original field annotation **and constraints**. Confidence retains the parent
finite-number rule and original coercions. Flags retain literal and list-size
constraints. Missing fields are not defaulted; invalid individual values are omitted.

These candidates reside exclusively in:

```json
{
  "unvalidated_wire_semantic_fields": {
    "label": "UNVALIDATED_WIRE_SEMANTIC_FIELDS",
    "limitations": ["EXPLORATORY", "NON-AUTHORITATIVE", "NOT A JUDGESIGNAL"],
    "fields": {},
    "invalid_individual_fields": []
  }
}
```

The empty object above illustrates the storage shape, not a recorded result.
The candidate container never becomes a `JudgeSignal`, policy input, Gateway
evidence or accepted benchmark assessment. For invalid observations, the report's
`j3` typed-assessment slot remains null. No exploratory aggregate metric is
predeclared or calculated in this amendment.

Top-level metadata/error lists are bounded at 64 entries. Any truncation is an
explicit fatal evidence limitation. Incomplete responses are not parsed around
the unchanged stop rule; JSON/field/rationale-length information stays unavailable.

## Observation states and canonical metrics

Reports expose separate state axes and true/false/unavailable counts:

- `HTTP_SUCCESS` (2xx).
- `JSON_PARSEABLE`.
- `WIRE_VALID`.
- `TYPED_ASSESSMENT_VALID` (accepted typed assessment after instrument guards).
- `PARSEABLE_BUT_WIRE_INVALID`.
- `INCOMPLETE_MAX_TOKENS`.
- `PROVIDER_REFUSAL`.
- `PROVIDER_FAILURE` and `TRANSPORT_FAILURE`, separately.

These axes may overlap; HTTP success does not imply parseability, wire validity or
accepted assessment validity. Unavailable is null, not false or zero. Terminal
outcomes remain separately counted. A wire-valid response from a different model
can have `WIRE_VALID=true` while `TYPED_ASSESSMENT_VALID=false` and abort the run.

Canonical J1 agreement still uses **only valid typed primary assessments**.
J1 is a deterministic engineering reference, not human truth. The unchanged
injection predicate and repeat-consistency rules never consume candidate fields.
No accuracy, safety ranking, human adjudication, J2 comparison or Gateway replay
is authorized or performed by this amendment.

## Offline preparation and future execution boundary

```console
python scripts/run_j3_amendment_001.py --plan
```

Plan mode has zero credential reads and zero network calls. It prints the exact
44-observation schedule, hashes, profile, unchanged limits and amended failure
taxonomy. It neither creates an execution nor supplies live authorization.

The future execution-seal path checks that the amendment manifest and all new
runtime/test dependencies exist in the current Git commit and match their
canonical bytes. It then pins exact HEAD plus raw source hashes for each request.
The historical parent freeze is still verified independently. The versioned
dependency set includes the characterization observer and its fingerprinted test:
`scripts/diagnose_j3_run001_failures.py` and
`tests/unit/test_j3_failure_characterization.py`. The runner imports the observer;
the manifest/plan hash both files. A four-file-only release would be incomplete.
No private historical evidence is part of that dependency set. Versioning does
not itself create a live execution seal or authorize a run.

Only a separately authorized future run can resolve the Anthropic-specific DPAPI
credential. Generic/OpenAI/environment credentials are not fallback sources.
Source/contract/profile checks precede credential access and every dispatch.
The future amended runner never invokes Gateway, USAspending or another model.

## Limits and review boundary

`flags=["NONE"]` remains **OPEN_DESIGN_FINDING** and is preserved literally.
512-token truncation incidence and 500-character rationale failures remain
measurement targets. No remedy is implemented. A future token-budget change
(for example J3-AMEND-002) or any prompt/schema/parser/stop-policy revision requires
its own explicit amendment and human authorization.

Run 001 remains immutable and incomplete. The diagnostic remains a separate
experiment. Human approval covers versioning this amendment; it does not
authorize Run 002 or any additional characterization observation.

## Initial offline validation of this amendment

- Focused amendment tests: **39 passed**.
- Full suite: **401 passed, 1 skipped**; the skipped configuration contract test
  applies to non-Windows hosts.
- Ruff lint and format, strict mypy (`33` production source files), and
  `git diff --check`: passed.
- Deterministic evaluation: **35/35** expected fixture outcomes.
- M2 benchmark generation: passed in a separate local output directory; existing
  repository artifacts were preserved.
- The amended offline plan confirms **35 + 9 = 44 scheduled, at most 44 HTTP
  requests, zero retries, zero credential reads and zero external calls**.
- MockTransport tests cover continued collection after consecutive wire failures,
  malformed JSON, incomplete output and refusal; all-invalid and mixed 44-row
  runs; per-field candidate rejection; canonical metric exclusion; private
  per-observation journals; and fatal boundary/evidence/accounting conditions.
- Legacy J3 and J2 both reproduce their three-failure stop in offline tests.
  Their source bytes and the original semantic contract are unchanged.
- Original Run 001 and characterization evidence hashes are unchanged.

These results establish offline implementation behavior only. No live Run 002
interoperability, performance, semantic accuracy or full-corpus outcome is claimed.

The subsequent journal-contract fix passed **45 focused tests** and **407 full
suite tests, with 1 non-Windows contract test skipped on Windows**. Its mocked
execution verifies 44 complete exclusive start records before their corresponding
44 mock requests, and 44 result records before advancing, with zero retries.
The strengthened journal regression fails against the prior runner in an isolated
copy. Ruff, format, mypy, 35/35 fixture evaluation, M2 benchmarks, offline plan and
diff-check also pass. These checks use no live provider calls or DPAPI access.
