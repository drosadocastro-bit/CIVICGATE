# B2B-FAA-C1 — controlled awarding-subtier Gateway integration

Status: PROPOSED_FOR_HUMAN_REVIEW. Local synthetic implementation only.
Cloud deployment HOLD. Git publication HOLD. Builder verification is not human approval.

## Baseline, isolation and recovered evidence

Verified and fetched origin/main: 94692596503601bc53d0358faf659afb260c69be.
New branch: feat/b2b-faa-c1-integration.
New worktree: LOCAL_INTEGRATION_WORKTREE.
No reset, rebase, clean, staging, commit, push, PR, merge or main checkout change.

The older codex/b2b-faa-c1-integration candidate at ad4a53a42912b7fefdff2ad082dc71722cbe4662 remains unchanged. Its twelve recorded candidate identities and seven research references were independently checked before reuse. All five authorized shared modules in current main matched that candidate's original before hashes. The recovered implementation is adapted onto current main, not a replacement of the older research.

The original FAA-001 and FAA-002 query model, characterization, blocker tests and negative controls are already in current main and remain byte-identical. The specialized FaaScopeV1 query schema and class AST match the preserved experimental contract. The two original negative assertions remain ordinary FAIL under the default legacy Gateway; they were not edited, xfailed or renamed.

Before-change inventory: 241 tracked files in the new worktree; 884 recorded files across four preserved worktrees and 624 external historical files. Preservation covers the recorded inventory, not every ignored file on disk.

Evidence directory:
PRIVATE_ORIGINAL_EVIDENCE_DIRECTORY

## Exact protected changes and trusted composition

Only five pre-existing runtime files change:

| File | Narrow change |
| --- | --- |
| src/civicgate/mcp/tools.py | Optional trusted contract at construction; use its schema for full input validation, policy, binding reload, find routing and result validation. |
| src/civicgate/governance/execution.py | Retain the selected immutable registry and pass the same contract to the existing deterministic evaluator. Existing private issuance, consumption, lifetime and binding checks remain. |
| src/civicgate/governance/policy.py | Optional full-scope validation and selected-schema propagation; no replacement policy, hard-denial or threshold change. |
| src/civicgate/governance/request_risk.py | Match recognized agency literals against the selected typed model; unsupported recipient relationships require review. No new language heuristics. |
| src/civicgate/mcp/discovery.py | Validate the selected four-schema registry and snapshots; discovery remains metadata only. |

InvocationContract is a frozen startup value with an immutable registry, captured schema identities and fixed callbacks. Its new module resides in channel_b/invocation_contract_v1.py; the earlier reference's governance/contracts.py is not created or changed. Three other models remain legacy. The value supplies no policy decision and issues no authority.

No caller, model or MCP argument can choose the composition. The request's version/role/tier/parent constants must match the trusted model; an alternative or extra field is rejected rather than dropped. The host is trusted: hostile arbitrary Python code, private-member replacement or a replaced adapter is outside this procedural boundary. Hash equality alone is not authenticated authority.

Omitting the contract retains the legacy path. The five shared file bytes change by explicit authorization; default behavioral compatibility must not be confused with byte identity of those five files. BoundedMCPServer, B2a http_app.py, shared models/envelopes, authority.py, global TOOLS, dependencies and README are unchanged.

The new FaaC1HTTPApp reuses the unchanged loopback B2a ingress, synthetic identity verification and local SQLite custody. This is a local stateful HTTP reference composition, not the stateless Databricks deployment or PostgreSQL integration. No deployed smoke composition is enabled. There is no channel failover.

## Complete trusted query contract

Trusted composition identifier: CHANNEL_B_FAA_C1_V1.
Query identifier: B2B-FAA-001-C1-v1.
The existing deterministic operation scope remains PUBLIC_SPENDING_RESEARCH; complete query arguments and selected model schema bind its FAA specialization.

All eighteen query fields are required; unknown fields fail:

| Fields | Required value or bound |
| --- | --- |
| contract_version | B2B-FAA-001-C1-v1 |
| method; endpoint | POST; https://api.usaspending.gov/api/v2/search/spending_by_award/ |
| awarding_agency | Federal Aviation Administration |
| agency_type; agency_tier | awarding; subtier |
| agency_toptier_name | Department of Transportation |
| fiscal_year | Explicit integer 2008 through 9999 |
| start_date; end_date | Exactly prior October 1 through selected September 30 |
| date_semantics | AWARD_SEARCH_DEFAULT_OVERLAP |
| award_types | Explicit, unique, nonempty selection from A/B/C/D/02/03/04/05/06/09/10/11 |
| page; limit | Page 1; explicit integer limit 1 through 100 |
| subawards | Explicit false, prime awards only |
| response_fields | Exact ordered projection in the payload below |
| sort; order | Award Amount; desc |

