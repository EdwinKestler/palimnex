You are the bounded implementer for Palimnex ontology workstream `ontology-phase-4-evaluation`, Phase 4, fix round 1.
You write only inside your task card's owned_paths. Re-read AGENTS.md,
.agents/skills/palimnex-ontology-workstream/SKILL.md, artifacts/ontology/phase-4/tasks/ontology-phase-4-evaluation.json,
artifacts/ontology/phase-4/briefs/COMMON.md, artifacts/ontology/phase-4/briefs/SEMANTIC_SPEC.md (section 4) and
artifacts/ontology/phase-4/briefs/ontology-phase-4-evaluation.md.

The independent review (artifacts/ontology/phase-4/reviews/ontology-phase-4-evaluation.review-receipt.json) accepted the
lane with these MINOR deviations from the spec. Fix exactly these and nothing else:
1. The 1e-12 tolerance is authorized ONLY for the cohort_gain comparison (gate 5). Remove it from
   protected_recall_not_reduced, the per-suite negative_abstention comparison and latency_within_bound, which must be
   exact comparisons (>= / <=). Do not change any PROMOTION_POLICY value, threshold, gate meaning or the cohort.
2. Gate 11 requires that the canonical JSON of the WHOLE report never contains any canary. Implement it: after the
   report is assembled (with privacy_canary provisionally computed from the case checks), serialize it with
   durable.canonical_json and set privacy_canary to false (and recompute status/held_reasons) if any runtime canary
   string occurs in it. Keep the canaries only in memory; never put them in the report.
3. Add unit tests: one per removed tolerance showing an exact-boundary comparison (equal passes; a value worse by any
   amount, e.g. 1e-13, fails), and one where a canary leaks into the report (monkeypatch a report field) so
   privacy_canary becomes false and status is held.
Do not run the real-repository evaluation. Then rerun your acceptance commands, update and validate your implementation
receipt (record the fixes), run git status, and print a short summary.
