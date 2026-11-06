# Fix round 1: ontology-phase-3-cohort (rebind after the retrieval refactor)

Same task card and owned paths. The retrieval lane refactored
`palimnex/retrieval.py` (read-only to you). RRF fusion now lives in
`_fuse_rankings`, around lines 167-182. Your `concept.rrf_fusion` binding
(lines 128-146) now covers symbol-scoring code, so it would bind the wrong
source.

Change only this:
- Rebind `concept.rrf_fusion` to the exact line range of `_fuse_rankings`
  (its `def` line through its last line). Read the file to get the exact
  numbers.
- Re-check every other binding against current source (`palimnex/core.py`
  also changed in Phases 2 and 3). Each range must still cover the code the
  concept names. Rebind any that drifted, and list every change in your receipt.
- Keep placeholders, concepts, aliases, cases and labels unchanged. If a case's
  `expected_paths` no longer holds because code moved to another file, say so in
  `unresolved_risks` instead of editing the case.
- Add an assertion to your test that each binding range starts at the `def` or
  `class` line or docstring it names, using a small `expected_anchor` text per
  concept kept in the test (not in the cohort file).

Run your focused test. Overwrite your receipt (fresh digests), status `tested`,
and record the new cohort SHA-256. Do not run the full suite.
