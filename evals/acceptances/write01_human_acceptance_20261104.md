# WRITE01 human acceptance — limited local synthetic scope

Record version: **v1**.

Recording date: **2026-11-04** (current local conversation date; not independently authenticated human clock evidence).

Decision: **HUMAN_ACCEPTED_LIMITED_LOCAL_SYNTHETIC_WRITE01**.

Documentary result: **WRITE01_HUMAN_ACCEPTANCE_RECORDED**.

## Human decision and provenance

The project owner, identified in this conversation as Danny, directly and explicitly accepted the exact WRITE-01 candidate for local, synthetic research. The assistant records that decision; it does not issue or expand it.

The decision was communicated in the current Codex conversation. No cryptographic signature, raw message export, provider-authenticated message identifier, exact human emission timestamp, or independent identity authentication was supplied. The accepted hashes establish documentary byte identity only. They do not authenticate the human identity, certify an organization, or create execution authority.

Builder ≠ Reviewer ≠ Authority. The prior technical review supports this record but is not a substitute for the human decision recorded here.

## Accepted candidate identity

- Candidate: `WRITE01_SYNTHETIC_REVIEW_V1`.
- Branch observed at recording: `codex/write01-synthetic-review`.
- HEAD: `ea59646fdfe54d8ce954b8917979a8370ad27bef`.
- TREE: `4c25cc3c2cd9f049e36b6075014c2e00121e4ec2`.
- Candidate manifest: `evals/manifests/write01_candidate_v1.json`.
- Manifest bytes: `2717`.
- Manifest SHA-256: `8fa4ab832b233f299f6382a2889e1f9892dbad5aeab9e9dfacc1e54b797facf6`.
- Synthetic dataset SHA-256: `7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d`.

The Git HEAD and tree do not identify these untracked candidate bytes. Acceptance is therefore bound to the following fourteen independently revalidated file identities:

| Accepted relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `docs/WRITE01_SYNTHETIC_REVIEW_V1.md` | 14932 | `8cb99b2339022dc684957118f60f3b44adb431941973c9f6d25b54eb9d114194` |
| `evals/manifests/write01_candidate_v1.json` | 2717 | `8fa4ab832b233f299f6382a2889e1f9892dbad5aeab9e9dfacc1e54b797facf6` |
| `evals/tests/test_write01_authority_v1.py` | 13935 | `8b2d500ffb1ab1685b582c7b4b72ea057fe1a73727c4152836a29d881b9f4cad` |
| `evals/tests/test_write01_gateway_v1.py` | 6911 | `2cfcbea7ec7fff76da11e49b34368b61b3260335f274e502f9a2ae35dca72f1a` |
| `evals/tests/test_write01_independent_v1.py` | 5567 | `a24501b2620fc82dda6edc599190036aed2a4d31729a65d46e4c127411fdd607` |
| `evals/tests/test_write01_mcp_v1.py` | 7952 | `d00e08561ef271e24fb2f9e68c4c59e2837dc35713719bde9be3cb57ff34ae3f` |
| `evals/tests/test_write01_store_v1.py` | 14500 | `e409e8d37ba4238e5ede79d2aca4fb17f6c62044d63909e82e9eb73ceff88b5d` |
| `evals/write01/authority_v1.py` | 14265 | `1a894f38eb523703517d116d05cac6a9ad505f46ae2c201bb6d7dfdbd21bde64` |
| `evals/write01/contract_v1.py` | 2795 | `72a28620609396ea57d5ad2b12abb540b284bc3a0111c5966e843d45d333efc1` |
| `evals/write01/demo_v1.py` | 4424 | `d07cb63a3c44032c1d41b33b1a2d0bee67a62dae2c61383f2605fced5bf2bd9b` |
| `evals/write01/gateway_v1.py` | 12849 | `65038fd229890d6ebf4c0135dfdd552ddc52ffe63d78be3e6f721f133328a40c` |
| `evals/write01/stdio_v1.py` | 7379 | `835fd5d1a7d0e5d9450a9cf2f8abb44db13df4abb49c3528a7e7fc08c0df7edd` |
| `evals/write01/store_v1.py` | 24140 | `2a332c11e7173eb4b0cca8fefa3ab894cb13961b1e7704577b1930fd9157b645` |
| `scripts/run_write01_synthetic_v1.py` | 5082 | `9f39bdda13188ec6447cea137974ef0f02d01e5336ca602010f4012aa02f6198` |

