# CIVICGATE: Potential Cloud Scaling
## Capability mapping to IBM watsonx Orchestrate and Databricks

**Status:** Research and architecture proposal, not a deployment or migration claim.  
**Prepared:** November 17, 2026 (UTC). Public-source review conducted November 16–17.  
**Purpose:** Identify platform capabilities that could support CIVICGATE at cloud scale, and specify what must remain custom or be validated before any equivalence is claimed.

## Executive summary

An analyst needs an AI assistant to retrieve public government data. The organization also needs to control which actions the assistant may take and retain evidence of what actually happened. CIVICGATE addresses that problem through a deliberately bounded governance workflow. A possible cloud evolution would preserve that workflow while using enterprise platforms for identity, hosting, access management, evaluation, and operational monitoring.

IBM watsonx Orchestrate and Databricks both publish capabilities relevant to this direction. Neither should be described as lacking agent governance. Several capabilities overlap with CIVICGATE; others could complement it. Similar product labels do not establish identical behavior, and a missing explicit match in the reviewed documentation is not proof that a platform cannot implement it.

**Current scope remains the local CIVICGATE prototype.** This document does not reactivate a dual-channel architecture, claim an IBM or Databricks deployment, certify cloud readiness, or change the November 20 delivery scope. Cloud scaling is future work requiring a separate design, authorization, implementation, and evaluation.

## How to read the comparison

- **Documented overlap:** A public official source describes a capability serving a similar purpose.
- **Integration opportunity:** A proposed way to use that capability with CIVICGATE. This is our architectural inference, not a vendor commitment.
- **Exact equivalence unverified:** The sources reviewed do not establish the same contract and failure behavior.

CIVICGATE descriptions below refer to the project's documented design and reviewed local work. They are not a fresh code audit or a claim that every component is integrated into the final UI. In particular, the latest complete LIVE presentation flow still requires integration and verification.

## Capability mapping

