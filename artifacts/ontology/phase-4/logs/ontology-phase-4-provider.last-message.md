Implemented Phase 4 local semantic provider within owned paths only.

- Public API: `HashedEmbeddingProvider`, `SemanticProviderError`, `implementation_digest`, `provider_identity`, `identity_digest`, and `checked_embed` in [semantic_local.py](/home/kestl/github/palimnex/palimnex/semantic_local.py).
- Added deterministic test doubles and `palimnex:semantic-provider-identity:v1` schema.
- Tests: 18 provider tests + 36 compatibility sentinels passed; strict mypy passed.
- Receipt validated: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-4/receipts/ontology-phase-4-provider.implementation-receipt.json).
- Deviations: none.
- Open risks: full suite and standard gate remain coordinator-owned; indexed files require coordinator reindex/evaluation. `cache_consulted: false` due task boundary.
- No Git writes, network access, live-state changes, or retrieval influence.