# J3-CREDENTIAL-ACCESS-001: selective DPAPI access

Status: proposed prospective implementation, offline review only. No publication,
credential access or live run is authorized by this document.
Parent: `ab561de8bf0a5cf61cc38e7f7caaba3c5861b9b0`.

## Decision and behavior

Credential selection and credential decryption are distinct operations.
Future frozen J3 executions require the secret store to decrypt only the
provider-owned credential explicitly requested by the selected provider
profile. Enumeration, lookup of a missing name, and access to unrelated
entries must not cause unrelated secrets to be decrypted.

The Anthropic profile owns `CIVICGATE_ANTHROPIC_JUDGE_API_KEY`; the OpenAI
profile owns `CIVICGATE_OPENAI_JUDGE_API_KEY`. There is no generic experimental
credential fallback.

Requested credential selection must precede decryption. `get` and `get_secret`
load the encrypted JSON container, select the exact name, and decode/decrypt
only that entry. Missing names return None with zero decryptions and no fallback.
`list_names` and the CLI list command do not decrypt. `set_value` encrypts only
the replacement/new value and preserves every other ciphertext string exactly.
The JSON layout and Windows-user DPAPI format are unchanged; no migration or
credential re-entry is required. File formatting is not a ciphertext identity.

The container's object/string shape is still validated. A structurally invalid
container fails closed. A corrupt ciphertext string belonging to another name
is not decoded or decrypted and does not block the requested entry. Corrupt
requested Base64, DPAPI or UTF-8 data fails explicitly without fallback. CLI
errors report the exception class only, never exception values. Reading the
encrypted container is not claimed to be zero filesystem access; decryption is
restricted to the selected entry.

The existing write mechanism remains a whole-file write. This pass does not
add concurrent-writer coordination or transactional filesystem semantics.
Tests prove an encryption failure occurs before the existing file is written.

## Prospective freeze and historical lineage

`src/civicgate/windows_dpapi.py` changed. Therefore
`ab561de8bf0a5cf61cc38e7f7caaba3c5861b9b0` remains the historical
provider-neutral baseline; selective access requires a new prospective
published baseline. Historical seals and manifests remain unchanged. No
verification check is disabled or bypassed.

The original validators and manifests remain unchanged. They correctly reject
this checkout because its source dependencies differ. They remain usable with
their original Git checkout; historical evidence is not regenerated.

The new `scripts/j3_credential_amendment.py` validates the separate
`docs/J3_CREDENTIAL_ACCESS_001.json` manifest. Its parent dependency map is
extracted from the published parent commit, normalized only for CRLF/LF, and
anchored by a SHA-256 constant in the new verifier. The manifest pins current
dependency hashes, exact allowed modifications, exact additions, both historical
manifest identities, the semantic contract and fixture corpus. It rejects extra
sources, missing sources, undeclared changes, rehashed unauthorized changes,
changed historical manifests and changed ancestry maps. The anchor can be
verified in a shallow CI checkout without downloading historical objects;
its extraction from the parent Git tree is retained in external review evidence.

Only the provider-neutral runner's future seal/verification path adopts this
new verifier. Both provider profiles, observer, semantic parser, prompt/schema,
fixture order, 35+9 schedule, journal/accounting logic, identity policy, failure
taxonomy and scoring remain unchanged. The CLI uses the same approved DPAPI
store and provider-specific credential name, with no environment fallback.

The execution seal includes the new manifest's raw hash. Sealing still requires
all dependencies (including the new manifest) to match committed content. Old
execution seals do not authorize this changed instrument. No execution seal is
created in this offline pass. Publication, exact-SHA CI, a new smoke decision
and any full-run authorization remain separate gates.

Tests of the historical manifest now explicitly assert rejection of the amended
checkout. The Git-binding unit test isolates its Git branch with a synthetic
manifest generator; production verification is not patched. No tests are skipped
to accept the changed identity. New tests prove the prospective verifier fails
on source, ancestry, manifest, allowlist and scientific-identity tampering.

## Evidence and scope

Native DPAPI calls and external network are forbidden in offline validation.
Cryptographic counters use synthetic entries and portable test doubles only.
The historical smoke's one logical retrieval did not prove one decryption:
the original helper decrypted all stored entries before selection. That finding
does not alter historical reports or semantic outcomes; it motivates this
prospective amendment. Neither historical model output nor a new live result
is generated to validate this change.

No evidence of credential disclosure was established. Sonnet Run 002 remains
unchanged. The Luna smoke remains historical evidence of interoperability,
but its one logical OpenAI credential retrieval must not be reinterpreted as
proof of exactly one exclusive OpenAI DPAPI decryption. No historical result
is rewritten, and no disclosure of Anthropic credentials is inferred.

Comparison remains PRACTICAL_PROVIDER_COMPATIBLE_JUDGE_COMPARISON.
Provider-specific configurations limit strict model-to-model causal comparability.
No new claim about Luna accuracy, safety or superiority follows from credential
isolation. Builder, reviewer and human authority remain distinct.
