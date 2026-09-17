# CivicGate

Governed MCP access to public US federal spending data. **Capability does not create authority.**

Milestone 1 is a sandbox prototype: Python 3.11+, Pydantic, four read-only MCP tools, a natural-language agent, advisory semantic judge and Agent K, and a deterministic authority gate. USAspending is the only government source. No governmental decisions, private systems, payment execution or government writes.

## Quickstart

From this repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\civicgate demo
.\.venv\Scripts\pytest -q
.\.venv\Scripts\python scripts/evaluate.py
```

On Linux/macOS replace `.\.venv\Scripts\` with `.venv/bin/`.
The demo uses **explicit synthetic data and a mock judge**, produces PERMIT / DENY / REVIEW_REQUIRED, and writes `audit/demo.jsonl`. It does not measure real-model accuracy. No synthetic fallback exists in live mode.

## Agent and model configuration

Configuration comes from environment variables; `.env.example` is a reference and is not automatically loaded. The default provider is unavailable and blocks execution for review.

```powershell
$env:CIVICGATE_PROVIDER = "openai_compatible"
$env:CIVICGATE_MODEL_BASE_URL = "http://127.0.0.1:8080/v1"
$env:CIVICGATE_AGENT_MODEL = "your-installed-agent-model"
$env:CIVICGATE_JUDGE_MODEL = "your-installed-judge-model"
# If required, set CIVICGATE_MODEL_API_KEY through your local secret mechanism.
.\.venv\Scripts\civicgate ask "Show federal awards to recipient WESTON SOLUTIONS INC in Puerto Rico during FY2025."
```

The endpoint must support chat completions and JSON object responses. There are no model credentials in this repository. Agent and judge interfaces can be replaced independently. The provider implementation is wired but real-model quality has not been evaluated. An invalid response, timeout or missing model cannot grant permission.

## MCP

Run `.\.venv\Scripts\civicgate-mcp`, or configure an MCP host with:

```json
{
  "mcpServers": {
    "civicgate": {
      "command": "D:\\CIVICGATE\\.venv\\Scripts\\python.exe",
      "args": ["-m", "civicgate.mcp.server"],
      "env": {"CIVICGATE_AUDIT_PATH": "D:\\CIVICGATE\\audit\\trace.jsonl"}
    }
  }
}
```

Pass model configuration in the host environment to enable semantic assessment. Missing configuration yields REVIEW_REQUIRED. Each tool takes `user_request` (the original request) and a validated `query` object. Clients cannot submit trusted judge signals, capability claims or policy decisions. Protocol-invalid requests return MCP `isError`; valid tool invocations return the common structured envelope.

| Tool | Goal |
| --- | --- |
| `find_federal_awards` | Retrieve a bounded award page |
| `get_federal_award` | Look up a known internal or generated award ID |
| `resolve_federal_recipient` | Present public identity candidates for clarification |
| `summarize_federal_spending` | Sum award amounts from one authorized returned page |

Limits: up to 100 awards, 25 recipient candidates, one page, date interval at most 367 calendar days. Searches require a recipient, agency or state filter. `state_code` means **place of performance**, not recipient address. Defaults cover contracts; selected non-loan assistance types are supported. Loans and IDVs are intentionally excluded from this first amount-aggregation contract.

Award totals are not fiscal-year transaction spending. A date filter finds matching awards; their award amounts may cover multiple years. Truncation is explicit and summaries never claim a population total. Name matches do not establish legal identity.

## Verification and evidence

```powershell
.\.venv\Scripts\ruff check .
.\.venv\Scripts\ruff format --check .
.\.venv\Scripts\mypy src
.\.venv\Scripts\pytest -q --junitxml=artifacts/tests.xml
.\.venv\Scripts\python scripts/evaluate.py
.\.venv\Scripts\pip-audit
# Optional public internet contract check; no API key:
.\.venv\Scripts\python scripts/live_smoke.py
```

See [evaluation](docs/EVALUATION.md), [build report](docs/BUILD_REPORT.md), [demo](docs/DEMO.md), [architecture](docs/ARCHITECTURE.md), [authority](docs/AUTHORITY_MODEL.md), [security](docs/SECURITY.md), [GSA alignment](docs/GSA_ALIGNMENT.md), and [mechanism transfer](docs/PRAETOR_MECHANISM_TRANSFER.md).

CI defines Ubuntu/Windows Python 3.11/3.12 checks and a Linux Docker smoke. Remote CI has not run until the repository is published and a workflow executes. Docker is stdio-only, runs as non-root, and exposes no port. Build with `docker build -t civicgate:test .`; use `python scripts/container_smoke.py` for protocol verification.

This is not production-ready. PRAETOR served only as a read-only mechanism reference; none of its research results validate CivicGate. No commit, push, deployment, extra domain or write capability is included.
