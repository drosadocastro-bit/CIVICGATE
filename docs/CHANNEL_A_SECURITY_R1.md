# Channel A security remediation R1 — development candidate

R1 adds a bounded request-scope signal to the existing deterministic policy. It
does not create another authority issuer, authenticate human intent, or claim
complete English/Spanish semantic understanding. The four registered tools,
AuthorityEnvelope, ExecutionBinding, single-use dispatch and result/provenance
handling remain in place. MCP stays pinned to 1.30.0.

## Request scope

The unchanged lexical hard-denial checks run first. A separate, versioned signal
recognizes a deliberately narrow factual-read grammar. Unknown words, mixed
instructions, unsupported purposes, discussion and negation require review.
The entire clause must be recognized; a benign retrieval prefix alone cannot
permit the remainder. Raw request bytes remain available in audit. Normalization
is used only for the independent signal.

The signal is evaluated inside `policy.evaluate`, including when the Judge or
Agent K is disabled by trusted configuration. A model's IN_SCOPE classification
or confidence cannot remove an independent review reason. Original request text
is supplied separately from the proposal and bound into the existing policy-fact
digest. Missing confidence calibration remains a limitation; 0.85 is a rule,
not a measured probability of correctness.

Names, natural-language filters and legitimate discussion outside the bounded
grammar may require review. Existing hard-denial false positives remain: R1
does not treat quoted or benign high-risk words as authority to bypass those
protections. The original 28-case corpus and lexical counts are unchanged.

The R1 follow-up requires explicitly JSON-quoted recipient/agency name values;
capitalization no longer delimits lookup data. Unquoted unknown text is retained
and requires review. See [the name-literal contract](CHANNEL_A_NAME_LITERAL_CONTRACT.md).
Literal values establish neither identity nor authorization. Terse
research intake requires a noun-phrase structure; ambiguous imperative uses of
"award" and "contract" cannot use that shorthand path.

## One trusted local owner

**Shared multi-client composition is prohibited.** The deployment contract is
one Gateway, one MCP server, one physical stdio channel, one trusted local client
owner. The host must give different clients separate processes/Gateways; it must
not multiplex different people or trust domains over a shared channel, transport,
agent or direct Gateway reference. No caller-supplied session identifier is an
authenticated identity.

A Gateway permanently rejects a second MCP server attachment. The server rejects
public SSE/HTTP transports and permanently reserves its stdio runner, including
after normal exit, failure or cancellation. Request ingress binds the actual
SDK-owned ServerSession object; a second SDK session cannot take over even with
identical caller metadata. These are composition guards, not human or tenant
authentication. Direct internal calls remain trusted compatibility interfaces.
Malicious Python inside the trusted process and private SDK access are not
sandboxed.

The existing tripwire counter remains instance-local: repeated same-owner
violations accumulate, and rewrapping/discovery does not reset them. No public
reset, reconnect reset, self-granted reset authority or new identity provider is
introduced. The Gateway lock still serializes shared-instance work; head-of-line
blocking is not solved. Constructing a new process/Gateway remains a trusted-host
operation and must not be offered as an untrusted reset service.

## Evidence and tests

The pre-remediation six-file review ZIP, original measurements and 1274 PASS,
0 FAIL, 1 SKIP result are preserved externally with their original identities.
The original lexical counts remain TP=4, FN=10, FP=11, TN=3. Current R1 expectations
are separate in `channel_a_remediation_r1_expectations.json`; the two old
cross-wrapper tests now explicitly assert rejected sharing. No historical FAIL,
frozen reference or scientific receipt is recoded.

The legacy evaluation fixture remains unchanged. R1's separate
`channel_a_legacy_evaluation_r1.json` records changed review expectations and uses
a clear read request for two transport-receipt tests. The current golden-path
test explicitly checks pre-dispatch review of an unrecognized free-form name;
the baseline test and its historical result remain recoverable from 61ac341.

CI explicitly selects the pinned projection with
`python scripts/evaluate.py --projection channel-a-legacy-evaluation-r1`.
The shared evaluator verifies the original fixture digest, the independently
pinned projection digest, the closed eight-case override contract and unique
case identities before creating a Gateway. Overrides apply only to parsed
in-memory cases. Tools, arguments, categories, transport factories and observable
receipt assertions are unchanged. Running without the option retains the
original evaluation contract and its known R1 incompatibility.

The projected report is separate at
`artifacts/evaluation.channel-a-legacy-r1.json`. It records both input digests,
the effective-case digest, changed fields and original/effective request text.
Six overrides version expected decision/status outcomes; two substitute a clear
read request to exercise the original transport receipts. Those substitutions do
not establish success for the original timeout/error requests: separate controls
require those original requests to remain held before backend dispatch.
Fixture expectation matches and request-success/availability metrics remain
distinct. A 35/35 projected match result is synthetic contract conformance,
not the original historical result or measured real-model accuracy.

The previous publication attempt's evaluator failure remains preserved. Its
first reached incompatible receipt expected two attempts and observed zero after
the request was held for review. This explicit versioned CI integration addresses
the evaluator/test contract divergence; it does not relax Gateway policy or
rewrite the historical fixture, failure or measurements.

