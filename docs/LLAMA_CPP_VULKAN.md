# Granite through llama.cpp and Vulkan

CivicGate can use the local llama.cpp path documented by H.E.L.M. without importing H.E.L.M. code, governance artifacts or authority. The H.E.L.M. checkout and its frozen records remain read-only. The portable boundary is the local OpenAI-compatible chat endpoint plus a direct GBNF grammar and independent CivicGate validation.

The exact model bytes available on this machine are:

```text
filename = granite-3.1-8b-instruct-Q3_K_L.gguf
sha256   = 3c24bb01ed1181cb936a9f03c41f1fd3341555ea68086a4b81713a137c765eb6
size     = 4,349,429,952 bytes
```

The H.E.L.M. reference build is `llama.cpp 0.4.1-dev`, commit `fb27a525d28381a16a4bb038858a10e4927381ca`, with Vulkan device `Vulkan1`, direct GBNF, and no unconstrained fallback. The corresponding local executable is `D:\llama.cpp\build\bin\Release\llama-server.exe`. The active LM Studio backend is a different build (`2.41.0`, commit `b49650a`) and currently runs the same GGUF with 19 GPU layers, context 131,072, batch `2048/512`, Flash Attention, KV offload and four parallel slots.

The reusable runner is `scripts/run_granite_llama_cpp_benchmark.py`. It sends a local-only `/v1/chat/completions` request with `proposal.json.gbnf`, records llama.cpp `usage` and `timings`, and then validates the returned Proposal and tool arguments with CivicGate's Pydantic models. It never writes the prompt, response body or API key. Use an environment variable for a server key; do not put the key in a command line or repository file.

The first direct run against the active LM Studio llama.cpp process used 8 calls (four fixtures, two repetitions) and the Q3_K_L hash above:

- median latency: **8.05 s**, p95 **12.57 s**;
- prompt tokens: **8,356** total; completion tokens: **606** total;
- prompt processing: **11.47 tokens/s** median;
- generation: **11.20 tokens/s** median;
- TTFT: **not exposed** by this non-streaming response;
- schema-valid Proposal: **100%**; expected tool selected: **100%**;
- tool-argument validity: **25%**; repeated valid proposals: **100% consistent**;
- transport errors and timeouts: **0**.

This direct GBNF result improves the outer Proposal contract compared with the native LM Studio diagnostic, while argument validity remains a separate semantic and schema concern. The two runs use different server paths and should not be treated as a global model-speed comparison. The deterministic CivicGate policy remains authoritative in both paths.

The active process is currently exposed on an LM Studio-managed loopback port. For a clean H.E.L.M.-aligned trial, unload the model from LM Studio first and start the pinned build in a separate local terminal. The command below is a template; it keeps the server on loopback and selects the discrete Vulkan device explicitly:

```powershell
$server = "D:\llama.cpp\build\bin\Release\llama-server.exe"
$model = "D:\lmstudio\models\lmstudio-community\granite-3.1-8b-instruct-GGUF\granite-3.1-8b-instruct-Q3_K_L.gguf"
& $server `
  --model $model `
  --host 127.0.0.1 --port 8080 --no-webui `
  --device Vulkan1 --n-gpu-layers 19 `
  --ctx-size 8192 --parallel 1 `
  --batch-size 2048 --ubatch-size 512 `
  --flash-attn on --kv-offload `
  --temperature 0 --top-p 1 --top-k 1 --min-p 0 --seed 23
```

Then run the benchmark with the exact model path. If the server was started without `--api-key`, no credential variable is needed:

```powershell
.\.venv\Scripts\python scripts/run_granite_llama_cpp_benchmark.py `
  --endpoint http://127.0.0.1:8080/v1/chat/completions `
  --model $model `
  --device Vulkan1 `
  --server-commit fb27a525d28381a16a4bb038858a10e4927381ca
```

The local result is written to the ignored `artifacts/granite-llama-cpp-benchmark.json`. The tracked grammar is [proposal.json.gbnf](../src/civicgate/llm/grammars/proposal.json.gbnf); its outer-envelope hash and all runtime metadata are recorded in that local evidence.
