# GSA evaluation gap matrix

Version 1 · November 12, 2026 · Documentation candidate; no GSA score or approval.

Authority: [official GSA hackathon guidance](https://www.gsa.gov/super-intelligence/si-community-of-practice/events-and-training/mcp-server-and-si-agent-government-hackathon), reviewed November 12; page updated November 4. The top-level judging categories are technical quality, innovation, mission alignment and presentation. The engineering checks below operationalize those categories for CIVICGATE; they are not invented GSA weights or extra mandatory deliverables.

GSA asks participants to select **one** category: Dataset Access, Service Read or Service Write. CIVICGATE voluntarily implements bounded examples of all three. WRITE is not mandatory for every entrant. The stated context is a sandbox/research prototype using public government data, without public deployment. Fictional DATA-01 fixtures test behavior but are not actual public FAA records; the project also targets the official public USAspending source, whose latest governed LIVE result remains withheld.

**VERIFIED** means evidence supports the precisely stated scope. **PARTIAL** means some evidence exists but the stated gap remains. **NOT_DEMONSTRATED** means the inspected sources do not establish it. **HOLD** means a documented restriction or failed gate remains. **NOT_APPLICABLE** means the requirement is not imposed on this submission by the reviewed page. None means production certification.

Source IDs refer to the [evidence register](GSA_EVIDENCE_REGISTER.md). Private reports are not presented as public downloads. New documents are proposed, not already merged.

## Technical quality

| Criterion / assessment check | Actual implementation and source | Status | Missing evaluation / required action | Priority |
|---|---|---|---|---|
| Readability and maintainability | Modular Python, explicit types and separated contracts; [architecture](ARCHITECTURE.md), [MCP models](../src/civicgate/mcp), C03 static checks | PARTIAL | Pin the exact submission slice and conduct focused human review; no whole-repository readability certification claimed | PRE_SUBMISSION |
| MCP names, descriptions, schemas | Four public research goals in [MCP tools](../src/civicgate/mcp/tools.py); host-specific FAA/WRITE contracts; bounded discovery | VERIFIED | Keep selected owner's tool set visible; four READ tools do not imply four tools in every WRITE context | PRE_SUBMISSION |
| Typed input/output contracts | Pydantic Proposal, tool schemas and post-result checks; [authority](AUTHORITY_MODEL.md), U02 nullable/metadata findings | PARTIAL | Keep invalid outputs withheld; full LIVE API contract compatibility remains unproven | PRE_SUBMISSION |
| Separation of concerns | Planner proposal, advisory Judge, deterministic owner, binding and adapter; [WRITE namespace](WRITE01_SYNTHETIC_REVIEW_V1.md) | VERIFIED | Explain that WRITE uses separately scoped authority, not a broadened legacy READ policy | PRE_SUBMISSION |
| Graceful failures and fail-closed behavior | C03 DENY/REVIEW/no-dispatch; U01 invalid response withheld; N01 rejection without retries | VERIFIED | Claim tested paths only; retain uncertain delivery and STOP limitations | PRE_SUBMISSION |
| Reliability under realistic concurrency/load | Bounded controls and restart probes exist; no representative operational load campaign | NOT_DEMONSTRATED | Later controlled reliability/availability measurements, outside this closeout | POST_HACKATHON |
| Performance and observed results | [evaluation summary](GSA_EVALUATION_SUMMARY.md) separates measured local/cloud latencies and rejected outcomes | PARTIAL | Keep two-case samples distinct; no hardware, throughput or SLO claim | PRE_SUBMISSION |
| Reproducibility | Published [three-case instructions](GSA_THREE_CASE_EVALUATION.md); C03 commands, JUnit and private freeze | PARTIAL | Select/publish approved minimal dependencies and reproduce exact submission snapshot; private local package is not main | SUBMISSION_BLOCKER |
| Method, inputs, outcomes and independent references | Frozen cases, SQL oracle, separately scored planner/governance; [DATA-01](MINI09_DATA01_EVALUATION_REPORT.md) | PARTIAL | Include preserved mismatches and denominators; broader natural-language coverage and independent labels remain absent | PRE_SUBMISSION |
| Security and exact-commit CI | Protected sources, documented scope guards and historical CI; [security](SECURITY.md) | PARTIAL | Verify exact submission jobs; no fresh application, dependency or security audit in this documentation task | PRE_SUBMISSION |

## Innovation

| Criterion / assessment check | Actual implementation and source | Status | Missing evaluation / required action | Priority |
|---|---|---|---|---|
| Bounded discovery distinct from authority | MCP discovery does not issue bindings; [A1 boundary](CHANNEL_A1_EXECUTION_BOUNDARY.md); [README](../README.md#mcp) | VERIFIED | Demonstrate discovery, MCP call and backend dispatch as separate events | PRE_SUBMISSION |
| Independent deterministic authorization | Favorable mock Judge cannot override REVIEW; C03 and [three cases](GSA_THREE_CASE_EVALUATION.md) | VERIFIED | Clarify deterministic independence from the model, not institutional independence | PRE_SUBMISSION |
| AuthorityEnvelope and single-use ExecutionBinding | Exact invocation binding, issuance/consumption and negative controls; [authority](AUTHORITY_MODEL.md) | VERIFIED | Present observable counts; do not imply network-level exactly-once | PRE_SUBMISSION |
| Planner and advisory Judge separation | Granite/NVIDIA planner paths; J3/J4 direct-judge history; C03 mock composition | PARTIAL | Real integrated multi-model behavior needs separate authorization/evidence | PRE_SUBMISSION |
| Governed DATA, READ and synthetic WRITE | Published DATA-01/WRITE-01; C03 integrated offline surface | VERIFIED | Label local/unpublished integration and synthetic storage; no government write | PRE_SUBMISSION |
| Durable attempt custody and evidence | N01 reservations/consumed leases; C03 local SQLite and no-refresh mutation | PARTIAL | Durable STOP remains PARTIAL; storage power-loss and hostile-host guarantees absent | POST_HACKATHON |

## Mission alignment

| Criterion / assessment check | Actual implementation and source | Status | Missing evaluation / required action | Priority |
|---|---|---|---|---|
| Access to public government information | Existing USAspending READ tools and public-data intent; U01 governed attempt failed response validation | PARTIAL | Explain useful target and demonstrated limits; another LIVE request is optional and needs separate approval | PRE_SUBMISSION |
| Accountable agent interaction | Inspectable policy reasons, bindings, provenance and withheld outcomes; C03 | VERIFIED | Show one authorized and one withheld path with the original question | PRE_SUBMISSION |
| Correct FAA scope | [R02.3](MINI09_R023_TRUSTED_HOST_COMPOSITION.md) isolates FAA awarding-subtier synthetic scope under DOT | PARTIAL | Full FAA new-award/transaction/live semantics remain unsupported; 54 definitions BLOCKED/SKIP | POST_HACKATHON |
| Public-sector reuse and operational value | Modular design and [ROI methodology](POTENTIAL_VALUE_AND_ROI.md) | NOT_DEMONSTRATED | Reuse and labor-saving hypotheses need a measured pilot; no agency endorsement/adoption claim | POST_HACKATHON |
| Research versus operational system | Clear synthetic storage, restricted LIVE experiments and no production deployment | VERIFIED | Retain labels and explicit authority boundaries in all submission materials | PRE_SUBMISSION |

## Presentation and deliverables

| Official criterion / deliverable | Evidence / current state | Status | Required action | Priority |
|---|---|---|---|---|
| Understandable explanation and architecture | Updated [README](../README.md), Channel A diagram, concise thesis | VERIFIED | Owner review of documentation candidate | PRE_SUBMISSION |
| Demonstration narrative and functional MCP evidence | Published three-case baseline; C03 six genuine offline observations and four-minute private rehearsal | PARTIAL | Finalize the exact recorded/live-local demo and fallback with truthful labels | PRE_SUBMISSION |
| Documented complete MCP code on GitHub | Public main `ced2628e4e447bf8ee8de478ad1257c0a3a2a1f6`; latest C03 changes outside repository | PARTIAL | Choose a reproducible published scope or separately approve publication of a reviewed local candidate | SUBMISSION_BLOCKER |
| Presentation: problem, solution, technical approach, demo | Located October 21 preliminary PPTX, 12 slides, historical Channel B content | PARTIAL | Update and visually review the final deck against selected evidence and official instructions | SUBMISSION_BLOCKER |
| Evaluation documentation: methodology, metrics, security, lessons, recommendations | Existing reports plus [current summary](GSA_EVALUATION_SUMMARY.md); older Word draft | PARTIAL | Owner-review final evaluation artifact/template; retain failures and limitations | SUBMISSION_BLOCKER |
| Independent video file | Not a separate requirement on reviewed official page | NOT_APPLICABLE | Record if useful; check any later organizer-specific submission instructions | PRE_SUBMISSION |
| Public deployment / operational certification | Excluded from prototype scope | NOT_APPLICABLE | Do not add deployment work to close this documentation task | POST_HACKATHON |
| Submission handoff and eligibility/category details | No submission receipt or current private organizer instruction reviewed | NOT_DEMONSTRATED | Owner verifies hand-in route and participant/category requirements before Nov 20 | SUBMISSION_BLOCKER |

The submission can tell a credible, bounded offline story without a perfect or continuously running LIVE system. New LIVE execution is a separate decision, not a way to conceal unsupported claims. See the [prioritized checklist](GSA_SUBMISSION_CHECKLIST.md) and [technical debt](TECHNICAL_DEBT.md).
