# R10 fix: ontology-phase-2-coverage-schema

Same task card and owned paths. Read
`artifacts/ontology/phase-2/integration/clarification-R10.md` and the updated
`artifacts/ontology/phase-2/briefs/EXPLAIN_SEARCH_SPEC.md`, then read the
coordinator's CLI in `palimnex/core.py` (functions
`concept_registry_selection` and `explain_search`, plus the `explain-search`
subparser), which is read-only to you.

Change only `docs/COVERAGE_RECEIPT.md`:
- The `search` member is the unchanged result of the bounded, source-backed
  retrieval used by `context` (`retrieve_sources`). It is NOT the output of
  `palimnex search`. Correct every sentence that says otherwise (around the
  current lines 71 and 88).
- Document the real command: `palimnex explain-search QUERY [--limit N]
  [--byte-budget N] [--backend local|cache] [--no-graph] [--registry PATH]`,
  with the defaults from the code (`--limit 5`, `--byte-budget 8192`,
  `--backend local`). `--registry` is repository-relative and refuses absolute
  paths and `..`. A missing default registry gives `registry_absent` with exit
  0; a missing explicit registry and any typed refusal give exit 1 with a
  non-echoing error and no document.
- Add nothing the code does not do.

No schema or fixture changes. Run your focused tests, overwrite your receipt
(fresh digests), status `tested`, and cite R10. Do not run the full suite.
