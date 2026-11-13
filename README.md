# CivicGate

[![CI](https://github.com/drosadocastro-bit/CIVICGATE/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/drosadocastro-bit/CIVICGATE/actions/workflows/ci.yml?query=branch%3Amain)

> CIVICGATE is not designed to make AI agents more powerful. It is designed to make their authority explicit, bounded, and verifiable.

## Executive summary

CIVICGATE is a local research prototype for governed MCP tool use. An AI planner proposes an action; an advisory Judge assesses it; deterministic policy authorizes, denies or holds it. Only an exact, single-use ExecutionBinding permits backend dispatch. The interface exposes the decision, execution and evidence. The project demonstrates synthetic data access, public-data READ contracts and a separate synthetic review-state WRITE, while preserving failed experiments and known limits. **Discovery is not authority.**

Documentation reviewed November 12, 2026 for the November 20 GSA submission. This is a **documentation candidate**, not deployment approval. As of November 13, 2026, remote `main` was verified at `732aae05e2a627352a7a3e88f30cc1e126410b20`; this is a dated baseline reference, not a claim about the current HEAD. The latest integrated chat candidate remains local and unpublished. No new LIVE execution is authorized by this README.

[![CIVICGATE Evidence Console displaying a recorded offline REVIEW_REQUIRED observation with zero bindings and zero backend operations](docs/images/civicgate-offline-review-required.png)](docs/images/civicgate-offline-review-required.png)

*Recorded offline/synthetic UI from the local, unpublished C03 candidate. The right panel shows a previous `REVIEW_REQUIRED` observation: **0/0 bindings and zero backend operations**. The left form is an unsubmitted draft, not the request that produced that result. Planner and Judge responses were mocked; `CLOSED` means documentary custody, not human acceptance. Captured by the project owner from a read-only preview; no new execution was started for this image.*

## Contents

- [Problem and purpose](#problem-and-purpose)
- [MCP server and tools](#mcp)
- [Capabilities and publication status](#capabilities-and-publication-status)
- [Architecture — local Channel A](#architecture--local-channel-a)
- [Deterministic governance](#deterministic-governance)
- [Planners and advisory Judge](#planners-and-advisory-judge)
- [Demonstration and reproduction](#demonstration-and-reproduction)
- [Evaluation results](#evaluation-results)
- [Security and known limitations](#security-and-known-limitations)
- [Potential ROI](#potential-roi)
- [Technical debt](#technical-debt)
- [AI-assisted development and human oversight](#ai-assisted-development-and-human-oversight)
- [Lessons learned](#lessons-learned)
- [Submission artifacts](#submission-artifacts)
- [Preserved implementation reference](#preserved-implementation-reference)

## Problem and purpose

Discovering an MCP tool does not establish permission to use it. A plausible model proposal can still express an unsupported scope, prohibited action or incomplete request. CIVICGATE makes those boundaries observable: original intent, typed inputs, host-selected owner, policy reasons, binding, backend outcome and result verification.

The contribution is the separation and demonstration of those controls. A favorable Judge, HTTP 200 or a well-formed model response cannot create authority. The intended public-sector value is accountable access to public information and reviewable actions, not autonomous government decision-making or proven operational savings.

## MCP

Run `.\.venv\Scripts\civicgate-mcp`, or configure an MCP host with:

```json
{
  "mcpServers": {
    "civicgate": {
      "command": "python",
      "args": ["-m", "civicgate.mcp.server"],
      "env": {"CIVICGATE_AUDIT_PATH": "audit/trace.jsonl"}
    }
  }
}
```

Pass model configuration in the host environment to enable semantic assessment. Missing configuration yields REVIEW_REQUIRED. Each tool takes `user_request` (the original request) and a validated `query` object. Clients cannot submit trusted judge signals, capability claims or policy decisions. Protocol-invalid requests return MCP `isError`; valid tool invocations return the common structured envelope.

| Tool | Goal |
| --- | --- |
| `find_federal_awards` | Retrieve a bounded award page |
| `get_federal_award` | Look up a known internal or generated award ID |
| `resolve_federal_recipient` | Present public identity candidates for clarification |
| `summarize_federal_spending` | Sum award amounts from one authorized returned page |

Limits: up to 100 awards, 25 recipient candidates, one page, date interval at most 367 calendar days. Searches require a recipient, agency or state filter. `state_code` means **place of performance**, not recipient address. Defaults cover contracts; selected non-loan assistance types are supported. Loans and IDVs are intentionally excluded from this first amount-aggregation contract.

Award totals are not fiscal-year transaction spending. A date filter finds matching awards; their award amounts may cover multiple years. Truncation is explicit and summaries never claim a population total. Name matches do not establish legal identity.

## Capabilities and publication status

GSA asks entrants to select **one** of Dataset Access, Service Read or Service Write. CIVICGATE voluntarily developed bounded examples of all three; that is a project choice, not an additional contest requirement. See the [official-criteria gap assessment](docs/GSA_EVALUATION_GAP_MATRIX.md).

| Capability | Implemented and evidenced scope | Publication / boundary |
|---|---|---|
| DATA-01 | 40 immutable fictional awards; separate SQL reference; host-selected FAA/FY2026/PR synthetic contract | Published evaluation components. FAA awarding subtier under DOT, PR **place of performance**, synthetic award-date semantics. Full FAA contract remains blocked. |
| Service READ | `find_federal_awards`, `get_federal_award`, bounded recipient resolution and summary in the original READ owner | Published MCP/Gateway implementation. Synthetic success is distinct from public API success. |
| USAspending V2 integration | One governed search received HTTP 200 but failed result validation; no validated records released | Local integration/forensic candidate, **LIVE HOLD**. Strict offline correction is not yet a successful LIVE result. |
| WRITE-01 | Update fictional award review status and append a note in a separate local SQLite overlay; exact host approval, expected version and idempotency | Published experimental namespace, synthetic-only. Original dataset unchanged; no real payment, award decision or government write. |
| Evidence Console and MINI10 Chat | FastAPI views, explicit synthetic actions, evidence inspection, mock Advisor and bounded READ chat | Published baseline. GET refresh does not grant execution authority; original MINI10 Chat does not enable WRITE. |
| Latest guided chat composition | Existing Console + actual A2/MCP with DATA/READ/WRITE owners, provider parsers under mocks and six observed synthetic scenarios | **Local, unpublished CHAT-COMPOSITION-CLOSURE-03**. Its governed WRITE UI is a separate candidate, not silently enabled in published MINI10. |

Dataset access and READ are distinct from a review-state mutation. An awarding agency is distinct from a funding agency; reported award amounts are distinct from fiscal-year obligations, outlays or physical performance. No FAA-to-DOT scope widening is permitted. [DATA-01](docs/MINI09_DATA01_EVALUATION_REPORT.md), [FAA host boundary](docs/MINI09_R023_TRUSTED_HOST_COMPOSITION.md), [WRITE-01](docs/WRITE01_SYNTHETIC_REVIEW_V1.md).

## Architecture — local Channel A

```mermaid
flowchart TB
    UI["Existing local FastAPI Console / MCP host"]
    OWNER["Trusted host selects contract and owner"]
    GRAPH["Optional LangGraph A2<br/>intake - discovery - planner - gateway - result"]
    MCP["MCP SDK stdio / JSON-RPC<br/>bounded discovery and typed invocation"]
    GW["Deterministic Gateway / selected authority<br/>PERMIT / DENY / REVIEW_REQUIRED"]
    JUDGE["Advisory Judge<br/>mock in current integrated rehearsal"]
    BIND["AuthorityEnvelope + exact single-use ExecutionBinding"]
    DATA["Authorized DATA / READ adapter<br/>synthetic in rehearsal"]
    WRITE["Dedicated WRITE-01 adapter<br/>synthetic SQLite review state only"]
    CHECK["Post-result validation"]
    EVIDENCE["Evidence Console<br/>policy, binding, dispatch, result, custody"]
    UI --> OWNER
    OWNER --> GRAPH
    OWNER -->|"direct governed client"| MCP
    GRAPH --> MCP
    MCP --> GW
    JUDGE -.->|"advises; cannot authorize"| GW
    GW -->|"PERMIT only"| BIND
    BIND -->|"selected READ scope"| DATA
    BIND -->|"separate exact WRITE approval"| WRITE
    DATA --> CHECK
    WRITE --> CHECK
    CHECK --> EVIDENCE
    GW --> EVIDENCE
    BIND --> EVIDENCE
```

The diagram shows the current **local composition design**, combining published owners with the unpublished integrated UI path. One host-selected owner governs an invocation; it is not an agent-selected route or a recursive multi-tool loop. The original READ path discovers four tools; dedicated WRITE has its own bounded contract. Direct MCP calls still enter the governed owner. The local host and installed code remain trusted assumptions.

Databricks/Channel B is historical and deferred, not an active branch or automatic failover. Preserve the [B2b evidence matrix](docs/research/B2B_EVIDENCE_MATRIX.md), [open risks](docs/research/B2B_OPEN_RISKS_AND_BLOCKERS.md) and [Genie-reported observations](docs/research/B2B_MVP_006I_LOG_ACCESS_AND_CUSTODY_ADDENDUM.md).

## Deterministic governance

PERMIT can issue a binding only for the exact authorized invocation. The binding must be consumed before adapter dispatch. Pre-dispatch DENY and REVIEW_REQUIRED produce zero authorized backend dispatches. Post-result validation can still withhold an invalid result after PERMIT; the public API failure demonstrated this distinction.

The host fixes the authorization context before discovery. A planner cannot choose a weaker owner, supply approval or convert a favorable Judge signal into execution permission. Evidence custody is separate: **CLOSED means documentary closure, not human acceptance**. [Authority model](docs/AUTHORITY_MODEL.md), [execution boundary](docs/CHANNEL_A1_EXECUTION_BOUNDARY.md).

## Planners and advisory Judge

| Component | Verified role and result class | Current limit |
|---|---|---|
| IBM Granite | Real local planner experiments; latest 4.2 **Q4_K_S** diagnostic: exact planner **1/2**, with two authorized synthetic dispatches | Metadata-correlated local admission; not a general accuracy/hardware claim or new inference permission |
| NVIDIA Nemotron | Historical native-tool planner experiment: exact **1/2**; G01 held by Gateway, G02 ambiguous before Gateway | Two-attempt budget exhausted. UI evidence is historical; no new request authorized |
| Luna | Advisory Judge adapters and separate historical J3/J4 direct-assessment runs | Current integrated rehearsal uses mocks. Independent semantic calibration remains unmeasured |
| Claude Evidence Advisor | Separate read-only evidence analysis capability, mock-verified in the published Console | It is not the policy Judge and cannot issue bindings, call MCP or close custody. No real Claude analysis is claimed here |

The newer integrated mock composition does not prove a real Granite/Nemotron + Luna session. Current provider access and a new experimental budget require separate admission and human approval. [Full evaluation summary](docs/GSA_EVALUATION_SUMMARY.md).

## Demonstration and reproduction

Use a bounded narrative: **PERMIT → DENY → REVIEW_REQUIRED**. Show the original question, selected tool/arguments, advisory signal where invoked, policy reason, binding counts, actual dispatch or its absence, result validation and custody. A permissive mock Judge does not remove REVIEW_REQUIRED.

For the **published synthetic READ baseline**, follow [MINI07.2/CP1.2 three-case evidence and instructions](docs/GSA_THREE_CASE_EVALUATION.md), [interactive Console](docs/GSA_MINI081_INTERACTIVE_SYNTHETIC_E2E.md) and [MINI10 READ Chat](docs/MINI10_GOVERNED_CHAT.md). Use their stated worker/Console environments and fresh private output directories. Source-pinned historical tests must retain their own mapped sources; do not assume all historical suites run against arbitrary new files.

For the **unpublished C03 integrated rehearsal**, the private package records six genuine offline observations: DATA, READ, synthetic WRITE, DENY, REVIEW and separately authorized overlay READ. Supported prompts are guided examples; edited unsupported intent is held. Its exact package and reproduction path need separate publication review. Genuine captured screenshots provide a labeled fallback; no approved public demo URL is available. Do not present captured evidence as fresh inference.

## Evaluation results

| Evidence class | Preserved observation | What it establishes |
|---|---|---|
| Published MINI07.1 | Three successful synthetic decision scenarios, reported separately from historical suites | Actual MCP/Gateway demonstration with scripted planner/Judge |
| Latest local C03 | Six genuine offline browser observations; worker 44 PASS, affected final profile 22 PASS, UI 4 PASS, as separate overlapping selections | Tested local wiring and custody; no real-model quality claim |
| Granite 4.2 diagnostic | Planner exact **1/2**; **2 PERMIT, 2 consumed bindings, 2 synthetic dispatches** | Local model integration and separate governance observations |
| NVIDIA G01/G02 | Planner exact **1/2**; G01 REVIEW_REQUIRED / REQUEST_INTENT_UNRESOLVED; G02 NVIDIA_AMBIGUOUS_RESPONSE; zero dispatch | Real bounded cloud responses, not successful execution of both tasks |
| USAspending smoke | HTTP 200 / 1,988 bytes, PERMIT/binding 1/1, then FAILED_VALIDATION → STOP; original **9 PASS / 1 FAIL** retained | Invalid result withholding; exact original response cause remains UNKNOWN |

See [methodology, latency/token measurements, failures and limitations](docs/GSA_EVALUATION_SUMMARY.md) and [source identities](docs/GSA_EVIDENCE_REGISTER.md). HTTP 200 is not planner success. Test counts are not independent semantic samples and overlapping selections must not be added. The judge-facing summary does not rescore frozen oracles.

## Security and known limitations

- **Durable STOP: PARTIAL.** No production, power-loss, hostile-host or distributed exactly-once certification.
- **USAspending LIVE: HOLD.** New inference, production WRITE and deployment remain unauthorized by this closeout. Historical one-time approvals are not ongoing execution permission.
- The **54 full FAA definitions remain BLOCKED/SKIP**. The scoped synthetic contract does not establish new-awards-only or fiscal-year transaction semantics.
- Independent golden-reference acceptance is **PENDING**; Judge calibration is **NOT_YET_MEASURED**. Holdout remains reserved and unexecuted; historical metadata exposure is disclosed.
- The current integrated candidate is unpublished and has only guided mock-provider observations. Known historical DATA-01, platform and timer failures remain recorded.
- SecretProvider/DPAPI is explicitly injected. Encrypted storage stays outside the repository; decrypted keys may exist in active provider memory. [Configuration details](#configuration-and-windows-credential-storage) remain specific to the implementation.

## Potential ROI

The potential value is less repeated integration and lookup work, clearer authorization review and faster diagnosis of withheld operations. Those benefits are not measured savings. [ROI methodology and sensitivity table](docs/POTENTIAL_VALUE_AND_ROI.md) show all assumptions, costs, a negative case and break-even case. No FAA productivity improvement or validated financial return is claimed.

## Technical debt

The [versioned debt register](docs/TECHNICAL_DEBT.md) separates submission work, accepted limitations and later research. It reconciles earlier risk records instead of rewriting failures or quietly treating HOLDs as closed.

## AI-assisted development and human oversight

**Daniel Rosado Castro** owns research direction, scope, authorization and final accountability. **Codex** contributed implementation, tests, repairs and evidence preparation; **Nova (GPT-6 Sol)** contributed technical review and research guidance. **Vela (Muse)** contributed repository review and Channel B work; **Genie Code** was the Channel B Databricks builder. The [collaboration record](docs/AI_ASSISTED_DEVELOPMENT.md) distinguishes owner-confirmed attribution, tool-executed evidence and documented limits.

**Human direction → AI implementation → testing → AI-assisted review → corrective work → human acceptance.** AI review is advisory, not independently accredited human auditing. **Builder ≠ Reviewer ≠ Authority.** No agency or vendor endorsement is implied.

## Lessons learned

Failed integrations taught the project to distinguish model structure, semantic correctness, authorization and verified execution; preserve uncertain sends; and use versioned fixes without changing original experiments. [Granite lessons](docs/GRANITE_PLANNER_LESSONS_LEARNED.md), [FAA scope findings](docs/MINI09_R021_DISPOSITION_AND_SCOPE_PROPOSAL.md) and the [evaluation summary](docs/GSA_EVALUATION_SUMMARY.md) make those findings part of the research contribution.

## Submission artifacts

- **Repository:** published MCP implementation plus this unmerged documentation candidate; local C03 code is a separately reviewed publication decision.
- **Presentation:** earlier deck exists; current final deck remains to be prepared/reviewed against the selected demo.
- **Evaluation:** [current synthesis](docs/GSA_EVALUATION_SUMMARY.md) and linked historical reports; final submission packaging remains pending.
- **Readiness:** [official-criteria gap matrix](docs/GSA_EVALUATION_GAP_MATRIX.md) and [prioritized checklist](docs/GSA_SUBMISSION_CHECKLIST.md).

The official page requires documented code, a presentation with demonstration and evaluation documentation. A separate video-file requirement was not established. No public demo link is invented. Documentation readiness does not mean GSA acceptance or operational approval.

## Preserved implementation reference

The expandable reference retains existing setup, diagrams and technical links. Milestone-specific status paragraphs and commands describe their original scope. They are not the current capability inventory above, fresh regression results or permission to execute a model/API. Older reports may contain local-only artifact references or reported observations that are not redistributed.

<details>
<summary>Open historical milestones, local setup, MCP contracts and enforcement details</summary>

## MINI08-CP1: console consolidation and Claude preflight

The proposed console presents manifest-checked evidence, the five LangGraph transitions, deterministic decisions, separately observed binding issuance/consumption, backend attempts and SQLite custody. GET views never dispatch. Only an explicit protected synthetic POST can start a demonstration; a separate manual **Analyze Evidence** request runs the mock Messages adapter. The Advisor cannot call MCP tools, issue bindings, change policy or close execution custody.

The original CP1 checkpoint was not published after its failed validation gate. Its source inventory, failures and original observer bytes remain preserved. The subsequent V3 observer and separately pinned CP1.1 worker restore phase/request correlation without changing deterministic policy, bindings or the strict evidence-admission validator.

See [checkpoint status and reproduction boundaries](docs/MINI08_CP1_CHECKPOINT.md), [interactive synthetic console](docs/GSA_MINI081_INTERACTIVE_SYNTHETIC_E2E.md), [mock Evidence Advisor](docs/GSA_MINI082_EVIDENCE_ADVISOR.md), and [Claude API preflight](docs/MINI08_CP1_CLAUDE_API_PREFLIGHT.md). These are local research capabilities, not cloud deployment or live-provider acceptance. The historical evidence and limitations below remain intact.

**MINI08-CP1.2 research checkpoint:** see the [three exact queries, proposed arguments and observed outcomes](docs/GSA_THREE_CASE_EVALUATION.md), including links to a small sanitized derivative of CP1.1's primary evidence. That derivative is not a redistribution of the private traces or SQLite captures. CP1.2 separately checks reproduction from an isolated publication snapshot; it does not claim real Granite/Luna inference, real Claude analysis or the complete FAA FY2026 contract. See [observer compatibility repair and prior verification](docs/MINI08_CP11_OBSERVER_COMPATIBILITY.md). CLOSED means documentary custody, not human acceptance.

For the restored interactive path, use separate existing compatible console and MCP worker environments. The optional console dependencies are listed in `requirements-evidence-console.txt`; its test dependencies are in `requirements-evidence-console-test.txt`. No live credentials are required. Choose **new**, disjoint output directories outside the checkout:

```powershell
$worker = Read-Host "Existing verified MCP 1.30.0 / LangGraph 1.2.15 worker Python"
$executions = Read-Host "NEW private synthetic execution directory"
$analyses = Read-Host "NEW private mock analysis directory"
python -B scripts/serve_evidence_console.py --catalog docs/examples/evidence_console_empty_catalog_v1.json --enable-synthetic-e2e --worker-python $worker --execution-root $executions --advisor-mode mock --advisor-output-root $analyses
```

Open the loopback address printed by the server. Explicitly select PERMIT, DENY and REVIEW_REQUIRED; Analyze Evidence is a separate mock-only action. GET viewing/refreshing does not execute a demonstration. Keep unsuccessful or uncertain attempts; there is no automatic retry or fallback.

**Historical CP1 static finding:** that candidate recorded 160 Mypy diagnostics in five optional console files. Its original report remains unchanged. Later compatibility/type and CI repairs belong to separate candidates; the [MINI10 acceptance record](evals/acceptances/mini10_human_acceptance_20261105.md) records its own passing checks and residual failures. The historical count is not a current-main diagnostic. This documentation review did not rerun application CI; verify the exact submission SHA before publication.

## MINI07.1: offline synthetic hackathon demonstration

The 2026-11-01 run exercised the existing LangGraph → MCP stdio → Gateway → adapter → evidence composition with synthetic providers and backend. Its selection reported **3 PASS, 0 FAIL, 0 ERROR, 0 SKIP**. These are three demonstration scenarios, separate from historical A1/A2, J3/J4 and other evaluation totals; they are not a semantic-accuracy benchmark.

| Scenario | Actual deterministic outcome | Binding issued / consumed | Adapter entries / MockTransport attempts | Custody |
| --- | --- | ---: | ---: | --- |
| Compatible legacy public-record read | PERMIT, RESULT_VERIFIED | 1 / 1 | 1 / 1 | CLOSED, close ACK observed |
| Request to blacklist a contractor | DENY before backend dispatch | 0 / 0 | 0 / 0 | CLOSED, close ACK observed |
| Unsupported complete FAA FY2026 request | REVIEW_REQUIRED despite synthetic IN_SCOPE Judge advice | 0 / 0 | 0 / 0 | CLOSED, close ACK observed |

MINI07.2 confirms the same existing integration and additionally records the actual five A2 node entries, compiled graph invocation and returned history, correlated with MCP, policy, binding and custody. Its separate three-case selection is reported in the checkpoint verification; it does not grant live model or backend authority.

All four tools were discovered; only `find_federal_awards` was invoked in these three cases. PERMIT returned the generic `FIXTURE_AWARD_1` record through the existing January–February 2025 Puerto Rico search contract. It is not an FAA FY2026 result. Hard DENY skipped the Judge; REVIEW_REQUIRED actually observed permissive synthetic Judge advice and retained `REQUEST_INTENT_UNRESOLVED`.

Logical MCP calls, provider requests, binding consumption, adapter entries and backend attempts are distinct observations. The providers used owned loopback fixtures; the backend used MockTransport. MINI07.1's evaluation wrapper reconciled captures and SQLite custody, including read-only restart checks. **CLOSED records evaluation custody, not human approval.** Core JSONL tracing alone is not a durable journal or a tamper-evident guarantee.

### Reproduce the local demonstration checkpoint

The original checked-in entrypoint below is preserved with MINI07.3's historical source inventory. Its inventory is intentionally not repinned to the newer main/CP1.1 sources: a mismatch must stop, not silently replay an old acceptance. Use the restored CP1.2 console command above for the current snapshot. The historical command uses only synthetic providers and MockTransport; no private evidence ZIP or live credentials are required.

Use an existing verified environment with the repository development dependencies. The recorded environment is **Windows/Python 3.13.7, MCP 1.30.0 and LangGraph 1.2.15**. From this checkout:

```powershell
python -B scripts/run_local_governance_demo.py --execute-synthetic
```

The runner checks the versioned source inventory, copies only its explicit allowlist into a new isolated directory, and supplies a private trusted source-root configuration to the existing guard. Output defaults to an external temporary evidence directory; it must be disjoint from the repository. It creates fresh run/observation identities and separate databases, with no automatic retry. Use the printed run path to inspect genuine captured evidence:

```powershell
python -B scripts/show_local_governance_demo.py --run 'ABSOLUTE_RUN_PATH'
```

Playback verifies the indexed identities and labels its output **PREVIOUSLY CAPTURED LOCAL SYNTHETIC EVIDENCE**. It makes no new MCP/provider/backend calls. Preserve a failed or uncertain attempt and investigate it before further execution.

The original MINI07.1 assertions and the A2/MCP and R3.2 regressions are available as separate fixed selections:

```powershell
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite mini071
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite a2
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite r32
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite r32-ab
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite r32-terminal
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite budget
python -B scripts/run_local_governance_demo.py --execute-synthetic --suite portability
```

Keep selection counts separate. See the [checkpoint scope and verification](docs/GSA_LOCAL_DEMO_CHECKPOINT.md) and [offline evaluation guide](evals/README.md). Original private captures, development failures and acceptance records remain in local custody and are not redistributed by this checkpoint.

**Retained limits:** The complete FAA FY2026 `new_awards_only` / awarding-subtier / DOT contract remains unimplemented in this demo; **54 FAA definitions remain BLOCKED/SKIP, with zero executed FAA definitions**. Live provider transport is NOT_AUTHORIZED; EVAL-002 and USAspending integration remain HOLD. Real Granite/Luna full-path evaluation and live USAspending are NOT_TESTED for MINI07.1. Durable-stop P2-02 remains PARTIAL, Judge calibration is NOT_YET_MEASURED, and holdout remains reserved, unexecuted and unadjudicated. Python-level guards do not establish OS isolation, power-loss safety or distributed exactly-once execution.

## Existing local CLI and test setup

The repository's separate synthetic CLI demo and test setup remain available. They are not the pinned MINI07.1 evidence run above. From this repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\civicgate demo
.\.venv\Scripts\pytest -q
.\.venv\Scripts\python scripts/evaluate.py
.\.venv\Scripts\python scripts/run_m2_benchmarks.py
.\.venv\Scripts\civicgate-trace audit/demo.jsonl --html audit/demo.html
```

On Linux/macOS replace `.\.venv\Scripts\` with `.venv/bin/`.
The CLI demo uses **explicit synthetic data and a mock judge** and writes `audit/demo.jsonl`; inspect its actual dispositions rather than treating it as the MINI07.1 result. It does not measure real-model accuracy. No synthetic fallback exists in live mode.

## Agent and model configuration

This is a configuration reference for separately authorized model-integration research, not a required step for MINI07.1. It does not lift the current live-execution HOLD.

Configuration comes from injected `ConfigurationProvider` and `SecretProvider` implementations. The default model provider is unavailable and blocks execution for review.

```powershell
$env:CIVICGATE_AGENT_PROVIDER = "lm_studio"
$env:CIVICGATE_AGENT_BASE_URL = "http://127.0.0.1:1234/v1"
$env:CIVICGATE_AGENT_MODEL = "your-installed-agent-model"
$env:CIVICGATE_JUDGE_PROVIDER = "unavailable"
# For an opt-in external judge, set its provider/base URL/model and inject
# CIVICGATE_JUDGE_API_KEY through a SecretProvider or process environment.
.\.venv\Scripts\civicgate ask "Show federal awards to recipient WESTON SOLUTIONS INC in Puerto Rico during FY2025."
```

Granite uses the local LM Studio chat-completions endpoint and strict `Proposal` parsing. External judges use the same provider-neutral contract through OpenAI-compatible or Anthropic Messages protocols. There are no model credentials in this repository. An invalid response, timeout or missing model cannot grant permission.

### Configuration and Windows credential storage

- `.env.example` is a non-secret configuration reference and is not loaded automatically. Keep credential placeholders blank and keep real credentials out of `.env` files and the repository. Legacy credential variables remain supported when explicitly supplied at runtime.
- The optional Windows DPAPI integration stores individually encrypted credential entries in `%LOCALAPPDATA%\CivicGate\secrets.json`, outside the repository, using current-user protection.
- Provider-specific judge entries are `CIVICGATE_OPENAI_JUDGE_API_KEY` and `CIVICGATE_ANTHROPIC_JUDGE_API_KEY`. Provider configuration determines credential selection.
- DPAPI is explicitly injected through `SecretProvider`; default entry points use process-environment credentials. Core governance does not depend on DPAPI.
- DPAPI protects secrets at rest. Runtime settings and provider instances retain decrypted keys in memory while in use. Do not serialize or log these objects or authentication headers. Model telemetry excludes credential fields, and audit traces apply credential redaction.

## Channel A1/A2: reviewed local development candidate

Channel A1 adds Bounded Tool Discovery over the fixed four-tool registry above. Discovery exposes only permitted metadata and schemas; it grants no execution authority. The existing deterministic policy still decides PERMIT / DENY / REVIEW_REQUIRED. Inside the Gateway, a private AuthorityEnvelope and exact ExecutionBinding tie a PERMIT to the tool, arguments, applicable schema, operation scope and policy context, and are verified immediately before backend dispatch.

Channel A2 adds the local LangGraph workflow `intake → discovery → planner → gateway → result`. Intake preserves the original request separately from the planner proposal. The runnable demonstration uses a deterministic synthetic planner and backend through real MCP stdio/JSON-RPC. Neither LangGraph nor Granite has direct backend authority. Granite remains behind the existing planner interface; discovery currently constrains available tool identities, and discovered schemas are **not dynamically passed into GranitePlanner**.

The host, installed code and local MCP server remain trusted. MCP `user_request` is caller supplied and is not authenticated human intent. Authorization is process-local and single-use; no cross-process exactly-once guarantee or malicious same-process Python sandbox is claimed. Unknown transport outcomes never trigger automatic orchestration retries. Existing bounded adapter transport retries remain a separate mechanism.

The original A1/A2 candidate was tested locally with **MCP 1.30.0, LangGraph 1.2.15, Windows/Python 3.13.7**. No other Python/platform combination was executed for that candidate. Its historical complete-suite result is **570 PASS, 2 FAIL, 1 SKIP**, separate from MINI07.1. Both FAILs are the unchanged J3 freeze-identity tests: candidate source identities differ from the frozen historical plan. No scientific re-freeze, historical amendment, xfail or test exclusion was performed. This historical suite is not wholly green; it is not a new full-suite run of the current local worktree.

The separate A2 synthetic demo can be run from this checkout using its existing development environment, or installed as described in the local CLI setup:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev,orchestration]"
.\.venv\Scripts\python -B scripts/demo_channel_a2.py
.\.venv\Scripts\python -B scripts/demo_channel_a2.py --request "Execute payment for this award"
.\.venv\Scripts\python -B scripts/demo_channel_a2.py --mode review
```

These commands demonstrate a permitted synthetic read, DENY, and REVIEW_REQUIRED. Each run writes to a fresh local evidence directory. Orchestration completion, policy decision, backend dispatch, response validation and provenance are separate observations; transport success does not imply verified results. No live model, API or production credential is needed.

See [A1 execution boundary](docs/CHANNEL_A1_EXECUTION_BOUNDARY.md) and [A2 orchestration and trust limits](docs/CHANNEL_A2_ORCHESTRATION.md). Technical review and branch publication do not grant production approval or governmental authority.

## Technical enforcement flow - Channel A

```mermaid
flowchart TB
    HOST["MCP host / agent"]
    A2["Optional A2 LangGraph workflow<br/>intake - discovery - planner - gateway - result"]

    subgraph A["CHANNEL A - Local MCP stdio"]
        MCP["MCP stdio server"]
        DISC["Bounded Tool Discovery<br/>tool names, metadata and schemas only"]
        GW["Gateway<br/>validated tool invocation and preflight"]
        JUDGE["Semantic Judge interface<br/>advisory; synthetic in offline demo"]
        K["Agent K<br/>advisory only"]
        POLICY["Deterministic policy<br/>PERMIT / DENY / REVIEW_REQUIRED"]
        ISSUE["ExecutionBoundary<br/>issue AuthorityEnvelope and ExecutionBinding"]
        CONSUME["ExecutionBoundary<br/>verify and consume exact binding"]
        STOP["STOP<br/>no adapter dispatch"]
        ADAPTER["Read-only adapter<br/>MockTransport in offline demo"]
        VALIDATE["Validate result and provenance"]
        POST["Post-dispatch review or error<br/>preserve initial PERMIT and dispatch"]
        RESPONSE["Structured response envelope"]
        TRACE["Decision trace (JSONL)<br/>reviewable, not inherently tamper-evident"]
    end

    HOST -->|"direct MCP client"| MCP
    HOST -->|"optional orchestration"| A2
    A2 -->|"MCP client invokes tools"| MCP
    MCP -->|"tools/list"| DISC
    MCP -->|"tools/call"| GW
    GW --> POLICY
    JUDGE -.->|"advisory signal"| POLICY
    K -.->|"advisory signal"| POLICY
    POLICY -->|"PERMIT"| ISSUE
    POLICY -->|"DENY / pre-dispatch REVIEW_REQUIRED"| STOP
    ISSUE --> CONSUME
    CONSUME -->|"verification passes; consume once"| ADAPTER
    CONSUME -->|"binding rejected"| STOP
    ADAPTER --> VALIDATE
    VALIDATE -->|"validated result"| RESPONSE
    VALIDATE -->|"review or failure"| POST
    POST --> RESPONSE
    STOP --> RESPONSE
    POLICY --> TRACE
    STOP --> TRACE
    ADAPTER --> TRACE
    CONSUME --> TRACE
    VALIDATE --> TRACE
    POST --> TRACE
```

**Reading guide:** Solid arrows represent requests, decisions, execution or audit flow; **dotted arrows are advisory signals**, never grants of execution authority. Discovery exposes metadata and schemas, not permission to invoke a tool. The optional A2 workflow is a separate MCP client path, not a mandatory stage of every MCP invocation. A post-dispatch `REVIEW_REQUIRED` can follow an originally authorized read and does not retroactively revoke that initial PERMIT.

The Gateway records decisions and execution evidence; post-result validation is separate from pre-dispatch authorization. MINI07.1 / MINI07.2 add evaluation-only capture reconciliation and SQLite custody around this path. Those tested custody properties do not automatically apply to every core Gateway call, and durable-stop remains PARTIAL.

## Historical and deferred work

Databricks / Channel B, B2a HTTP transport and B2b PostgreSQL/fencing are separate historical experiments and deferred integration work. Reported execution-disabled App smoke cycles reached RUNNING and later stopped; the health test returned HTTP 403, with a `Host rejected` signature that narrowed the diagnosis without independently establishing the incoming Host or proxy trust. Governed cloud MCP execution and automatic cross-channel failover have not been demonstrated. These observations do not establish current cloud resource state, deployment readiness or redundancy. Preserve their failures and UNKNOWNs in the [B2b evidence matrix](docs/research/B2B_EVIDENCE_MATRIX.md) and [open risks](docs/research/B2B_OPEN_RISKS_AND_BLOCKERS.md). They are not branches of the current local architecture.

## Verification and evidence

```powershell
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\mypy src
.\.venv\Scripts\pytest -q --junitxml=artifacts/tests.xml
.\.venv\Scripts\python scripts/evaluate.py
.\.venv\Scripts\pip-audit
```

No live check is part of MINI07.1 or this documentation closeout. The following historical research commands can contact a model or the public API and require separate authorization while live execution is HOLD:

```powershell
# Reference only: local Granite inference, not the synthetic demo.
# .\.venv\Scripts\python scripts/run_granite_lmstudio_benchmark.py --model ibm/granite-3.1-8b
# After separately starting a local llama.cpp Vulkan server:
# .\.venv\Scripts\python scripts/run_granite_llama_cpp_benchmark.py --model <local-gguf-path>
# For Granite 4.2's reasoning-aware chat template, add --disable-thinking.
# Reference only: public internet contract check, not authorized by this README.
# .\.venv\Scripts\python scripts/live_smoke.py
```

See [evaluation](docs/EVALUATION.md), [build report](docs/BUILD_REPORT.md), [demo](docs/DEMO.md), [architecture](docs/ARCHITECTURE.md), [authority](docs/AUTHORITY_MODEL.md), [security](docs/SECURITY.md), [GSA alignment](docs/GSA_ALIGNMENT.md), and [mechanism transfer](docs/PRAETOR_MECHANISM_TRANSFER.md).

Reviewed run closure: [GPT-5.6 Luna J3 completed run](docs/J3_LUNA_5_6_RUN.md).
Prepared for human review: [GPT-6 Luna J4 sanitized run closure](docs/J4_GPT6_LUNA_RUN.md).

Milestone 2 details: [MILESTONE_2](docs/MILESTONE_2.md), [Granite benchmark](docs/GRANITE_AGENT_BENCHMARK.md), [llama.cpp Vulkan path](docs/LLAMA_CPP_VULKAN.md), [judge benchmark](docs/JUDGE_BENCHMARK.md), [hybrid evaluation](docs/HYBRID_EVALUATION.md), and [live limitations](docs/LIVE_MODEL_LIMITATIONS.md). The optional Granite runners record local latency, TTFT and token statistics without saving prompts, responses or API credentials.

CI defines Ubuntu/Windows Python 3.11/3.12 checks and a Linux Docker smoke. Historical GitHub Actions run `35294741095` passed all five jobs, including M2 benchmark generation, dependency audit and the hardened container smoke. It is separate from the A1/A2 findings and MINI07.1, not current verification of this dirty local candidate. Docker is stdio-only, runs as non-root, and exposes no port. Build with `docker build -t civicgate:test .`; use `python scripts/container_smoke.py` for protocol verification. The local Docker daemon was unavailable during that build; no fresh local Docker verification is claimed here.

This is not production-ready. PRAETOR served only as a read-only mechanism reference; none of its research results validate CivicGate. Public API responses, model traffic and credentials are ignored by default; reviewed sanitized M2 benchmark artifacts are the exception. That original READ-only milestone did not include WRITE. The subsequently published WRITE-01 candidate adds a separately authorized synthetic review-state capability; it does not add government-system writes or change the original READ policy.

</details>
