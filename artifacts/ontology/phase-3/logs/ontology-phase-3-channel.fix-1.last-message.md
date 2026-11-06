Implemented Phase 3 FIX ROUND 1 within owned paths only.

Change:

- [ontology_shadow.py](/home/kestl/github/palimnex/palimnex/ontology_shadow.py:16) now reuses the registry’s 3–128 character constants.
- Runtime concept-ID validation enforces those bounds while preserving canonical sorted/duplicate checks.
- [test_ontology_shadow.py](/home/kestl/github/palimnex/palimnex/tests/test_ontology_shadow.py:410) proves runtime/schema parity for lengths 2, 3, 128, and 129 with refreshed digests.
- Refreshed [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3/receipts/ontology-phase-3-channel.implementation-receipt.json).

Parity evidence:

- Ontology shadow: 18/18 passed
- Retrieval shadow + ontology evaluation: 20/20 passed
- Concepts + coverage regressions: 43/43 passed
- Strict mypy: passed
- Receipt validator: `status: valid`
- Public schema and documentation were already correct and remain unchanged.

No Git, cache, ledger, network, indexing, or foreign-path writes were performed. `cache_consulted: false`; the full suite and standard gate remain delegated as required.