# GPT-6 Luna J4 completed run: sanitized closure

Documentation status: **J4_GPT6_LUNA_RUN_CLOSURE_READY_FOR_HUMAN_REVIEW**.

This is an evidence-grounded summary of one completed direct-judge run, not a publication decision or semantic adjudication. The original external freeze, authorization, journals, and result remain unchanged. The [machine-readable summary](J4_GPT6_LUNA_RUN.json) is a new allowlisted derivative, not a copy of the private result.

## Frozen identity and provenance

| Field | Value |
| --- | --- |
| Experiment | CIVICGATE-J4-GPT6-LUNA-001 |
| Completed run | gpt6-luna-j4-20260925T010613828350Z |
| Execution HEAD | 28a3304a09b7515745b194e2b5b0f333f9e0e6a7 |
| Profile / model | j4-gpt6-luna / gpt-6-luna |
| Provider / protocol | OpenAI / OpenAI-compatible Chat Completions |
| Endpoint | https://api.openai.com/v1/chat/completions |
| Frozen inference profile | medium reasoning; 512 max completion tokens; JSON-object response format |
| Schedule | 35 primary observations, then nine repeats |
| Maximum / actual HTTP requests | 44 / 44 |
| Retries / recorded Gateway executions | 0 / 0 |

| Original source artifact | SHA-256 of exact bytes |
| --- | --- |
| freeze.json | b8a10753ebb38164ae4da73c4059507a7775f1cb60a3507b2bff2b8a964b2908 |
| authorization.json | ef50a0700afcb4da995886c3cb20e571508662cdbc7cc47e0ce62a09a50b7774 |
| started.json | 9dd1cfdedee4b96692e3ac4184c7c85115933ce903bce15ca283e9800acdb3aa |
| result.json | 70e177edce7d67d360d605ef058840ad8ffeaef737ce1e31ffb67f6505ac0f46 |

The content of result.sha256 matches the computed result.json digest. The execution HEAD identifies the frozen instrument, not this documentation checkout. The 70 frozen source dependencies were checked against that commit using the established CRLF-to-LF source hashing convention. The 44 payload identities use canonical decoded JSON, not raw HTTP wire bytes. The seven scientific identity hashes are recorded in the [JSON summary](J4_GPT6_LUNA_RUN.json) and match the unchanged [declared profile](J4_GPT6_LUNA_PROFILE.json), [payload contract](J4_GPT6_LUNA_PAYLOAD_CONTRACT.json), fixtures, semantic contract, source adjudication, and [model-neutral reference](JUDGE_HUMAN_SEMANTIC_REFERENCE_V1.json).

This Markdown records the exact-byte SHA-256 of the new JSON summary: **944427f9a0e7d3540678af04639caf2ec2434e6b049230b84767d67fdd3268da**. The JSON does not embed its own digest.

## Observed contract and transport result

The instrument emitted the exact completion classification **J3_EXPERIMENT_COMPLETE_ALL_ASSESSMENTS_VALID**. The J3 prefix is the shared runner's emitted label for this J4 experiment; it has not been renamed.

| Individually reconciled observation | Count |
| --- | ---: |
| Primary / repeat | 35 / 9 |
| Attempted / not attempted | 44 / 0 |
| HTTP 200 | 44 |
| Returned model equal to gpt-6-luna | 44 |
| finish_reason equal to stop | 44 |
| JSON parseable / wire valid / typed valid | 44 / 44 / 44 |
| Nonvalidated, provider, transport, or schema failures | 0 |
| Refusals or max-token-incomplete responses | 0 |
| Fatal reasons | 0 |

All 44 unique sequence numbers and case-observation keys matched the frozen schedule. Each START payload hash matched its scheduled payload; each RESULT matched the corresponding report row. There are 44 START and 44 RESULT journals, no sequence-45 journal, and zero recorded retries. Journal reconciliation is evidence from this instrument, **not an independent audit of all network traffic**. The private result is an instrument report, not a complete raw HTTP capture. These observations establish contract compliance for this completed run, not semantic correctness or downstream governance effectiveness.

## Observed latency and usage

