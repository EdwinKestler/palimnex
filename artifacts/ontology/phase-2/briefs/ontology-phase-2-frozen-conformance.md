# Lane brief: ontology-phase-2-frozen-conformance (after core and schema)

Read `COMMON.md` and `EXPLAIN_SEARCH_SPEC.md` first. You own
`palimnex/tests/test_coverage_frozen.py` only. `palimnex/coverage.py`, the two
new schemas and their fixtures are finished and read-only to you; read their
code and receipts in `artifacts/ontology/phase-2/receipts/`. The frozen matrix
is the committed `palimnex/tests/fixtures/ontology/cases.v0.json` (SHA-256
`a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b`), which is
read-only. Assert that digest.

## Deliverables

1. **Phase 2 conformance**, one `subTest` per case with `gates_phase: 2` (12
   cases). Phase 2 fixtures use placeholder locator digests
   (`binding_digests_are_placeholders`) and some carry a `runtime_condition`.
   Read `artifacts/design/ontology-phase-0/frozen-cases/README.md` and each
   case's `runtime_condition`, then **materialize** the case in a temporary
   checkout:
   - a `.palimnex.json` whose project identity matches the fixture registry;
   - each bound source file, written with content whose selected range is
     non-empty and admissible;
   - each placeholder digest replaced by the real digest of the selected range,
     and `registry_digest` recomputed;
   - drift applied after binding where the case requires stale (for example,
     changing bytes for digest drift, as `runtime_condition` says);
   - a synthetic search result with the existing search fields, shaped by
     `runtime_condition` for the truncation and byte-budget cases.
   Materialization may change only placeholders, digests and synthetic
   inputs. It never changes a label, alias, concept, status or expected ID set.
   Then build the receipt with `palimnex.coverage` and assert
   `expected_status` and the exact covered, uncovered, stale and ambiguous ID
   sets. Also run `validate_receipt` on every produced receipt.
2. **Disputed cases** (`expected_status_disputed`, for example ONT-STALE-*):
   assert the labels anyway. If the implementation disagrees with a disputed
   label, keep the test failing and report it. Do not hide it.
3. **Parity**: every produced receipt and every fixture under
   `palimnex/tests/fixtures/retrieval_coverage/` must get the same
   accept/reject answer from `palimnex.coverage.validate_receipt` and from the
   JSON Schema (local `referencing.Registry`). Also wrap each produced receipt
   with `build_explain_search` and validate it against the explain-search
   schema. Report any disagreement as a failing test plus an
   `integration_patch_proposals` entry.

If a case fails because `palimnex/coverage.py` is wrong, the test stays
failing, you report it, and your receipt status is `partial`. You do not edit
the core module.
