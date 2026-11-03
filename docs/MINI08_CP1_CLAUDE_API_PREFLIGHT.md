# MINI08-CP1 — Claude Evidence Advisor API preflight

Documentation reviewed on **2026-11-03**. This is a research checkpoint and a plan for a separately authorized validation. No authenticated Models request, credential lookup, inference, credit inspection or billing operation was performed.

The checkpoint still implements **MOCK_ONLY**. It has no usable live switch. Documentary preflight readiness must not be interpreted as readiness to dispatch a paid request.

## Current implementation and contract comparison

The implementation is `src/civicgate/evidence_console/anthropic_advisor_v1.py`; selection and report admission are in `evidence_advisor_v1.py`. The optional console remains separate from Granite, Luna and deterministic Gateway authority.

| Requirement | Verified implementation / documented contract | Remaining gate |
| --- | --- | --- |
| Messages endpoint | Wire candidate targets `POST https://api.anthropic.com/v1/messages` with model, max_tokens, system and one user message | Real-provider compatibility NOT_TESTED |
| Version | Candidate explicitly sends `2023-06-01`; current official documentation presents `2026-10-21` | Review version/model compatibility before any live admission; do not silently change this checkpoint |
| Model | Explicit trusted configuration; mock identity is `synthetic-claude-advisor-v1` | Authenticated available Sonnet identity UNKNOWN |
| Input bound | 32,768 bytes for the complete serialized mock request body, including system text and wrapper | This is not a billable-token bound |
| Output / response | max_tokens 2,048; response body capped at 65,536 bytes | Verify the selected model's limits and billable categories |
| Deadline | Ten-second absolute monotonic adapter deadline, checked around send/read/parse; later service custody checks | No OS preemption or hard real-time claim |
| Attempts | At most eight mock requests per configured process/session, one reserved client attempt each | Future one-request session must have an independent one-attempt cap |
| Money | Decimal per-request/session **synthetic** cost reservations; default zero mock dollars | Real pricing, token ceilings, remaining credits and monetary maximum UNKNOWN |
| Transport | Exactly `httpx.MockTransport`; other/unspecified transports rejected before secrets | Reviewed live transport does not exist in this candidate |
| Authority | No tools, MCP connector, binding issuer, policy mutation or custody-control permission exposed to Claude | Preserve this boundary in any future transport |