| Measure | Value across 44 observations |
| --- | ---: |
| Instrument-observed assessment latency, median | 4827.7895 ms |
| Latency, minimum / maximum | 2776.97 / 8030.928 ms |
| Input tokens | 20253 |
| Output tokens | 11828 |
| Total tokens | 32081 |
| Reasoning tokens | 8382 |

All four usage fields were exposed for all 44 observations. Reasoning tokens are included in output tokens and must not be added again to total usage. Latency includes the instrument-observed assessment path; it is not isolated internal model-reasoning time. No cost estimate or cross-model latency comparison is made here.

## Separately initiated live attempts

The completed run was the third known live attempt. **Zero retries within each attempt** does not mean only one attempt was initiated. No observations from different attempts were pooled.

| Run ID | Result SHA-256 | Exact classification | Attempted / typed valid / not attempted | HTTP statuses | Fatal reason |
| --- | --- | --- | ---: | --- | --- |
| gpt6-luna-j4-20260924T225637591916Z | 2675a74b1ebc1fd859988ec212da7fbe34a84b716a5af0711d514eeb3879d942 | J3_EXPERIMENT_INCOMPLETE | 1 / 0 / 43 | 403 × 1 | PROVIDER_HTTP_FAILURE |
| gpt6-luna-j4-20260925T000929043642Z | ed6f08dca2171c8a132accea7a06e5b9843bbf7d73c1804c0aa8ec1b8f660501 | J3_EXPERIMENT_INCOMPLETE | 2 / 1 / 42 | 200 × 1; 403 × 1 | PROVIDER_HTTP_FAILURE |
| gpt6-luna-j4-20260925T010613828350Z | 70e177edce7d67d360d605ef058840ad8ffeaef737ce1e31ffb67f6505ac0f46 | J3_EXPERIMENT_COMPLETE_ALL_ASSESSMENTS_VALID | 44 / 44 / 0 | 200 × 44 | None |

Both incomplete attempts recorded provider HTTP 403 with model_not_found. Their observation label was AUTHENTICATION_REJECTED, while the experiment's fatal reason was PROVIDER_HTTP_FAILURE. Those are distinct recorded fields; they do not prove an invalid credential. The completed attempt followed an **operator-reported** waiting period of more than 30 minutes after a permission change. The earlier rejection did not recur in its 44 requests. No exact permission-change timestamp was established, and permission propagation remains an **unconfirmed** explanation. Waiting is not asserted to have caused recovery.

## Legacy runner metrics and pending review

The original runner reported **5/35 engineering-reference agreement**. This measures agreement with an engineering reference, not accuracy or human-adjudicated correctness. Its frozen injection-fixture metric reported **6/6 under tested conditions**; that mechanical result is not independent human evidence of injection robustness or downstream containment.

The three repeat groups—valid-recipient, blacklist, and ambiguous-recipient—each carry the runner aggregate label **SEMANTIC_VARIABLE**. That label does not prove classification, flags, and confidence all changed, and repeat variability is separate from wire-contract validity.

The result emits **NOT_MEASURED_NO_INDEPENDENT_HUMAN_LABELS** for accuracy and related error rates. A frozen human reference *does* exist: it contains 27 evaluable cases and eight excluded cases. This runner did not apply that reference as an independent human semantic adjudication. A later review can retain the 27/8 split, analyze repeats separately, and keep all 44 observations in the contract-compliance record. No case receives a new semantic disposition here.

- Semantic review status: **PENDING**.
- Cross-model comparison status: **NOT_PERFORMED_IN_THIS_CLOSURE**.
- Judge selection status: **NOT_SELECTED**.

## Bounded conclusion and preservation

> GPT-6 Luna completed all 44 observations under the frozen J4 profile with
> contract-valid responses, matching returned model identities and zero
> retries. This establishes observed contract compliance for this completed
> run; it does not establish semantic accuracy, general stability, downstream
> governance effectiveness, or the cause of the earlier access rejections.

The judge is advisory and grants no authority. This closure excludes credentials, authorization headers, provider request IDs, raw traffic, verbatim model responses, rationales, reasoning text, private logs, and machine-specific paths. Original execution evidence and prior attempts remain separate and unchanged. No provider, Gateway, or credential-store action was performed to prepare this documentation. Publication and any judge-selection decision require separate human review.
