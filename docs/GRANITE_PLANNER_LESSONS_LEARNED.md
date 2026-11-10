# Granite planner integration: findings and lessons

Research note, version 1, 2026-11-09. Scope: Channel A, local planner inference with synthetic government-data backends. The project owner approved preserving these lessons and preparing a separate Granite 4.2 candidate. This note does not authorize a new inference trial or declare the new model accepted.

The Granite 3.1 experiments are part of CIVICGATE's engineering evidence. Their failed proposals, integration defects, incomplete observations and successful containment remain valid findings. They must not be replaced by a cleaner result from a newer model.

## What was observed

The selections below are separate experiments and analyses. Their counts overlap and must not be added together.

| Selection | Recorded outcome | Interpretation |
| --- | --- | --- |
| Granite 3.1 Q3_K_L functional V1: four frozen cases, two repetitions each | Eight HTTP 200 responses; six `INVALID_PROPOSAL_SCHEMA`; two exact G03 proposals. Original oracle: **2/6 exact planner matches among representable cases**. | HTTP success did not establish a usable proposal. G01 FIND and G02 GET failed before Gateway. Detailed reasons for the six rejected V1 objects were not retained. |
| V1 deterministic governance | G03 reached Gateway twice and received `REVIEW_REQUIRED`, reason `NAME_LITERAL_PROPOSAL_UNSUPPORTED`, despite synthetic Judge `IN_SCOPE`. Bindings issued/consumed: **0/0**; backend dispatches: **0** across V1. | The actual observed Gateway decisions were two REVIEW outcomes. The separately reported **4/8 governance matches** also include two G04 planning failures; those must not be relabeled as Gateway REVIEW decisions. |
| Diagnostic V2 bridge preparation | **0/2 sends**; false object-identity mismatch before inference. An additive `ABORTED_PRE_DISPATCH` record was later authorized. | An integration defect, not a model-quality measurement. The old SQLite ledger remained OPEN and unchanged; documentary closure did not manufacture a persisted STOP. The root is excluded from reuse. |
| Recovery V2 | **1/2 sends consumed**; G01 `CANCELLED_DELIVERY_UNKNOWN`; SQLite STOPPED; G02 not attempted. | Unknown delivery consumes budget. The unused slot is not authorization to continue after STOP. No planner-quality score is supported by this attempt. |
| Timeout investigation and versioned correction | Offline reproduction observed competing 20-second deadlines; a later profile separated HTTP/internal/A2 limits as **90/120/130 seconds**. | Timing and cancellation observability require their own evidence. Synthetic timer order does not retrospectively prove which component cancelled the historical LIVE attempt. |
| Completed timeout-V2 diagnostic trial | **2/2 sends**; both HTTP 200 / `finish_reason=stop`; JSON objects lacked `tool` and `arguments` and had one redacted extra field. No Gateway evaluation, bindings or dispatches. | Sanitized diagnostics located the Proposal boundary. They did not establish the unknown wrapper's meaning or whether an otherwise usable native call existed. |
| Tool-format investigation | **87 offline PASS**: 39 checks against the frozen parser using MockTransport, 39 checks of a proposed format specification, nine controls. | The parser accepts JSON in `message.content`, not native `message.tool_calls`. A populated second native channel can be ignored when valid content is present. These are format checks, not new model samples or planner accuracy. |

G04 concerned a complete FAA-specific request not representable by the tested contract. Its planning failure provided containment. It does not prove the model intentionally recognized the semantic limitation. The 54 historical FAA full-contract definitions remain BLOCKED/SKIP.

## Engineering lessons

1. **Measure the boundaries separately.** Transport response, JSON parsing, Proposal validation, tool-argument validation, deterministic policy, binding consumption, backend dispatch and result validation are different events. An HTTP 200 or `tool_executed=True` cannot substitute for the later observations.
2. **Make the response contract explicit.** The frozen requests sent top-level `grammar` without `tools`, `tool_choice` or `response_format`. Sending a grammar did not independently establish server enforcement. Select one documented response mode before the request; reject conflicting or multiple proposals rather than guessing which one the model intended.
3. **Normalize proposals without granting authority.** A normalized `Proposal(tool, arguments)` still requires the registered tool schemas, host-selected owner, A2 discovery checks, MCP and the real deterministic Gateway. Native function calls are proposals; they cannot issue bindings or directly execute an adapter.
4. **Keep privacy-safe diagnostics at rejection boundaries.** Record controlled field locations/types, finish-state categories, presence/count of native calls and fixed error codes. Do not store raw responses, arguments, credentials or Pydantic exception inputs merely to make debugging easier. `[Hidden]` log text does not reveal the hidden tool names or prove execution.
5. **Budget time and delivery explicitly.** Separate preflight from HTTP waiting and final acceptance. Preserve distinct timeout/cancellation categories. Reserve durably before submission, retain uncertain attempts, STOP without retries or refunds and never reopen historical custody to finish an experiment.
6. **Preserve denominators and failed runs.** Safe containment is a governance result, not automatic planner success. Schema validity is not semantic correctness. `COMPLETED` is an experiment-accounting state; documentary `CLOSED` is not human acceptance.

