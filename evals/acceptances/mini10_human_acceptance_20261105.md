# MINI10 human acceptance — limited local synthetic scope

Record version: **v1**.

Recording date: **2026-11-05** (current local conversation date; not independently authenticated human clock evidence).

Decision: **HUMAN_ACCEPTED_LIMITED_LOCAL_SYNTHETIC_MINI10**.

Documentary result: **MINI10_HUMAN_ACCEPTANCE_RECORDED**.

## Human decision and provenance

The project owner, identified in this conversation as Danny, directly and explicitly accepted the exact MINI10 Governed Chat candidate for local, synthetic research. The assistant records that decision; it does not issue, expand, or independently authenticate it.

The decision was communicated in the current Codex conversation. No cryptographic signature, raw message export, provider-authenticated message identifier, exact human emission timestamp, or independent identity authentication was supplied. The accepted hashes establish documentary byte identity only. They do not authenticate the human identity, certify an organization, or create execution authority.

Builder ≠ Reviewer ≠ Authority. The prior technical review supports this record but is not a substitute for the human decision recorded here.

## Accepted candidate identity

- Candidate: `MINI10_GOVERNED_CHAT_V1`.
- Branch observed at recording: `codex/mini10-governed-chat`.
- Baseline HEAD: `13e9f769a8c14aed208b0b73e42d569a1849fa7c`.
- Baseline TREE: `c047034a1f9bf6befb5937c5b8996a7381c00ad9`.
- Accepted file count: `19`.
- Accepted total bytes: `151795`.
- Canonical inventory SHA-256: `fd51f0233a79355a0b03b30ba95e613b0bfaeaa87b3c05fdc76d85b513a65a57`.

The canonical inventory is the UTF-8 encoding of the nineteen rows sorted by relative path, each serialized as `path<TAB>bytes<TAB>sha256<LF>`, including the final LF.

The Git HEAD and tree do not identify these modified and untracked candidate bytes. Acceptance is therefore bound to the following nineteen independently revalidated worktree identities:

| Accepted relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `docs/MINI10_GOVERNED_CHAT.md` | 6410 | `4792c53d4636bb501f4e6190de0a3b17a55f799c6a92dbf930f602e954481e01` |
| `evals/demos/mini10_chat_fixtures_v1.py` | 4241 | `9cf105337e89e25e9cbaa60fb84e2f021aff071fb1e6d589356142561c36a404` |
| `evals/demos/test_mini10_chat_v1.py` | 2639 | `02ed57c9f37ffdf3120096e1752a869fa6ab1d077e2f0f6c756f43961aacab43` |
| `evals/tests/test_mini10_chat_benchmark_v1.py` | 4655 | `ffe5edcccde309b9da3790ac00ba67db3a80d46b06d30cc836e5bca97fb508e4` |
| `scripts/evaluate_mini10_chat_v1.py` | 12479 | `45533be0772e28aaa1daa4ff8d252c89b55e8eef057ff9f266bac80a2c686e53` |
| `scripts/run_console_chat_synthetic_v1.py` | 12563 | `b19ca2bd57a35068de147f7b89ce3f4eb4a8463ddae34051c7c40374e29a7c8f` |
| `scripts/serve_evidence_console.py` | 8156 | `b11387638e7f0d39292bc8043f9c8db27e6ccbebc17e2747f0bd1f5bbfadbee3` |
| `src/civicgate/evidence_console/app.py` | 21013 | `2d6803f0310ebfccd2ac80471c7b1f32e928265a1962ecba3cf88334cd7c45d9` |
| `src/civicgate/evidence_console/chat_execution_v1.py` | 18377 | `a236832467781418423520c3affa32f62fff9740516117b1754e46a5df006d55` |
| `src/civicgate/evidence_console/chat_planner_v1.py` | 3535 | `90e0deb3bddab5ab609c2a6f8ae6d65d8fb49e4bba432a278d4cf3f2ef98ba0b` |
| `src/civicgate/evidence_console/static/chat.js` | 7717 | `7bcf7b047d9aa9a0b29dedf3973a88e9fbca006fd1a89e435c57e6ccfe78be88` |
| `src/civicgate/evidence_console/static/console.css` | 19856 | `ca720a177ca654b3eb889d3402b616ab97c120a919d6644ee8cbf29d7dc3cef5` |
| `src/civicgate/evidence_console/templates/base.html` | 2429 | `f0a616a95ff799d862de4427d78d3729a776f8f19c7a33e31170e7ca8a7279e8` |
| `src/civicgate/evidence_console/templates/chat.html` | 4642 | `aafa89f8a424931b5aa4fae96cb28315a611a2d0eee29ae71571accc28b26b32` |
| `tests/evidence_console/test_chat_api_v1.py` | 5818 | `c86bb79c81b913ce89fd08bff5d40c2b716b664b6819c525387d6edee30cdb69` |
| `tests/evidence_console/test_chat_execution_v1.py` | 5471 | `fc9ce4c9778faf5b1542a86e41187b39db2e6f2575e2da8ccb7005fd37439183` |
| `tests/evidence_console/test_chat_http_v1.py` | 5716 | `d9791ac760e13b5d5c940ebc7cf2f71150f75f44f1644efd37013aa6c4e2dea8` |
| `tests/evidence_console/test_chat_planner_v1.py` | 5211 | `d8e53a61b60cc8076fdb82cc21300dcadbcd464f8d06e984d4df36329a9e79b8` |
| `tests/fixtures/mini10_chat_benchmark_v1.json` | 867 | `07b0a2080bbdb64c5f08c0230c345524f96eb382574ba831e7824f5abef1cd5b` |

