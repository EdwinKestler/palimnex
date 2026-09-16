# Palimnex repeated-session evaluation

Status: implementation contract for the approved memory follow-up. Executable
coverage and measured results must be recorded below before this document is
used as evidence of completion. This document does not reopen the accepted
PM2.5 slice or its narrow exception `PM-ACCEPT-001`.

## Purpose and evidence boundary

The existing frozen v25 and development v26 fixtures measure source discovery.
Repeated-session evaluation adds chronological ingestion, process restarts,
corrections, applicability changes, and eventual forgetting. A deterministic
retriever can establish evidence availability and isolation. It cannot establish
that a model answered correctly or completed a task more reliably.

The attached retention specification is design input for the cleanup adapter.
Its generic signed custody packs, classification vocabulary, and proposed tool
names are not claims about the current encrypted Palimnex pack format.
Evaluation must use actual implemented operations and report unsupported cases
as unsupported, rather than replacing forget with visibility filtering.

## Harness contract

Each scenario starts with an independent temporary checkout and ledger. Each
comparison arm gets identical initial source bytes and chronological inputs,
but a separate ledger, runtime directory, and process. No run uses the user's
ledger, Redis namespace, exported packs, or existing frozen evaluation files.

For every session, the controller supplies only the actions and queries visible
at that session boundary. A fresh Python subprocess opens the persistent ledger,
applies those actions through public APIs, retrieves context, emits its result,
and exits. A new `MemoryLedger` object in the same process alone does not count
as a process restart. Persist session identifiers and predecessor identifiers
when later corrections reference them; do not recreate historical records.

The child process receives neither gold answers nor later-session actions.
Gold remains in the controller's scoring input outside the admitted source
corpus. Do not write the complete fixture, expected answer, expected marker,
future source file, or evaluation report into a retrieved document. The complete
fixture may be trusted development code, but this separation is an API boundary,
not a security sandbox against a malicious child process.

Chronological order is explicit and validated. Observed-time APIs determine
record creation; fixtures cannot silently insert future facts using backdated
timestamps. Expiry tests use an explicit supported test clock or controlled
boundary passed to the cleanup API, never wall-clock sleeps or alteration of
the live ledger clock.

Comparison arms:

| Arm | Retrieval input | Interpretation |
|---|---|---|
| Source only | Current admitted sources and fixed byte/result budgets | Baseline with no historical-memory benefit |
| Accepted memory | The same sources plus eligible historical context | Measures retrieval contribution of existing memory |
| Memory with cleanup | The same timeline, plus real retention plan/apply operations | Measures retained evidence and deletion compliance only after the cleanup adapter is exercised |

Source-only can ingest the same events for equivalent chronology, but it must
never pass its ledger into retrieval. Cleanup comparisons require equivalent
baseline tasks and independent state. A forgotten answer is expected to become
unavailable; counting it as a retained-knowledge failure would misstate quality.

## Scenario matrix

The implementation target is 30 development scenarios with six sessions each,
generated from a pinned generator and configuration. Parameterized cases must
report their shared scenario family; 30 instances do not establish 30 independent
task families. Record both the generator/configuration digest and the digest of
the realized cohort. The implemented count must be reported as its actual
count, not this target.

| Family | Repeated-session sequence | Required observation |
|---|---|---|
| Correction | Learn old value, resume, supersede it, resume again | Current evidence supports the correction and does not expose the obsolete value as current |
| Revocation | Learn fact, revoke it, resume | No resurrection, including previously promoted facts |
| Branch applicability | Capture checkout-specific outcome, change admitted source state, resume | Inapplicable capture excluded; repository-scoped history remains eligible under its actual contract |
| Environment failure | Record failed operation and environment attribution, restart, query recovery | Evidence remains labeled historical and does not become an execution permission |
| Workflow resume | Record completed step and next step, restart into a new session | Prior evidence available without falsely claiming the next action ran |
| Missing premise | Ask before learning, ingest later, repeat | Initial abstention; no future-session evidence leakage |
| Conflict | Record incompatible observations and explicit relation | Conflict metadata retained; presence of evidence is not adjudication of truth |
| Retained knowledge | Retain held, active-session, and durable records during cleanup | Eligible surviving evidence and identity unchanged |
| Forgotten knowledge | Expire eligible record, plan/apply cleanup, restart, query/import | Value absent from supported stores and no restore-based resurrection |

