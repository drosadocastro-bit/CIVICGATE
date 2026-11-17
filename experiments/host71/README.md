# Host71: dormant READ-only candidate

This is a new, curated experimental release, not a historical LIVE approval or a production-ready UI. The source-level release gate remains closed. There is no browser interface, activation switch, credential bootstrap, or executable approval harness in this package.

## Scope

The dormant coordinator composes one Nemotron planner, one Luna advisory judge, one bounded USAspending READ, and one Nemotron final answer. It binds the final answer to the fresh READ capture, keeps durable attempt reservations and uncertainty fences, and requires separately installed, reviewed authority. No WRITE route is exposed by this candidate. The existing repository supplies shared dependencies; it is not duplicated here.

`dependency-freeze-v3.json` hashes the shared repository dependency set. `chat-source-inventory-v1.json` is a newly generated inventory of this candidate. Neither carries forward permission or historical release fingerprints. Changing a bound file invalidates its inventory and requires review and regeneration.

## Offline verification

From the repository root, with its `src` on `PYTHONPATH`:

```text
python -B -m pytest experiments/host71/tests --confcutdir=experiments/host71/tests -q -p no:cacheprovider
```

The test bootstrap blocks external networking before runtime imports. End-to-end tests use disposable copies, a test-only gate patch, fake credential storage, HTTP mocks, and external-network denial. They exercise the genuine orchestration branch, but do not make actual provider or USAspending calls. LIVE-shaped receipts inside these isolated tests are simulations, not evidence of LIVE execution. Production candidate files remain gated.

Tests cover successful composition, planner timeout, partial READ uncertainty, answer contract failures, authority/capture/readback tampering, and consumed reservations. Local verification is Windows Python 3.13 only; the configured Windows/Linux CI matrix is not yet verified.

## Limits and next review

No provider cost is guaranteed by a local preflight estimate. Provider accounting and current pricing require separate verification before any authorized execution. Free-form factual checking is bounded and does not prove complete semantic correctness. Successful answers remain review-required: AI-generated responses may contain mistakes. Always check the cited sources. Award Amount is not actual spending, and bounded public READ results are partial.

A real execution still requires reviewed activation, independently installed authority, applicable credential access, current provider/cost checks, and explicit scope approval. This package does not grant any of them. No secret, historical raw response, personal approval identifier, or historical custody database is included.
