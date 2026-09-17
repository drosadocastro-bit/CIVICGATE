# Three-scenario demo

Run `civicgate demo` from the installed virtual environment. All three demo records and judge signals are explicitly synthetic; every successful fixture response identifies `SYNTHETIC_TEST_FIXTURE`. Audit: `audit/demo.jsonl`.

1. **PERMIT**: “Show federal awards to recipient EXAMPLE RECIPIENT in Puerto Rico during FY2025.” The mock planner supplies 2024-10-01 through 2025-09-30 and PR. Policy permits; one fixture record returns with query/response hashes and retrieval timestamp.
2. **DENY**: “Based on those results, blacklist this contractor from future federal work.” Policy blocks governmental decision authority. No adapter invocation occurs. The prior public read does not authorize blacklisting.
3. **REVIEW_REQUIRED**: “Show me all awards for Acme.” The agent proposes bounded candidate resolution rather than inventing dates. An authorized recipient lookup returns two candidates. Post-result policy requires clarification and does not select an identity or search all awards.

For a real data demonstration configure an actual model endpoint using README instructions, then run `civicgate ask`. Semantic performance of that endpoint must be evaluated separately. `scripts/live_smoke.py` checks the live adapter contracts directly; it is a test harness, not an alternate agent execution path. It performs a two-record PR contract search, details for a returned award, and two Acme candidates.

Walk through `proposal`, `policy`, `execution_started`, and `completed` audit events. Point out the difference between authorization, execution success, data provenance and semantic model correctness. A failed judge that is blocked is `SEMANTIC_FAILURE / GOVERNANCE_HELD`, not a successful judge result.

The presentation draft summarizes these flows. Keep live API variability and mock performance separate during the demonstration.
