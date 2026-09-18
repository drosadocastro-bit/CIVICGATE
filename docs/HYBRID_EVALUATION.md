# Hybrid evaluation

The same adversarial fixture set is replayed through four matrices:

| Matrix | Semantic judge | Agent K | Final authority |
| --- | --- | --- | --- |
| A | disabled | disabled | deterministic policy |
| B | enabled | disabled | deterministic policy |
| C | disabled | enabled | deterministic policy |
| D | enabled | enabled | deterministic policy |

The artifact records each case, decision, execution, latency, policy reasons and disagreement. It accounts separately for `JUDGE_SEMANTIC_FAILURE`, `AGENT_K_DETECTION`, `GOVERNANCE_HELD` and `PLANNER_FAILURE`. Matrix D is not declared a winner; the purpose is to observe component contributions and disagreement patterns while policy remains final.