The independently specified 24-case EN/ES set was fixed before implementation
and evaluation. Developers saw the specification; this is not a blinded human
adjudication or a population-accuracy sample. R1 measurements use only synthetic
permissive, unavailable, conflicting, cautious and disabled Judge conditions.
Reports must include unsafe permits, benign hard denials and benign review holds
separately. Conservative review of every unfamiliar request is not proof of
semantic understanding.

MCP/LangGraph still make one logical tool invocation without automatic tool
retry. Lost responses and post-dispatch errors remain DISPATCH_UNKNOWN. Existing
bounded read-only HTTP adapter retries are a different layer and are unchanged;
no cross-process exactly-once guarantee is claimed.

R1 is not production approval. Publication, deployment, live model/API operations
and any authority/scientific transition require separately authorized work.

## Final intent/argument consistency correction

Explicit name recognition alone cannot authorize a different lookup. The policy
now receives immutable, schema-validated effective arguments from Gateway and
checks every recognized recipient/agency literal against its corresponding
recipient_name/awarding_agency filter. Missing, mismatched, wrong-role or
unsupported relationships require REVIEW_REQUIRED before authority issuance.
Only the existing two Search tools express this scoped-read relationship;
award-ID detail and recipient-candidate resolution do not establish it.

The same JSON decoder and recognizer supply both syntax and field roles,
including Unicode case-insensitive labels. Exact equality follows existing Text
validation's outer-whitespace stripping; no case, accent, Unicode normalization,
homograph or internal-space equivalence is inferred. Escapes cannot hide existing
hard-denial terms. A1 independently checks agreement between the policy argument
snapshot and the invocation it binds, then applies its existing single-use
pre-dispatch gate. Planner arguments are never rewritten. The full rule and its
limits are in [the name-literal contract](CHANNEL_A_NAME_LITERAL_CONTRACT.md).

The reported agency mismatch, missing filter, wrong filter role and unrelated
tools were reproduced through the actual Gateway with a synthetic backend. All
20 discrepant proposals across the four Judge/Agent K configurations now require
review with zero dispatches; four matching agency searches remain permitted.
Independent review also found a Unicode recipient-label role confusion. Its
failing controls were preserved before correction; the final recognizer-derived
role and actual MCP object/JSON-string ingress are covered by new regressions.

## Residual availability and historical results

The original corpus still has **11 lexical false positives** (TP=4, FN=10,
FP=11, TN=3); those benign hard denials were not weakened to improve metrics.
The independent realistic set still has **20 benign natural-language requests
requiring REVIEW_REQUIRED**, with 0 PERMIT and 0 DENY under all five synthetic
Judge modes. A conservative hold is not proof of complete semantic understanding.
Supplemental filters not explicitly constrained by a recognized name, entity
existence and complete natural-language request/proposal equivalence remain
outside this narrow check. The 0.85 Judge threshold remains uncalibrated.

The earlier pre-publication local reference is **1995 PASS, 0 FAIL, 1 SKIP** on
Windows/Python 3.13.7, MCP 1.30.0 and LangGraph 1.2.15. It includes 252 new
intent/argument adversarial controls and 26 new actual SDK stdio cases. The skip
is the existing non-Windows DPAPI contract test on Windows. All model and public
data responses in these security evaluations are synthetic; no real-model
accuracy or production approval follows from their results.

After explicit CI projection integration, the local full-suite result is
**2028 PASS, 0 FAIL, 1 SKIP**, including 56 evaluator-reporter tests (33 additional
controls). The projected CLI matches 35/35 expected synthetic outcomes; the
historical valid-category success metric remains 4/8, rather than being replaced
by the fixture-match count. Ruff, formatting, Mypy, dependency checks, offline M2
reports and the synthetic MCP stdio demo pass. The initial local dependency audit
against pip 25.2 is preserved; applying the workflow's existing pip/setuptools
bootstrap yields no known dependency vulnerabilities. This does not audit the
unpublished local package against PyPI vulnerability records.

Earlier evidence remains separate and unchanged: original Security Sprint
1274 PASS / 0 FAIL / 1 SKIP, initial R1 1476 PASS / 0 FAIL / 1 SKIP, and the named
literal follow-up 1717 PASS / 0 FAIL / 1 SKIP. The intermediate intent candidate's
1943 PASS run and subsequently discovered failing Unicode controls are retained;
that earlier passing suite did not cover the newly found adversarial class.

The original A2 branch's **570 PASS, 2 FAIL, 1 SKIP** remains a historical result.
Its two J3 freeze-identity findings are not recoded, excluded or represented as
the same test contract as the later successful integration CI on main baseline
61ac3416af4a109a2e1fd3f58b6aab1415737e43. That existing integration result is
[CivicGate validation run 38442804502](https://github.com/drosadocastro-bit/CIVICGATE/actions/runs/38442804502).
No J3/RQ6 frozen manifest, historical failure, scientific receipt or original A2
evidence is modified by this development candidate. Publication requires fresh
local checks and CI on its exact commit; it does not authorize a merge, deployment,
live model/API operation or scientific authority transition.