All nineteen identities and the canonical inventory digest matched immediately before this record was created.

## Compatibility preservation

The shared `src/civicgate/llm/live.py` remains outside the accepted nineteen-file delta and retains its frozen identity:

- bytes: `17595`;
- SHA-256: `d0802f083aa5dcdbbf7025c1e22b7a2e2211d8029a868c5def15beb0d1fd025a`;
- working-tree diff: none.

The following historical manifests remain byte-identical:

- CP1: `6ad01000d9ca729d8ffdf0d023e149fd1cfce0fc6b18ca65f022835f1a30f1c1`;
- CP1.1: `082091edc166b86fde7bd93674960ce15eb7447d07ebaea355ce2afe6e5f420c`;
- GSA local checkpoint: `299f26ea5f2985c859e8c0806633df0891ade46100a9d76da7a8fb2e1ea60c42`.

## Technical review basis

The acceptance acknowledges the reported bounded local evidence without converting technical results into broader authority:

- Console/Advisor: `501 PASS / 0 FAIL / 9 SKIP`;
- MINI10 focused selection: `85 PASS`;
- six CP1/CP1.1 compatibility cases: `6 PASS` after preserving the original `6 FAIL` evidence;
- fresh synthetic benchmark: `MINI10_BENCHMARK_VERIFIED`;
- A1/A2/MCP: `221 PASS`;
- R3.2: `373 PASS`;
- R02.2: `171 PASS`;
- R02.3: `89 PASS`;
- WRITE-01 under the documented Windows/Python 3.12 CI-compatible environment: `142 PASS`;
- Ruff, format, Mypy, `pip check`, and the three CI-equivalent dependency audits: PASS, with zero reported dependency advisories.

These selections overlap and must not be added together. The technical review and delegated technical roles are not independent human or organizational certification.

## Accepted limitations

Acceptance is limited to the exact local synthetic research candidate above. It expressly preserves and accepts the following limitations:

- DATA-01 retains two unresolved historical discrepancies;
- WRITE-01 retains twelve failures under the documented Windows/Python 3.11 selection;
- genuine Granite inference remains inactive and its effective identity is not verified for MINI10;
- the optional Granite adapter uses a private implementation boundary and is not approved for live activation;
- Chat-to-WRITE remains disabled and uncomposed;
- durable STOP remains `PARTIAL`;
- no exactly-once, power-loss durability, hostile-host isolation, operating-system isolation, production security, live USAspending, or cloud claim is established;
- local `CLOSED` custody is documentary and is not human acceptance;
- hashes identify bytes but do not independently authenticate the human reviewer.

## Current authorization boundary

The owner authorized only:

1. revalidation of the nineteen accepted identities and canonical digest;
2. creation of this additive documentary acceptance record and its self-excluding evidence manifest;
3. preparation of a future controlled Git checkpoint plan that detects any EOL or Git-clean-filter transformation before publication.

The owner did **not** authorize staging, commit, push, merge, deployment, provider activation, live model calls, real USAspending access, Chat-to-WRITE, modification of historical manifests, or production operations.

```yaml
HUMAN_ACCEPTANCE: HUMAN_ACCEPTED_LIMITED_LOCAL_SYNTHETIC_MINI10
MINI10_HUMAN_ACCEPTANCE_RECORD: DOCUMENTARY_ONLY
MINI10_CHECKPOINT: PLANNING_ONLY
GIT_STAGING: NOT_AUTHORIZED
GIT_COMMIT: NOT_AUTHORIZED
GIT_PUSH: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
DEPLOYMENT: NOT_AUTHORIZED
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
GRANITE_EFFECTIVE_IDENTITY: UNKNOWN_NOT_ACTIVATED
CHAT_TO_WRITE: DISABLED_NOT_COMPOSED
USASPENDING_INTEGRATION: HOLD
DATA01: 2_HISTORICAL_DISCREPANCIES_PRESERVED
WRITE01_WINDOWS_PYTHON311: 130_PASS_12_FAIL_PRESERVED
FAA_FULL_CONTRACT: BLOCKED
DURABLE_STOP: PARTIAL
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

Any changed accepted byte identity, scope, or security condition requires a new human decision. A future checkpoint must independently compare worktree bytes, staged Git blobs, and any EOL normalization before commit.

## Preservation

This record is additive. It does not rewrite the nineteen accepted files, `live.py`, frozen manifests, historical test outcomes, DATA-01 failures, WRITE-01 failures, or operational HOLD records.

The companion `evals/manifests/mini10_human_acceptance_evidence_v1.json` pins this Markdown record and the nineteen accepted candidate identities. That companion manifest excludes its own digest to avoid circular self-identification; its final SHA-256 must be reported separately.
