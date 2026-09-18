# Live model limitations

Live planning and judging require externally configured endpoints and credentials. No credential, API response, latency, cost or model output is committed. Normal CI is deterministic and credential-free; `.github/workflows/live-evaluation.yml` is manual and opt-in.

The opt-in workflow runs `scripts/run_live_model_evaluation.py` for a single typed planner and judge contract check, then writes a local ignored artifact. It does not promote a model, issue policy decisions or publish raw provider bodies.

LM Studio telemetry may not expose TTFT, prompt/generation rates or VRAM. The benchmark records those as unavailable. Endpoint version, model/GGUF hash, backend, device, sampling settings, prompt, parser, timeout and repetitions must be captured before a trial. Changing quantization or generation settings changes the comparison.

Live USAspending checks are also separate observations: retain UTC timestamp, endpoint, query and response fingerprints, latency, schema validity, record count and truncation. Do not freeze changing public content or treat one sample as uptime or factual assurance.
