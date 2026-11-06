# Lane brief: ontology-phase-2-coverage-core

Read `COMMON.md` and `EXPLAIN_SEARCH_SPEC.md` first. You own
`palimnex/coverage.py` and `palimnex/tests/test_coverage.py`. The
frozen-conformance lane and the coordinator's CLI build on your public API, so
make it explicit, documented and stable.

## Implement `palimnex/coverage.py` (stdlib + `palimnex.*` only, strict mypy)

Implement `artifacts/design/ontology-phase-0/coverage/SEMANTICS.md` exactly:

- `COVERAGE_SCHEMA = "palimnex:retrieval-coverage:v1"`,
  `EXPLAIN_SEARCH_SCHEMA = "palimnex:explain-search:v1"`,
  `QUERY_DIGEST_POLICY = "sha256-utf8-nfc-lf-preserve-whitespace-case:v1"`, and
  the accepted bounds (256 visible / 4,096 total per collection, 16 / 64
  nested) as constants.
- `CoverageError(ValueError)` with a stable `reason` and no echoed values.
  Reuse or wrap `palimnex.concepts.ConceptRegistryError` for registry refusals.
- `query_digest(query: str) -> str` per the "Query digest" section, including
  the existing 8 KiB query bound.
- `build_coverage_receipt(registry, query, search_result, *, root, resolvers=None) -> dict`:
  - `registry` must be an approved-kind `ConceptRegistry`; otherwise a typed
    refusal. Its project identity must equal the checkout's (the same
    `cache_v3.project_id` and `core.project_slug` helpers Phase 1 uses);
    otherwise a typed cross-project refusal.
  - Recognition is `palimnex.concepts.match_aliases` (R9 applies). Verification
    is `palimnex.concepts.verify_source_bindings`, restricted to recognized,
    non-ambiguous concepts. Classify each concept as exactly one of covered,
    uncovered, stale or ambiguous candidate per SEMANTICS.md. Map Phase 1
    `BindingVerification.reason` values to the four stale reasons (`missing`,
    `version_changed`, `digest_changed`, `unavailable`). Document the mapping
    and ground it in the Phase 1 reason codes. Any reason that is really an R7
    refusal stays a typed error.
  - Identities: project; checkout (`checkout_id` taken from
    `search_result["checkout_id"]` and checked against the recomputed root
    digest, refusing on mismatch); corpus (`search_result["corpus_fingerprint"]`
    plus `cache_v3.index_policy_digest(root)`); and registry digest, using the
    derivation strings the accepted schema requires.
  - `retrieval_state` derived only from the search result's existing fields
    (`results`, `candidate_count`, `omitted_count`, `byte_budget`,
    `items_bytes`; see `palimnex/retrieval.py` and the cache_v3 search
    equivalent). Keep retrieval truncation and byte-budget omission separate,
    and document exactly how each is derived. If the existing fields cannot
    separate them faithfully, say so in `unresolved_risks` rather than guessing.
  - Fixed semantic disclosure (provider disabled, no influence), the status
    decision table, integer coverage, ordering, truncation flags and counts,
    and `receipt_digest` over canonical JSON with `receipt_digest` excluded.
  - Never include the raw query, source excerpts or scanner findings.
- `validate_receipt(receipt) -> None`: plain-Python structural validation
  mirroring the accepted schema, plus the cross-field rules JSON Schema cannot
  express (disjointness, R = C + U + S + A, the status table, counts versus
  truncation flags, ordering, digest).
- `build_explain_search(search_result, receipt | None, *, registry_path, registry_source) -> dict`
  exactly per `EXPLAIN_SEARCH_SPEC.md`. `search_result` is deep-copied and
  never altered.

## Tests: `palimnex/tests/test_coverage.py`

Use temporary checkouts with a real `.palimnex.json` project identity and
source files whose real digests are bound. Cover: each status row, including
ambiguity precedence with other concepts covered, stale-only `unanswerable`
and verified-plus-stale `partial`; uncovered (no bindings); every stale-reason
mapping; R7 refusals with no echo; cross-project and candidate-kind refusals;
`0/0` staying integers; truncation and byte-budget omission never by themselves
causing `unanswerable`; collection truncation at the bounds; query-digest
vectors (CRLF, CR, NFC, case and whitespace kept); digest stability and tamper
detection through `validate_receipt`; deterministic ordering; the
explain-search wrapper in both states; and the guarantee that `search_result`
is unchanged (compare deep copies). No Redis.
