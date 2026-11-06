Implemented R12 FIX ROUND 1 within the three owned paths:

- [ontology_eval.py](/home/kestl/github/palimnex/palimnex/ontology_eval.py)
- [test_ontology_eval.py](/home/kestl/github/palimnex/palimnex/tests/test_ontology_eval.py)
- [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3/receipts/ontology-phase-3-evaluation.implementation-receipt.json)

### Real-run gates

| Gate | Value | Proving test |
|---|---:|---|
| `baseline_identical` | `true` | `test_mismatching_direct_baseline_fails_identity_gate` |
| `no_critical_regression` | `true` | `test_critical_baseline_pass_shadow_fail_is_a_critical_regression` |
| `no_case_regression` | `true` | `test_noncritical_regression_fails_only_the_all_case_regression_gate`; `test_baseline_fail_shadow_pass_is_not_a_regression` |
| `no_new_forbidden` | `true` | `test_unchanged_gates_fail_on_their_defining_conditions` |
| `abstention_not_regressed` | `true` | Same defining-condition test; `test_v26_shadow_equals_baseline` |
| `ambiguity_never_contributes` | `true` | Same defining-condition test |
| `channels_visible` | `true` | Same defining-condition test |
| `bounded` | `true` | Same defining-condition test |

Absolute critical results:

| Suite | Baseline | Shadow | Regressed IDs |
|---|---:|---:|---|
| `v27` | 4/12 | 5/12 | `[]` |
| `challenges_v26` | 0/0 | 0/0 | `[]` |
| `cohort` | 3/3 | 3/3 | `[]` |

Validation:

- 11 focused tests passed in 96.792s.
- Strict mypy passed.
- Implementation receipt validation: `valid`.
- `critical_green` was removed.
- No files outside `owned_paths` were edited.
- Full suite and standard gate remain delegated to the coordinator as required.
- Final `cache_consulted: false`; Redis was unavailable and was not started or mutated.