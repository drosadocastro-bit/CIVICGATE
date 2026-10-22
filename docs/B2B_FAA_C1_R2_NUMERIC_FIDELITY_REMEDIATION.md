# FAA-C1-R2 — exact monetary value and fingerprint remediation

Status: PROPOSED_FOR_INDEPENDENT_HUMAN_REVIEW. Local synthetic candidate only.
Git publication HOLD. Cloud deployment HOLD. No builder self-acceptance.

## Baseline and preserved red evidence

Worktree: `LOCAL_INTEGRATION_WORKTREE`.
Branch: `feat/b2b-faa-c1-integration`.
HEAD: `94692596503601bc53d0358faf659afb260c69be`.
The fourteen existing candidate identities matched before work. No change to main,
other worktrees, index, dependencies or historical evidence is authorized or made.

The independent review at
`PRIVATE_REVIEW_ARTIFACT`
was read with `EVIDENCIA_AUDITORIA.json` before source edits. Its 19,152 bytes hash to
`10ca5d2372c99a9b42050e13e57209f01acf96557d0957d45b9b1fd05bdfaf90`, matching the review evidence.
All five audit output identities are preserved in `04-independent-review-identities.json`.

Evidence directory:
`PRIVATE_R2_EVIDENCE_DIRECTORY`.

Before remediation, two explicit raw UTF-8 JSON fixtures reproduced CR-F01 through
actual Gateway plus MockTransport: both distinct amounts published as
`9007199254740994.0`, both RESULT_VERIFIED, with one dispatch each and the same
fingerprint `ec808ad0cb729adcd551c81079916e81faf231e0553a240bddae41ee2ed8c9fc`.
The red assertion, raw bytes, output and XML are retained as `original-raw-1.json`,
`original-raw-2.json`, `test_original_cr_f01.py`, `01-original-cr-f01-observation.json`
and `03-original-red-scoped.*`. It is a preserved **1 FAIL**, not an xfail.
The earlier `02-original-red.*` run failed collection because pytest attempted to
inspect `PRIVATE_EXTERNAL_COLLECTION_PATH` (WinError 1337). A separately logged run fixed the
external test root; it did not edit a source/test assertion or overwrite the failed run.

The first fixture has different IDs from the independent review, so its old hash is
not expected to equal the review's `64ccc490...`. The review's exact `raw_utf8` bodies
and query were also replayed after correction, without reconstructing their numbers
through float. Results are in `18-numeric-outcomes.json`:

| Exact reviewer JSON literal | Published canonical amount | New response fingerprint |
| --- | --- | --- |
| 9007199254740993.01 | 9007199254740993.01 | 7942f52343c88732391043b5ba15bdd762d38acb87e989242b799eb486424b32 |
| 9007199254740994.00 | 9007199254740994 | 6d94e86c5166093e73924365c145e97416f1e4b41a90cd2088b40a66c6de058d |

Both are now exact, distinct, PERMIT / RESULT_VERIFIED, with one synthetic read each.
Removing redundant fractional zeros preserves mathematical value; this is not a
claim of preserving monetary formatting or a SHA-256 collision remedy.

## Numeric contract defined before implementation

`06-numeric-contract-before-implementation.json` records the proposed local domain
before source edits. The version is **FAA-C1-MONEY-v1**. Its limits are conservative
engineering limits for this candidate, not USAspending guarantees, currency rules,
or an authorization to broaden production support. Human review is required before
broader integration. There is no rounding fallback for unsupported values.

| Property | Exact candidate rule |
| --- | --- |
| Input JSON | Strict UTF-8 JSON; integer tokens to int, decimal/exponent tokens directly to Decimal; duplicate keys and NaN/Infinity rejected |
| Token length | At most 96 ASCII characters for numeric tokens; integer tokens also bounded before int construction |
| Decimal grammar | Optional minus, JSON integer part, optional fraction, optional e/E signed exponent; no whitespace, leading plus/zeros, underscores or locale syntax |
| Precision | At most 38 Decimal coefficient digits, including retained trailing coefficient zeros |
| Exponents | Explicit exponent magnitude at most 38; Decimal tuple exponent before canonical trailing-zero removal also within -38 through 38 |
| Magnitude | Strictly less than 10^24 in absolute value |
| Fractional scale | At most 12 effective decimal places after removing trailing zeros; finer nonzero fractions withheld, never quantized |
| Negative values | Accepted under the same bounds |
| Zero | Positive, negative and scaled zero canonicalize to 0 within representation bounds |
| Scientific notation | Supported within bounds; output always plain fixed-point decimal |
| Existing strings | Strict JSON-number-grammar strings remain accepted, including the original fixture's quoted 123.45; arbitrary or malformed strings, booleans, null and nonfinite values are rejected |
| In-process floats | Rejected as monetary evidence, even if apparently integral; earlier rounding cannot be repaired |
| Publication | Canonical ASCII decimal string, no exponent, redundant fractional zeros, leading plus or negative zero |

