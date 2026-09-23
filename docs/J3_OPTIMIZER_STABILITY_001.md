# J3-OPTIMIZER-STABILITY-001

Status: prospective implementation for human review; not published or live-authorized.
Parent: `c06550cfd235c8d3c7690ebbdbb06a3d252cb3e1`.

This follow-on amendment does not rename or reopen
J3_CREDENTIAL_ACCESS_001_PUBLISHED_CI_PASS. The published credential manifest
and document remain unchanged. Logical credential retrieval is not equivalent
to exclusive secret decryption; no credential disclosure is established.

## Findings and correction

The historical credential verifier used integrity-critical Python assertions.
Normal execution rejected a tampered parent commit; optimization removed the
checks and accepted it. The hardened credential verifier and this follow-on
verifier use explicit runtime branches, with sanitized failure classifications.
This finding alone does not establish an end-to-end execution bypass.

Separately, Python -OO removes the wire model's docstring, which Pydantic used
as the schema description. The generated prompt then hashed to
`7327cf94207aedef07fe4b7fedb42475063c49f87d82836737592defca343605`.
This was genuine contract drift, not a permitted alternate hash.

The exact published description is now an explicit runtime string supplied
through `ConfigDict(json_schema_extra=...)`. The human-readable docstring may
remain, but the schema no longer depends on it. Inherited extra=forbid and
allow_inf_nan=False, wire fields, defaults, bounds and enums remain unchanged.
Subprocess tests cover normal, -O, -OO, PYTHONOPTIMIZE=1 and =2; each generates
the actual schema/prompt and exercises valid and invalid wire values.

The normal schema serialization hash is
`5241e54925bb6ab9e06abbc82b8d885b556875e0bfc1180be4ab848ec3050981`.
All modes must retain the published complete prompt hash
`166b69f0682198a8d5f872aef5d8f5367293e209d8c2ee185719175723ac77f3`.
External review evidence compares the actual serialized bytes with an isolated
copy of the published parent. No hash constant is substituted for generation.

## Prospective lineage and enforcement

The separate optimizer manifest anchors the parent's 58 dependency hashes,
including the exact published credential manifest, to a fixed SHA256 digest.
It declares five modified dependencies and three added dependencies explicitly.
Its own manifest is excluded from its self-referential source map, but is
included in the future execution seal's raw hashes and committed-content check.
Undeclared sources, changed ancestry, rehashed unauthorized modifications,
historical-manifest changes, source drift and contract drift fail closed with
`OPTIMIZER_STABILITY_FREEZE_MISMATCH`.

The credential verifier retains `CREDENTIAL_AMENDMENT_FREEZE_MISMATCH` and
rejects this changed checkout against its immutable published manifest.
The future shared runner requires the optimizer amendment for both sealing
and execution verification. No older seal authorizes the changed instrument.
No actual live execution seal is created by this task.

The only allowed modifications are the live wire-description implementation,
the already hardened credential verifier, shared runner amendment wiring,
credential historical-rejection tests and shared-runner verifier-routing tests.
Additions are this document, the optimizer verifier and its tests. Source
allowlists are bounded review decisions, not permission to rehash other edits.

## Scientific and authority boundaries

Fixture SHA256 remains
`28ea919de499ad244ecdd0d7ac90a8fb9513b85d942dd2f7aa72e4f4129c82bc`.
The schedule remains 35 primary + 9 repeats, maximum 44 requests, zero retries.
Comparison remains PRACTICAL_PROVIDER_COMPATIBLE_JUDGE_COMPARISON.
Provider profiles, observers, scoring, completion/identity rules, journals,
request accounting, failure taxonomy and governance authority are unchanged.
Selective DPAPI behavior is unchanged. Historical Sonnet/Luna/J2 evidence,
manifests, seals and publication reports are preserved.

Validation uses temporary files, subprocesses and offline mocks only. Mock
Gateway activity is reported separately from zero live Gateway activity.
No real credentials, native DPAPI decryptions or provider calls are authorized.
Human review precedes any publication; later live execution needs separate
authorization. Capability does not create authority.
