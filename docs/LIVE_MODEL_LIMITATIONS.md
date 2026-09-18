# Live model limitations

Live planning and judging require externally configured endpoints and credentials. No credential, API response, latency, cost or model output is committed. Normal CI is deterministic and credential-free; `.github/workflows/live-evaluation.yml` is manual and opt-in.

The opt-in workflow runs `scripts/run_live_model_evaluation.py` for a single typed planner and judge contract check, then writes a local ignored artifact. It does not promote a model, issue policy decisions or publish raw provider bodies.

LM Studio telemetry may not expose TTFT, prompt/generation rates or VRAM. The benchmark records those as unavailable. Endpoint version, model/GGUF hash, backend, device, sampling settings, prompt, parser, timeout and repetitions must be captured before a trial. Changing quantization or generation settings changes the comparison.

For local diagnosis, `scripts/run_granite_lmstudio_benchmark.py` can use LM Studio's native `/api/v1/chat` endpoint, which exposes TTFT and token statistics. In the recorded session, the operator called the model Granite 3.2 while LM Studio reported `ibm/granite-3.1-8b`; that identity mismatch remains a review condition. Native benchmark evidence is kept in the ignored local artifact and does not replace the configured `/v1/chat/completions` integration contract.

The H.E.L.M.-aligned direct path is documented in `docs/LLAMA_CPP_VULKAN.md`. It uses a local llama.cpp server with direct GBNF, then applies CivicGate's independent Proposal and tool-argument validation. Granite 4.2 needs `--disable-thinking` with the current LM Studio template so its constrained JSON arrives in `content` instead of `reasoning_content`; the runner records that choice. It avoids the failing OpenAI-compatible constrained route observed in this session, but it does not make invalid dates or authority-sensitive requests safe; deterministic policy and review gates still decide.

Live USAspending checks are also separate observations: retain UTC timestamp, endpoint, query and response fingerprints, latency, schema validity, record count and truncation. Do not freeze changing public content or treat one sample as uptime or factual assurance.
