# Palimnex ontology adoption plan

Status: **proposal awaiting owner decision; not indexed (see `AGENTS.md`).**

This document and the accompanying repository-local skills authorize planning,
work decomposition, and review only. They do not authorize implementation of
the ontology feature, model or network calls, changes to live Redis or SQLite
state, ledger migration, retention-policy activation, erasure, pack activation,
Git writes, publication, deployment, or any other external action.

## Decision requested

Approve a phased, optional ontology overlay for Palimnex that adds:

1. a deterministic retrieval-coverage and answerability receipt;
2. a reviewed, source-bound concept registry;
3. optional ontology-aware retrieval in shadow mode;
4. an optional local semantic provider behind the existing evaluation hold; and
5. machine-readable contracts for parallel implementation and independent
   review.

The proposal does not replace Palimnex with NVIDIA Auto Ontology or adopt its
Postgres, pgvector, Next.js, text-to-SQL, hosted-model, or Kubernetes stack.

## Reviewed baseline and provenance

The Palimnex baseline is release line `2.9.0`:

- repository files and Git are authoritative for current source;
- SQLite is authoritative for accepted historical memory;
- Redis is a rebuildable discovery and hot-view projection;
- deterministic lexical, symbol, and structural-graph channels are fused for
  source retrieval;
- `project-memory:semantic-provider:v1` is disabled, network-free, and has no
  retrieval influence; and
- imported and recalled history remains historical-only and non-authorizing.

The external comparison reviewed NVIDIA Auto Ontology `1.2.0` at commit
`c4495670947eb7b4616f0dd9900e5ced2a48ca1e` on 2026-11-05. Useful patterns are
reimplemented cleanly. NVIDIA source is Apache-2.0; any copied code would retain
its copyright, license, and notice obligations rather than being silently
relicensed as MIT.

Three graph meanings remain distinct:

| Graph | Meaning | Authority |
| --- | --- | --- |
| Repository structural graph | Files, symbols, headings, links, imports, and explicit document relations | Current source must still be reopened and verified |
| Proposed concept graph | Reviewed concepts, aliases, source bindings, and concept relations | Retrieval support only; never operational authority |
| Historical audit graph | Sessions, events, evidence, claims, retention actions, and tombstones | Historical evidence only |

## Intended outcome

An agent should be able to ask a repository question and receive two separate
artifacts:

1. the existing bounded, source-backed retrieval result; and
2. a versioned coverage receipt explaining which approved concepts were
   recognized, covered, ambiguous, or uncovered, and which current source
   locators support that assessment.

Absence of a registry must preserve current behavior. Candidate or unapproved
concepts must have no retrieval influence. An optional semantic provider may
influence retrieval only after a separately frozen comparison passes and the
owner explicitly approves promotion.

## Goals

- Represent repository concepts and exact aliases with stable identities.
- Bind approved concepts to current source locators and content digests.
- Distinguish `answerable`, `partial`, `ambiguous`, and `unanswerable` without
  equating coverage with correctness.
- Preserve deterministic, offline, model-free operation as the default.
- Make ontology influence visible as a separate retrieval channel.
- Keep every new result bounded, canonical, versioned, and non-authorizing.
- Make parallel implementation safe through disjoint ownership, dependency
  receipts, independent review, and serial integration of shared files.
- Retain Palimnex's privacy, compatibility, rollback, and evaluation gates.

## Non-goals

- Enterprise database cataloging or text-to-SQL.
- Adopting Postgres, pgvector, Next.js, LangGraph, NIM, Vault, or Helm.
- Automatic LLM generation of trusted ontology entries.
- Treating a persisted candidate or boolean certification flag as approval.
- Automatic learning from query history.
- Sending admitted repository source to a remote model by default.
- Adding ontology data to the durable ledger in the first release.
- Changing cache-v3, pack-v2, ledger-v1, context-v1, or other existing wire
  formats in place.