A synthetic FY2025 example is test input, not a newly authorized human query.
The exact observed MockTransport payload is:

~~~json
{
  "fields": [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Funding Agency",
    "Funding Sub Agency",
    "generated_internal_id"
  ],
  "filters": {
    "agencies": [
      {
        "name": "Federal Aviation Administration",
        "tier": "subtier",
        "toptier_name": "Department of Transportation",
        "type": "awarding"
      }
    ],
    "award_type_codes": [
      "A",
      "B",
      "C",
      "D"
    ],
    "time_period": [
      {
        "end_date": "2025-09-30",
        "start_date": "2024-10-01"
      }
    ]
  },
  "limit": 20,
  "order": "desc",
  "page": 1,
  "sort": "Award Amount",
  "subawards": false
}
~~~

The preserved official search-filter snapshot is SHA-256
843353f954e8524296dfaf7369ff04996702a03dfb30ad2caa108489bc7be776.
The preserved spending-by-award contract snapshot is
69d3262a78e91d60a78121a73808b5e2dff457a32fa91b1f8378accea6ea8348.
Both were rehashed against the original 2026-10-19 retrieval inventory. The latter explicitly defines subtier plus toptier_name and the requested awarding/funding fields. This is verification against preserved documentation, not a current live API probe.

[Official filter reference](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/search_filters.md);
[official search reference](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md).

## Query, policy, authority, dispatch and result

1. The agent proposes a bounded query; immutable trusted startup selection determines the permitted schema/constants.
2. Strict validation retains the complete effective query in PolicyFacts.arguments_json.
3. The original deterministic policy evaluates the original request, effective scope and advisory signals. No model or discovery response issues authority.
4. Only PERMIT can obtain the existing private process-local AuthorityEnvelope and exact ExecutionBinding. The binding includes schema, full arguments, operation scope, policy facts and decision.
5. The local HTTP journal acknowledges intent before consumption; its source snapshot includes uncommitted/new Python modules, not just HEAD.
6. Consumption checks object origin, context, exact arguments/schema, age and single use immediately before dispatch. The adapter receives the consumed arguments and deterministically renders the same complete scope.
7. One synthetic HTTP attempt occurs. Both adapter and Gateway validate attribution/provenance before releasing a verified record. No result-triggered query expansion, redirect, pagination, fallback or retry occurs.

The original user_request remains a trusted-local-host input, not cryptographically authenticated human intent. No general natural-language FY parser was added. The effective proposed FY is validated and policy-visible; matching a human's arbitrary prose remains a separate semantic limitation.

Exact examples are in 19-query-policy-binding-dispatch-traces.json:

| Scenario | Initial authorization | Mock dispatches | Final observation |
| --- | --- | ---: | --- |
| FAA awarded; funding another subtier | PERMIT | 1 | PERMIT, RESULT_VERIFIED |
| Other DOT awarding subtier; FAA funding | PERMIT | 1 | REVIEW_REQUIRED, FAILED_VALIDATION, result absent |
| Hard-denied governmental action | DENY | 0 | No binding or backend request |
| Explicit other-agency request | REVIEW_REQUIRED | 0 | No binding or backend request |
| Response lost before headers | PERMIT | 1 | Original PERMIT retained, RESULT_UNKNOWN, DISPATCH_UNKNOWN, RETRY_BLOCKED |

Real local SDK tests additionally verify durable intent, rejection of a second call and restart HOLD after uncertainty. Complete HTTP rejection and partial response are distinguished from a pre-header transport interruption. An authorized read is never retroactively described as no dispatch.

## Attribution and response limits

A nonempty verified page requires Awarding Agency exactly DOT and Awarding Sub Agency exactly FAA. Both funding fields remain separate and required. FAA funding with non-FAA awarding is rejected; funding FAA also requires DOT as funding parent. Other funding hierarchies are preserved as reported strings, not independently catalogue-authenticated.

Missing/null critical attribution or identity, excess rows, wrong page/limit, contradictory truncation, duplicate JSON keys/award IDs, non-finite amounts, upstream warnings and unsupported fields withhold the entire result. No row salvage or metadata repair occurs. Unexpected query award types are denied before dispatch; an unrequested returned Award Type field is rejected as response drift. The fixed projection does not independently re-prove every returned record's FY/type membership.

Optional/null agency_slug, awarding_agency_id, recipient_id and documented page cursors are non-authoritative metadata. The upstream contract permits some critical fields to be null; this candidate deliberately withholds those responses. Live response compatibility, especially different award categories, remains unverified.

An empty page makes no completeness claim. A truncated page remains one page. Award Amount is never labeled FY obligations or total FAA spending. Only SYNTHETIC_TEST_FIXTURE provenance is accepted by this adapter. Fingerprints establish object/query consistency, not authenticated government origin. Construction requires exactly httpx.MockTransport; there is no live backend entrypoint.

