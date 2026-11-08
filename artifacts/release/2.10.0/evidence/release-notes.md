Palimnex 2.10.0 closes the ontology adoption (`docs/ONTOLOGY_ADOPTION.md`): a reviewed, source-bound concept registry, coverage receipts and `explain-search`, ontology shadow evaluation, opt-in ontology influence (off by default), the held local semantic shadow experiment and reviewed retrieval feedback records. API v1, ledger schema v1, event kinds and production retrieval defaults are unchanged.

Install the published package: `pipx install "palimnex[crypto]==2.10.0"` (also `uv tool install` or `pip`; see `docs/INSTALL.md`). Upgrading: follow `docs/UPGRADING.md` and run `palimnex index --incremental` afterwards. No ledger migration is needed. `retention-migrate --no-snapshot` is removed. Downgrading to 2.9.x after recording retrieval feedback needs care: 2.9.x `context` and `capsule` may surface feedback facts.

## Changes

- Removed `retention-migrate --no-snapshot`, as announced in 2.9.0. The CLI
  always takes the verified pre-migration snapshot; SDK API v1 retains the
  deprecated `migrate_retention(snapshot=False)` path.
- Added `palimnex.concepts`, the reviewed concept-registry foundation
  (ontology adoption Phase 1, `docs/ONTOLOGY_ADOPTION.md`). It is a
  standard-library loader and validator for `palimnex:concept-registry:v1`
  (`palimnex/schemas/concept-registry.v1.schema.json`, documented in
  `docs/CONCEPT_REGISTRY.md`), with a canonical digest, deterministic alias
  normalization, exact-alias matching with explicit ambiguity, candidate and
  approved separation, and source-binding verification that reports drift as
  stale. It is opt-in: only `explain-search` (below) loads a registry, no
  configuration key does, and concepts have no retrieval influence, so behavior
  without a registry is unchanged.
- Added `palimnex explain-search QUERY` (ontology adoption Phase 2), which
  prints one `palimnex:explain-search:v1` document. It holds the unchanged
  bounded source retrieval result (`retrieve_sources`, as used by `context`) and
  a `palimnex:retrieval-coverage:v1` receipt from the new `palimnex.coverage`
  module. The receipt reports which approved concepts the query names and
  whether their bound sources are covered, uncovered, stale or ambiguous, as
  `answerable`, `partial`, `ambiguous` or `unanswerable`. Coverage is not
  correctness. The registry defaults to `ontology/concept-registry.v1.json`
  (never indexed) and is overridden with `--registry`. Without it, coverage is
  `registry_absent`. Options: `--limit`, `--byte-budget`,
  `--backend local|cache`, `--no-graph`. Read-only, with no ranking influence;
  `search`, `context` and every existing format are unchanged. See
  `docs/COVERAGE_RECEIPT.md`.
- Added ontology-aware retrieval in shadow mode (ontology adoption Phase 3).
  `palimnex.ontology_shadow` ranks chunks that overlap the verified source
  bindings of approved, unambiguous concepts named in the query.
  `palimnex.retrieval.shadow_retrieve` fuses that fourth channel beside
  lexical, symbol and graph in a separate shadow ranking and reports it as
  `palimnex:ontology-shadow-comparison:v1`. The returned ranking is never
  changed. `palimnex evaluate-ontology-shadow [--limit N]` compares baseline
  and shadow over the frozen v27 cases, the v26 challenge negatives and a new
  frozen evaluation-only cohort with its own test registry
  (`palimnex/evaluation/ontology-shadow.v1.json`). It reports the Phase 3 gates
  and always `promotion_authorized: false`, exiting 2 when a gate fails.
  `retrieve_sources`, `search`, `context` and `explain-search` output is
  byte-identical. See `docs/ONTOLOGY_SHADOW.md`.
