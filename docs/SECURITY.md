# Security boundaries

Sandbox and local stdio only. No public deployment, inbound HTTP listener, private records, procurement decisions, payment execution, eligibility determinations, government writes or arbitrary endpoint tools.

## Trust boundaries

Agent proposals, user text, judge output and source strings are untrusted. Only server code supplies capability and transport configuration. MCP annotations are descriptive hints; the gateway enforces policy independently. Test adapters and mock judge require explicit construction/configuration; production configuration never falls back to them.

The USAspending adapter uses a fixed HTTPS origin, bounded path identifiers, no redirects, no credentials, no ambient proxy/netrc configuration, 5-second connect / 15-second I/O timeout, 20-second total limit per attempt, three attempts maximum, and bounded exponential delays (0.2 / 0.4 seconds). Only timeouts, transport failures, HTTP 429 and 5xx are retried. Read-only POST searches are safe to retry. Responses are capped at 2 MB decompressed and validated before release.

Model configuration is distinct from public-data access. Model credentials go only to the configured model origin. HTTPS is mandatory except loopback HTTP. Redirects and URL-embedded credentials are rejected. Model calls have a 30-second outer budget, bounded tokens and a 100 KB response cap. No model output is executed as code or used as a URL. Provider errors are converted to unavailable semantic state without exposing provider response bodies.

Milestone 2 separates `ConfigurationProvider` and `SecretProvider`; `.env` files are never loaded as an authority source. An optional Windows DPAPI-backed store encrypts local values at rest and is isolated at the process edge. GitHub live evaluation receives credentials only from repository secrets. Benchmark artifacts contain statuses, metrics and fingerprints, never API keys or raw credential-bearing responses.

## Audit

Audit appends before execution and after results. Failure to write the pre-execution audit prevents execution. Failure of final logging is surfaced as an invocation error; a previous public read cannot be undone. Files are append-only by application convention, not cryptographically tamper-proof. Use OS permissions and rotation outside the MVP. Retention/disk quotas are operator responsibilities.

Known token patterns and credential-named fields are redacted, and model configuration is never written. Arbitrary secrets pasted without recognizable labels cannot be reliably detected: supply only public research questions. Full user requests and public records otherwise appear in the local audit file. The in-memory diagnostic window is capped at 1000 events.

## Explicit limitations

Containment is process-local and resets on restart; no multi-user authentication is claimed. Stdio relies on OS process access. If HTTP is added later, it needs separate caller authentication/authorization and session isolation; model credentials must never double as gateway credentials.

No hidden tools, sandbox escapes or robust prompt-injection immunity are claimed. Source text remains data and is never automatically executed. Python module privacy is not a security boundary against malicious code running in the same process. Untrusted model/plugin code must not be installed in the trusted server process.

Docker runs UID 10001 without published ports. CI tests read-only root filesystem, dropped capabilities, no-new-privileges and a writable temporary audit directory. Local Docker daemon availability is documented separately from Dockerfile correctness.