- Authorizing Git, provider, deployment, migration, retention, erasure, or
  other external actions.

## Safety and authority invariants

1. **Repository source remains current authority.** Every source binding is
   reopened and digest-verified before it supports a coverage result.
2. **Generated entries are candidates.** A model, heuristic, import, or agent
   may propose a concept; only a reviewed repository change can approve it.
3. **Approval is not a runtime badge.** An `approved` registry record means the
   committed artifact passed review; it does not authorize an external action.
4. **Ambiguity fails closed.** A query matching more than one incompatible
   concept is `ambiguous`, not covered.
5. **Coverage is not correctness.** It reports semantic support, not that a
   later answer is true or complete.
6. **Privacy admission precedes derivation.** Source bytes are scanned before
   concept extraction, alias generation, embedding, or reranking. Refusals do
   not echo secret values.
7. **No silent downgrade.** Once an explicitly enabled ontology or semantic
   channel participates, its corruption or provider failure is reported rather
   than silently presented as the configured result.
8. **History stays non-authorizing.** Ontology records and feedback recalled
   from the ledger remain `historical_only` and `authorizes_actions: false`.
9. **External calls require separate authority.** Enabling a contract does not
   authorize a model endpoint, network request, paid provider, or data upload.
10. **Parallelism does not expand scope.** Child-agent completion is not owner
    approval, integration authority, or permission to commit or publish.

## Target architecture

```text
committed repository source
        |
        +--> existing deterministic scan/index -------------------+
        |                                                         |
        +--> approved concept registry --> exact alias matcher ---+--> coverage receipt
        |                                                         |
        +--> optional local semantic provider --shadow/promoted---+--> retrieval rank fusion
                                                                  |
durable historical ledger ----------------------------------------+--> context assembly
                                                                  |
                                                        non-authorizing output
```

Approved registry content is committed source. Redis may hold only a
rebuildable projection derived from the registry after a separate cache design;
it is never the only copy. The first release should avoid persistent ontology
state in Redis and avoid all durable-ledger schema changes.

## Proposed versioned contracts

### `palimnex:concept-registry:v1`

The exact JSON Schema remains a Phase 0 decision. The contract should contain:

- project identity and registry version;
- stable concept ID and canonical name;
- bounded, normalized aliases;
- definition and optional relation type;
- source locators and content digests;
- lifecycle status: `candidate`, `approved`, `superseded`, or `withdrawn`;
- predecessor identity for supersession;
- provenance describing `manual`, `deterministic`, or `model_candidate` origin;
- registry digest over canonical content;
- `authority: historical_only`; and
- `authorizes_actions: false`.

Candidate generation output must remain under an ignored private path or the
unapproved `artifacts/design/` boundary. Candidate state cannot share the
approved registry read path without an explicit flag that leaves retrieval
influence disabled.

### `palimnex:retrieval-coverage:v1`

The receipt should contain:

- query digest rather than persisted raw query text by default;
- project, checkout, corpus, and registry identities;
- recognized concepts and exact matching aliases;
- covered concepts and verified source bindings;
- uncovered concepts;
- ambiguous concepts and candidate IDs;
- deterministic coverage ratio and bounded counts;
- truncation and byte-budget state, distinct from answerability;
- status: `answerable`, `partial`, `ambiguous`, or `unanswerable`;
- semantic/provider influence disclosure;
- `authority: evidence_only`; and
- `authorizes_actions: false`.

Do not add these fields to `project-memory:context:v1`. Use a separate result
or design `context:v2` later after an explicit compatibility review.

### Future semantic provider contract

`project-memory:semantic-provider:v1` currently means disabled, network-free,
and no retrieval influence. Do not broaden that meaning silently. A later
interface or version must bind:

- provider/model ID and revision;
- artifact digest and vector dimensions;
- local/remote disclosure and network policy;
- embedding and optional reranking capability;
- input privacy policy;
- deterministic test double identity;
- failure and timeout behavior; and
- promotion evidence identity.

