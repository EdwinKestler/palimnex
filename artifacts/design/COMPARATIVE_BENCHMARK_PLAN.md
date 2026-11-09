# Palimnex comparative benchmark plan

Status: experiment plan; no comparative results have been measured yet.

## Purpose

This benchmark will compare Palimnex with representative agent-memory systems
without collapsing different capabilities into a single leaderboard score.
Palimnex is repository- and evidence-oriented, while several comparison systems
primarily manage conversational facts. The benchmark therefore separates
retrieval quality, longitudinal correctness, end-to-end task performance,
privacy and erasure behavior, durability, and operational cost.

The first comparison set is:

- Palimnex, pinned to the exact commit under test;
- Mem0 Open Source;
- Graphiti;
- LangMem with a persistent LangGraph store;
- Letta, evaluated according to its persistent-memory-block model; and
- a transparent vector-retrieval baseline with no memory-management layer.

Hosted products and proprietary features belong in a separate track. Results
from a hosted service must not be presented as results for its open-source
edition, or vice versa.

## Core principles

1. Repository files and frozen inputs are authoritative. No system may receive
   expected answers, future events, scoring labels, or hidden test metadata.
2. Retrieval, answer correctness, task success, erasure, durability, and cost
   are reported separately. There is no aggregate "best memory" score.
3. Every run records exact code, package, model, prompt, configuration, fixture,
   hardware, and seed identities.
4. Unsupported capabilities are reported as unsupported, not as successful
   zero-cost operations.
5. Logical absence from search is not proof of physical erasure.
6. Development fixtures and held-out fixtures have distinct identities and
   digests. Held-out data is read only by the preregistered evaluation run.
7. Palimnex's existing frozen fixtures remain unchanged. A neutral held-out
   corpus is required before making comparative claims.

## Comparison modes

Each system is evaluated in two modes.

### Matched-core mode

Where the systems permit it, use the same:

- embedding model and revision;
- reader model and revision;
- generation parameters;
- retrieval limit and context-byte/token budget;
- input records and timestamps;
- hardware and process isolation; and
- cold-start, warm-cache, and restart boundaries.

This mode isolates the contribution of storage, indexing, retrieval, and memory
lifecycle behavior.

### Native-best-practice mode

Configure each system according to its maintained documentation. Native graph,
reranking, extraction, consolidation, or always-visible memory features are
allowed, but every component and model call must be disclosed and charged.

Letta's always-visible memory blocks are not equivalent to ranked retrieval.
Consequently, Letta participates in end-to-end quality, context consumption,
latency, persistence, and lifecycle comparisons, but retrieval-rank metrics are
reported only when its tested configuration actually performs ranked retrieval.

## Adapter contract

The harness should expose a small capability-aware interface:

```text
reset(namespace)
ingest(session, event)
correct(memory_id, replacement)
revoke(memory_id)
query(text, limit, context_budget)
restart()
erase(scope)
stats()
```

Every adapter also declares whether it supports corrections, revocations,
temporal queries, namespace isolation, persistent restart, logical deletion,
verified derivative cleanup, and export/import. Capability declarations are
validated with smoke tests rather than trusted as descriptive metadata.

An adapter must return normalized observations without discarding native output:

- ranked evidence identifiers and payloads, where applicable;
- scores and score components exposed by the system;
- context bytes and estimated tokens;
- model, embedding, and reranker calls;
- operation and wall-clock latency;
- storage and process resource measurements; and
- native receipts, errors, and lifecycle states.

## Experiment 1: frozen retrieval

Index identical source snapshots, then issue frozen queries with path- or
record-level relevance labels. Run both Palimnex's existing v27 fixture and a
neutral held-out repository fixture. The neutral fixture must be reviewed and
frozen before adapters are tuned against it.

Report:

- Recall at 1, 3, 5, and 10;
- mean reciprocal rank;
- nDCG at 5 when relevance is graded;
- forbidden or obsolete hit rate;
- evidence-path correctness;
- retrieved bytes and tokens; and
- p50, p95, and p99 query latency.

The Palimnex v27 result is a regression control, not sufficient evidence of
superiority, because it was designed for this repository.

