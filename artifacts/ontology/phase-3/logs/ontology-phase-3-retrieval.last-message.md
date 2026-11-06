Implemented `ontology-phase-3-retrieval` within all owned paths.

- Added `palimnex.retrieval.shadow_retrieve(...)`, returning the unchanged baseline plus `palimnex:ontology-shadow-comparison:v1`.
- `retrieve_sources` compatibility verified across 96 golden combinations and six repository queries.
- Tests: 57 passed total (9 focused, 48 regressions); strict mypy passed.
- [Implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3/receipts/ontology-phase-3-retrieval.implementation-receipt.json) validates successfully.
- No deviations, Git writes, network calls, or live-state mutations.

Open risks: the coordinator still owns reindexing, full-suite/standard-gate execution, cache-backed validation, and complete Phase 3 evaluation. Redis was unavailable (`cache_consulted: false`).