## Delivery phases

Each phase is independently reviewable, stoppable, and releasable. Later phases
do not inherit implementation, network, Git, or promotion authority from an
earlier approval.

### Phase 0 — Contract freeze and threat model

Deliverables:

- approved concept-registry and coverage-receipt schemas;
- status, ambiguity, supersession, and source-drift semantics;
- privacy and size limits;
- compatibility and rollback decision;
- frozen positive, partial, ambiguous, negative, stale-source, and secret
  cases; and
- approved workstream manifest with exclusive file ownership.

Exit gate:

- owner approves the contract and moves the design into `docs/` with the first
  implementing change;
- no unresolved reader-breaking or durable-schema change; and
- independent reviewer accepts the threat model and test matrix.

### Phase 1 — Reviewed concept-registry foundation

Implement the approved registry schema, bounded loader, canonical digest,
normalized exact-alias matching, ambiguity detection, source verification, and
candidate/approved separation. This phase provides the trusted input needed by
the coverage engine; it does not yet alter retrieval ranking.

Likely isolated surfaces:

- a new `palimnex/ontology.py` or `palimnex/concepts.py`;
- `palimnex/schemas/concept-registry.v1.schema.json`;
- `palimnex/tests/test_ontology.py`; and
- read-only validation/status integration performed serially by the
  coordinator.

Exit gate:

- exact field, size, identity, alias, and canonical-digest validation;
- candidate and approved paths remain separate;
- conflicting aliases are explicit ambiguity rather than implicit coverage;
- source drift and secret non-echo tests;
- no change to existing retrieval output when the feature is absent; and
- standalone gate remains green.

### Phase 2 — Deterministic coverage receipt

Implement a model-free coverage engine over the accepted Phase 1 registry. It
must distinguish retrieval diagnostics from concept coverage and return a
separate `palimnex:retrieval-coverage:v1` receipt.

Likely isolated surfaces:

- a new coverage module or a bounded addition to the ontology module;
- `palimnex/schemas/retrieval-coverage.v1.schema.json`;
- focused full, partial, zero, ambiguous, truncation, and omission tests; and
- a read-only CLI/SDK result integrated serially by the coordinator.

Exit gate:

- deterministic ordering, coverage math, and canonical receipt digest;
- full, partial, zero, and ambiguous coverage tests;
- stale registry/source state fails visibly;
- byte-budget omission and retrieval truncation are not labeled
  `unanswerable`;
- no change to existing retrieval output when coverage is not requested; and
- standalone gate remains green.

### Phase 3 — Ontology-aware retrieval in shadow mode

Add an optional concept/alias channel to the existing rank-fusion design.
Shadow mode calculates comparison output but cannot alter returned ranking.

Exit gate:

- all current critical retrieval cases remain green;
- no new forbidden-path hits;
- negative-query abstention does not regress;
- ambiguity never counts as covered;
- graph, lexical, symbol, and ontology channels remain separately visible;
- candidate caps, byte budgets, and deterministic tie-breaking remain bounded;
  and
- owner separately approves any move from shadow to retrieval influence.

### Phase 4 — Optional local semantic experiment

Use the existing semantic-provider seam, but define a new compatible contract
instead of weakening v1. Begin with injected local/in-process embeddings and no
persistent vector store.

The frozen v27 retrieval corpus is necessary but insufficient for semantic
promotion because it already has Recall@5 `1.0`. Add a separately frozen cohort
covering paraphrases, aliases, ambiguity, unrelated negatives, source drift,
and privacy canaries.

Exit gate:

- no critical regression;
- baseline Recall@5 is not reduced;
- required recall or MRR improvement is met;
- p95 stays within the approved bound;
- negative abstention and privacy gates pass;
- provider identity, revision, dimensions, and artifact digest are bound; and
- explicit owner approval promotes the provider. A promotable report is not
  itself promotion authority.