## Experiment 2: longitudinal memory

Replay independent repositories or users through multiple process-separated
sessions. Scenario families include:

- durable fact recall;
- correction of an earlier value;
- explicit revocation;
- conflicting observations;
- missing-premise abstention;
- workflow continuation without claiming an unexecuted step ran;
- branch or environment applicability;
- retained knowledge after cleanup; and
- forgotten knowledge after authorized cleanup.

Measure current-fact recall, obsolete-evidence exposure, abstention accuracy,
evidence support, cross-session persistence, resurrection after restart, mean
context bytes, and p95 retrieval latency. Palimnex's existing source-only,
accepted-memory, and memory-with-cleanup arms should be retained as internal
controls.

LongMemEval can provide a recognizable external dataset for information
extraction, multi-session reasoning, temporal reasoning, knowledge updates, and
abstention. Its end-to-end results remain separate from repository-maintenance
results.

## Experiment 3: end-to-end answer quality

Pass each system's retrieved context to the same pinned reader model and prompt.
Use deterministic generation where supported and repeat nondeterministic runs
with preregistered seeds.

Score these questions independently:

1. Did retrieval expose the required evidence?
2. Did the reader use the evidence correctly?
3. Is the answer supported by the visible evidence?
4. Did the reader abstain when the premise was absent?
5. Did the answer expose forbidden or revoked information?

This separation prevents a capable reader model from concealing weak retrieval
and prevents strong retrieval from being blamed for a reader failure.

## Experiment 4: repository-maintenance tasks

Create held-out tasks in repositories not used to tune any adapter. Candidate
tasks include:

- locating the implementation of a specified behavior;
- selecting the correct file before editing;
- resuming a multi-session maintenance task;
- avoiding a previously recorded failed approach;
- applying repository-specific safety and authority rules; and
- producing a patch whose claims cite the authoritative source.

Measure task completion, supported claims, wrong-file edits, regressions,
unnecessary edits, context consumption, model calls, cost, and wall-clock time.
The same coding agent and tool permissions must be used across memory arms.

At minimum, compare source-only, full-context, vector baseline, and each memory
system. Memory retrieval must never be treated as authorization for Git,
network, provider, migration, retention, or erasure actions.

## Experiment 5: correction and revocation safety

Insert fact A, correct it to fact B, and later revoke B. Query the present value,
the historical value, and ambiguous formulations that overlap the obsolete
fact's vocabulary.

Report:

- current-state accuracy;
- historical-state accuracy when explicitly requested;
- obsolete-as-current exposure;
- revoked-information exposure;
- correction and revocation latency; and
- behavior after restart, reindex, consolidation, and import where supported.

## Experiment 6: erasure and retention

Insert unique canary strings, request the strongest supported deletion, restart
the service, rebuild derived indexes, and query through every supported access
path. Inspect storage only within the isolated benchmark namespace.

Report separately:

- logical search absence;
- canonical-store deletion;
- vector, graph, cache, and projection cleanup;
- snapshot, backup, pack, or export persistence;
- resurrection after restart or import;
- scope isolation; and
- verification receipts or unsupported boundaries.

The benchmark does not claim forensic deletion from storage media. It must not
use `FLUSHDB`, `FLUSHALL`, raw Redis-key deletion, or another project's
namespace.

## Experiment 7: crash, restart, and concurrency

Inject deterministic failures at these boundaries where adapters expose them:

- before canonical commit;
- after canonical commit but before indexing;
- during correction or revocation;
- during graph or projection updates;
- during deletion and verification; and
- during concurrent writes to the same logical subject.

After restart, test integrity, duplicates, partial state, stale retrieval,
idempotent retry, cross-namespace contamination, and resurrection. If a system
does not expose a safe injection point, record the scenario as untested rather
than simulating success.

## Experiment 8: scale and operational cost

Run practical dataset tiers such as 1,000, 10,000, 100,000, and 1,000,000
records. A system may stop at a declared resource boundary without invalidating
its smaller-tier results.

For ingestion and querying, report:

- throughput and p50/p95/p99 latency;
- cold-start, warm-cache, and post-restart behavior;
- peak resident memory;
- canonical and derived disk usage;
- network requests;
- embedding, extraction, reranking, and reader-model calls;
- input and output tokens; and
- hosted-provider cost where applicable.

## Fixtures and leakage controls

Use three fixture classes:

1. **Regression:** existing Palimnex v27 cases, unchanged.
2. **Development:** public cases for adapter construction and debugging.
3. **Held-out:** owner-reviewed cases sealed before the comparative run.

Every realized cohort receives a canonical digest. Requests given to an adapter
contain only events visible at that session boundary. Gold answers, expected
paths, future actions, forbidden markers, and scoring rules stay in the
controller. The run manifest binds the cohort, code, adapters, models, prompts,
budgets, hardware description, and scoring protocol.

## Statistical treatment

- Use paired cases across systems.
- Repeat model-dependent runs with a preregistered seed count.
- Report sample counts and confidence intervals.
- Report per-family distributions as well as means.
- Preserve failures and timeouts in the denominator.
- Correct for multiple comparisons when making system-to-system significance
  claims.
- Treat deterministic fixture results as regression evidence, not estimates of
  real-world prevalence.

## Adoption gates

Before publishing comparative claims:

- every adapter passes namespace-isolation and leakage smoke tests;
- fixtures and manifests are digest-pinned;
- Palimnex's normal gate and frozen evaluation remain green;
- no critical case regresses silently;
- all model and provider calls are accounted for;
- raw observations are retained separately from summaries;
- unsupported and untested capabilities are visible; and
- a clean environment can reproduce the documented run.

Thresholds for declaring a benchmark release must be fixed before the held-out
run. They must cover retrieval, obsolete/forbidden exposure, abstention,
end-to-end support, task regressions, and reproducibility rather than only mean
accuracy.

## Implementation phases

### Phase 0: protocol freeze

Define the schemas, capability vocabulary, scoring rules, resource accounting,
fixtures, and manifest. Review licensing and redistribution constraints for all
external datasets.

### Phase 1: deterministic local harness

Implement Palimnex, vector-baseline, Mem0 OSS, Graphiti, and LangMem adapters.
Run deterministic retrieval and lifecycle smoke tests with no reader-model
calls. Add Letta once its normalized end-to-end measurement boundary is fixed.

### Phase 2: development comparison

Run retrieval, longitudinal, correction, revocation, restart, and scale tests on
the public development fixtures. Adapter changes are allowed, but every change
invalidates earlier comparative summaries.

### Phase 3: same-model end-to-end run

Freeze the model, prompt, token budgets, and adapters. Measure supported-answer
quality and repository-task outcomes on development cases.

### Phase 4: held-out evaluation

Reserve the held-out cohort once, execute the preregistered run, preserve raw
results, and publish limitations alongside metrics. Tuning after this read
requires a new disjoint held-out cohort.

### Phase 5: lifecycle and chaos validation

Run erasure, crash recovery, concurrency, and resurrection tests. Keep these
security and operational findings separate from quality rankings.

## First deliverable

The smallest useful implementation is a local, deterministic harness comparing
Palimnex, Mem0 OSS, Graphiti, LangMem, and the vector baseline on:

1. frozen retrieval;
2. correction and revocation;
3. abstention;
4. process-separated persistence; and
5. context bytes and retrieval latency.

It should reuse Palimnex's existing longitudinal envelopes and external scoring
boundaries where they are generic enough, without changing frozen fixtures or
claiming that deterministic evidence replay measures model task success.

## References

- [Palimnex longitudinal evaluation](../../docs/LONGITUDINAL_EVALUATION.md)
- [Palimnex frozen-ranking interpretation](../../docs/DESIGN.md)
- [Mem0 Open Source overview](https://github.com/mem0ai/mem0/blob/main/docs/open-source/overview.mdx)
- [Mem0 memory model](https://github.com/mem0ai/mem0/blob/main/docs/core-concepts/how-it-works.mdx)
- [Graphiti documentation](https://help.getzep.com/graphiti/getting-started/welcome)
- [LangMem conceptual guide](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
- [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks)
- [LongMemEval, ICLR 2025](https://openreview.net/pdf?id=pZiyCaVuti)