## Actual verification

| Check | Result |
| --- | --- |
| Before-change full tests on verified main, Windows/Python 3.13.7 | 2491 PASS, 0 FAIL, 1 SKIP; two existing malformed-planner Pydantic warnings |
| Candidate full regression | 2679 PASS, 0 FAIL, 1 SKIP; same two malformed-planner warnings; 438.15 seconds |
| Same baseline test IDs and outcomes | PASS: all 2492 baseline nodes retain their outcomes; 188 added nodes pass; none missing |
| FAA focused Gateway, real local MCP HTTP and new independent controls | 188 PASS, 0 FAIL, 0 SKIP |
| Legacy explicit differential | Four schemas/discovery and ten Gateway response/policy/wire cases exactly match; only random request_id and retrieval time excluded |
| FAA-001/002 characterization and historical blocker tests | 219 PASS; one preserved malformed-provenance fixture warning |
| Unchanged FAA-001 required-property negative controls | 2 FAIL; same legacy toptier and attribution causes |
| Compatible Linux/Python 3.11.17 subset | 469 PASS, 0 FAIL, 0 SKIP; one historical fixture warning |
| Ruff and formatting | PASS; 208 Python files checked/formatted |
| Mypy | PASS; 63 source files |
| Installed dependency consistency | PASS |
| Final scope/preservation verification | PASS: 884 files across four original worktrees and 624 external historical files retain their hashes; 236 non-authorized baseline files unchanged; index empty |

The focused total includes 109 recovered Gateway/MockTransport cases, 14 local SDK HTTP cases and 65 new independent controls. The 65 include 36 manually specified exact-wire cases spanning three FYs and all twelve permitted award codes, last-gate tampering, cross-version issuer isolation, unsupported fields and complete/partial HTTP outcomes.

The complete-suite XML comparison, preserved in 25-regression-comparison.json, establishes these unchanged subsets. These counts overlap the full run and must not be added to it:

| Existing family | Before PASS | After PASS | Changed outcomes |
| --- | ---: | ---: | ---: |
| A1 boundary and discovery | 76 | 76 | 0 |
| A2 orchestration, stdio and client | 89 | 89 | 0 |
| R1 containment, semantics, literal and argument consistency | 721 | 721 | 0 |
| B2a HTTP and recovery | 50 | 50 | 0 |
| B2b P0.1 admission / P0.2 stateless | 166 | 166 | 0 |
| Synthetic PostgreSQL ledger, fencing, history and transport guard | 247 | 247 | 0 |

The unchanged SKIP is test_dpapi_edge_refuses_non_windows on Windows. Historical experiment FAILs are separate from the ordinary tests/ suite; zero failures in that suite does not erase them.

Overlapping targeted, full and Linux runs are not summed as independent observations. The ordinary full test path is tests/; the two FAA negative assertions under experiments/ were explicitly run separately and preserved as FAIL.

Windows environment: Python 3.13.7, MCP 1.30.0, Pydantic 2.13.5, httpx 0.28.1, LangGraph 1.2.15, pytest 9.1.1, Ruff 0.16.8, Mypy 2.3.1. No dependency changes or installs.

Linux used cached image sha256:e2ba71a30941a2df449bc674565ac3078dae60007dc72628e0f6ba0730c9c77d, read-only source, read-only root and network=none. It contains Python 3.11.17/MCP 1.30.0 but no Git. Tests importing real Git identity/custody were not run there; no fake Git or revision was substituted. Actual SDK HTTP/custody is verified on Windows only. Docker Desktop was initially stopped, started for these local checks and stopped afterward.