### Phase 5 — Separately approved optional extensions

Deferred extensions:

- reviewed query-to-locator feedback stored as existing event kinds with a new
  versioned payload;
- ranking influence from feedback only after a separate evaluation;
- static local concept/source/audit graph exploration; and
- a separately designed disposable semantic cache if in-memory performance is
  insufficient.

Automatic query-history learning and a hosted graph/UI service remain out of
scope until separately approved.

## Parallel-agent execution model

The repository-local skills define three roles:

| Role | Skill | Responsibility |
| --- | --- | --- |
| Coordinator/integrator | `palimnex-ontology-coordinator` | Contract status, dependency DAG, exclusive ownership, shared-file integration, final gates |
| Bounded implementer | `palimnex-ontology-workstream` | One approved workstream with exact files, dependencies, tests, and exit criteria |
| Independent reviewer | `palimnex-ontology-review` | Read-only adversarial review of source grounding, privacy, compatibility, quality, and rollback |

Parallel agents may be started only when the user explicitly requests
delegation or parallel work. The coordinator remains responsible for the final
integration decision.

### Approval evidence and serial bootstrap

Implementation authority is recorded as a separate bounded artifact, not
inferred from a task imperative, child completion, or proposal existence:

```yaml
schema: palimnex:ontology-approval-evidence:v1
authority_source: user_message
evidence_locator: conversation turn or approved repository record
grantor_claim: repository owner or authorized maintainer
design_identity:
  path: docs/ONTOLOGY_ADOPTION.md
  sha256: <64 hex>
source_proposal_identity:
  path: artifacts/design/Ontologyadoptionplan.md
  sha256: <64 hex>
approved_phases: [0]
authorized_actions: [ontology_phase_0_contract]
excluded_actions: [ontology_phase_1_registry]
recorded_at: <RFC 3339 timestamp>
implementation_authorized: true
network_authorized: false
git_write_authorized: false
live_state_authorized: false
```

An agent cannot cryptographically authenticate a conversational grantor. It
records the exact authority source and stops when scope, phase, or grant is
ambiguous. A generic `continue` or request for parallelism is not approval of
an unapproved implementation phase.

Before the first implementation wave, one serial coordinator-owned bootstrap
change records the approved design under its final `docs/` path, verifies its
digest, and issues task cards referencing that identity. Child implementers do
not move or rewrite the design concurrently.

Action identifiers are exact and phase-scoped:

```text
ontology_phase_0_contract
ontology_phase_1_registry
ontology_phase_2_coverage
ontology_phase_3_shadow
ontology_phase_4_semantic
ontology_phase_5_extensions
```

Approval-evidence digests and task digests are SHA-256 over Palimnex canonical
JSON: UTF-8 JSON with sorted keys, `,`/`:` separators, Unicode preserved, and
NaN/Infinity refused. A task is not valid merely because it passes JSON Schema;
the coordinator's local semantic validator must also prove that its phase,
design identity, action ID, and authority booleans are within the approval.

### Workstream task card

Every child agent receives a machine-readable task card containing:

```yaml
workstream_id: ontology-phase-N-short-name
phase: N
action_id: ontology_phase_N_name
objective: bounded outcome
exclusions: []
approved_design_identity: path and digest
approval_evidence: bounded approval artifact and digest
owned_paths: []
read_only_paths: []
forbidden_paths: []
dependencies: []
acceptance_commands: []
required_output: ImplementationReceipt
network_authority: false
git_write_authority: false
live_state_authority: false
```

An agent without an exact task card performs analysis only. Overlapping
`owned_paths` stop the affected workstreams; they are not auto-resolved.

### File-ownership rules

- The coordinator owns shared CLI dispatch, public compatibility documents,
  configuration defaults, changelog/release metadata, and final integration.
