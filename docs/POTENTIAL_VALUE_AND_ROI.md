# Potential value and ROI methodology

Version 1 · November 12, 2026. No operational labor baseline, adoption study or measured financial return is available. CIVICGATE's demonstrated outcomes are technical observations; the benefits below are hypotheses to measure in a future authorized pilot.

| Potential benefit | Existing technical basis | Measurement still needed |
|---|---|---|
| Less manual lookup and integration effort | Bounded typed public-awards tools; governed synthetic lookup | Comparable tasks with and without the tool, including review and failure-handling time |
| Reusable policy and tool interfaces | Separate planner, owner, Gateway, adapter and evidence contracts | Cost of adding a second authorized workflow; ongoing schema maintenance |
| Less repeated integration development | Existing MCP/A2/Console reused across bounded experiments | Engineering hours versus a documented alternative, including testing/security work |
| Faster authorization-evidence review | Correlated policy, binding, backend and custody observations | Reviewer time, completeness and error rate on the same evidence tasks |
| Better visibility into failed or withheld operations | Preserved DENY, REVIEW_REQUIRED and post-result STOP | Time to diagnose incidents and proportion of unresolved cases |
| Less rework from invalid or unauthorized actions | Binding checks and result withholding in tested paths | Real rework frequency and cost; no assumed avoided-loss amount |

## Transparent calculation

Use one consistent annual horizon and currency:

```text
Potential annual labor value = annual request volume × minutes potentially saved / 60
                              × assumed loaded hourly rate
Annual total investment = implementation allocation + operations + model usage
                          + security + maintenance costs
Estimated net benefit = potential annual labor value − annual total investment
Illustrative ROI = estimated net benefit / annual total investment × 100
```

Use ROI only when total investment is positive and defined. Avoid double-counting implementation or maintenance. Released staff time is capacity, not necessarily cash savings or a reduced budget. Quality/review costs and unsuccessful requests must be included; governance can add work as well as reduce rework.

## ILLUSTRATIVE SCENARIOS — NOT MEASURED SAVINGS

All entries below are hypothetical assumptions, not FAA/GSA rates, actual workloads, model prices or a CIVICGATE budget. Annual volume is fixed at 10,000 requests, assumed loaded rate at $60/hour and assumed all-in annual investment at $30,000. Only minutes saved varies.

| Hypothetical minutes saved per request | Potential labor value | Assumed investment | Estimated net benefit | Illustrative ROI |
|---:|---:|---:|---:|---:|
| 1 | $10,000 | $30,000 | −$20,000 | −66.7% |
| 3 | $30,000 | $30,000 | $0 | 0.0% |
| 5 | $50,000 | $30,000 | $20,000 | 66.7% |

The hypothetical break-even point is three minutes per request under these assumptions. There is no evidence that CIVICGATE saves three minutes. This table is a sensitivity illustration, not a forecast, financial recommendation or cost cap. NVIDIA free-prototyping statements do not provide a transactional billing guarantee.

Before an operational value claim, collect a task-matched baseline, actual authorized usage and costs, human verification time, failure/rework rates, maintenance effort and adoption volume. Report uncertainty and results that show no improvement. [Evaluation evidence](GSA_EVALUATION_SUMMARY.md) and [technical debt](TECHNICAL_DEBT.md) define what remains unmeasured.
