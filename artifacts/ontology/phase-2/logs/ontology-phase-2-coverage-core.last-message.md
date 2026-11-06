Implemented `ontology-phase-2-coverage-core` within the three owned paths.

Public API added in [coverage.py](/home/kestl/github/palimnex/palimnex/coverage.py):

- `query_digest`
- `canonical_receipt_digest`
- `build_coverage_receipt`
- `validate_receipt`
- `build_explain_search`
- Typed `CoverageError` and public contract constants

Validation:

- 16 coverage tests passed
- 28 Phase 1 regressions passed
- 5 schema tests passed
- 10 downstream explain-search tests passed
- Strict mypy passed
- Implementation receipt validated successfully

Receipt: [ontology-phase-2-coverage-core.implementation-receipt.json](/home/kestl/github/palimnex/artifacts/ontology/phase-2/receipts/ontology-phase-2-coverage-core.implementation-receipt.json)

Open risks: existing search fields cannot always distinguish byte-budget omission from limit truncation; Phase 1 applies its 128-character normalization bound to the complete query; mixed stale reasons conservatively aggregate as `unavailable`. Cache was unavailable (`cache_consulted: false`). Indexed files changed, so reindex/evaluation and the full gate remain delegated to the coordinator.