- A workstream owns only the exact paths named in its task card.
- Child agents do not stage or commit.
- Dirty and untracked user files remain untouched.
- Cross-workstream needs are returned as an `IntegrationPatchProposal` rather
  than edited outside ownership.
- Frozen fixtures are single-owner integration files and are never edited in
  parallel.
- An independent reviewer does not repair the implementation it reviews unless
  the user separately changes its role and scope.

Reviewer assignments use the separate reviewer contract and require the
approved design, approval evidence, implementation task card, repository state,
actual diff, and acceptance criteria.

### Delivery waves and dependency DAG

```text
Wave 0: owner decision, contract freeze, and serial approved-design bootstrap
   |
   +-- Registry/schema implementation --------+
   +-- Coverage fixture/scorer preparation ---+--> serial Phase 1 integration
   +-- Interface patch proposal --------------+              |
   +-- Independent threat review -------------+              v
                                                    full integration gate
                                                               |
Wave 1: accepted deterministic registry -----------------------+
   |
   +-- Coverage engine lane ------------------+
   +-- Coverage evaluation lane --------------+--> serial Phase 2 integration
   +-- Independent regression review ---------+
   |
Wave 2: accepted registry + coverage
   |
   +-- Shadow retrieval lane -----------------+
   +-- Expanded frozen evaluation lane -------+--> serial promotion decision
   +-- Independent regression review ---------+
   |
Wave 3: accepted shadow baseline
   |
   +-- Provider contract/mock lane -----------+
   +-- Semantic cohort/scorer lane -----------+--> serial provider integration
   +-- Privacy/compatibility review ----------+
```

Do not concurrently edit `palimnex/retrieval.py`, `palimnex/core.py`,
`.palimnex.json`, a public schema, or a frozen fixture. Assign each integration
bottleneck to one owner per wave.

### Handoff receipt

Each implementation workstream reports:

- workstream and approved-design identities;
- exact owned and changed files;
- dependency receipts consumed;
- exact test commands and results;
- compatibility and wire-format effects;
- privacy and authority checks;
- cache and ledger state;
- unresolved decisions and integration patch proposals;
- Git status; and
- status: `implemented`, `tested`, `partial`, `blocked`, or `refused`.

Each reviewer reports the reviewer vocabulary instead: `accepted`,
`accepted_with_limits`, `rejected`, or `blocked`.

Child reports are evidence, not authorization. The coordinator reviews actual
source and diffs before integration.

## Validation matrix

| Area | Required cases |
| --- | --- |
| Registry | Exact fields, bounds, duplicate IDs, conflicting aliases, normalization, ambiguity, supersession, stable digest |
| Source binding | Missing, changed, excluded, path traversal, symlink, cross-project, and second-read digest mismatch |
| Coverage | Full, partial, zero, ambiguous, truncation, byte-budget omission, deterministic ordering |
| Privacy | Secret refusal before derivation, no secret echo, no credential/model response persisted |
| Retrieval | Baseline disabled identity, shadow non-influence, bounded channels, deterministic tie-breaking, no silent downgrade |
| Semantic provider | Model/revision/artifact identity, dimensions, NaN/Inf, malformed vectors, timeout, local/remote disclosure |
| Compatibility | Existing readers, CLI exits, context v1, cache v3, ledger v1, pack v2, migration and rollback boundaries |
| Evaluation | Critical cases, forbidden paths, Recall@5, MRR, negative abstention, ambiguity, p95, frozen fixture digest |

Per-workstream focused tests run first. Material integration then runs:

```bash
python3 palimnex.py validate --deep
python3 palimnex.py evaluate --limit 5
PATH="$PWD/.venv/bin:$PATH" ./scripts/palimnex_check.sh
python3 palimnex.py ledger-status
```

After approved indexed-file changes, reindex before deep validation and final
evaluation. Proposal-only files under `artifacts/design/` remain unindexed.

## Compatibility boundaries

Preserve at minimum:

