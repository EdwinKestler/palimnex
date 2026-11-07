Implemented Phase 4 semantic evaluation within owned paths only.

- Public API: `evaluate_semantic_shadow`, `SemanticEvaluationError`, fixed promotion policy, pinned cohort, and R15 benchmark protocol in [semantic_eval.py](/home/kestl/github/palimnex/palimnex/semantic_eval.py).
- Contract: `palimnex:semantic-shadow-evaluation:v1` schema and [documentation](/home/kestl/github/palimnex/docs/SEMANTIC_SHADOW.md).
- Tests: 14 evaluator tests and 52 regression tests passed; strict mypy passed.
- [Implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-4/receipts/ontology-phase-4-evaluation.implementation-receipt.json) validated successfully.
- No deviations, Git writes, network calls, or live-state mutations.

Open risks: real frozen-cohort quality/R15 measurement, reindexing, full suite, and standard gate remain delegated to the coordinator. Redis was unavailable, so `cache_consulted: false`.