Physical deletion requires separate database/WAL/pack canary inspection. Empty
retrieval results alone prove neither physical erasure nor correct cleanup.

## Metrics and result integrity

Development reports record scenario/session/query counts, process restart
count, fixture digest, code identity, backend configuration, output byte
budget, source fingerprints, and whether cleanup operations actually ran.
Measure evidence hit rate, forbidden/stale evidence exposure, negative-query
abstention, serialized output bytes, and retrieval latency separately per arm.
Report missing or truncated context explicitly. Never substitute the same
scalar for evidence recall, answer correctness, and task success.

Model and task metrics remain `not_measured` until real external results are
supplied. Zero model calls and development-only status must remain visible.
Latency from synthetic local subprocesses is not a production model or Redis
latency measurement. Storage measurements must distinguish canonical bytes,
derived bytes, retained recovery copies, and unresolved external copies.

Before an external answer/task run, freeze a manifest binding cohort identifier
and digest, development/held-out designation, code identity, arm configuration,
model identifier/version, prompt/config digests, token/output budgets, task
identifiers, and scoring protocol version. Store per-query visible-input
digests and the manifest digest with persisted results. Reject changed bindings,
duplicate result identifiers, missing arms, missing results, unknown tasks,
non-finite metrics, and result scores outside the declared range. Manifest
hashing establishes consistency, not model-provider authenticity.

The proposed persisted exchange has three documents. SHA-256 values below are
lowercase 64-character hex strings, computed over canonical UTF-8 JSON; the
manifest excludes its own `manifest_digest` from its digest input.

```json
{
  "schema": "project-memory:longitudinal-run:v1",
  "run_id": "operator-selected-unique-id",
  "cohort": {"id": "development-v1", "split": "development", "digest": "SHA256", "generator_digest": "SHA256", "config_digest": "SHA256"},
  "code_digest": "SHA256",
  "model": {"id": "exact-model-id", "version": "declared-version"},
  "prompt_digest": "SHA256",
  "model_config_digest": "SHA256",
  "budgets": {"input_tokens": 8192, "output_tokens": 1024, "context_bytes": 16384},
  "arms": ["source_only", "accepted_memory"],
  "queries": [{"scenario_id": "s01", "session": 1, "query_id": "q01", "arm": "source_only", "visible_input_digest": "SHA256"}],
  "scoring_protocol": "external-labels-v1",
  "manifest_digest": "SHA256"
}
```

The controller stores the complete manifest before execution. Each runner
request contains only the manifest digest, scenario/session/query/arm identity,
visible-input digest, current question/context, and declared model/budgets.
It excludes scoring gold and future actions. A persisted result envelope is:

```json
{
  "schema": "project-memory:longitudinal-answer:v1",
  "manifest_digest": "SHA256",
  "scenario_id": "s01", "session": 1, "query_id": "q01", "arm": "source_only",
  "visible_input_digest": "SHA256",
  "answer": "runner response",
  "abstained": false,
  "usage": {"input_tokens": 100, "output_tokens": 20},
  "labels": {
    "method": "human",
    "answer_correct": true,
    "evidence_supported": true,
    "abstention_correct": null,
    "task_success": null
  }
}
```

These shapes are an integration proposal until implemented. A result cannot
silently change its manifest's model, budgets, cohort, or arm configuration.
Require every `(scenario_id, session, query_id, arm)` exactly once when scoring
a complete run. Null labels mean unmeasured and are excluded from that metric's
denominator, with measured/total counts reported. An entirely unmeasured metric
is null, never zero or success. Budget overruns and missing identities invalidate
the run rather than silently removing difficult cases. No provider credential,
secret source text, or raw external answer should enter repository fixtures.

