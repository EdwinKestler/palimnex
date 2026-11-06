# Phase 0 ontology threat model

Status: **draft pending the Phase 0 exit gate**

This document applies only to the optional ontology overlay described by
`docs/ONTOLOGY_ADOPTION.md`. It does not approve a registry, implementation,
provider, migration, policy activation, or retrieval influence. Repository
files remain current authority. Redis remains disposable discovery state and
SQLite remains historical-only evidence.

## Security objectives

The ontology path must remain deterministic, offline, bounded, source-backed,
and non-authorizing by default. It must fail visibly when an explicitly enabled
channel is corrupt or unavailable, and it must distinguish semantic coverage
from answer correctness, ambiguity, source drift, retrieval truncation, and
byte-budget omission.

The numbered invariants below refer to **Safety and authority invariants 1-10**
in `docs/ONTOLOGY_ADOPTION.md`.

## Assets and trust boundaries

| Asset or actor | Trust and authority | Boundary crossed |
| --- | --- | --- |
| Repository source | Current source of truth after admission and a fresh read | Filesystem paths and bytes enter source resolution, privacy admission, indexing, and coverage |
| Approved concept registry | Reviewed repository source used only for retrieval support | Registry records enter alias matching and source verification |
| Candidate entries | Untrusted proposals with no retrieval influence | Heuristic, model, import, or agent output approaches the approved read path |
| Redis projection | Rebuildable, disposable, and never sole authority | Derived data crosses from admitted source into a cache namespace and back into retrieval |
| SQLite ledger | Accepted historical evidence only | Recalled events and imported records enter context assembly |
| Coverage receipt | Evidence-only diagnostic output | Query-derived matching and verified bindings become a bounded external artifact |
| Future semantic provider | Disabled and unregistered in the portable bundle | Admitted bytes or derived text would enter a model boundary and scores would return |
| Parallel agents | Untrusted with respect to scope expansion and approval | Work products cross exclusive ownership and serial integration boundaries |

The main high-risk transitions are candidate-to-approved registry,
registry-to-matcher, locator-to-current bytes, source-to-derived alias or
embedding, Redis-to-retrieval, ledger-to-context, channel failure-to-result,
receipt-to-operator decision, and agent output-to-shared integration.

## Threat analysis and frozen evidence

"No direct control" means the ontology feature does not exist yet. A cited
analogue is useful evidence about the repository's established pattern, but it
does not satisfy the future ontology contract by itself.

