# Ontology Phase 3 — handoff (v1.0 · 2026-11-06)

Status: **implemented and tested; independent review complete; R12 confirmed by
the owner on 2026-11-06. Nothing is committed or pushed. Promotion to retrieval
influence is NOT authorized.**
Approval: `artifacts/ontology/phase-3/approval-evidence.json`.

## Delivered

| Path | What |
| --- | --- |
| `palimnex/ontology_shadow.py` | Ontology channel (chunks overlapping verified bindings of approved, unambiguous concepts), the `palimnex:ontology-shadow-comparison:v1` builder and validator |
| `palimnex/retrieval.py` | `retrieve_sources` refactored with byte-identical output; `shadow_retrieve` returns the unchanged baseline plus a comparison |
| `palimnex/ontology_eval.py`, `palimnex evaluate-ontology-shadow` | Baseline-versus-shadow evaluation over v27, the v26 challenges and the cohort; exit 0 when every gate holds, 2 when any fails, 1 on error |
| `palimnex/evaluation/ontology-shadow.v1.json` | Frozen evaluation-only cohort: 12 concepts, 26 cases, SHA-256 `f71f3fb923c4f9d8084ffc2ae5c450049f692a5ad93e305afedc5a040b2b435c`; excluded from the index |
| `palimnex/schemas/ontology-shadow-comparison.v1.schema.json`, `docs/ONTOLOGY_SHADOW.md` | Public contract and reader docs |

## Evidence

- Full suite: 411 tests OK. Strict mypy: 16 files clean. Standard gate passed.
  Ledger integrity ok with 0 events. Redis restored to stopped.
- Production retrieval unchanged: `palimnex evaluate` Recall@5 1.0, MRR 0.9,
  every critical case passes. The coordinator compared the committed and the
  refactored `retrieve_sources` on 40 inputs: all identical. The reviewer
  repeated the comparison independently with its own inputs.
- Shadow evaluation: all eight gates true (`baseline_identical`,
  `no_critical_regression`, `no_case_regression`, `no_new_forbidden`,
  `abstention_not_regressed`, `ambiguity_never_contributes`,
  `channels_visible`, `bounded`); `regressed_case_ids` empty in every suite.

| Suite | Baseline | Shadow |
| --- | --- | --- |
| v27 (13 search cases) | 5 pass, MRR 0.27, critical 4/12 | 6 pass, MRR 0.38, critical 5/12 |
| Cohort (26) | 3 pass, MRR 0.10 | 7 pass, MRR 0.27 |
| v26 challenges (6) | identical | identical |

- Independent review (Grok 4.6 xhigh). Round 1: 0 blockers, 0 majors, 1 minor
  (comparison validator lacked the 3-128 concept-ID length bound), fixed and
  re-checked as RESOLVED. **Final reviewer statuses:** channel, cohort,
  retrieval and evaluation `accepted`; integration `accepted_with_limits`.
  The integration limits and how each was closed:
  1. Socket-backed commands not run by the reviewer: the coordinator ran the
     full suite, `palimnex_check.sh`, index, `palimnex evaluate` and
     `ledger-status` unsandboxed, and all passed (`integration/gate-final.log`).
  2. No integration receipt existed when reviewed: now written and validated
     (`receipts/ontology-phase-3-integration.implementation-receipt.json`).
  3. Cache-backed `palimnex evaluate` not re-run by the reviewer: re-run by the
     coordinator; every critical case passes.
- The recorded implementation-wave ownership checks were clean. A later audit
  against the pre-rereview snapshot correctly reports two coordination-record
  deltas outside implementation ownership: the post-fix channel review receipt
  and the coordinator's one-shot integration-receipt helper. Neither is a
  product/source edit by an implementation lane. No implementation agent wrote
  outside its assigned paths, no reviewer changed product/source files, and
  there were no sandbox escapes.

## For the owner

1. **R12 confirmed 2026-11-06** (`integration/clarification-R12.md`): "critical cases remain green"
   means production retrieval stays byte-identical and the shadow causes no
   critical regression. The original `critical_green` (every critical case
   passes under the shadow) was unattainable because the baseline
   `retrieve_sources` itself passes only 4/12 critical v27 cases; v27 is
   calibrated for the cache `search`. The reviewer judged R12 faithful, and the
   owner confirmed it for the Phase 3 exit gate.
2. **Observation:** `retrieve_sources` never abstains on the real repository,
   even for unrelated queries; abstention evidence comes from the v26
   negatives.
3. **Promotion is not requested or authorized.** Moving any concept influence
   into returned rankings needs a separate approval, a new versioned behavior,
   and evidence on a real approved registry. This phase used only the
   evaluation-only cohort.
4. **Not committed.** Phase 4 (local semantic experiment) needs its own approval.
