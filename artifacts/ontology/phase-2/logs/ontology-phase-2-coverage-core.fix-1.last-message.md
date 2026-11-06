Implemented the exact omission-attribution fix in [coverage.py](/home/kestl/github/palimnex/palimnex/coverage.py:313) and added real-retrieval/decision-table tests in [test_coverage.py](/home/kestl/github/palimnex/palimnex/tests/test_coverage.py:401).

- Coverage tests: 18/18 passed.
- Strict mypy: passed.
- Concept regressions: 29/29 passed.
- Receipt validation: passed.
- Frozen coverage: 2 byte-budget cases fail because the read-only harness does not supply `retrieval_limit`.

The validated [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-2/receipts/ontology-phase-2-coverage-core.implementation-receipt.json:1) records `partial` and the required coordinator call-site/harness updates. Indexed files changed; reindex/evaluation remains delegated. No Git, network, cache, or ledger writes occurred.