Keeping strict numeric strings is deliberate compatibility with the original
FAA-C1 response model and fixtures. This task does not silently redefine every
string as invalid. They pass the same bounded exact-value checks as numeric tokens.
Representation limits may reject an excessively padded equivalent value; equivalence
applies only within the accepted domain. No arbitrary precision domain is promised.

`1`, `1.0`, `1.00`, `1e0` and the accepted string `"1.00"` all mean the canonical
monetary value `1`. Their raw JSON byte identities remain different. All supported
zero signs/scales map to `0`. Canonicalization uses Decimal tuples and fixed-point
formatting, never float, quantize, normalize, locale formatting or context-sensitive
arithmetic. Tests also lower the host Decimal precision and trap inexact arithmetic.

## Exact processing path and protected interfaces

1. HTTPX yields response content bytes (not authenticated TLS/HTTP wire provenance).
   The existing response size, status, content-type and single-attempt gates remain.
2. `parse_response_bytes` parses numbers exactly from those bytes using the same
   bounded parser in adapter and validator. It rejects duplicate keys and nonfinite constants.
3. `AwardRowV1` validates a finite bounded Decimal and unchanged DOT/FAA attribution.
4. JSON-mode row serialization emits the canonical decimal string. Python typed
   validation retains Decimal; no float round trip occurs.
5. `FaaResponseOutcome`, an FAA-local frozen subclass of the existing RequestOutcome,
   carries the original immutable response bytes alongside its parsed object. The
   shared interface/schema is not edited. Mutable parsed objects remain trusted-host
   material and are checked against the retained bytes.
6. Gateway's existing callback reparses the original bytes. It compares canonical
   content with the adapter's object, revalidates attribution/provenance, and checks
   the exact canonical published records and existing attempt metadata. It no longer
   reconstructs alleged source bytes with the old lossy JSON dump.
7. The existing shared DataBatch/Envelope and MCP serialization carry only JSON-safe
   records with amount strings. Actual local SDK HTTP tests verify those exact bytes'
   values after publication and durable intent/finish events.

Only `faa_adapter_v1.py` and `faa_profile_v1.py` are changed relative to the R2 start.
The small FAA-local `faa_money_v1.py` helper is necessary to give both validations one
versioned exact rule without changing global provenance or protected shared code.
Two new test files and this additive report complete R2. The earlier builder report
and its original claimed results are historical and remain byte-identical.

All five shared integration seams, `models/provenance.py`, the global fingerprint,
query/wire canonicalization, shared Envelope, Channel A/B2a source and dependency pin
are unchanged. FaaScopeV1's AST/schema and all eighteen policy-visible query fields
remain unchanged. Neither a monetary response nor its digest issues authority.

## Canonical content versus raw and source identity

The response content recipe is:

```text
canonical_content = UTF8(JSON(original parsed response,
    replace each Award Amount with exact canonical decimal string,
    sorted keys, compact separators, ensure_ascii=False, no NaN, no trailing newline))
response_fingerprint = SHA256(ASCII("FAA-C1-MONEY-v1") + LF + canonical_content)
raw_response_sha256 = SHA256(original received JSON content bytes)
```

Other fields and types remain in content identity; unsupported non-JSON types and
floats are rejected. The prefix deliberately changes FAA response fingerprint
semantics and prevents accidental comparison with the old recipe. Query fingerprints
and legacy Channel A/B2a response fingerprints are unchanged. Historical fingerprints
are never recomputed in place or reinterpreted as the new version.

