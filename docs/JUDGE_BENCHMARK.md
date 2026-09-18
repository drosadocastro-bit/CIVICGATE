# Semantic judge benchmark

J1 is the deterministic mock fixture provider. J2 is GPT-5.6 Luna through an OpenAI-compatible endpoint. J3 is Claude Sonnet 5 through the Anthropic Messages API. All three use the same provider-neutral contract, schema, policy, Agent K path, timeout and retry budget. Credentials are external and live calls are opt-in.

Measure human-label agreement, false positives/negatives, ambiguity, consequential interpretation, overreach, malformed output, abstention/uncertainty, calibration, repeat and paraphrase consistency, injection resistance, latency, tokens and cost independently. There is no single judge safety score. Fixture expectations are engineering labels, not independent human adjudication; therefore J1 is marked synthetic-only and J2/J3 are unavailable in normal CI.

The judge supplies semantic evidence. It never grants permission, changes capabilities, or bypasses a deterministic denial.
