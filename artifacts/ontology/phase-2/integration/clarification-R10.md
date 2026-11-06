# R10: which search result `explain-search` embeds (coordinator clarification, Phase 2)

**Finding.** `palimnex search` with the default cache backend calls
`palimnex.cache_v3.search`. It returns only `query`, `fresh` and `results` (plus
`cache_mode` and `authoritative_backend` added by the CLI). It has no checkout
identity, corpus fingerprint, candidate or omission counts, byte budget, or
semantic-influence disclosure, and it applies no byte budget at all. The
accepted coverage contract (`artifacts/design/ontology-phase-0/coverage/SEMANTICS.md`,
"Identity bindings" and "Bounds and truncation") grounds every one of those
fields in `palimnex/retrieval.py`: `retrieve_sources`, the bounded,
source-backed retrieval that `context` already uses. The schema also requires
`byte_budget >= 1`, which a backend without a budget cannot report faithfully.

**Clarification.** `explain-search` embeds, unchanged, the result of
`palimnex.retrieval.retrieve_sources` for the same query. That is "the existing
bounded, source-backed retrieval result" in the design's "Intended outcome". It
does not embed the `palimnex search` CLI output. Flags mirror `context` and that
function's own defaults: `--limit` (default 5, range 1-100), `--byte-budget`
(default 8192), `--backend local|cache` (default `local`; `cache` passes a
Redis client and never silently downgrades), `--no-graph`, and `--registry`.

**Effect.** No contract, schema or coverage-engine change; `search` keeps its
output; every identity and disclosure field in the receipt is real rather than
inferred. Owner decision (sibling objects in one document) is unchanged. The
only change is which existing retrieval result fills the `search` member.
`EXPLAIN_SEARCH_SPEC.md` and `docs/COVERAGE_RECEIPT.md` are corrected
accordingly. Listed for the owner at Phase 2 handoff.

## Codex technical confirmation (2026-11-06)

Confirmed against the accepted coverage contract, `retrieve_sources`, the
unchanged `search` command, local and cache-backed command output, and the full
test/evaluation gates. The bounded result used by `context` is the correct
embedded search object because it carries the checkout, corpus, byte-budget,
omission, semantic-influence, and authority fields the receipt binds. This
confirmation does not approve retrieval influence or Phase 3.
