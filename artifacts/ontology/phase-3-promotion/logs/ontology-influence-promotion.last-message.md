Implemented `ontology-influence-promotion` within all owned paths.

- Added `evaluate_ontology_promotion(...)` and `OntologyPromotionError` in [ontology_promotion.py](/home/kestl/github/palimnex/palimnex/ontology_promotion.py).
- Produces deterministic `palimnex:ontology-promotion-evidence:v1` for local and offline `FakeRedis` backends without authorizing activation.
- Added 5 focused tests; all passed. Strict mypy and receipt validation also passed.
- Receipt: [implementation-receipt.json](/home/kestl/github/palimnex/artifacts/ontology/phase-3-promotion/receipts/ontology-influence-promotion.implementation-receipt.json).

Open risks: Redis cache validation was unavailable (`cache_consulted: false`); no real approved registry exists yet; full suite, standard gate, reindex, and evaluation remain delegated to the coordinator. No Git writes or out-of-scope edits were made.