# B2b open risks and blockers

Status: **research checkpoint; cloud deployment HOLD**. Prepared 2026-10-21.

| Boundary | Evidence / limitation | Required next evidence or decision |
| --- | --- | --- |
| Non-cooperative API send after ownership loss | G1/G2 remain genuine FAIL even when the result is withheld | Explicit human acceptance of a bounded B2b-NC contract; do not claim physical zero-send cancellation |
| Cooperative receiver | Fencing applies to the protected same-database effect and trusted publication order | Separate B2b-FR research approval; authentic publisher, deployment and storage assumptions remain unverified |
| Real caller identity | Cloud forwarded headers and App service identity do not establish actual caller authority | Supported caller-identity contract, independent verification and trusted enrollment; no unverified header substitution |
| Durable intent and uncertain outcomes | In-memory trace and ephemeral App storage are insufficient | Verified durable store and custody; unknown outcomes remain HOLD, with no automatic retry, replay or failover |
| FAA scope | Legacy schema cannot represent required subtier query; attribution negative controls still fail | Review separate FAA-C1 amendment and its complete shared-interface regression before integration |
| Shared-client availability | Per-caller bounds do not establish coalition resistance or global fairness | Keep finite trusted enrollment assumptions explicit; additional policy requires human approval |
| SDK recovery | Unguarded late HeaderMismatch can duplicate a request/effect | Keep raw failure; no migration to SDK 2.3 or automatic recovery from this checkpoint |
| Host/proxy boundary | Reported Host rejection narrows the cause; exact received Host and proxy guarantees UNKNOWN | Separately authorized bounded observation, with original Host decision unchanged |
| Private diagnostic retrieval | Local owner/capability tests do not establish cloud log ACL, retention, worker attribution or current runtime | Independently supported retrieval/custody procedure before another diagnostic deployment |
| Diagnostic metadata | Host hash may be guessed; local budgets reset after restart and may be exhausted by other traffic | Treat metadata as sensitive; no public response fields or unauthenticated endpoint |
| Snapshot provenance | Local digests match cloud-reported values, not independently fetched runtime bytes | Preserve cross-source limitation; require independent cloud/source or runtime evidence for stronger claims |
| Cloud operational state | Earlier startup/shutdown observations are historical/reported; no cloud call in this task | Check current state only in separately authorized session; do not infer STOPPED from an unavailable endpoint |
| 006I | [Supplied report reconciled](B2B_MVP_006I_LOG_ACCESS_AND_CUSTODY_ADDENDUM.md); local identity verified, cloud claims Genie-reported | Document-location gap closed; effective readers, private custody, permission semantics and worker attribution remain unresolved |
| Public publication | Repository is public and main has no reported active protection rule | Exact-content human push approval; PR/merge remain separately gated |

## Verification limits

The curated tests are deterministic/synthetic except real local transports and local filesystem/process behavior. SQLite receiver simulation is not PostgreSQL engine proof. Real PostgreSQL was not restarted or revalidated here. FAA tests use MockTransport, not live USAspending. No real model, OAuth token, cloud resource or scientific observation was used.

The cached Linux image lacks Git. Its two Git-dependent modules account for 124 cases verified in Windows only. The initial Linux collection error is preserved. This limitation is not hidden as a safety PASS or a source repair. Full repository, SDK 2.3 and complete cloud-package suites were not rerun for this additive slice; their historical outcomes remain distinct.

Public-source review combines exact inclusion, pattern scanning, import/dependency inspection and manual review of sensitive contexts. No selected credential, private key, workspace identifier, personal path or internal FAA data was detected. This is bounded review, not proof that arbitrary concealed data or all dependency vulnerabilities are impossible.

Original J3/A2/RQ6 evidence, earlier failure outputs, the approved package, original reports and accepted authority mechanisms remain unchanged. Technical success does not grant publication, deployment or execution authority.
