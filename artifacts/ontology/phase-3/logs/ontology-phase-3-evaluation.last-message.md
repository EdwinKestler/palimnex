Implemented `evaluate_ontology_shadow(root, *, limit=5)` in [ontology_eval.py](/home/kestl/github/palimnex/palimnex/ontology_eval.py:682), returning `palimnex:ontology-shadow-evaluation:v1`.

- Tests: 6/6 passed, exercising two deterministic 45-case evaluations.
- Strict mypy: passed.
- Receipt validation: passed; see [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3/receipts/ontology-phase-3-evaluation.implementation-receipt.json).
- No foreign-path, Git, network, Redis, or ledger writes.

Open risks: `critical_green` is currently false—shadow passes 5/12 critical v27 search cases versus baseline 4/12. Cohort negative abstention is 0.0 for both rankings. Redis-backed validation and the full standard gate remain delegated to the coordinator.