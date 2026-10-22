# FAA-C1-R4 publication candidate: evidence boundaries

Status: READY_FOR_HUMAN_REVIEW. Git publication HOLD. Cloud deployment HOLD.
This package grants no execution, publication, merge or deployment authority.

## Package identity and use

This is a 20-file review overlay, not a standalone runnable repository. Apply only
in a separately authorized isolated checkout of base 94692596503601bc53d0358faf659afb260c69be with the existing
pinned dependencies. The package contains 16 unchanged source/test files, two
sanitized historical reports, this note and a minimal manifest. No raw private
inventory, internal audit log, credential, environment or complete repository is
included. A manifest is a consistency record, not an independently authenticated
authority or government-source signature.

All 16 source/test identities equal the R3 inventory. Only six private filesystem
references in the two reports were replaced with documentary labels, and each
report received an editorial notice. The private originals remain unchanged.
The manifest records original and derivative hashes separately. Private redaction
mapping is intentionally excluded. Historical report line numbers may differ from
the original review; those reports describe their original runs and original code
stages, including the pre-R2 numerical limitation.

## Fresh R4 observations

Windows/Python 3.13.7; MCP 1.30.0; Pydantic 2.13.5; HTTPX 0.28.1; LangGraph 1.2.15.
The isolated derivative passed 277 FAA/R2 focused tests and the complete tests/
suite: 2768 PASS, 0 FAIL, 1 SKIP. The unchanged skip is the Windows-specific DPAPI
platform control. The same 2769 test-node outcomes match R3. Ruff check and format,
strict Mypy, installed dependency consistency and git diff --check passed.

Fresh base and candidate A1/discovery/B2a suites each passed 126 tests. Four legacy
schemas, four discovery entries and ten policy/dispatch/result projections match
the base exactly after exclusion of request UUID and retrieval timestamp. This is
bounded behavioral compatibility, not proof that the five intentionally changed
shared modules are byte-identical to the base. Their R4 bytes equal reviewed R3.
Targeted and full tests overlap and must not be summed as independent evidence.

The first R4 runs had external test-directory setup errors; all command, error and
XML evidence remains preserved privately. New runs followed correction of that
external setup, without modifying code or tests. A read-only audit helper also
encountered a locale-decoding error; its subsequent UTF-8 inspection changed no
source bytes. These preparation errors are not hidden or reported as product
failures. Two malformed-planner Pydantic warnings remain in the complete suite.

## Preserved historical findings

The two original FAA legacy negative assertions still produce two ordinary FAILs
in a fresh separate R4 run. They are outside tests/, not xfailed or erased. The
original CR-F01 precision failure and its initial collection error remain unchanged
private evidence. The R2 correction preserves exact bounded decimal values and
canonical fingerprints in the synthetic contract. Historical G1/G2, HeaderMismatch,
J3/RQ6 and earlier research findings remain unchanged; no scientific re-freeze was
performed.

R3 Linux/Python 3.11 subset (554 PASS), the 101-case numerical oracle and earlier
reviewer replays are historical observations, not fresh R4 executions. R4 did not
run Linux, PostgreSQL, Databricks, OAuth or a live model/API.

## Limits and technical debt

FAA transport is restricted to httpx.MockTransport. Actual USAspending response
compatibility, category/nullability coverage, returned identifiers, fiscal-year
semantics and data completeness are NOT_VERIFIED. Award amounts on one bounded
page are not total FAA spending. Fixture fingerprints do not authenticate government
origin or immutable pre-adapter raw-response custody. Equivalent decimal byte
representations can share canonical content identity while raw-body hashes differ.

The local host and startup composition are trusted. No independent human-intent
authentication, production caller identity, cloud Host/proxy guarantee or distributed
exactly-once execution is established. Initial authorization, dispatch, final
validation, provenance and post-dispatch REVIEW_REQUIRED remain separate facts.
No automatic retry or Channel A/B failover is authorized.

Known future-work gates remain: TD-A05 evidence/claim discipline; TD-A06 duplicated
HTTP composition; TD-A07 shared-core dependency on an experimental contract;
TD-A08 issuer isolation versus independently isolated version identity; TD-B01
planner/discovery scope integration; TD-B03 uncalibrated confidence; TD-B05 live
response drift; TD-B06 cloud identity; TD-B07 distributed custody/uncertainty.
CR-F01/TD-B09 synthetic numeric remediation does not close the live-backend gates.
No new P0/P1 finding was identified in this bounded documentary audit and unchanged
source verification. This is not an exhaustive new vulnerability audit or independent
human acceptance. Broader scope needs separate evidence and authorization.

## Review gates

Danny must review these exact publication identities and separately authorize any
future commit/PR. Remote state, CI and publication have not been reverified here.
No commit, push, PR, merge, upload, README change, dependency upgrade, real tool call
or cloud operation occurred. Production and cloud readiness are not claimed.
