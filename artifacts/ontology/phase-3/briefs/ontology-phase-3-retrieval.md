# Lane brief: ontology-phase-3-retrieval (wave B, after the channel lane)

Read `COMMON.md` and `SHADOW_SPEC.md` section 2 first. You own
`palimnex/retrieval.py` and `palimnex/tests/test_retrieval_shadow.py`.
`retrieval.py` is a shared bottleneck that `context`, `explain-search` and the
challenge evaluation all depend on. Its baseline behavior must not change by a
single byte. `palimnex/ontology_shadow.py` is finished and read-only to you.

## Step 0: capture golden outputs BEFORE editing

Before you touch `retrieval.py`, write a short script under /tmp that runs the
current `retrieve_sources` over:
- a fixed temporary corpus (several Python and Markdown files with symbols and
  imports, so the lexical, symbol and graph channels all fire) and at least 12
  queries, with `include_graph` both True and False, two limits and two byte
  budgets; and
- this repository itself (`root` = the repository, local mode) with at least 6
  queries.
Record the SHA-256 of `canonical_json(result)` for each, and embed the
temporary-corpus digests as constants in your test. Treat repository-corpus
results as a same-run equality check (call the function twice, before and after
shadow), not as pinned constants, because the repository changes.

## Implement

- Refactor `retrieve_sources` into a channel-ranking helper and a fusion
  helper, so the baseline and the shadow share one computation of the lexical,
  symbol and graph rankings. Keep `retrieve_sources`' signature, validation
  order, errors and output exactly as before.
- Add `shadow_retrieve(...)` exactly per SHADOW_SPEC section 2. It calls
  `palimnex.ontology_shadow.ontology_channel` once and returns
  `{"baseline": ..., "comparison": build_shadow_comparison(...)}`. Validate the
  comparison with `validate_shadow_comparison` before returning.
- No caching, no persistence and no Redis writes. `client` behaves exactly as
  in `retrieve_sources` (cache errors never silently downgrade).

## Tests: `palimnex/tests/test_retrieval_shadow.py`

- Golden digests for the temporary corpus match after the refactor.
- `shadow_retrieve(...)["baseline"] == retrieve_sources(...)` for every golden
  input, and with `registry=None` the shadow equals the baseline
  (`diff.identical`).
- With a registry whose concept binds a chunk that the baseline ranks low or
  not at all, the shadow promotes it, while the baseline is unchanged.
- Ambiguous, stale, uncovered and candidate concepts change nothing.
- Channel ranks for all four channels are visible on shadow items, and the caps,
  budget and limit are respected.
- Frozen Phase 3 cases from `palimnex/tests/fixtures/ontology/cases.v0.json`
  (read-only, SHA-256
  `a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b`):
  ONT-SEC-002 (secret source bytes are refused with no echo and no shadow
  result) and ONT-CAND-002 (a candidate alias collision neither makes the
  approved concept ambiguous nor alters ranking). Materialize placeholders
  exactly as the Phase 2 frozen harness does; labels never change.
- `context` and `explain-search` behavior unchanged: run
  `palimnex.tests.test_explain_search` and `palimnex.tests.test_coverage_frozen`
  (in your acceptance commands).