All fourteen identities matched immediately before this record was created. The thirteen manifest payloads matched their recorded byte sizes and SHA-256 values; the self-excluded manifest supplied the fourteenth identity.

## Technical review basis

The focused WRITE01-CP01 review completed with no reportable security finding inside the tested fourteen-file scope.

- Codex Security scan ID: `0d4368fa-6afe-4eb2-ad38-239153d4edf4`.
- Acceptance-review artifact SHA-256: `daa9127944130debf0d435c52faa9b5b2dc9a0c6ae1f230aca020281f1f3d4e9`.
- Primary SQLite reconciliation SHA-256: `f415330baafd30238ea2964a792a217130545190e82bf96fb38aab28cde07bd6`.
- Fresh WRITE-01 selection: `142 PASS / 0 FAIL / 0 ERROR / 0 SKIP`.
- Supplemental owner-isolation probes: `12 PASS / 0 FAIL`.
- Ruff, format and Mypy checks: PASS within the reviewed local environment.

These test selections are separate and are not added together. The technical review and delegated technical roles are not independent human or organizational certification.

## Accepted scope and limitations

Acceptance is limited to the exact local synthetic research prototype above. It acknowledges, without removing, the following limitations:

- no exactly-once certification;
- no power-loss durability certification;
- no hostile-host or operating-system isolation certification;
- `owner_id` is composition provenance, not an OS or SQLite access-control principal;
- process-local Gateway blocking is not a global persistent owner STOP;
- durable unresolved-`OPEN` protection is target-scoped under the tested SQLite assumptions;
- no live provider, real USAspending, Databricks, cloud, production or authenticated human-identity claim;
- no full FAA contract or production WRITE capability is accepted.

The immutable synthetic awards dataset remains separate from the mutable review-state overlay. This acceptance does not authorize mutation of real FAA or governmental records.

## Current authorization boundary

The owner authorized only:

1. revalidation of the fourteen accepted identities;
2. creation of this additive documentary acceptance record and its identity manifest;
3. preparation of a future controlled Git checkpoint plan for review.

The owner did **not** authorize staging, commit, push, merge, deployment, provider activation, live API calls, or operations outside the synthetic environment. A later checkpoint requires separate explicit authorization after its exact publication inventory and validation plan are reviewed.

```yaml
HUMAN_ACCEPTANCE: HUMAN_ACCEPTED_LIMITED_LOCAL_SYNTHETIC_WRITE01
WRITE01_HUMAN_ACCEPTANCE_RECORD: DOCUMENTARY_ONLY
WRITE01_CHECKPOINT: PLANNING_ONLY
GIT_STAGING: NOT_AUTHORIZED
GIT_COMMIT: NOT_AUTHORIZED
GIT_PUSH: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
DEPLOYMENT: NOT_AUTHORIZED
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
USASPENDING_INTEGRATION: HOLD
FAA_FULL_CONTRACT: BLOCKED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
DURABLE_STOP: PARTIAL
```

If any accepted byte identity, scope, or security condition changes, this acceptance no longer identifies the changed candidate and a new human decision is required.

## Preservation

This record is additive. It does not rewrite the original candidate manifest, candidate sources, tests, synthetic dataset, prior technical review, historical failures, or operational HOLD records.

The companion `evals/manifests/write01_human_acceptance_evidence_v1.json` pins this Markdown record and the accepted candidate identities. That companion manifest excludes its own digest to avoid circular self-identification; its final SHA-256 must be reported separately.
