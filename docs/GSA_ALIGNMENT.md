# GSA alignment

Design reference: [GSA MCP Server and AI Agent Government Hackathon](https://www.gsa.gov/artificial-intelligence/ai-community-of-practice/events-and-training/mcp-server-and-ai-agent-government-hackathon), reviewed September 17, 2026; displayed update September 14, 2026. This records design alignment, not GSA approval or eligibility verification.

**CivicGate is a Dataset Access Server prototype using publicly available government data in a sandbox context.** No public deployment is included.

| Criterion | CivicGate implementation | Evidence / boundary |
| --- | --- | --- |
| Technical quality | Small Python modules, strict Pydantic contracts | Typecheck, lint, source layout |
| Reliability and evaluation | Bounded calls, explicit failures, repeatable fixtures | Evaluation JSON and tests; live checks reported separately |
| MCP design | Four named research goals with input/output schemas | Real stdio client smoke |
| Innovation | Probabilistic interpretation with deterministic authority | Non-overridable denial tests |
| Mission alignment | Public federal spending research | USAspending contract evidence |
| Presentation | PERMIT, DENY, REVIEW_REQUIRED walkthrough | Demo and presentation draft |

Deliverable status: local Git repository prepared; publishing to GitHub remains an external handoff. Presentation and evaluation artifacts are local. No participant affiliation, government authority, certification or competition acceptance is claimed.
