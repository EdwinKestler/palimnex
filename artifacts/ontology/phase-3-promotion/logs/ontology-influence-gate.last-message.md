Implemented `ontology-influence-gate` within all four owned paths.

- Added [`palimnex.ontology_influence`](/home/kestl/github/palimnex/palimnex/ontology_influence.py): setting parser, fail-closed activation, implementation digest, promotion-evidence validator, disclosure, and context/explain-search v2 wrappers.
- Added 16 focused tests; all passed.
- All 55 regression tests passed; strict mypy passed.
- Added [activation and rollback documentation](/home/kestl/github/palimnex/docs/ONTOLOGY_INFLUENCE.md).
- [Implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3-promotion/receipts/ontology-influence-gate.implementation-receipt.json) validates successfully.

Open risks: Redis was unavailable (`cache_consulted: false`); reindex/evaluation and the full standard gate remain delegated to the coordinator. Retrieval/CLI integration belongs to the other lanes. No Git or live-state writes were performed.