The official [Messages reference](https://platform.claude.com/docs/en/api/messages/create) documents the endpoint, request fields, response model, content and completion signals. The [API version history](https://platform.claude.com/docs/en/api/versioning) documents both version dates. Public documentation is not evidence of this account's effective access.

The current parser admits only matching model identity, message/assistant envelopes, `end_turn`, bounded text-only content, JSON reports and supported usage values. Missing usage remains null. It does not implement every current response variant. In particular, the current Messages documentation shows refusal details separately in `stop_details`, including an `end_turn` example. Before live use, explicitly review refusal handling; `end_turn` alone must not be treated as proof of a usable non-refusal report. Strict content-block shape may also reject additional provider fields. These are live-admission review requirements, not a claim of a newly observed real API failure.

## Obtaining an exact available Sonnet identity later

This procedure is **not executed by this checkpoint**:

1. Separately authorize a read-only metadata session for the intended Claude organization/workspace and approved credential source. Do not print request headers, keys or account identifiers in public evidence.
2. Use the authenticated `GET https://api.anthropic.com/v1/models` endpoint with an explicitly reviewed API version. The Models endpoint uses `after_id` pagination, not the newer generic `page` scheme used by some other endpoints. Select a bounded page size; defaults and maximums are documented. Preserve sanitized response status, time, exact returned model IDs and capability/lifecycle facts.
3. While `has_more` is true, use the prior `last_id` as `after_id`. Detect repeated/missing cursors and bound page count; an incomplete listing is PARTIAL. Do not turn a missing entry on one page into a global unavailability assertion.
4. Under the current documented representation, identify candidates by the explicit `line == "sonnet"` field and require suitable lifecycle/capabilities. Do not infer the model line from a name substring when `line` is null. A display name is descriptive, not the request identity. A public model catalog does not establish account access.
5. Human review selects one exact returned `id`, supported input/output limits and lifecycle. When an alias is involved, use authenticated `GET /v1/models/{model_id}` to resolve it and preserve the returned canonical identity. Pin the canonical ID expected in the response; the candidate currently rejects requested/returned mismatches rather than silently accepting an alias substitution.

The [List Models contract](https://platform.claude.com/docs/en/api/models/list) documents the listing, fields and cursor protocol. The [Get a Model contract](https://platform.claude.com/docs/en/api/models/retrieve) explicitly supports alias resolution. Do not substitute a model ID copied from examples for an authenticated result.

## Credential boundary

The existing `SecretProvider.get_secret(name)` protocol is the credential injection boundary. `EnvironmentSecretProvider` reads explicit process-environment values; it does not load `.env` files. `WindowsDPAPIStore` is an optional injected provider. Its existing CLI default is `%LOCALAPPDATA%\CivicGate\secrets.json`, outside the repository, using current-Windows-user DPAPI protection.

The store is a general named mapping, not a whitelist of judge keys. The CLI's named entry support does not make a name automatically recognized by an adapter. Existing `CIVICGATE_ANTHROPIC_JUDGE_API_KEY` routing is for the Judge and must not implicitly activate the Evidence Advisor. No JOI credential location or ownership claim applies here.

A future separately reviewed advisor edge may use a distinct approved name such as `CIVICGATE_ANTHROPIC_ADVISOR_API_KEY`; that is a **proposed name, not currently consumed configuration**. Inject only the required provider at the trusted process boundary. Decrypt/read only the selected entry, place the key in the in-memory authentication header, and exclude it from prompts, HTML/JavaScript, reports, telemetry, exceptions and Git. Never embed credentials in URLs or record the full client request. Existing core runtime settings/provider objects may retain decrypted keys in memory while used; DPAPI is at-rest protection, not a claim that plaintext never exists.

In this candidate, the `secrets` argument is deliberately discarded and never read or retained. The mock header contains an explicitly synthetic non-credential value. No real store or environment secret was inspected or changed during preflight. The [API authentication overview](https://platform.claude.com/docs/en/api/overview) documents authentication/version headers and workspace selection; any required workspace routing must be verified for the actual credential, not guessed.

## Exact sanitized payload approval

The three local previews are **candidate data for human review**, not an upload authorization. Their manifests identify the selected evidence projection and the exact mock wire body separately. The additive [preview script](../scripts/preview_evidence_advisor.py) accepts `--catalog` and `--output-root`; use an operator-verified catalog containing exactly one preserved PERMIT, DENY and REVIEW_REQUIRED observation, with a fresh output directory outside the repository and input roots. This preparation does not execute the captured observations or establish current-runtime compatibility. The CP1 previews use the genuine preserved MINI08.1 captures; any current-checkpoint execution blocker remains separate. See [checkpoint instructions](MINI08_CP1_CHECKPOINT.md) for the command and private output inventory.

Approve one specific preview digest and exact configuration before a later paid validation. The user message contains only the 25 allowlisted enum/count/boolean/hash fact slots, observation alias `obs-1`, source aliases/byte counts/digests, integrity and limitations. Original requests, planner arguments, result records, log text, personal/private paths and raw directories are excluded. The complete outbound body also includes the system instruction, explicit model ID and max_tokens, so changing those requires a new wire preview and approval.

References are checked against the selected local inventory and exact fact-to-source associations. Resolving a source hash does not authenticate human provenance or verify the model's prose. Findings remain advisory with `semantic_verification=NOT_ESTABLISHED`; UNKNOWN/PARTIAL facts must not be promoted to verified conclusions. Claude receives no tool definitions and no mechanism to request execution or alter documentary OPEN/CLOSED state.

## Budget and one-request admission

Official [pricing](https://platform.claude.com/docs/en/about-claude/pricing) and [token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting) must be rechecked for the exact selected model/version and exact body. Token counting is a separate authenticated endpoint, even when documented as free; it is not called here. A returned count is an estimate, not an independently certified hard billable maximum. Do not infer an input token ceiling from the byte cap.

Before admission, establish a conservative billable input ceiling and output ceiling for the exact payload and all supported billing categories. With verified per-token prices and no separately billable features, the reviewed bound would be `input_ceiling * input_price + output_ceiling * output_price`. Include any additional applicable category or block if its bound is unknown. Do not insert invented rates, credits or a numeric cost approval into this document.

The operator must independently verify the relevant account's remaining usable credits or applicable billing/spend limit and any auto-reload setting. Public billing documentation cannot establish the user's balance. Credits and monthly spend limits are distinct controls; neither a plan subscription nor a reported balance proves current request eligibility. Anthropic notes that a client timeout/disconnect can still incur a charge. An uncertain request therefore retains its reservation and blocks automatic retry. See [API billing](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage) and [limits](https://platform.claude.com/docs/en/api/rate-limits).

For one future paid validation, all of the following must be true before dispatch:

- Explicit human authorization names the one analysis, exact model, exact payload/wire digest, maximum cost and one-attempt session.
- Available model identity, version and account/workspace access are freshly supported; all conditional response/alias/refusal concerns are resolved by a separately reviewed live candidate.
- Credits or spend limit, verified pricing, token ceilings and the numerical cost bound are recorded with appropriate private provenance.
- A reviewed credential source supplies the key in memory; no credentials are requested through the browser console.
- Acknowledged local intent and atomic budget reservation precede the single permitted HTTP attempt. Delivery uncertainty is preserved; no refund, retry, redirect, fallback provider or alternate client is automatic.
- Responses remain separate states: transport observed, typed report parsed, references resolved and final acceptance. Deadline/custody failure cannot become confirmed success. No result changes deterministic MCP authority.

The real API test must be separate from the synthetic demonstration. Failure of one must not trigger the other as fallback.

## Errors are not evidence findings

Timeout, cancellation, unavailable configuration, exhausted budget, 429, 5xx, HTTP rejection, malformed/truncated JSON, model mismatch, unsupported/refusal response, oversize body and invalid citations are provider/admission failures. They produce a stable failure status and no fabricated finding. Unknown usage/cost remains UNKNOWN, and an error message or matching JSON shape cannot establish paid completion. The [official error contract](https://platform.claude.com/docs/en/api/errors) distinguishes HTTP error categories; this prototype deliberately does not follow automatic retry recommendations because its own authorization permits one attempt only.

## Readiness and retained gates

| Fact | Current classification |
| --- | --- |
| Messages shape and local report references | VERIFIED_OFFLINE with mock provider |
| Exact available Sonnet model | UNKNOWN — Models API NOT_QUERIED |
| Real Anthropic transport | NOT_IMPLEMENTED / NOT_AUTHORIZED |
| Remaining credits or applicable spend limit | UNKNOWN — not inspected |
| Real pricing and billable ceiling for selected request | UNKNOWN — no real model selected |
| Numerical maximum authorized cost | UNKNOWN — no paid authorization |
| Approved external payload | PENDING human approval; local previews only |
| Judge calibration / independent golden references | NOT_YET_MEASURED / PENDING |

```text
EVIDENCE_ADVISOR_PROVIDER: MOCK_ONLY
REAL_ANTHROPIC_EXECUTION: NOT_AUTHORIZED
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
MONETARY_ADMISSION: BLOCKED_UNTIL_VERIFIED
EVAL002_EXECUTION_AUTHORIZATION: HOLD
USASPENDING_INTEGRATION: HOLD
P2_02_DURABLE_STOP: PARTIAL
FAA_FULL_CONTRACT: BLOCKED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

The preflight prepares a reviewable procedure; it grants no API activation, account change, purchase, execution or deployment authority. Stop after the checkpoint and documentation.
