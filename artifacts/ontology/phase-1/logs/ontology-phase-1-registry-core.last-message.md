Implemented and validated `ontology-phase-1-registry-core`.

- Public API: `normalize_alias`, `canonical_registry_digest`, `parse_registry`, `load_registry`, `match_aliases`, `verify_source_bindings`, frozen result dataclasses, bounds, and typed `ConceptRegistryError` in [concepts.py](/home/kestl/github/palimnex/palimnex/concepts.py:34).
- Tests: 22/22 focused; 318/318 full suite; strict mypy clean; standard gate passed, including 20 retrieval cases at Recall@5 1.0.
- Receipt: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-registry-core.implementation-receipt.json) validated successfully.
- Deviations: none. No Git, network, ledger, or live-state writes.
- Open risks: source-locator v1 cannot project-bind resolvers that make no scope claim. Redis was unavailable, so `cache_consulted: false`; indexed files changed and the coordinator must reindex/evaluate after integration.