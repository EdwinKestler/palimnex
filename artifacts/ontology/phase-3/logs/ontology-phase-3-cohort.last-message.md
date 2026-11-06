Implemented `palimnex:ontology-shadow-cohort:v1` in [ontology-shadow.v1.json](/home/kestl/github/palimnex/palimnex/evaluation/ontology-shadow.v1.json): 12 concepts, 26 cases, and one intentional two-concept alias collision. It is evaluation-only and adds no runtime API or retrieval influence.

- Tests: 6/6 passed.
- Receipt validation: passed.
- Receipt: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3/receipts/ontology-phase-3-cohort.implementation-receipt.json)
- Deviations: none.
- Open risks: coordinator full-suite/standard-gate validation remains; source edits may stale line bindings; end-to-end behavior depends on retrieval/evaluation lane integration.
- Indexed files changed: yes—the new test is indexable, so the coordinator should reindex/evaluate after integration. `cache_consulted: false`.