Raw SHA distinguishes textual form, whitespace, ordering and signed/scaled zeros.
Canonical fingerprint identifies supported value content, intentionally ignoring
those equivalences and numeric-string versus numeric form for Award Amount.
The raw bytes live in the FAA-local call evidence and are included separately in the
reproduction artifacts. No new public raw-body field or production durable raw-body
custody guarantee is added to Envelope or the journal.

A fully malicious trusted Python host could replace source bytes and every matching
claim. This patch detects inconsistent/lossy projections, including coherently
rehashing a collapsed object while original bytes differ; it does not authenticate
government origin or create an unforgeable receipt.

## Actual validation and independent oracles

| Check | Fresh R2 outcome |
| --- | --- |
| Original raw-byte precision property before patch | 1 FAIL preserved |
| FAA-focused original and R2 suites | 277 PASS: all 188 original cases plus 89 added |
| R2 tests | 85 numeric cases plus 4 real loopback MCP HTTP cases |
| Full tests/ regression | 2768 PASS, 0 FAIL, 1 SKIP; 442.44 s; same two malformed-planner Pydantic warnings |
| Baseline node/outcome comparison | PASS: all 2680 original nodes retain outcomes; 89 new PASS; original XML is a historical reference, not a fresh baseline run |
| Fresh legacy before/after | PASS: four schemas, four discovery entries, ten decision/envelope/wire cases; only request_id and retrieval time excluded |
| Linux/Python 3.11.17 targeted subset | 554 PASS; one unchanged malformed-provenance fixture warning |
| Original FAA legacy negative controls | 2 FAIL preserved in a new run, same toptier and attribution causes |
| Ruff / formatting | PASS; 212 Python files |
| Strict Mypy | PASS; 64 source files |
| Dependency consistency | PASS; no packages installed or upgraded |
| Protected-file preservation / diff check | PASS: 248 protected current files, 884 prior-worktree files, 665 external historical files and five independent review outputs unchanged |


Fresh full-run subsets, included in the 2768 total rather than added to it: A1 76 PASS, A2 89 PASS, R1 721 PASS, B2a 50 PASS, B2b_P01_P02 166 PASS, synthetic_postgres_fencing 247 PASS. The single SKIP remains the non-Windows DPAPI test executed on Windows.

The new raw fixture template and expected decimal text are test-owned constants.
Fingerprint expectations use an explicit prefix and independent standard-library
serialization after assigning the expected exact amount; production helpers do not
compute the oracle's expected amount. Tests cover ordinary cents, signs, zero,
exponents, boundary precision/scale/magnitude, invalid types/syntax, duplicate keys,
actual MCP serialization, context independence, altered raw bytes/object/output/hash,
and a coherently rehashed collapsed projection. An independent integer/string grid
exercises exact/idempotent normalization under three Decimal contexts.

`18-numeric-outcomes.json` contains 56 fresh individual raw-byte observations
(20 accepted, 36 withheld), expected and observed values, complete canonical content,
policy traces and envelopes; it additionally includes the two exact reviewer cases.
These overlap tests and must not be added to PASS counts. The comparison is not a
statistical accuracy evaluation or an independent human acceptance decision.

Windows: Python 3.13.7, MCP 1.30.0, Pydantic 2.13.5, httpx 0.28.1,
LangGraph 1.2.15, pytest 9.1.1, pytest-asyncio 1.4.0, Ruff 0.16.8, Mypy 2.3.1.
The exact runtime inventory is `21-runtime.json`.
Linux: cached image `sha256:e2ba71a30941a2df449bc674565ac3078dae60007dc72628e0f6ba0730c9c77d`,
Python 3.11.17, network none, read-only repository/root, temporary /tmp, no install.
Its missing Git prevents the HTTP custody harness there: real MCP HTTP is verified
on Windows only, not Linux. Docker was started only for local tests and stopped afterward.

The first lint pass corrected two import-order findings in new/authorized files;
logs 07 and 08 are preserved. No pre-existing test expectation was changed.

## Reproduction

