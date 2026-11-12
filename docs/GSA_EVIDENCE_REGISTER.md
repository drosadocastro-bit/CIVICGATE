# Evidence register and publication boundary

Version 1 · November 12, 2026. This is a sanitized documentary index, not a LIVE admission manifest or a replacement for accepted source inventories. No credentials, raw provider bodies, private absolute paths, full prompts, SQLite databases or archives are included.

## Baseline and visibility

Public GitHub main was read as [`ced2628e4e447bf8ee8de478ad1257c0a3a2a1f6`](https://github.com/drosadocastro-bit/CIVICGATE/commit/ced2628e4e447bf8ee8de478ad1257c0a3a2a1f6), the merge of Granite checkpoint PR #25. The local published checkpoint is `5c20beef1d290f9f14e92b6a189ecf76255709be`, tree `e460d58819960946aff31d830a35e3272c2678c2`. Its README Git blob `198672883ba808cdd9d70a848a243de7e82b56a3` matches the remote main listing. Working-tree EOL bytes and Git-published bytes are not assumed interchangeable.

This documentation candidate is prepared outside the worktrees as an unapplied overlay. The existing modified README, application sources, Git indexes and private evidence remain untouched. The official GSA page was consulted; no operational APIs, models, WRITE actions or holdout cases were accessed. No application test was rerun.

| Source group | Public access / observation class | Used for |
|---|---|---|
| P01 — published implementation and historical docs | Repository paths at the identified checkpoint; not all historical private raw artifacts are published | DATA/READ/WRITE boundaries, accepted limitations and reproduction instructions |
| G01 — Granite checkpoint | [Published report](../evals/reports/granite/GRANITE_EVALUATION_CHECKPOINT_V1.md) and [safe result](../evals/reports/granite/granite42_diagnostic_live_v1.json) | Separate LIVE planner and governance observations; historical failures |
| J01/J02 — Luna | [J3](J3_LUNA_5_6_RUN.md), [J4](J4_GPT6_LUNA_RUN.md), published sanitized direct-judge summaries | Contract validity and measured timing; not integrated Gateway execution or calibration |
| N01 — NVIDIA execution 10 | Private retained report, JUnit, reconciliation and ledger; source identity below | Two LIVE requests, G01 REVIEW and G02 rejection; exhausted budget |
| U01 — USAspending smoke 02 | Private retained failed-response report and evidence inventory | HTTP 200 followed by withholding/STOP; original body not retained |
| U02 — response forensics 03 | Private, unpublished offline candidate/report and JUnit | Demonstrated parser defects, 58-PASS candidate, 55-PASS/1-FAIL inherited selection; exact LIVE cause UNKNOWN |
| C03 — chat composition closure 03 | Private, unpublished candidate, JUnit, browser observations and screenshots | Guided offline DATA/READ/WRITE wiring, mock providers, actual local custody |
| B01 — Channel B | [Published matrix](research/B2B_EVIDENCE_MATRIX.md) and [006I addendum](research/B2B_MVP_006I_LOG_ACCESS_AND_CUSTODY_ADDENDUM.md) | Historical local reconciliation versus Genie-reported cloud observations |

N01, U01/U02 and C03 identities permit comparison with the owner's retained records; they are **not publicly downloadable evidence** or proof that a reader can reproduce private environments. Publication review must choose a minimal sanitized reproduction package if those local implementations become part of the submitted code. No private-path hyperlink is substituted for public evidence.

## Exact source identities rechecked for this documentation

The table identifies exact report/summary bytes. Published entries use Git object content from the checkpoint above; private entries use retained file bytes. Hashes do not authenticate a person, approve source, establish all historical network activity or attest runtime memory.

| Source ID | Artifact | SHA-256 | Visibility |
|---|---|---|---|
| `C03_ASSESSMENT` | `ASSESSMENT.md` | `66bc57d3910f31567bf1bd7bbd3259f15f2e32f972d9e7b4c9dc1476a1561d86` | Private retained source |
| `C03_VALIDATION` | `VALIDATION.md` | `7397175b3a0a97c8f8204f4d93a503470ebadf7131f4f0ea992800d9e7b24fed` | Private retained source |
| `C03_BROWSER` | `browser-observations.json` | `685b50586d28b5bcec390b1e5df19abb8da8ede87601f74ea2cd12dbd494cea9` | Private retained source |
| `C03_READONLY` | `browser-readonly-verification.json` | `86fbeddf10a0de1186fe8cd6f2c9d26582979028cb089f6f3fb6235a0a90accd` | Private retained source |
| `C03_INVENTORY` | `evidence-inventory-v1.json` | `635e59325675a71be94431a3cbd3de411f5fb911dd6ca249e2453f83155d1a72` | Private retained source |
| `NVIDIA_EXECUTION` | `NVIDIA_G01G02_LIVE_EXECUTION_REPORT.md` | `e2534541cb964a30bde929361582ca334320b143831f69cec98aaada2fd4d957` | Private retained source |
| `NVIDIA_INVENTORY` | `sha256-evidence-inventory.json` | `600b0d8338c9c91ff7c57271aef96a39303ca41dcef7853fd06029739e10eb43` | Private retained source |
| `USA_FORENSICS` | `USASPENDING_RESPONSE_FORENSICS_REPORT.md` | `5aec7b613651ab40f5c040669bf41e057a1f3c69feacb066f3f0a0dfabe0df94` | Private retained source |
| `USA_TESTS` | `test-results.json` | `f96bfa793017f24c198536755cf8c5dd2070578b9abd358d546a3b50838ca516` | Private retained source |
| `USA_FORENSICS_INVENTORY` | `sha256-evidence-inventory.json` | `8bdf29695c323b08cc8c6034634241e409dbcf6bec982d9cd05f6826e065a11a` | Private retained source |
| `NVIDIA_PROTECTED` | `source-inventory-lifecycle-v2.json` | `efc03551ec1fb019a17aa13c7e07700d65f0b20be44ac149ca6dd5c72adbe565` | Private retained source |
| `docs/GRANITE_PLANNER_LESSONS_LEARNED.md` | `GRANITE_PLANNER_LESSONS_LEARNED.md` | `cf69a61c39cb7d72f25df148caa84370e1ae5fa771a351bc9c59373fa8b1dd84` | Published Git bytes |
| `evals/reports/granite/GRANITE_EVALUATION_CHECKPOINT_V1.md` | `GRANITE_EVALUATION_CHECKPOINT_V1.md` | `5f9b7264c87f138f363a0ca696cb15ab07f2824cc6e2c38cde68ab49fe9042c3` | Published Git bytes |
| `evals/reports/granite/granite42_diagnostic_live_v1.json` | `granite42_diagnostic_live_v1.json` | `68c3c4a24247cd46e3eba7db21dea8cc7215938d36993ed002f180c86d26ab95` | Published Git bytes |
| `docs/J3_LUNA_5_6_RUN.md` | `J3_LUNA_5_6_RUN.md` | `9c90fb9f3a39000a628c9e0a04b5fc4037e1e7ca8b173806284216d2ee17c331` | Published Git bytes |
| `docs/J4_GPT6_LUNA_RUN.md` | `J4_GPT6_LUNA_RUN.md` | `39b3f6cdc59241bec0b67a8f9e577e77cb86cdd61922b21b75c6d82ccc6ba444` | Published Git bytes |
| `docs/MINI09_DATA01_EVALUATION_REPORT.md` | `MINI09_DATA01_EVALUATION_REPORT.md` | `83426052f19d948c9b683ddb67ece83dc583ac08523af1fbeb180f7999ee6442` | Published Git bytes |
| `docs/MINI09_R021_DISPOSITION_AND_SCOPE_PROPOSAL.md` | `MINI09_R021_DISPOSITION_AND_SCOPE_PROPOSAL.md` | `2cf9ed144b786695416b7c4563ca869b8eba488ff4796e79e7054a14bae77eaf` | Published Git bytes |
| `docs/MINI09_R023_TRUSTED_HOST_COMPOSITION.md` | `MINI09_R023_TRUSTED_HOST_COMPOSITION.md` | `1cafb0ea0ca53264b375635c45aa76b93e2e2eb6d9db54d30533cdacc11a4a43` | Published Git bytes |
| `docs/WRITE01_SYNTHETIC_REVIEW_V1.md` | `WRITE01_SYNTHETIC_REVIEW_V1.md` | `8cb99b2339022dc684957118f60f3b44adb431941973c9f6d25b54eb9d114194` | Published Git bytes |
| `docs/WRITE01_CP02_CHECKPOINT.md` | `WRITE01_CP02_CHECKPOINT.md` | `01bfdc2b60bbba0afdf69d8f153a4836dd60aa89a4e9b4e966ae41cf750e86af` | Published Git bytes |
| `evals/acceptances/mini10_human_acceptance_20261105.md` | `mini10_human_acceptance_20261105.md` | `852bf9e77ad7b382027047870636982a2877d2ac4e9bdd080ce9e30e645593d0` | Published Git bytes |
| `docs/research/B2B_OPEN_RISKS_AND_BLOCKERS.md` | `B2B_OPEN_RISKS_AND_BLOCKERS.md` | `7f16715e387fc0d02f5ad0a41c1352b03e3ca552862878e2729739a4a5e6e5e1` | Published Git bytes |
| `docs/research/B2B_MVP_006I_LOG_ACCESS_AND_CUSTODY_ADDENDUM.md` | `B2B_MVP_006I_LOG_ACCESS_AND_CUSTODY_ADDENDUM.md` | `f11ea1f8ebf9ef9c04870dfcc6b0a7e61b4f30f5beffd3450448017a74577a09` | Published Git bytes |
| `evals/data01/awards_v1.json` | `awards_v1.json` | `7aa5521b2cd4010d8a4e66d847eb599c5368cb92b36e1a250e54c66d88c3569d` | Published Git bytes |
| `USA_SMOKE` | `USASPENDING_LIVE_SMOKE_REPORT.md` | `81807ab667318fa2cd2d031a64197f1e7287e06fcee386c552fa0554eb66ae98` | Private retained source |
| `USA_SMOKE_INVENTORY` | `sha256-evidence-inventory.json` | `9eb30ee24950b2d0a60eba721df43bb867c73bcadba8f97f127adc8b11dffc9d` | Private retained source |

The 88 protected NVIDIA source entries were independently rehashed against inventory `efc03551ec1fb019a17aa13c7e07700d65f0b20be44ac149ca6dd5c72adbe565` for preservation. No source identity or trust anchor was changed or approved. This source-preservation check is not a fresh launcher security audit.

C03's source inventory is `5da66efebfb71f1425cfbc404c29bcae1598f707ce2c966489b54ac57995e623`; its evidence inventory is separately identified above. The six browser observations and JUnit files were inspected without running the application. Test counts are prior results, not new PASS claims.

## Submission draft inventory

Two earlier private artifacts were located and inspected at package/text level; no new slide rendering or document visual certification was performed:

- `CIVICGATE_GSA_Preliminary_Deck_2026-10-21.pptx`: 12 slides; SHA-256 `9a3d2c108431f8e02118384789161434e74e14bad47cd0f56974a19a4357da77`.
- `CIVICGATE_GSA_Preliminary_Evaluation_2026-10-21.docx`: SHA-256 `5fbacba11bbcdeeb3b0a636a2cf3a96702063f80f0b212597aab54b8b6f34bdc`.

Both include historical Channel B content. Neither is certified as the current final submission. Older build-report LIVE claims belong to their own instruments; unavailable local `artifacts/` files are not treated as newly inspected primary evidence. Current CI is not certified by this documentation task: the commit-filtered connector returned no workflow runs, which is **insufficient evidence**, not a failed-CI conclusion.

## Authorization and retained state

Historical one-time LIVE approvals remain tied to their completed/stopped experiments. The C03 proposed LIVE profiles are unapproved and their roots uninitialized. This task authorizes documentation editing only. NVIDIA's 2/2 and the USAspending smoke's 1/1 budgets remain consumed.

Durable STOP remains PARTIAL; full FAA coverage BLOCKED/SKIP; independent golden-reference acceptance PENDING; Judge calibration NOT_YET_MEASURED; USAspending LIVE HOLD; production WRITE and deployment NOT_AUTHORIZED. Holdout remains reserved/unexecuted, with historical metadata exposure retained as a limitation. No state in an older frozen report is rewritten by this register.
