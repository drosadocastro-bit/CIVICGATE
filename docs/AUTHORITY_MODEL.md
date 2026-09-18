# Authority model

Capability does not create authority. The sole capability is `PUBLIC_SPENDING_RESEARCH`; it is assigned by trusted server code and is not a request field.

| Component | Permitted role | Authority |
| --- | --- | --- |
| Agent model | Interpret and propose registered tool arguments | None |
| Semantic judge | Scope, uncertainty and risk signals | None |
| Agent K | Behavioral pressure and containment signals | None |
| Deterministic policy | Apply ordered fixed rules | PERMIT / DENY / REVIEW_REQUIRED |
| Adapter | Execute an already authorized public read | None |

DENY takes precedence over advisory confidence. Hard tripwires cover consequential decisions, private data and bypass attempts. Unknown tools, invalid arguments, unapproved capabilities, nonpublic sources and K containment deny. The judge cannot reverse them, even with confidence 1.0 and IN_SCOPE.

REVIEW_REQUIRED covers unbounded scope, unavailable adapter/provenance facts, failed planning, failed judge, insufficient confidence, semantic flags and advisory K risks. The default confidence threshold is 0.85, externally configurable in [0,1]. Missing/failed semantic assessment cannot permit. Post-result recipient ambiguity, empty candidate resolution and source conflicts also require clarification. No runtime method grants exceptions or rewrites policy.

PERMIT authorizes only the specified factual read. It does not certify a response, establish legal identity or authorize downstream governmental action. An authorized read that times out returns PERMIT with status ERROR, null result and an actionable error. The audit shows that execution was attempted. Protocol-level invalid input is rejected by the MCP SDK before gateway invocation and has no fabricated governance decision.

Repeated denial: two denials in a gateway process trigger containment of later calls through deterministic policy. Agent K itself only reports the signal. No new authority is derived from repetition, model agreement or prior successful retrieval.

Keyword tripwires are conservative and incomplete: benign discussions of denied topics may be blocked, and paraphrases can evade lexical detection. Real-model semantic calibration, multilingual coverage and adversarial robustness are not established. Read-only tool design limits actual capabilities regardless of semantic classification. A client can lie about its intended use; the server cannot inspect an external agent's hidden context or prevent misuse of public data after retrieval.

## Milestone 2 provider roles

`GranitePlanner` supplies a typed proposal from the local LM Studio endpoint. `LiveJudgeProvider` supplies a typed semantic signal from an external OpenAI-compatible or Anthropic endpoint. `ConfigurationProvider` and `SecretProvider` keep model settings and credentials outside governance; the optional Windows DPAPI implementation remains an edge integration. Provider failures, malformed output and unavailable credentials produce explicit review or containment states. They never create a new capability or bypass the ordered policy checks.
