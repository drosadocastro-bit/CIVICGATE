# WRITE01-CP02 — controlled checkpoint and EOL publication identity

**Status before publication:** VERIFIED FOR THE AUTHORIZED CHECKPOINT; CI must be observed after the single normal push.

This additive record documents the limited Git checkpoint authorization for the
accepted local synthetic WRITE-01 candidate. It does not replace the original
candidate manifest or the earlier human-acceptance evidence, and it creates no
runtime authority.

## Baseline and authorized scope

- Branch: `codex/write01-synthetic-review`.
- Parent HEAD: `ea59646fdfe54d8ce954b8917979a8370ad27bef`.
- Parent tree: `4c25cc3c2cd9f049e36b6075014c2e00121e4ec2`.
- Authorized commit message:
  `feat(write01): checkpoint accepted synthetic review-state prototype`.
- Publication inventory: the previously reviewed 16 paths plus this checkpoint
  record and the additive EOL identity receipt, for 18 paths total.

The later owner decision `AUTHORIZE_WRITE01_LF_PUBLICATION_IDENTITY` authorizes
only the verified Git serialization described below. It does not broaden the
accepted WRITE-01 behavior or operational scope.

## Original and publication identities

| Role | Relative path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Accepted historical CRLF artifact | `evals/manifests/write01_candidate_v1.json` | 2,717 | `8fa4ab832b233f299f6382a2889e1f9892dbad5aeab9e9dfacc1e54b797facf6` |
| Git-published LF serialization | `evals/manifests/write01_candidate_v1.json` | 2,640 | `0e8efad999017824dea58c2e1ff77b248aa8714293d5f8866dc46c35797fa350` |

Independent binary verification established:

- the original contains exactly 77 CRLF terminators, zero LF-only terminators
  and zero CR-only terminators;
- the staged form contains exactly 77 LF terminators and no CR bytes;
- replacing every original `CRLF` with `LF` in memory produces the staged bytes
  exactly;
- the 77-byte size reduction equals the exact terminator count, with zero other
  byte changes;
- both forms are UTF-8 without a BOM, end with their respective line terminator
  and contain no trailing-whitespace lines;
- both parse as JSON, are recursively equal, have canonical semantic SHA-256
  `88fa3a67b0ae488164924f8e4f85bcb534d849877f4bae212daa60762c6c8fe0`,
  and preserve all 29 compared internal reference fields.

The observed Git attributes are `text=auto` and `eol=lf`. No change to
`.gitattributes` is part of this checkpoint.

## Preservation

The historical 2,717-byte CRLF working artifact was not edited. Its accepted
identity remains pinned by the unchanged human-acceptance records. The earlier
acceptance Markdown remains 7,143 bytes with SHA-256
`9a2847ba089d79098d3d76416865c1d5615cdfcd8049063c9dda86c925d22955`,
and its companion evidence JSON remains 5,655 bytes with SHA-256
`df023ae8076998f8fd28c5649beb2484fc786ece7948014d7203b4ca078b2dc1`.

All other 15 previously staged files are byte-identical between the working
tree and Git index. Neither legacy policy, Gateway behavior, tests, source code
nor historical evidence was changed to accommodate the EOL mapping.

The machine-readable correspondence is recorded in
[`write01_cp02_eol_publication_identity_receipt_v1.json`](../evals/manifests/write01_cp02_eol_publication_identity_receipt_v1.json).

## Pre-publication verification

| Check | Fresh result |
| --- | --- |
| WRITE-01 controlled selection | 142 PASS / 0 FAIL / 0 ERROR / 0 SKIP |
| Supplemental antibypass controls | 12 PASS / 0 FAIL |
| Ruff lint | PASS |
| Ruff format | PASS — 12 files |
| Mypy with optional console dependencies | PASS — 77 source files |
| Binary EOL equivalence | PASS |
| Recursive JSON and internal-reference equivalence | PASS |

An initial Mypy preparation attempt used the minimal environment without the
optional FastAPI dependency and produced 22 dependency-related diagnostics in
the Evidence Console. The same unchanged sources passed in the correct optional
dependency environment. No code or configuration was changed to suppress that
preparation failure.

CI results are intentionally not preclaimed in this commit. They must be tied
to the exact pushed commit SHA and all five expected GitHub Actions jobs must
finish successfully before the checkpoint is reported as CI verified.

## Retained boundaries

```yaml
WRITE01_SCOPE: LIMITED_LOCAL_SYNTHETIC_ONLY
DURABLE_STOP: PARTIAL
LIVE_PROVIDER_TRANSPORT: NOT_AUTHORIZED
USASPENDING_INTEGRATION: HOLD
REAL_WRITE: NOT_AUTHORIZED
MERGE: NOT_AUTHORIZED
PRODUCTION_DEPLOYMENT: NOT_AUTHORIZED
```

This checkpoint does not certify exactly-once execution, power-loss durability,
hostile-host isolation, live-provider behavior or production readiness.
