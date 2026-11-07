# Ontology retrieval influence — handoff (v1.0 · 2026-11-06)

Status: **implemented, tested and independently reviewed; R13 confirmed by the
owner on 2026-11-06. Not activated, not committed, not pushed.** Approval:
`artifacts/ontology/phase-3-promotion/approval-evidence.json`.

## Delivered

| Path | What |
| --- | --- |
| `palimnex/ontology_influence.py` | Setting parser (`off`, `shadow`, `enabled`; missing means off), fail-closed activation (approved, project-matching, unambiguous, current registry bound by digest; evidence bound by digest, implementation digest, `promotable`, local and cache backends), evidence validator, disclosure, context v2 and explain-search v2 wrappers |
| `palimnex/retrieval.py`, `palimnex/experience.py` | `retrieve_sources(influence=...)`: off and shadow byte-identical; enabled fuses the ontology channel and discloses it; context returns v2 only when influenced; Phase 3 evaluation pinned to the uninfluenced baseline |
| `palimnex/ontology_promotion.py`, `palimnex evaluate-ontology-promotion` | Baseline versus influenced evidence over local and offline-cache backends; exit 0 promotable, 2 held, 1 error; never activates or writes |
| `palimnex ontology-status` | Reports the setting and whether `enabled` would activate (0 ready or off, 2 refused, 1 malformed) |
| Schemas | `project-memory:context:v2`, `palimnex:explain-search:v2`, `palimnex:ontology-promotion-evidence:v1` |
| `docs/ONTOLOGY_INFLUENCE.md` | Activation, refusals, v2 results, rollback |

## How the owner activates it later

1. Commit a reviewed `ontology/concept-registry.v1.json`.
2. Run `palimnex evaluate-ontology-promotion` and save its output as a file in
   the repository.
3. Set `.palimnex.json` `ontology_influence` to
   `{"mode": "enabled", "registry_digest": ..., "promotion_evidence": ...,
   "promotion_evidence_digest": ...}`.
4. Run `palimnex ontology-status` (expect `ready`).

Rollback is `{"mode": "off"}`. Any later change to `concepts.py`,
`ontology_shadow.py`, `ontology_influence.py` or `retrieval.py` invalidates the
evidence by design.

## Evidence

- Full suite: 454 tests OK. Strict mypy: 18 files clean. Standard gate passed.
  Index fresh and deep-validated. Ledger integrity ok with 0 events. Redis
  stopped.
- Off identity: `retrieve_sources` and `assemble_context` byte-identical to the
  committed code on 80 inputs (coordinator), and independently by the reviewer.
- Production sentinel: `palimnex evaluate` passes every critical case, Recall@5
  1.0, MRR 0.8917. MRR was 0.9; `authorized-erasure` moved from rank 2 to 3
  because the new `test_ontology_promotion.py` ranks first (corpus drift).
  Cache `search` code is unchanged.
- Phase 3 shadow gates are all still true (cohort SHA-256 now `07b5f066…`, R13).
- Defects the coordinator's gate caught and fixed: a local named `status` in
  `core.main` shadowed the `status()` function and broke `palimnex status`
  (now `status_report`); the cohort `rrf_fusion` binding drifted after the
  retrieval refactor (rebound per R13).
- Independent review (Grok 4.6 xhigh). Gate, schemas, retrieval and promotion
  are **accepted** (0 blockers, 0 majors, 0 minors). Integration was
  **accepted_with_limits** after a focused re-review that marked the round-1
  minor (COMPATIBILITY wording) and the `status` fix RESOLVED and judged R13
  faithful. Its limits, and how each was closed:
  1. Socket-backed commands were not run by the reviewer: the coordinator ran
     them unsandboxed and they passed (`integration/gate-final.log`).
  2. No integration receipt existed when reviewed: it is now written and
     validated against the R13 task card.
  3. The reviewer saw a stale index caused by the final doc fix: it was
     re-indexed and deep-validated afterwards
     (`integration/gate-final-reindex.log`).
- The recorded implementation-wave ownership checks were clean. A later audit
  against the pre-rereview snapshot reports two coordination-record deltas
  outside implementation ownership: the post-fix integration review receipt
  and the coordinator's one-shot integration-receipt helper. Neither is a
  product/source edit by an implementation lane. No implementation agent wrote
  outside its assigned paths, and no reviewer changed product/source files.

## For the owner

1. **R13 confirmed 2026-11-06** (`integration/clarification-R13.md`): cohort
   line ranges are maintained when the same bound code moves; the question,
   expected answer, labels and other frozen semantics never change.
2. **Commit** before Phase 4 starts. Phase 4 also edits `retrieval.py`, and
   committing first keeps the two changes in separate diffs.
3. Phase 4 is approved and ready to start.
