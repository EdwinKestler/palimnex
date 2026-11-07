Implemented and validated Phase 4 semantic shadow channel.

- Added `SemanticShadowError`, `SemanticChannel`, `EmbeddingMemo`, `semantic_channel`, `semantic_shadow_retrieve`, `validate_semantic_comparison`, `policy_digest`, and R14 constants in [semantic_shadow.py](/home/kestl/github/palimnex/palimnex/semantic_shadow.py).
- Added the `palimnex:semantic-shadow-comparison:v1` schema and focused tests.
- 17 focused tests passed; 54 compatibility tests passed; strict mypy passed.
- Receipt validation passed: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-4/receipts/ontology-phase-4-channel.implementation-receipt.json).
- No deviations or integration patch proposals. `palimnex/retrieval.py` remains unchanged.
- Open risks: full suite and standard gate remain delegated to the coordinator; semantic quality evaluation and required reindex/evaluation await integration. Redis was unavailable (`cache_consulted: false`).
- No Git, network, ledger, or live-state writes were performed.