## Why evaluate Granite 4.2 separately

IBM documents Granite 4.2 8B for tool use and publishes a Q4_K_M GGUF. This supports selecting a research candidate, not claiming it already outperforms 3.1 in CIVICGATE. No preserved CIVICGATE comparison verifies the suggested three-second latency increase. [IBM model card](https://huggingface.co/ibm-granite/granite-4.2-8b), [official GGUF collection](https://huggingface.co/ibm-granite/granite-4.2-8b-GGUF).

The initial proposed format is **CONTENT_JSON**, using the published LM Studio `response_format.json_schema` contract. This measures structured planner proposals and tool selection; it does not test Granite 4.2's native `tool_calls` interface. A different native-call experiment would need its own explicit format and validation. [LM Studio structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output), [tool-use contract](https://lmstudio.ai/docs/developer/openai-compat/tools).

The new profile must not silently inherit all 3.1 settings. IBM recommends `temperature=1.0`, `top_p=0.95`, and an output allowance of 2,048 tokens for non-thinking mode. Non-thinking is a chat-template choice; effective support by the installed LM Studio runtime remains unverified. The profile therefore records proposed settings separately from observed runtime facts. No model setting was changed while preparing this note. [IBM generation and template guidance](https://huggingface.co/ibm-granite/granite-4.2-8b#inference).

Preserve the four frozen 3.1 inputs and independent oracles. A future initial G01/G02 subset would use a new approval and custody root, with no borrowing from exhausted or stopped budgets. Pin the exact new GGUF, served model ID, template/mode and request schema. Compare tool choice, complete arguments, semantic scope, policy outcome, binding/dispatch evidence, latency and token availability separately. If sampling, template and wire format change with the model, label this an integration comparison; it cannot isolate a model-only improvement.

## Evidence identities

These source documents and primary artifacts are retained privately. Local machine paths, credentials, raw logs, model responses and SQLite files are intentionally absent from this repository note. The hashes identify the documents summarized here; they do not authenticate a reviewer or make the private evidence publicly reproducible.

| Retained source document | SHA-256 |
| --- | --- |
| `GRANITE02_LOCAL_FUNCTIONAL_TRIAL_RESULT_20261109.md` | `a78d5424409d1ba194252e8bce38aaa1d0e3ec88060f9ba9071891e3f70ae7f4` |
| `GRANITE02_PLANNER_RCA_01.md` | `3fd735f1ebfc44ccd37d6610be71b31133b45ff0c1c53c64b744c5983ae12b24` |
| `GRANITE02_V2_RECOVERY_LIVE_REPORT.md` | `e49789af195e1523a118a8fc82dac81b486df636af7bffc50f66a0a3fa1b782f` |
| `GRANITE02_TIMEOUT_FIX_REPORT.md` | `7101978b532d070dd917af3b96400f8dc39caad32ef603f767953b6b43f850ed` |
| `GRANITE02_TIMEOUT_V2_LIVE_REPORT.md` | `2449d7b949373ad6a90a3f80d03667730c9d82c05c1b67714db20e86933e17cb` |
| `GRANITE02_TOOL_FORMAT_DIAGNOSIS.md` | `ef86a4aa386f49648b2bb96ca674450288a203a1f6f1972798f991d71c3423bd` |

Primary V1 evidence inventory: `b55f76b58fe216ff43c50ca5a3580cf7f9cefb40bbc38e185dfeda682a615d84`. Frozen four-case oracle fixture: `f03367b179d661b0cdd22989667f8e613c399234c486af29dc6ea5380af86682`. Completed timeout-V2 root inventory: `cf517e976dd68aff6f0651d1497e9e4c83d02f6f4b79795cdbbd474c0e3af5c7`. Tool-format package inventory: `5df1e03616d4d76266d1025f94933048f9d4c754d3213200e05a92047bdf18f6`. Inventory scopes and self-exclusions remain those of their original manifests.

## Retained boundaries

Existing runtime admission remains `METADATA_CORRELATED_ONLY`. Direct post-initialization context measurement, backend PID attestation, in-memory GGUF identity and effective GPU offload were not established by the reported evidence. The historical hardware/GPU preflight remains HOLD, and durable STOP remains PARTIAL.

V1 is sealed at 8/8; recovery V2 is STOPPED at 1/2; the completed timeout-V2 trial is sealed at 2/2. The performance benchmark remains 0/20. Preparing a 4.2 profile does not authorize inference, a benchmark, model loading, real USAspending/FAA access, cloud providers, Chat-to-WRITE, deployment or Git publication. Independent golden-reference acceptance and judge calibration remain pending.

Capability does not create authority. Evidence from unsuccessful integration is still evidence.
