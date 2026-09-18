# Repository security boundary

The repository includes the public USAspending adapter and its documented public API origin because those are source code and interface documentation. It does not include local API traffic or model configuration.

Ignored by default:

- `.env` files except the deliberately empty `.env.example` template.
- API keys, tokens, credentials, certificates and private key formats.
- `audit/` traces and `*.ndjson` runtime captures.
- Generated API responses and local evaluation/test environment captures under `artifacts/`.

The three reviewed M2 benchmark summaries (`granite-agent-benchmark.json`, `judge-benchmark.json`, and `hybrid-evaluation.json`) are sanitized, credential-free artifacts and are tracked explicitly. Live API captures remain ignored even when the source endpoint is public.

The ignore rules protect the Git repository; they do not delete existing local files. Before publishing, the working tree was checked for credential-shaped values. The only API-looking strings are the public USAspending endpoint, empty configuration placeholders, test literals used to verify redaction, and documentation. Actual credentials must still be supplied through the local environment or secret store and must never be pasted into tracked files.

To refresh local evidence without changing repository contents:

```powershell
.\.venv\Scripts\python scripts\live_smoke.py
.\.venv\Scripts\python scripts\evaluate.py
```
