# Granite planner benchmark

The benchmark compares the planned CivicGate role for IBM Granite 3.1 8B Q3 and IBM Granite 4.2 8B Q4 through the same LM Studio OpenAI-compatible endpoint. Its classification is `PRACTICAL_DEPLOYMENT_COMPARISON`. It does not establish a globally better model.

Before trials, record LM Studio version, GGUF filename and hash, model quantization, backend/device, context and maximum output tokens, temperature/top-p/top-k/seed, reasoning setting, system and schema prompt, timeout, repetitions, fixtures and strict parser. A missing item leaves the trial `BLOCKED_CONDITIONS_NOT_FROZEN`.

Report latency, exposed TTFT, prompt and generation token rates, observed memory/VRAM, timeout/error counts, tool selection, argument validity, malformed output, unnecessary invocations, ambiguity preservation, authority overreach, hidden-tool attempts and repeat consistency separately. `NOT_EXPOSED` is a valid observation; it is never converted to zero.

Role conclusions are limited to `MODEL_ACCEPTABLE_FOR_CIVICGATE_PLANNER`, `MODEL_REQUIRES_REVIEW`, or `MODEL_NOT_ACCEPTABLE_FOR_CIVICGATE_PLANNER`. Quantization, generation and runtime are confounded until the exact trial conditions are frozen.

## Recorded local run

The `scripts/run_granite_lmstudio_benchmark.py` runner reads the local LM Studio inventory and uses its native `/api/v1/chat` endpoint, which exposes TTFT and token statistics. It stores only metadata, fingerprints and typed results in `artifacts/granite-live-benchmark.json`; that file remains ignored along with API traffic.

In the September 2026 run, the operator label was `Granite 3.2`, but LM Studio reported the identity `ibm/granite-3.1-8b`: Granite 3.1 8B, GGUF `Q3_K_L`, 8B, 4,349,475,027 bytes and one loaded instance. The inventory exposed context 131,072, eval batch 2,048, physical batch 512, parallelism 4, Flash Attention and GPU KV cache. The 19-layer offload and 6.76 GB VRAM are operator-supplied values; the API did not expose them, so they remain separate from provider observations.

Four representative fixtures were executed twice each with temperature 0, top-p 1 and a 512-token maximum:

- 8/8 calls completed without timeout; median latency was 7.15 s and p95 was 12.19 s.
- Median TTFT was 303 ms; total input was 8,628 tokens and total output was 501 tokens.
- Median generation speed was 9.45 tokens/s.
- 75% of outputs passed the `Proposal` schema; 25% also validated the tool arguments.
- Two of the three fixtures with a valid `Proposal` were consistent across repetitions. The injection fixture changed arguments between repetitions, and the private-records fixture produced invalid output; both remain review findings.

These figures describe planner behavior, not an authority decision. CivicGate's deterministic policy remains authoritative and must block or route for review proposals that are ambiguous, out of scope or invalid. This native measurement is separate diagnostic evidence: the configured agent integration continues to use `/v1/chat/completions`, which returned a model-load error in this session and must be rechecked after confirming the exact LM Studio model identity.

### Direct llama.cpp and GBNF run

The same Granite instance was also tested through the direct llama.cpp server managed by LM Studio, using `proposal.json.gbnf` and the same Pydantic parser. Across 8 calls, median latency was **8.05 s**, p95 was **12.57 s**, with **8,356** input tokens, **606** output tokens, **11.47 prompt tokens/s** and **11.20 generation tokens/s**. TTFT was not exposed. The `Proposal` envelope was valid in **100%** of calls, the expected tool matched in **100%**, complete arguments were valid in **25%**, and valid proposals were **100%** consistent across repetitions. There were no timeouts or transport errors.

The envelope improvement comes from the direct GBNF constraint; it is not evidence that the model is Granite 3.2 or a global speed comparison. The observed identity remains Granite 3.1 Q3_K_L, and validation of arguments, dates, authority and scope remains independent.

### Direct Granite 4.2 run

The same matrix was repeated with `granite-4.2-8b-Q4_K_S.gguf`, SHA-256 `6b2438a9177be0883b27722dadd5271c8e18806e068a7fc30a42c481c000c092`, using LM Studio's Vulkan process, 21 GPU layers, batch `2048/512`, server context `131,072` and `enable_thinking=false` in the chat template. Across 8 calls, median latency was **9.02 s**, p95 was **14.41 s**, with **8,070** input tokens, **682** output tokens, **11.42 prompt tokens/s** and **11.05 generation tokens/s**. TTFT was not exposed. The `Proposal` envelope was valid in **100%** of calls, the expected tool matched in **100%**, complete arguments were valid in **25%**, and valid proposals were **100%** consistent across repetitions. There were no timeouts or transport errors.

With the template's default behavior, Granite 4.2 placed the JSON in `reasoning_content` and left `content` empty; the runner recorded that as a channel incompatibility rather than a valid proposal. The comparable benchmark uses `chat_template_kwargs: {"enable_thinking": false}` so the same envelope is delivered in `content`. CivicGate's deterministic policy remains authoritative.
