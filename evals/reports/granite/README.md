# Granite planner evaluation checkpoint

This directory is the current documentary entry point for CIVICGATE's local Granite planner research. It preserves the sequence of model observations, integration defects, offline controls and admission decisions without replacing unsuccessful experiments with later results.

Scope: real local planner inference where explicitly authorized, actual A2/MCP/Gateway governance, and **synthetic read-only government-data backends**. It does not document live FAA or USAspending access, a complete FAA contract, cloud deployment or production acceptance.

## Read this checkpoint

| Artifact | Purpose |
| --- | --- |
| [Checkpoint report](GRANITE_EVALUATION_CHECKPOINT_V1.md) | Experiment chronology, evidence boundaries, current findings and retained limitations. |
| [Experiment registry](experiments_v1.json) | Sanitized machine-readable inventory of separate trials, offline selections, diagnostics and admission HOLDs. |
| [Latest diagnostic LIVE result](granite42_diagnostic_live_v1.json) | Allowlisted G01/G02 metrics from the completed Granite 4.2 Q4_K_S diagnostic trial. |
| [Checkpoint manifest](../../manifests/granite_evaluation_checkpoint_v1.json) | Identities of the selected checkpoint files, source-evidence references and publication exclusions. |
| [Historical lessons, version 1](../../../docs/GRANITE_PLANNER_LESSONS_LEARNED.md) | Preserved earlier research note written before the later Granite 4.2 trials. Its future-tense proposals are historical, not current execution authority. |

## Current finding

The latest authorized two-request Granite 4.2 Q4_K_S trial completed with two valid Proposal envelopes, two schema-valid argument objects and two correct tool selections. **Exact planner/oracle match was 1/2**, while **expected Gateway governance outcomes were 2/2**. Each case received PERMIT, issued and consumed one ExecutionBinding, entered the adapter once and made one synthetic MockTransport attempt. Both results were verified and SQLite custody completed.

G01's argument fingerprint did not match its frozen oracle. Three observed arguments versus four expected arguments does not establish which argument was absent or different. G02 matched exactly. Earlier argument-validation failures remain unexplained at their original evidentiary resolution.

The bounded functional integration is demonstrated; general model accuracy, superiority and calibration are not established. The two-request authorization is exhausted. The CPU/GPU benchmark was discarded and not executed. Durable STOP remains PARTIAL, and existing operational HOLDs remain in force.

## How to interpret the files

LIVE model observations, offline fixture checks, preparation failures and zero-inference admission HOLDs are different evidence classes. Their PASS counts and scoring denominators must not be added together. A valid response, deterministic PERMIT, consumed binding, observed backend attempt and correct answer are separate claims.

The repository files are explicit safe projections. Original requests, responses, result bodies, private identifiers, machine paths, credentials, raw logs, SQLite databases, model binaries and historical evidence archives remain outside this checkpoint. The [checkpoint report](GRANITE_EVALUATION_CHECKPOINT_V1.md) explains the projection and custody boundaries.

This is a **documentation checkpoint**, not a portable LIVE runner or a replay authorization. Validating its JSON, arithmetic, hashes and links does not rerun or certify the recorded experiments. Reproducing a model trial would require separately reviewed implementation identities, local runtime configuration, fresh admission, independent custody and explicit human execution authorization.
