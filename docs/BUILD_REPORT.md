# Milestone 1 build report

Completed locally September 17, 2026 in `D:\CIVICGATE`. New Git repository initialized; no commit, remote repository, push or deployment created. The reference PRAETOR checkout remains untouched; its pre-existing status and HEAD were unchanged at the final check.

## Delivered

- Python package and CLI natural-language agent with replaceable agent/judge providers.
- Four Pydantic MCP tools: `find_federal_awards`, `get_federal_award`, `resolve_federal_recipient`, `summarize_federal_spending`.
- Agent → governed interface → deterministic policy → public adapter. Judge and Agent K are advisory. PERMIT executes; DENY blocks; REVIEW_REQUIRED requests clarification or configuration repair.
- USAspending search/detail/recipient adapter; bounded page aggregate; timeout/retry/error contracts; no fallback data.
- Provenance, redacted audit, explicit mock provider and labeled synthetic demos.
- Unit/integration/adversarial/MCP tests, 16 replay fixtures, component metrics and live contract evidence.
- GitHub Actions matrix, non-root stdio Docker scaffold, documentation and six-slide editable presentation.

The local generated file inventory is intentionally ignored along with API captures, audit logs and environment snapshots. The tracked file list is available from GitHub after publication.

## Verification

| Check | Local outcome |
| --- | --- |
| Windows / Python 3.13.7 | 77 tests passed; JUnit evidence in artifacts/tests.xml |
| Ruff lint and formatting | Passed |
| mypy strict, source package | Passed, 20 source files |
| pip check | No broken requirements |
| Dependency vulnerability audit | No known vulnerabilities after updating local pip; local unpublished CivicGate package skipped by database |
| Fixture evaluation | 16/16 expected outcomes; component metrics retained separately |
| MCP stdio | Real subprocess initialize/list/call passed; four tools with output schemas |
| Live USAspending | Search, detail and recipient contracts passed; timestamped hashes in artifacts/live-smoke.json |
| Presentation | Six editable slides exported, package/layout validated and all rendered slides visually inspected |
| GitHub CI | Defined for Ubuntu/Windows Python 3.11/3.12; not executed remotely |
| Docker runtime | Not run locally: Docker CLI exists but Linux engine named pipe is unavailable |

The initial dependency audit flagged the virtual environment's pip 25.2. It was updated to 26.2.1; CI and Docker now upgrade pip before installation. No advisory was suppressed. The environment snapshot is observational, not a cross-platform lockfile.

## PRAETOR reuse boundary

Reimplemented concepts: strict schemas, deterministic authority precedence, pre-action containment signals, separate semantic/governance outcomes, provenance validation, explicit adapter failures, bounded execution, review paths and audit events. Credential separation and non-root container concepts were adapted to a local stdio prototype. The transfer matrix identifies observed source files, differences and required new tests.

Not ported: G2/G3/G3B artifacts, freeze machinery, adaptive runtime, NEXRAD fixtures, historical claims or research results, experiment archives, governmental writes, long-term memory, multi-agent orchestration, RAG, vector databases and dynamic policy.

## Remaining limitations

Real-model semantic accuracy is unmeasured; only the provider contract is implemented. The mock planner recognizes the prescribed demo patterns and is not a general natural-language interpreter. Lexical authority checks can overblock or miss paraphrases. An external MCP client can misrepresent intended use. Recipient name search is not legal-entity verification; candidate selection remains manual. Summary amounts describe the returned award page, not FY transaction spending. No availability/load guarantee, tamper-proof audit, persistent containment or production readiness is claimed.

The Python 3.11/3.12 CI matrix and Linux container need actual execution. GitHub publication and model configuration remain external handoffs. Scope stops at this one public-data domain and read-only capability.