| ID and boundary | Threat | Mitigating design invariant(s) | Existing source control | Frozen cases | Residual risk |
| --- | --- | --- | --- | --- | --- |
| T01 approval evidence to task | A forged, stale, or over-broad approval record claims a phase or action the owner did not authorize. | 3 (approval is not a runtime badge), 9 (external calls need separate authority), 10 (parallelism does not expand scope) | `.agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py:validate_task` binds phase, action, design identity, exclusions, and authority booleans. It cannot authenticate a conversational grantor. | ONT-CAND-001, ONT-CAND-002 | Repository validation proves internal consistency, not human identity or intent. Serial owner review remains required. |
| T02 registry to alias matcher | Alias poisoning, normalization collision, or insertion-order selection produces false confidence. | 2 (generated entries are candidates), 4 (ambiguity fails closed), 5 (coverage is not correctness) | No direct ontology control exists. `palimnex/retrieval.py:retrieve_sources` provides deterministic pointer tie-breaking for existing channels, but has no concept-alias policy. | ONT-AMB-001, ONT-AMB-002, ONT-NORM-001, ONT-NORM-002, ONT-NORM-003 | Case folding, Unicode normalization, whitespace policy, maximum aliases, and conflict rules still need contract freeze and adversarial implementation tests. |
| T03 candidate store to approved read path | Persistence, a boolean field, child-agent completion, or model output silently promotes a candidate. | 2 (generated entries are candidates), 3 (approval is not a runtime badge), 10 (parallelism does not expand scope) | No direct ontology control exists. The historical analogue `palimnex/experience.py:is_capture` validates exact candidate fields and digest, while `apply_capture` keeps results `historical_only` and `authorizes_actions: false`; it does not approve concepts. | ONT-CAND-001, ONT-CAND-002 | Phase 1 must use separate candidate and approved read paths. Filesystem placement alone is not approval. |
| T04 locator to repository source | A reviewed binding becomes stale, changes version, or changes during a read, yet remains counted as covered. | 1 (repository source remains current authority), 7 (no silent downgrade) | `palimnex/locators.py:resolve_locator` checks resolver version and range digest. `palimnex/security.py:read_bounded_file` checks size and file identity before and after reading. | ONT-STALE-001, ONT-STALE-002 | The coverage error surface is not frozen: stale state may refuse the operation or emit a diagnostic receipt. A second-read race test is still required in Phase 1/2. |
| T05 locator path to filesystem | Absolute paths, parent traversal, final symlinks, or symlinked parents escape the repository. | 1 (repository source remains current authority) | `palimnex/locators.py:RepositoryResolver.resolve` rejects absolute and parent-traversal paths. `palimnex/security.py:read_bounded_file` requires normalized relative components and opens every component with no-follow semantics. | ONT-PATH-001, ONT-PATH-002 | Platform filesystem semantics and race conditions require focused tests. Malformed-binding versus receipt-error behavior remains open. |
| T06 project identity to registry, cache, or resolver | A valid record from another project is accepted locally, leaking source or importing foreign meaning. | 1 (repository source remains current authority), 8 (history stays non-authorizing) | `palimnex/cache_v3.py:project_id`, `namespace`, and `hot_namespace` bind cache keys to a committed UUID. `palimnex/experience.py:apply_capture` rejects a project mismatch. Source-locator v1 itself has no project field. | ONT-CROSS-001, ONT-CROSS-002 | Phase 0 must decide whether project binding lives in the registry envelope, resolver registration, or both without changing source-locator v1. |
| T07 admitted bytes to aliases, concepts, embeddings, or reranking | Credential material is transformed into an alias, concept, vector, prompt, log, or diagnostic before admission, preserving or exporting a secret. | 6 (privacy admission precedes derivation), 9 (external calls require separate authority) | `palimnex/security.py:scan_text` and `scan_bytes` report rule IDs and lines without matched values. `palimnex/locators.py:select_range` scans bytes before returning them. No ontology derivation pipeline exists. | ONT-SEC-001, ONT-SEC-002 | Derived representations can retain information even when they do not reproduce source text. Any semantic phase needs proof that scanning precedes all derivation and that refusals persist no value. |
| T08 enabled channel to returned result | Registry corruption, cache corruption, resolver failure, or provider error is silently presented as a normal baseline result. | 7 (no silent downgrade), 1 (repository source remains current authority) | `palimnex/retrieval.py:retrieve_sources` makes local mode explicit and propagates cache failures. `palimnex/cache_v3.py:_posting_candidates` rejects malformed or source-divergent postings. `palimnex/semantic.py:semantic_status` rejects every configured mode except disabled. | ONT-STALE-001, ONT-STALE-002, ONT-PATH-002 | The future ontology channel needs a distinct failure disclosure. Operators may still retry in baseline mode, but that must be an explicit new request. |
| T09 Redis projection to retrieval | A stale, corrupt, or cross-namespace ontology projection changes recognition or coverage without reopening approved source. | 1 (repository source remains current authority), 7 (no silent downgrade) | Existing cache controls in `palimnex/cache_v3.py:validate`, `_deep_validate`, and `_posting_candidates` compare the projection with a fresh source snapshot and project namespace. No ontology projection is approved. | ONT-STALE-001, ONT-CROSS-001, ONT-CAND-002 | A future projection design must bind registry digest and generation identity and remain optional. Phase 0 does not authorize persistent ontology state in Redis. |
| T10 SQLite ledger to context or registry | Historical aliases, feedback, imports, or corrections are treated as current ontology approval or operational authority. | 3 (approval is not a runtime badge), 8 (history stays non-authorizing) | `palimnex/durable.py:MemoryLedger` declares all returned authority historical-only. `palimnex/experience.py:is_capture` and `apply_capture` enforce `historical_only` and `authorizes_actions: false`. No registry reads from the ledger. | ONT-CAND-001, ONT-SUPER-002, ONT-WITH-001 | Future feedback could create de facto popularity-based approval. Query-history learning remains out of scope and must not be inferred from these drafts. |
| T11 lifecycle state to matcher | Superseded or withdrawn records reappear through an old alias, or a non-active collision makes an active concept ambiguous. | 2 (only reviewed active content may influence retrieval), 3 (approval is not a runtime badge), 4 (ambiguity fails closed) | No direct ontology control exists. Existing durable supersession is a different historical graph and must not be reused as the concept lifecycle implementation. | ONT-SUPER-001, ONT-SUPER-002, ONT-WITH-001, ONT-WITH-002 | Whether inactive concepts are omitted entirely or disclosed as non-influencing diagnostics remains an owner decision. |
| T12 unbounded input to validator, matcher, or receipt | Oversize registries, aliases, queries, sources, result arrays, or nested data cause denial of service or bypass validation. | 1 (only bounded verified source supports coverage), 6 (admission precedes derivation) | `palimnex/security.py:scan_bytes` caps admitted bytes; `read_bounded_file` caps file reads. `palimnex/locators.py:SourceLocator` bounds identities, encoded locators, ranges, and source bytes. `palimnex/retrieval.py:budget_items` bounds serialized output and `retrieve_sources` caps limits and candidates. | ONT-TRUNC-001, ONT-TRUNC-002, ONT-BUDGET-001, ONT-BUDGET-002 | Exact registry, concept, alias, relation, and receipt limits belong to the schema lanes and are not frozen by this threat lane. |
| T13 retrieval diagnostics to coverage receipt | Truncation or byte-budget omission is mislabeled unanswerable, while partial or ambiguous evidence is mislabeled fully covered. | 4 (ambiguity fails closed), 5 (coverage is not correctness), 7 (no silent downgrade) | `palimnex/retrieval.py:retrieve_sources` separately reports candidate count, omitted count, byte budget, and mode. No coverage receipt exists. | ONT-PAR-001, ONT-PAR-002, ONT-TRUNC-001, ONT-TRUNC-002, ONT-BUDGET-001, ONT-BUDGET-002 | The receipt contract must preserve independent omission and truncation fields; a single ratio cannot encode these states. |
| T14 frozen evaluation to promotion decision | Cases are relabeled after seeing results, the candidate is tuned to the fixture, or synthetic retrieval metrics are treated as deployment evidence. | 3 (a certification result is not approval), 5 (coverage is not correctness), 9 (external activity needs separate authority) | `palimnex/challenge.py:evaluate_challenges` verifies a pinned fixture digest and reports `promotion_eligible: false`, plus explicit latency and quality boundaries. `palimnex/semantic.py:promotion_decision` is only a metrics gate and does not authorize promotion. | All ONT-* cases; especially ONT-NEG-001, ONT-NEG-002, ONT-AMB-001, ONT-AMB-002 | A known frozen cohort can still be overfit. The owner must record the matrix digest at exit, prohibit opportunistic relabeling, and later add held-out review. |
| T15 semantic-provider boundary | Source leaves the machine, provider identity drifts, malformed vectors enter ranking, or provider failure silently falls back. | 6 (privacy before derivation), 7 (no silent downgrade), 9 (external calls require separate authority) | `palimnex/semantic.py:semantic_status` permits only disabled mode and reports no network, provider, or influence. `promotion_decision` rejects non-finite/out-of-range metrics and requires non-regression plus latency bounds. | ONT-SEC-002, ONT-TRUNC-001, ONT-CAND-002 | Vector shape, model revision, timeouts, remote disclosure, and malformed result handling require a later separately approved contract. Phase 0 authorizes no provider call. |
| T16 agent output to shared integration | Parallel agents overwrite another lane, edit shared files, or treat a receipt as permission to commit or publish. | 10 (parallelism does not expand scope) | `.agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py:validate_manifest` rejects overlapping ownership and cyclic dependencies; `validate_receipts` binds receipt identities and changed paths. | ONT-CAND-001, ONT-CAND-002 | Schema validation cannot stop an agent from writing a foreign path before handoff. The coordinator must inspect the actual diff and integrate serially. |
| T17 receipt to operator action | A coverage ratio, `tested` receipt, authenticated record, or successful agent run is interpreted as operational authorization or proof of answer correctness. | 3 (approval is not a runtime badge), 5 (coverage is not correctness), 8 (history stays non-authorizing), 10 (child completion is not approval) | The contract validator returns `authorizes_actions: false`. Existing retrieval output in `palimnex/retrieval.py:retrieve_sources` also sets `authorizes_actions: false`. | ONT-POS-001, ONT-PAR-001, ONT-AMB-001, ONT-NEG-001 | Humans and downstream tools may still ignore the field. The future receipt needs fixed authority constants and documentation at every presentation boundary. |