| CIVICGATE responsibility | IBM watsonx Orchestrate | Databricks | Proposed scaling treatment |
|---|---|---|---|
| **Policy before an action** | Asset controls and custom runtime controls provide relevant governance mechanisms. [IBM controls](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=overview-controls) | Service Policies, documented as **Beta**, support request/result evaluation and ALLOW, DENY, ASK decisions. Enforcement can deny on evaluation error; logging-only mode is different. [Service Policies](https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/) | Documented overlap. Retain CIVICGATE's authority contract initially, and test interactions with platform policy. Do not equate ASK automatically with REVIEW_REQUIRED or assume matching labels preserve semantics. |
| **Bounded tool discovery and invocation** | MCP tool controls and rate limits can complement domain-specific validation. [IBM controls](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=overview-controls) | Unity Gateway tool selection can remove tools from discovery and reject their invocation; automatic inclusion of future tools can remain off. [Govern an MCP](https://docs.databricks.com/aws/en/ai-gateway/govern-mcp-service) | Documented overlap. Preserve explicit argument, result-size, date-window, and destination limits in the tool implementation. Tool selection is not proof of cryptographic definition pinning or argument binding. |
| **Single-use authorization bound to an exact action** | Dynamic credentials and TTLs are documented, but they do not by themselves establish a single-use grant for exact tool arguments. [Secure AI agents](https://developer.ibm.com/tutorials/securing-ai-agents/) | Access grants and service policies are relevant layers, but the sources reviewed do not establish CIVICGATE's exact consumable-binding contract. [Service Policies](https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/) | Exact equivalence unverified. Preserve or implement a durable atomic reservation/consumption mechanism and prove replay prevention across workers and restarts. |
| **Identity and least privilege** | IBM documents agent identity and an MCP OBO integration pattern. The tutorial explicitly configures an audience and scopes; configuration is required. [OBO tutorial](https://developer.ibm.com/tutorials/secure-rbac-mcp-context-variables-obo-watsonx-orchestrate/) · [Agent identity](https://www.ibm.com/new/announcements/agent-identity-in-ibm-watsonx-orchestrate-is-now-generally-available) | MCP authentication distinguishes inbound authentication from outbound connection credentials. User identity propagation depends on the connection and authentication mode. [MCP authentication](https://docs.databricks.com/aws/en/agents/mcp-tools/authentication-networking) | Integration opportunity. Specify the user, agent, service identity, scopes, audience, and credential owner for every hop. Do not assume a shared connection preserves the individual caller. |
| **Semantic evaluation separated from authority** | Custom LLM-as-Judge evaluation is documented; runtime controls also exist. It is inaccurate to characterize all IBM judgment as offline-only. [IBM capability announcement](https://www.ibm.com/new/announcements/ibm-watsonx-orchestrate-advances-enterprise-ai-agent-management-with-new-capabilities-at-techxchange-2026) | MLflow supports model-based judges and code-based scorers. [MLflow scorers](https://docs.databricks.com/gcp/en/mlflow3/genai/eval-monitor/concepts/scorers) | Documented overlap in evaluation. Preserve the rule that an advisory model score alone cannot authorize an action. Calibrate thresholds rather than treating confidence as a safety guarantee. |
| **Agent K behavioral reporting** | Granite Guardian guardrails use models, so they are not a direct equivalent to a deterministic, model-free reporter. [IBM release notes](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=notes-whats-new-in-watsonx-orchestrate) | Code-based scorers could evaluate deterministic signals, but evaluation machinery is not automatically an execution-time Agent K replacement. [MLflow scorers](https://docs.databricks.com/gcp/en/mlflow3/genai/eval-monitor/concepts/scorers) | Exact equivalence unverified. Keep the reporter's inputs, outputs, and lack of authorization power explicit. Use platform evaluations to test it rather than silently replacing it. |
| **Evidence and operational observability** | Identity audit information and session termination controls are documented. [Agent identity](https://www.ibm.com/new/announcements/agent-identity-in-ibm-watsonx-orchestrate-is-now-generally-available) | MCP usage/audit information and request-response traces are documented; trace collection requires setup. [Govern an MCP](https://docs.databricks.com/aws/en/ai-gateway/govern-mcp-service) | Integration opportunity. Correlate platform events with CIVICGATE receipts and request IDs. Logs alone do not prove complete custody, exactly-once behavior, or unchanged source data. |
| **Governed synthetic WRITE** | Approval workflows can be part of a governance design, but do not establish CIVICGATE's exact mutation contract. [IBM governance example](https://www.ibm.com/new/product-blog/how-aligne-ai-scales-continuous-ai-governance-without-scaling-headcount) | ASK can pause an MCP input call for human approval. [Service Policies](https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/) | Documented overlap, not automatic equivalence. Keep WRITE synthetic; preserve exact approval, idempotency, version checking, and failure evidence. No production write authorization is implied. |

## Two possible cloud paths

### IBM-oriented path

Use Orchestrate's enterprise agent/tool controls and configured identity integration around a CIVICGATE-governed MCP service. Keep the service's deterministic action checks and evidence contract until a replacement is demonstrated to preserve them. Use vendor evaluation and audit facilities as additional evidence, not as an automatic substitute for per-action receipts.

This is a proposed integration pattern, not an already supported CIVICGATE adapter. Hosting, transport, credential custody, product editions, regional availability, and access permissions still require verification.

### Databricks-oriented path

Explore a governed MCP integration with Unity Catalog/Unity Gateway, and MLflow for evaluation. Separate platform access permissions from the application's authorization logic. If Service Policies are used, confirm the Beta feature is enabled and test the exact enforcement mode and failure behavior.

This is also a proposed integration pattern. Public documentation does not establish that these capabilities are enabled in the hackathon workspace, nor authorize creating resources or consuming compute.

## What must be proven before scaling

The following are proposed acceptance criteria, not completed cloud tests:

1. **One authority contract:** Define how platform denial, CIVICGATE denial, human review, and advisory model output combine. No lower layer may silently override a denial.
2. **Identity boundaries:** Validate token issuer, intended audience/resource, scopes, expiry, and caller propagation at the appropriate boundary. Store credentials only in approved secret storage.
3. **Distributed single-use behavior:** Demonstrate atomic grant consumption under concurrent requests, timeouts, retries, worker crashes, and restart. Do not infer exactly-once external effects solely from a local counter.
4. **Untrusted tool content:** Test malicious descriptions/results, schema drift, unexpected redirects, and unauthorized destinations. Discovery must not create authority.
5. **Evidence continuity:** Link authorization, invocation, backend outcome, validation, and user-visible result. Preserve UNKNOWN when an external outcome is uncertain.
6. **Budget and operations:** Separate rate limits, token limits, estimates, and enforceable spending controls. Dashboard costs are not a guaranteed monetary ceiling.
7. **Independent evaluation:** Run the same versioned cases locally and in the candidate cloud implementation. Compare both successful and denied paths, not just HTTP 200 responses.
8. **Human approval for rollout:** Review the exact source version, infrastructure, permissions, data exposure, operating costs, and rollback/stop procedure before deployment.

## Corrections carried forward from the earlier drafts

- IBM OBO should not be labeled categorically “not audience-bound”: its official tutorial includes an audience parameter.
- Granite Guardian model-based guardrails must not be equated with Agent K's model-free deterministic reporting.
- Databricks already documents per-interaction policies and approval behavior; absence of governance is not a defensible differentiation claim.
- `iss` and audience address different concerns. RFC 9207's authorization-response issuer identifier mitigates authorization-server mix-up; audience/resource validation restricts the token's intended recipient. Neither alone establishes the full identity stack. [RFC 9207](https://www.rfc-editor.org/rfc/rfc9207.html)
- The supplied Genie document is a task brief and record of decisions, not a completed Databricks equivalence report. Its private execution/history statements cannot be independently verified through vendor documentation.
- “No explicit equivalent found in the reviewed sources” is appropriate; “the vendor cannot do this” is not.

## Suggested short positioning

> CIVICGATE is a local-first prototype for bounded, evidence-backed agent actions. A potential cloud evolution could combine its action-level governance contract with IBM watsonx Orchestrate or Databricks capabilities for identity, access control, evaluation, and observability. These are proposed integration paths, not verified deployments or claims of one-to-one product equivalence.

## Review limitations

This is a public-documentation comparison, not a tenant inspection, security certification, vendor endorsement, or comparative benchmark. Some IBM documentation pages were accessible through indexed excerpts and related official publications rather than full-page retrieval. Product behavior, edition, region, preview status, and configuration must be reconfirmed during a future implementation. Original source documents are preserved unchanged; this consolidated note supersedes their technical comparison wording only where explicitly corrected above.
