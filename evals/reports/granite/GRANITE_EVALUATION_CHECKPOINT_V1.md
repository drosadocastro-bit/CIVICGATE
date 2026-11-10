# Granite planner evaluations: documentary checkpoint V1

Checkpoint date: 2026-11-09 in the client's timezone. Some execution evidence uses UTC timestamps on 2026-11-10. This report is an additive, sanitized account of existing evidence. Preparing or committing it does not run another experiment or approve a provider, model, deployment or policy change.

## Scope and current conclusion

CIVICGATE's bounded local integration with a real Granite planner reached the actual A2 → MCP stdio → deterministic Gateway → ExecutionBinding → synthetic adapter → result-validation path. The latest Granite 4.2 Q4_K_S diagnostic trial produced two valid envelopes and argument objects, with two correct tool selections. Exact planner/oracle agreement remained **1/2**, separately from **2/2 expected governance outcomes**.

This is evidence of a functioning local integration under its tested conditions. It is not a production certification, an independent benchmark or a general model-quality estimate. The backend observations are synthetic; no live FAA or USAspending operation is implied. The complete FAA contract and its 54 historical blocked/skipped definitions remain unresolved by these experiments.

The [machine-readable registry](experiments_v1.json) separates experiments from offline tests, failed preparation, runtime diagnostics and admission HOLDs. The [latest safe result](granite42_diagnostic_live_v1.json) records the two current case observations. Original private artifacts remain the primary evidence; this public-facing selection does not replace them.

## Evidence classes

| Class | What it establishes | What it does not establish |
| --- | --- | --- |
| Authorized local LIVE trial | Observed model response, parsing, governed continuation or rejection, and bounded attempt custody. | General reasoning accuracy, production safety or a repeatable hardware benchmark. |
| Offline regression | Behavior of code and instrumentation against explicit synthetic inputs. | Real Granite reasoning quality or real network-provider reliability. |
| Preparation/integration failure | A reproducible implementation or setup defect and its correction boundary. | A failed model-quality measurement when no usable model response was obtained. |
| Runtime/admission diagnostic | The particular local configuration or availability facts actually observed. | A loaded-model attestation, effective GPU measurement or inference authorization. |
| Human decision | The expressly recorded approval and its bounded scope. | Cryptographic identity authentication, independent scientific adjudication or broader execution authority. |

Repeated cases, overlapping suites and model observations are not interchangeable sample counts. The original denominators below are retained. A planning failure that prevents dispatch is not automatically a Gateway REVIEW decision or a successful planner interpretation.

## Five distinct LIVE experiments

| Experiment | Attempt accounting | Planner observation | Actual governance and backend observation |
| --- | --- | --- | --- |
| Granite 3.1 Q3_K_L functional V1 | 8/8 consumed; four frozen cases with two repetitions each. | Six Proposal-schema rejections. Original exact score: **2/6 representable observations**, both from G03. | G03 reached Gateway twice and received REVIEW_REQUIRED despite a favorable synthetic Judge. Zero bindings and zero backend dispatches across the trial. |
| Granite 3.1 recovery diagnostic V2 | 1/2 consumed; custody STOPPED; G02 not attempted. | G01 ended CANCELLED_DELIVERY_UNKNOWN. No supported planner-quality score. | Delivery uncertainty consumed the attempt; no continuation was authorized from the unused slot. |
| Granite 3.1 completed timeout-V2 diagnostic | 2/2 consumed; completed. | Both responses failed Proposal-schema validation. Diagnostics identified missing required envelope fields and a redacted extra field. | No Gateway evaluation, bindings or backend dispatches. |
| Granite 4.2 Q4_K_S content-JSON V1 | 2/2 consumed; completed. | Both passed JSON/Proposal parsing, then failed tool-argument validation. Selected tools and detailed argument errors were not retained and remain UNKNOWN. | No Gateway evaluation, bindings or backend dispatches. |
| Granite 4.2 Q4_K_S diagnostic LIVE V1 | 2/2 consumed; completed. | Tool match 2/2, valid envelope 2/2, valid argument schema 2/2, **exact planner match 1/2**. | Both cases received PERMIT, each with one issued/consumed binding, one adapter entry, one MockTransport attempt and RESULT_VERIFIED. |

The original functional V1 also reported 4/8 governance matches, including planning failures for an unrepresentable case. That historical aggregate must not be relabeled as four actual Gateway REVIEW decisions. The observable Gateway REVIEW count was two.

Different model versions, quantization, wire formats, sampling settings, instrumentation and timeout profiles were used across this sequence. It is an integration history, not a controlled model-only comparison. No verified three-second model-latency tradeoff or model-superiority claim follows.