- `project-memory:cache:v3`;
- `project-memory:cache-chunk:v1`;
- `project-memory:document-graph:v2`;
- `project-memory:ledger:v1`;
- `project-memory:pack:v2`;
- `project-memory:context:v1`;
- `project-memory:semantic-provider:v1`;
- `project-memory:evaluation:v1`;
- current Redis namespaces and immutable-generation behavior;
- current SQLite object sets and exact readers; and
- current CLI command and exit-code behavior.

A reader-breaking event kind, ledger meaning, record shape, cache layout, or
context envelope requires a new version and, where durable, a separate migration
design. This proposal intentionally avoids durable-schema changes.

## Rollback

- Before ontology influence: disable or remove the optional registry and
  reproduce baseline retrieval exactly.
- In shadow mode: stop calculating the shadow channel; returned rankings were
  never changed.
- After an approved deterministic channel: switch back to baseline mode and
  rebuild disposable projections. The committed registry remains ordinary
  reviewed source and can be reverted through normal Git review.
- Semantic provider: disable the injected provider and rebuild any separately
  designed disposable semantic projection. Never reinterpret existing cache-v3
  vectors.
- Durable feedback: if later approved, withdraw influence without deleting
  historical events; supersession/revocation semantics remain intact.

Rollback does not delete exported copies, model contexts, backups, or external
provider data. Those surfaces require their own documented controls.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Generated ontology becomes de facto truth | Candidate-only state and reviewed source change for approval |
| Alias collision creates false confidence | Explicit ambiguity state; ambiguity never counts as covered |
| Source changes after approval | Reopen and digest-verify every binding |
| Semantic provider leaks source | Local-only first experiment; remote calls require a separate privacy design and authority |
| Ontology changes baseline retrieval silently | Absence/disabled identity tests and mandatory shadow phase |
| Parallel agents overwrite work | Exclusive owned paths, coordinator-owned bottlenecks, receipt barriers |
| Frozen evaluation is tuned to current winners | Separate frozen ontology cohort; no opportunistic relabeling |
| New format breaks old readers | Additive new identifiers and separate receipts; no context/cache/ledger mutation in place |
| Feedback creates popularity bias | Defer automatic learning; require source-verified explicit acceptance and separate promotion |

## Open owner decisions

1. Approve, reject, or revise the overall phased approach.
2. Choose `ontology.py` or `concepts.py` as the implementation module name.
3. Choose the committed registry location and file format after approval.
4. Choose the read-only CLI spelling: `answerability`, `ontology-coverage`, or
   `explain-search`.
5. Decide whether exact approved aliases may influence lexical retrieval in the
   first release or remain shadow-only through Phase 3.
6. Decide whether remote semantic providers are permanently excluded or only
   disabled by default.
7. Approve the additional frozen cohort and promotion thresholds.
8. Confirm that query-history feedback remains out of scope for the first
   ontology release.

## Definition of done

Ontology adoption is complete only when:

- approved contracts have moved into `docs/` with their implementation;
- deterministic coverage and registry behavior pass focused and adversarial
  tests;
- baseline mode is behaviorally compatible;
- shadow comparison passes the frozen gates;
- any retrieval influence has separate explicit owner approval;
- independent review accepts source grounding, privacy, compatibility, and
  rollback;
- the standard gate and fresh retrieval evaluation pass;
- no runtime state, credentials, provider responses, or keys are committed;
- implementation, integration, commit, push, publication, and live acceptance
  are reported as separate states; and
- the final handoff records `cache_consulted`, ledger integrity, Git state, and
  remaining limitations.

## Recommended next action

Review and decide the Phase 0 open questions. If approved, record bounded
approval evidence, perform the serial approved-design bootstrap into `docs/`,
issue schema-validated disjoint task cards through
`palimnex-ontology-coordinator`, and begin the registry/schema, coverage-fixture,
interface-proposal, and independent-review lanes in parallel.
