Implemented `ontology-phase-2-coverage-schema` within owned paths only.

- Added public `palimnex:retrieval-coverage:v1` and `palimnex:explain-search:v1` schemas.
- Added 9 valid and 10 invalid fixtures, schema tests, and [reader documentation](/home/kestl/github/palimnex/docs/COVERAGE_RECEIPT.md).
- Focused acceptance: 30/30 tests passed.
- [Implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-2/receipts/ontology-phase-2-coverage-schema.implementation-receipt.json) validated successfully.
- No deviations, Git writes, network calls, or live-state changes.
- Open risks: full gate and end-to-end CLI integration remain coordinator-owned.
- Indexed files changed; coordinator must reindex and evaluate after integration. `cache_consulted: false` because `.palimnex` was forbidden.