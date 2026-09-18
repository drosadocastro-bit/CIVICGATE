# Granite planner benchmark

The benchmark compares the planned CivicGate role for IBM Granite 3.1 8B Q3 and IBM Granite 4.2 8B Q4 through the same LM Studio OpenAI-compatible endpoint. Its classification is `PRACTICAL_DEPLOYMENT_COMPARISON`. It does not establish a globally better model.

Before trials, record LM Studio version, GGUF filename and hash, model quantization, backend/device, context and maximum output tokens, temperature/top-p/top-k/seed, reasoning setting, system and schema prompt, timeout, repetitions, fixtures and strict parser. A missing item leaves the trial `BLOCKED_CONDITIONS_NOT_FROZEN`.

Report latency, exposed TTFT, prompt and generation token rates, observed memory/VRAM, timeout/error counts, tool selection, argument validity, malformed output, unnecessary invocations, ambiguity preservation, authority overreach, hidden-tool attempts and repeat consistency separately. `NOT_EXPOSED` is a valid observation; it is never converted to zero.

Role conclusions are limited to `MODEL_ACCEPTABLE_FOR_CIVICGATE_PLANNER`, `MODEL_REQUIRES_REVIEW`, or `MODEL_NOT_ACCEPTABLE_FOR_CIVICGATE_PLANNER`. Quantization, generation and runtime are confounded until the exact trial conditions are frozen.