- Added opt-in ontology retrieval influence. `.palimnex.json`
  `ontology_influence.mode` is `off` (the default when the key is missing),
  `shadow` or `enabled`. Off and shadow leave every output byte-identical.
  `enabled` must name the approved registry digest and a promotion-evidence
  file and digest. Activation refuses, with an explicit error and no fallback,
  unless the registry is approved, belongs to this project, is unambiguous and
  current, and the evidence matches it, matches the current implementation, is
  `promotable` and covers the local and cache backends. Influence changes only
  `retrieve_sources` and its consumers: `context` then returns
  `project-memory:context:v2` and `explain-search` returns
  `palimnex:explain-search:v2`, each disclosing the influence. Cache-backed
  `search`, `symbols`, `impact` and `palimnex evaluate` are unchanged.
  `palimnex evaluate-ontology-promotion [--registry PATH] [--limit N]` prints
  `palimnex:ontology-promotion-evidence:v1` (exit 0 promotable, 2 held) and
  never activates anything. `palimnex ontology-status` reports the setting and
  whether it activates. Rollback is `mode: off`. See
  `docs/ONTOLOGY_INFLUENCE.md`.
- Added a local semantic shadow experiment (ontology adoption Phase 4), evidence
  only. `palimnex.semantic_local` provides a deterministic in-process provider
  over the existing hashed embedding (`palimnex-hashed-embedding`, revision 1,
  384 dimensions, behavioural implementation digest), described by
  `palimnex:semantic-provider-identity:v1`, with typed refusals for provider
  failures, timeouts, wrong counts or dimensions and NaN/Inf.
  `palimnex.semantic_shadow` computes a semantic channel beside the unchanged
  baseline and reports `palimnex:semantic-shadow-comparison:v1`; its memo is
  in-process only. `palimnex evaluate-semantic-shadow` prints
  `palimnex:semantic-shadow-evaluation:v1` over the protected suites, the frozen
  `palimnex:semantic-shadow-cohort:v1` fixture, drift and privacy-canary cases,
  with the owner's gates (exit 0 promotable, 2 held, 1 refused). A promotable
  report is not promotion. `retrieve_sources`, `context`, `explain-search`,
  `search`, `symbols`, `impact`, `palimnex evaluate`, `semantic-status`,
  `semantic-gate` and `project-memory:semantic-provider:v1` are unchanged. No
  model download, network or vector store. See `docs/SEMANTIC_SHADOW.md`.
- Added reviewed retrieval feedback records (ontology adoption Phase 5).
  `palimnex.feedback` stores an explicit, reviewer-attributed judgement that a
  query is or is not answered by a source range, as
  `palimnex:retrieval-feedback:v1` payloads on existing ledger event kinds
  (`fact`; `correction` to change the judgement; `revocation` with
  `palimnex:retrieval-feedback-withdrawal:v1` to withdraw it, never deleting
  history). The source range is digest-verified against current admitted
  bytes; query, note, reason and reviewer are privacy-scanned and never echoed.
  New owner-run commands `feedback-record`, `feedback-correct` and
  `feedback-withdraw` write the ledger; `feedback-report [--include-history]`
  prints `palimnex:retrieval-feedback-report:v1` with `current`, `stale`
  (source drift), `superseded`, `withdrawn` and `invalid` states. Feedback is
  `historical_only` and has no retrieval influence: `retrieve_sources`,
  `context`, `explain-search`, `search` and `palimnex evaluate` never read it.
  The ledger schema and event kinds are unchanged. See
  `docs/RETRIEVAL_FEEDBACK.md`.
- Added the first reviewed concept registry for this repository,
  `ontology/concept-registry.v1.json`: 16 source-bound concepts with
  conservative multi-word aliases, from source admission and locators through
  retrieval fusion, the durable ledger, retention, migrations, packs, the audit
  graph and the ontology, semantic and feedback surfaces. It was drafted from
  source code without access to the evaluation questions, independently
  reviewed concept by concept, and frozen before any evaluation used it. It
  powers `explain-search` coverage receipts by default. Promotion evidence
  over the local and cache backends is `promotable` (no case or critical
  regression on any suite), but
  ontology influence stays off: enabling it remains the owner's
  `.palimnex.json` decision. The registry binds this checkout only; other
  projects need their own.