## Preparation, diagnostics and offline evidence

The registry retains the intervening phases rather than treating them as additional successful model experiments:

- Original implementation, mock tests and functional-runner preparation remained separate from real inference. Favorable mock proposals and expected mock governance outcomes are fixture/instrument results.
- Model-loading, estimate-only, listener and HTTP-availability investigations exposed limitations in observation. The historical 12/12 successful HTTP window is retained as a secondary transcript transcription, not a newly captured primary network trace. Its reported scope was availability during that window, not future reliability or effective GPU execution. TCP connection states were not substitutes for server HTTP responses.
- Runtime admission evolved through context/parallelism reconciliation and safe metadata checks. The limited profile deliberately records metadata correlation without claiming PID-to-instance attestation, directly observed post-initialization context or effective GPU offload.
- An initial two-case bridge stopped before inference because duplicate plan parsing was compared by object identity. Its zero-send root was later given an additive ABORTED_PRE_DISPATCH documentary disposition; the original SQLite root was not silently reset or represented as a successfully persisted STOP.
- A later recovery consumed one request with uncertain delivery. Existing evidence and offline timing investigations characterized competing deadlines; they did not retrospectively prove every historical cancellation cause.
- The corrected timeout profile separated HTTP, internal and outer A2 deadlines as **90/120/130 seconds**, using monotonic timing and reserving before sends. Historical results of **11 PASS / 1 FAIL**, a corrected targeted **1 PASS**, and the subsequent fresh complete regression remain separate selections.
- The tool-format investigation reported **87 offline PASS**: 39 frozen-parser checks, 39 proposed-format checks and nine controls. These are not 87 real model samples. A log entry saying hidden tool calls did not identify their content or prove they were correct.
- The Granite 4.2 content candidate selected explicit structured JSON content. Its native-call channel is not the evaluated proposal interface. Initial development failures, including identity-STOP classification corrections, were preserved separately from later passing selections.
- Argument diagnostics were validated with **44 offline PASS**, including privacy controls, strict-validator equivalence, wrong registered-tool observations and bounded error projection. Those tests did not recover the discarded detail of prior LIVE responses.
- The diagnostic LIVE integration then ran **one fresh full-bridge offline regression**, reported as **1 PASS / 0 FAIL / 0 SKIP**, with two intentionally invalid synthetic argument objects and exact diagnostic-to-SQLite correlation. It demonstrated both rejection boundaries; it did not itself provide fresh Gateway PERMIT evidence.
- A Q4_K_M authorization text initially conflicted with the frozen Q4_K_S candidate. Admission stopped with zero inference submissions. The owner explicitly clarified Q4_K_S before the later authorized trial. No model variant was silently substituted.

These selections overlap. Their assertion counts must not be summed into a single PASS total, semantic sample count or accuracy percentage. Preserved failures and later successful corrections coexist in the registry.

## Latest diagnostic LIVE result

| Measurement | G01 | G02 |
| --- | --- | --- |
| Expected and recognized tool | find_federal_awards | get_federal_award |
| Tool matches frozen oracle | true | true |
| Envelope and argument-schema validity | valid / valid | valid / valid |
| Exact argument/oracle match | false | true |
| Recorded argument count | 3 | 1 |
| Sanitized argument errors | none | none |
| Diagnostic canonical bytes | 769 | 765 |
| Gateway disposition | PERMIT | PERMIT |
| Binding issued / consumed | 1 / 1 | 1 / 1 |
| Adapter entries / synthetic HTTP attempts | 1 / 1 | 1 / 1 |
| Result verification | RESULT_VERIFIED | RESULT_VERIFIED |
| Planner latency including preflight (ms) | 11039.816 | 6309.019 |
| Observed HTTP wait interval (ms) | 5722.800 | 1104.421 |
| Provider-reported input/output tokens | 1015 / 67 | 1013 / 38 |

The G01 oracle contains four arguments while its observed proposal contains three. The retained evidence does not establish which argument was absent or different. Its original frozen prompt does not explicitly request a limit of five while the oracle expects five. That pre-existing experimental limitation is disclosed without repairing the proposal or changing the score. Validity and bounded-policy PERMIT do not establish complete semantic preservation for G01.

The Gateway, not Granite, issued PERMIT and the bindings. Both actual paths visited intake, discovery, planner, gateway and result. The backend used MockTransport only. Eight sanitized Gateway events and four backend observation events supported the two case records; actual adapter entry and MockTransport attempts were checked separately from tool_executed.