## Required fail-closed ordering

For repository-backed coverage, the intended order is:

1. validate the approved registry envelope, project identity, lifecycle, and
   canonical digest;
2. reject candidate, superseded, and withdrawn influence;
3. validate and normalize bounded aliases, reporting collisions as ambiguity;
4. scan admitted source bytes before any concept, alias, embedding, prompt, or
   reranking derivation;
5. reopen every supporting source through source-locator v1, then verify
   version, range, and digest;
6. compute deterministic coverage independently of retrieval truncation and
   byte-budget omission; and
7. emit a bounded evidence-only receipt with channel influence, errors,
   authority, and omission state visible.

An explicitly enabled channel that fails at any step must not be presented as
if that channel participated successfully. An operator may separately request
baseline retrieval, but that is a new explicit mode, not an implicit fallback.

## Frozen-case integrity and use

`../frozen-cases/cases.v0.json` provides stable IDs for positive, partial,
ambiguous, unrelated, stale-source, secret, truncation, byte-budget,
supersession, withdrawal, candidate, path, cross-project, and normalization
behaviors. Its digest is recorded only at the owner-approved Phase 0 exit gate.
Until then it is a draft. Phase 1-3 implementations must consume the recorded
file without changing labels to make a candidate pass.

The secret cases store construction recipes only. The offline checker rebuilds
each canary in memory, proves the scanner detects it, scans all files owned by
this workstream, and prints rule identifiers only if a violation occurs.

