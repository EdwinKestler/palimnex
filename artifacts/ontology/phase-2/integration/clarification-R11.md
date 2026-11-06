# R11: query length versus the alias bound (coordinator correction of R9, Phase 2)

**Finding.** The coverage-core lane reported, and the coordinator reproduced,
that `palimnex.concepts.match_aliases` refuses any query whose normalized form is
longer than 128 code points (`alias_bound at query`). `explain-search` would
therefore fail on ordinary questions longer than about one sentence.

**Cause.** R9 (`artifacts/ontology/phase-1/integration/clarification-R9.md`)
said queries follow "the same steps 1-6 unchanged". Step 6 of the registry
normalization procedure rejects keys longer than 128 code points. It is a bound
on stored matching keys (aliases and canonical names), not on query text. The
coverage contract bounds queries separately at 8 KiB of UTF-8. The error was
the coordinator's, in R9's wording.

**Correction (no contract change).**
- Registry keys: steps 1-6 exactly, including the 128 code-point bound.
  Unchanged.
- Queries: refuse more than 8,192 UTF-8 bytes (`query_bound`); privacy scan
  (unchanged); map `str.isspace()` to U+0020 (R9); then steps 1-5: NFKC,
  casefold, refuse C*, punctuation and separators to space, collapse. A query
  that normalizes to empty is refused (`query_bound`). No 128 code-point query
  bound.

**Authority.** The fix is in committed Phase 1 code. The Phase 2 integration
lane (coordinator) was amended to own `palimnex/concepts.py` and
`palimnex/tests/test_concepts.py` for this fix only; other task cards and their
receipts are unchanged (`bundle-validation.r11.json`). Listed for the owner at
Phase 2 handoff.

## Codex technical confirmation (2026-11-06)

Confirmed against the accepted coverage-query bound, the stored-key contract,
the R9 frozen whitespace case, focused long-query tests, and the full gate.
Queries use an 8 KiB strict UTF-8 bound and normalization steps 1-5; stored
aliases and canonical-name keys retain the 128-code-point step 6. No frozen
label or retrieval ranking behavior changed. This confirmation does not approve
Phase 3.