Exact argument arrays, environment and isolated Linux invocation are preserved in `28-verification-commands.json`. Use the recorded Windows interpreter and this worktree. Put its `src` and root in
PYTHONPATH and use a fresh external output directory, never overwrite historical logs.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH="$PWD/src;$PWD"
python -B -m pytest tests/mcp/test_faa_c1_r2_numeric.py tests/mcp/test_faa_c1_r2_numeric_http.py tests/mcp/test_faa_c1.py tests/mcp/test_faa_c1_controlled_acceptance.py tests/mcp/test_faa_c1_http.py -q -p pytest_asyncio.plugin -p no:cacheprovider
python -B -m pytest tests -q -p pytest_asyncio.plugin -p no:cacheprovider
python -B tests/mcp/faa_legacy_projection.py
python -B -m pytest experiments/b2b_faa_001/contract_gap_counterexample.py -q -p pytest_asyncio.plugin -p no:cacheprovider
python -B -m ruff check .
python -B -m ruff format --check .
python -B -m mypy src --strict
python -B -m pip check
```

The separate historical negative-control command intentionally exits nonzero.
`tests/` does not include that experiments/ file; both result sets are reported.
Do not rerun the original red harness against R2 and overwrite its historical output.
Its original source copies and measurements remain in the evidence directory.

## Remaining limits and human gate

This remediates the supported synthetic numeric domain. New magnitude/scale/precision
limits and canonical fingerprint identity require explicit review before broader
integration. Live USAspending compatibility, category/nullability availability,
per-row FY/type revalidation and production raw-response custody are not established.
No claim of general financial arithmetic or official currency precision is made.

CR-D02 (duplicated HTTP initialization), CR-D03 (shared core import coupling) and
CR-E04 (version-test interpretation) remain outside this narrow repair. The version
negative control demonstrates private issuer isolation; it does not independently
prove binding of InvocationContract.version. Query contract_version remains bound
in the exact arguments/schema. No protected module was changed to address that debt.

No real models, tokens, cloud operations, USAspending calls, commits, pushes, PRs or
merges. Local HTTP identities are synthetic fixtures. G1/G2, HeaderMismatch, J3/RQ6,
the original FAA failures and every recorded previous result remain historical.

CR-F01: REMEDIATED (supported synthetic domain)
NUMERIC CANONICALIZATION: VERIFIED_SYNTHETIC
RESPONSE FINGERPRINT INTEGRITY: PASS
CHANNEL A/B2a DIFFERENTIAL: PASS
HISTORICAL EVIDENCE: PRESERVED (recorded inventory)
INDEPENDENT REVIEW: PENDING
GIT PUBLICATION: HOLD
CLOUD DEPLOYMENT: HOLD

## Exact code identities

The final R2 inventory also measures this report; the accumulated candidate inventory
identifies all eighteen current review files separately from the prior fourteen.

| File | Before SHA-256 | After bytes | After SHA-256 |
| --- | --- | ---: | --- |
| src/civicgate/channel_b/faa_adapter_v1.py | 4a5648d648373bb05f43c936c1b79c122b613b89eeb5cc54322fc3e1d3a67de1 | 8296 | 27313df420b6adca1b74a1d68a7ad6b70b6dd6a6d4a21b00de328f14b7d177cd |
| src/civicgate/channel_b/faa_profile_v1.py | ffd9db9b7ecaa047becd7503b8178fef30796a2fb413e500361eb781e9508752 | 12447 | 0b5bfe87b06eb11c42716e5017bf37525fbbb726e65fb6dc36a2d542cf83cfe5 |
| src/civicgate/channel_b/faa_money_v1.py | NEW | 3563 | 146e6d65b0956a4a82e4c56ec5a4bcd9899b91f15cebfeaded6c0bfe77e6aa3b |
| tests/mcp/test_faa_c1_r2_numeric.py | NEW | 10682 | 06184e7cf8279d0fd20ab81270228d7046a9081dd1eec899a120b47402526d41 |
| tests/mcp/test_faa_c1_r2_numeric_http.py | NEW | 1937 | ea2b28f0bb52a6a22ecbc56562834086ec053d3478e26a030a57adc3f9d5230c |

> R4 editorial notice: This is a publication-sanitized derivative of an unchanged private original (SHA-256 c326291b34094ddcdbe33eaffd3032f960041b790eea3a949596645cff39d082). Only private filesystem references were replaced with non-runnable documentary labels. All technical content and historical results remain unchanged; these results describe the original runs, not fresh R4 verification. Current scope and evidence limits are recorded in review/EVIDENCE_BOUNDARIES.md.