## Open questions for the owner

1. When registry admission or source verification fails, should the public
   operation return a typed error with no coverage receipt, or an evidence-only
   receipt whose status is conservatively `unanswerable` plus an explicit
   failure field? The disputed stale, secret, path, and cross-project cases
   mark this unresolved boundary.
2. Freeze the alias normalization algorithm: case folding method, Unicode form,
   which whitespace classes collapse, punctuation behavior, and whether the
   normalized value or only its digest may be persisted.
3. Confirm that `superseded` and `withdrawn` concepts are excluded from
   recognized IDs, not merely excluded from covered IDs, while their state may
   still appear in a separate non-influencing diagnostic.
4. Choose where project identity is bound for external source resolvers. The
   registry envelope can bind the project without changing source-locator v1,
   but resolver responses may need an additional registered-project check.
5. Freeze numeric limits for registry bytes, concepts, aliases per concept,
   alias bytes, relations, source bindings, query bytes, receipt arrays, and
   total receipt bytes in the schema lanes.
6. Confirm that truncation and byte-budget omission never change semantic
   status by themselves and always remain separate receipt fields.
7. At the Phase 0 exit gate, record the exact matrix digest and require a new
   reviewed version rather than relabeling v0 after any implementation result.

## Out of scope

This draft does not authorize product code, a public schema, a registry read
path, a Redis projection, a ledger change, a semantic provider, network use,
Git writes, publication, migration, retention action, erasure, pack activation,
or retrieval influence.
