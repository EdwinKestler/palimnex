Implemented Phase 4 evaluation fix round 1 within owned paths only.

- Removed unauthorized tolerances; `1e-12` remains only for `cohort_gain`.
- Added whole-report canonical canary detection, held-status recomputation, and redaction.
- Added exact-boundary and report-leak tests in [test_semantic_eval.py](/home/kestl/github/palimnex/palimnex/tests/test_semantic_eval.py:416).
- Updated and validated the [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-4/receipts/ontology-phase-4-evaluation.implementation-receipt.json:45).

Acceptance results:

- Evaluator tests: 17 passed.
- Strict mypy: passed.
- Dependent suites: 52 passed.
- Receipt validation: valid.
- Secret-pattern scan: zero findings.
- Real-repository evaluation: not run, as required.

No policy values, thresholds, cohort, schema, or documentation changed. Git status remains dirty with pre-existing/parallel work; all five lane-owned files are untracked, and no Git writes were performed. Redis was sandbox-blocked, so `cache_consulted: false`.