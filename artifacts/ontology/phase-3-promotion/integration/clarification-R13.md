# R13: maintaining cohort line bindings when bound source moves (coordinator, influence promotion)

**Finding.** The unsandboxed gate failed
`test_ontology_shadow_cohort.test_bound_paths_and_line_ranges_are_current` for
`concept.rrf_fusion`. The influence retrieval lane's edit to
`palimnex/retrieval.py` moved `_fuse_rankings` from lines 167-181 to 174-188.
The Phase 3 anchor test exists to catch exactly this. The cohort's digests are
placeholders materialized at evaluation time, so without the test the binding
would have silently pointed at other code.

**Decision.** Line ranges in the frozen evaluation cohort are maintained
against source movement. A rebinding may change only a binding's `range` so
that it again starts at the anchor its concept names. Labels, aliases,
concepts, cases, expected paths and placeholders never change. Every rebinding
records the new cohort SHA-256.

**This change.** `concept.rrf_fusion`: `palimnex/retrieval.py` 167-181 changed to
174-188 (the same function, 15 lines). No other binding moved (the anchor test
passes for all others). The cohort file is owned by the coordinator-owned
integration lane for this rebinding only (`bundle-validation.r13.json`); other
task cards and their receipts are unchanged.

**Forward note.** Phase 4 also edits `retrieval.py`. Its integration step must
re-run the cohort anchor test and rebind under this rule before the gate.

## Owner confirmation

The repository owner confirmed R13 on 2026-11-06 and instructed the coordinator
to commit the ontology-influence work before Phase 4 starts. This confirmation
permits maintenance of a frozen question's source line range only when the same
named implementation moved. It does not permit changing the question, concept,
aliases, expected paths, expected answer, labels, or promotion thresholds.