Development lint findings (draft import grouping and the recovered projection helper's loop capture/formatting) remain in 05 and 07 logs. The task-owned helper was corrected; no historical file or failed result was rewritten.

The final documentation check initially mistook the substring PENDING_ inside PUBLIC_SPENDING_RESEARCH for an unfinished report marker. That check failure is retained in 28; the final check uses the exact placeholder names. No runtime or test change resulted.

## Reproduction and review boundary

From this worktree with its src and repository root in PYTHONPATH:

~~~powershell
python -B -m pytest tests/mcp/test_faa_c1.py tests/mcp/test_faa_c1_http.py tests/mcp/test_faa_c1_controlled_acceptance.py -q -p pytest_asyncio.plugin -p no:cacheprovider
python -B tests/mcp/faa_legacy_projection.py
python -B -m pytest tests -q -p pytest_asyncio.plugin -p no:cacheprovider
python -B -m pytest experiments/b2b_faa_001/contract_gap_counterexample.py -q -p pytest_asyncio.plugin -p no:cacheprovider
~~~

The last command intentionally returns nonzero for the unchanged legacy negative properties. Use fresh evidence/temp directories and the recorded environment; do not overwrite earlier logs.

No real PostgreSQL server, SDK 2.x experiment, cloud endpoint, model inference or USAspending request was executed. Applicable synthetic PostgreSQL/transport regressions are part of the full tests; original G1/G2, HeaderMismatch, FAA failures, J3/RQ6 and earlier research remain preserved. These synthetic results do not certify distributed fencing or production durability.

Human review should assess the five default-preserving seams, strict response subset and separate local HTTP composition. Future cloud integration still needs independently supported identity, durable journal, deployment approval and live response compatibility. This task grants none of those.

Recommendation: proceed to independent human technical review of this local synthetic candidate. The prior worktrees, all recorded historical identities and all tested code bytes remain unchanged except for the five explicitly authorized files in the new worktree. This is builder verification, not independent acceptance or production readiness.

FAA-C1 GATEWAY INTEGRATION: VERIFIED (local synthetic scope)
CHANNEL A DIFFERENTIAL: PASS
FAA ATTRIBUTION: VERIFIED SYNTHETIC
HISTORICAL EVIDENCE: PRESERVED (recorded inventory)
CLOUD DEPLOYMENT: HOLD
GIT PUBLICATION: HOLD

## Source identities

The original candidate and scientific files are unchanged. Below are measured candidate bytes; absent before means new in the current integration worktree. The external final-candidate-identities.json also measures this report itself after completion.

| Relative path | Before SHA-256 | After bytes | After SHA-256 |
| --- | --- | ---: | --- |
| src/civicgate/channel_b/faa_adapter_v1.py | NEW | 7787 | 4a5648d648373bb05f43c936c1b79c122b613b89eeb5cc54322fc3e1d3a67de1 |
| src/civicgate/channel_b/faa_http_v1.py | NEW | 5373 | e764ee526222ba862ef77d287e09627d09d3b8bad7d2599d48f13eeeb99ffd41 |
| src/civicgate/channel_b/faa_profile_v1.py | NEW | 11837 | ffd9db9b7ecaa047becd7503b8178fef30796a2fb413e500361eb781e9508752 |
| src/civicgate/channel_b/invocation_contract_v1.py | NEW | 2494 | a8862ac66c9e2c7adc61fe78a560121bb9c9b9ad3398a34311141e7c67a5f968 |
| src/civicgate/governance/execution.py | ef9b993940f5abf6b292c598494d2811914513db71f2c5abf9d0fab0c7583ce1 | 13332 | cd75f40bbc3addb343a4127c377b73b7ff90cb12972dca7d4cd9c881a08599fc |
| src/civicgate/governance/policy.py | f850dfc7565dd3111379adbb4ba43cfde3550a7ccdaff362bbc5bc94c32c26fc | 3681 | 50204b8374528c2f902153d9d1be83c623152d1874a754663bd3d2399549ba24 |
| src/civicgate/governance/request_risk.py | 8760a5354479afa8ad60e77c6e68b7ee8a2bdebeb2507ec10779daf2dba25057 | 9903 | 242d51e5b674666cc7d8aa1c5115a74372b24afcd1fa3661c8d8ca3c893ae08f |
| src/civicgate/mcp/discovery.py | 47cc497223a76da648b1c05cfd2ad6bf076804e87b1140b2761df6dc1157d55e | 5221 | 18a618589bbf53543d1e21f51f4fcc1d2466d174ea8cb02b707c0aabcce2a686 |
| src/civicgate/mcp/tools.py | 1e0efe77959a221a95c0188dac817d807c919fa74e41c59215f1d163ad3412a1 | 23424 | db025fda046a8dcd85f4af2ea37332f90a532740cdf7551b9a0e8c50603c0eb8 |
| tests/mcp/faa_legacy_projection.py | NEW | 3207 | 867a338330c8283105b7738523bc8abaf869d074f2403d9f53856f94d72af533 |
| tests/mcp/test_faa_c1.py | NEW | 19574 | 0faa83bd1c3378c2f23a8becf8d0bebc8aa9e699c76f846e8c4cdb6d54ded239 |
| tests/mcp/test_faa_c1_controlled_acceptance.py | NEW | 8087 | 86fcc00764f0562bb57039e1b461922055c28283386bd6ccb94d5998ca0b2a43 |
| tests/mcp/test_faa_c1_http.py | NEW | 8862 | f638dc73d2fe0dcb17564e6171b6bb9b960fe9161eb28396147e743c6fdddfc1 |

> R4 editorial notice: This is a publication-sanitized derivative of an unchanged private original (SHA-256 f7a914b5f3de208ddbfc94590c529fc1ae1061a0c2868d1529974c9a818a6a97). Only private filesystem references were replaced with non-runnable documentary labels. All technical content and historical results remain unchanged; these results describe the original runs, not fresh R4 verification. Current scope and evidence limits are recorded in review/EVIDENCE_BOUNDARIES.md.