SQLite completed with two durable reservations, two initiated sends, two observed responses and two known terminal APPLICATION_RETURNED outcomes. Both case and diagnostic hashes matched the corresponding attempt records; integrity checking succeeded and readback did not change database bytes. No timeout, unknown delivery, retry, fallback, refund or redispatch was recorded. COMPLETED describes documentary custody, not independent human acceptance.

The whole invocation took 33.370 seconds. Planner latency includes preflight, including repeated artifact admission. HTTP waits are application intervals, not pure model generation time. Provider token reports are not independently measured hardware or cost data. The CPU/GPU benchmark was **DISCARDED_NOT_EXECUTED**; no throughput or hardware-performance claim is made.

Both latest proposals admitted cleanly, so this trial produced no argument-error categories to explain the previous rejections. Earlier INVALID_TOOL_ARGUMENTS observations remain genuine, preserved and unresolved. A later successful schema admission is not causal proof of a reasoning or integration fix.

## Evidence identities and public projection

The following original source documents remain private. Only safe basenames and SHA-256 identities of reviewed technical documents are recorded here. Hashes establish document identity; they do not authenticate a reviewer, prove runtime loading, provide confidentiality or make unavailable originals independently reproducible.

| Source document | SHA-256 |
| --- | --- |
| GRANITE02_LOCAL_FUNCTIONAL_TRIAL_RESULT_20261109.md | `a78d5424409d1ba194252e8bce38aaa1d0e3ec88060f9ba9071891e3f70ae7f4` |
| GRANITE02_V2_RECOVERY_LIVE_REPORT.md | `e49789af195e1523a118a8fc82dac81b486df636af7bffc50f66a0a3fa1b782f` |
| GRANITE02_TIMEOUT_V2_LIVE_REPORT.md | `2449d7b949373ad6a90a3f80d03667730c9d82c05c1b67714db20e86933e17cb` |
| GRANITE42_Q4KS_LIVE_TRIAL_REPORT_V1.md | `ed549e54c9d4004ba3abcf2eb7feb7159e5c66cd9b4727f6a459b65dc6f120c7` |
| GRANITE42_DIAGNOSTIC_LIVE_REPORT_V1.md | `99cdfafbc221d4127fdcf22110f5eda62e6e2f327d5bd02ef464aa84078b8eb0` |

Additional original inventory and report references are recorded in the [experiment registry](experiments_v1.json), the [latest result projection](granite42_diagnostic_live_v1.json) and the [checkpoint manifest](../../manifests/granite_evaluation_checkpoint_v1.json). Their original scopes and self-exclusions remain applicable. The latest trial's readback verified preservation of 205 indexed historical artifacts and 36 original preparation artifacts; the only authorized preparation additions were its new GO and LIVE-root records.

Public selection is allowlisted. It excludes private requests, responses, result bodies, argument values, reviewer rationale, per-run private identifiers, machine paths, logs, temporary databases, credentials, model binaries and archives. Original protected sources are not rewritten or normalized to construct a cleaner history. The earlier [lessons note](../../../docs/GRANITE_PLANNER_LESSONS_LEARNED.md) is preserved as version 1; its proposed future model settings and future-tense scope remain dated historical statements.

This checkpoint does not copy the environment-bound LIVE adapters into a new public implementation. Their private paths and source bindings require a separate portability review. The committed summaries support review of documented results and identities, not a credential-free portable replay of the private trial. Checkpoint validation of files, arithmetic and links is not a new model or Gateway test run.

## Retained boundaries

- METADATA_CORRELATED_ONLY admission remains the demonstrated evidence model. Post-initialization context was not directly observed; PID attestation was not verified; effective GPU offload remains UNKNOWN. A verified GGUF on disk does not attest to the in-memory model.
- Every historical budget/root retains its original consumed, completed, aborted-documentary or STOPPED state. The latest two-request authorization is exhausted at 2/2. No unused slot, new inference, retry or model load is authorized by this checkpoint.
- Durable STOP remains PARTIAL. There is no certification of hostile-host isolation, power-loss durability, hard real-time preemption, network-level exactly-once or universal failure containment.
- Independent golden-reference acceptance remains PENDING; Judge calibration remains NOT_YET_MEASURED. Engineering task-agent cross-checks are not independent human or organizational adjudications.
- Hardware/GPU preflight HOLD, remaining operational HOLDs, complete FAA-contract BLOCKED/SKIP and synthetic-only backend restrictions remain intact. No real USAspending, FAA system, production WRITE, cloud provider or deployment is included.

The working research conclusion is a satisfactory bounded local integration with **partial documented planner precision**. Human authority and deterministic governance remain distinct from model capability and documentary evidence.
