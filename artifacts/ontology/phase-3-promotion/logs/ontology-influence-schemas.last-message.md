Implemented and validated `ontology-influence-schemas`.

- Added public contracts: `project-memory:context:v2`, `palimnex:explain-search:v2`, and `palimnex:ontology-promotion-evidence:v1` in [schemas](/home/kestl/github/palimnex/palimnex/schemas).
- Added 3 valid and 9 single-failure invalid fixtures plus [schema tests](/home/kestl/github/palimnex/palimnex/tests/test_influence_schemas.py).
- Tests: 30/30 passed, including coverage and SDK regressions.
- [Implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3-promotion/receipts/ontology-influence-schemas.implementation-receipt.json) validates successfully.
- Deviations/integration proposals: none.
- Open risks: Redis validation was unavailable (`cache_consulted: false`); coordinator must reindex, evaluate, and run the full suite/standard gate after integration. Indexed files changed.
- No Git writes or changes outside owned paths.