Implemented Phase 1 Fix Round 2 within owned paths:

- Registry normalization: [CONCEPT_REGISTRY.md](/home/kestl/github/palimnex/docs/CONCEPT_REGISTRY.md:56) now states all C* code points—including TAB, LF, and CR—are refused in registry keys.
- Query normalization: whitespace is converted to U+0020 before the same six-step procedure; other controls are refused. R9 is cited.
- Receipt: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-registry-schema.implementation-receipt.json:1) refreshed with current digests and `tested` status.

Validation:

- Focused suite: 25/25 passed.
- Receipt contract validation: passed.
- No Git, network, cache, ledger, or live-state operations.
- Indexed documentation changed; coordinator reindex/evaluation remains deferred as required.