Answer correctness, evidence support, abstention correctness, and executable
task outcomes require separate fields. Scorers must distinguish automated
checks, human labels, and model-judge labels. An imported success boolean is
an externally asserted label, not independently verified task completion.

Held-out evaluation requires a disjoint frozen cohort and an exclusive durable
claim before the first model read. The claim registry lives outside disposable
run directories and survives crashes. A failed run remains consumed unless the
predeclared protocol explicitly permits a retry without renewed gold exposure.
Until that guard and disjoint cohort exist, every report remains development
evidence and is ineligible for confirmatory promotion.

## Required tests and acceptance

Test process restarts against persistent state, independent arm/scenario
directories, absence of future actions and gold in child requests, expected
abstention before ingestion, correction/revocation suppression, checkout
applicability changes, budget enforcement, and truthful unsupported-cleanup
and unmeasured-model flags. Freeze and test external-result binding rejection
before using imported task scores. The original v25/v26 fixtures and their
hashes remain unchanged.

| Artifact | Documentation | Testing | Rollback |
|---|---|---|---|
| Repeated-session harness, pinned development generator/configuration, machine-readable report | This contract plus actual command/output evidence | Isolation, chronological leakage, restart, correction, applicability, metric-honesty tests | Remove only this slice's selected source additions through the slice's sealed source rollback; dispose only harness-created temporary directories |
| Cleanup comparison adapter | Supported-store and deletion boundary record | Retained-record equivalence, forbidden-value canaries, import suppression, crash/retry tests | Before final purge, documented recovery; after purge, disable new cleanup without restoring erased values |
| External task scorer and future held-out guard | Frozen manifest/scoring protocol and cohort provenance | Binding tamper, duplicate/missing result, exclusive-claim and consumed-run refusal tests | Preserve consumed-run registry; disable evaluation without reopening the cohort |

No paid calls, downloads, chain operations, or model execution are required to
validate the deterministic harness. Paid/model runs need an actual configured
runner and declared budget; this document does not invent either.

## Implemented development runner

The root entrypoint now provides `evaluate-longitudinal`, `longitudinal-prepare`,
`longitudinal-score`, and `longitudinal-reserve`. The Python APIs live in
`palimnex/longitudinal.py`. The current generator implements six families:
recall, correction, revocation, abstention, historical failure/workflow hints,
and cleanup, with five parameter variants each and six sessions each. The
broader scenario matrix above remains a coverage roadmap: checkout capture and
conflict behavior have separate unit coverage but are not yet longitudinal
families; workflow hints do not constitute executed workflow tasks.

Each of the three arms gets 180 session observations, for 540 fresh child
processes. Source-only evidence success was 0.25; history and history-with-cleanup
were 1.0, with abstention 1.0 in all arms. Cleanup erased 30 isolated scratch
records. These are development evidence results, not independent task-family
counts, model success, statistical significance, or held-out measurements.
The controller checks obsolete-value absence for correction/revocation cases.

`longitudinal-prepare PRIVATE_NEW_DIRECTORY --model-id ID --model-version VERSION`
replays development cases and writes owner-only `manifest.json`, `requests.json`
and `development-report.json`. Prepared requests contain query and retrieved
context, not gold labels or future actions. This command does not call a model.
`longitudinal-score MANIFEST RESULTS` validates bindings, completeness, label
provenance, and declared usage budgets; it reports global and per-arm metrics
with measured denominators. Supplied labels remain externally asserted.

`longitudinal-reserve MANIFEST PRIVATE_PERSISTENT_REGISTRY` reserves a held-out
cohort by its digest using an exclusive, fsynced marker before execution. A
crash or changed run ID cannot reopen that cohort. This guard cannot prevent
an external caller from bypassing the API; retain the registry outside disposable
run directories. No held-out cohort was read, no model endpoint was configured,
and no paid call was made in this implementation session. Actual model runs
and their outcome labels remain unevaluated.

The repository gate is `scripts/palimnex_check.sh`. Runtime deletion is tested
on isolated ledgers only. The supported local-erasure boundary is recorded in
`docs/RETENTION.md`.
