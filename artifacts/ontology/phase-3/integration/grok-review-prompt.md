You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 3 (ontology-aware retrieval in SHADOW mode)
under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented none of it, including the
coordinator's integration work, which you also review. Do not modify, create or delete any repository file; scratch
work under /tmp. No network, no Git writes, no palimnex commands that write (`python3 palimnex.py
evaluate-ontology-shadow` and `explain-search` are read-only and allowed). Never read .env*, .palimnex/, secrets/,
benchmark/.

Authority and contract:
- Approved design: docs/ONTOLOGY_ADOPTION.md ("Phase 3" exit gate, invariants, accepted decisions: shadow visible only
  through evaluate-ontology-shadow; frozen evaluation-only test registry). Phase 2 exit gate:
  artifacts/ontology/phase-2/exit-gate.json.
- Coordinator spec: artifacts/ontology/phase-3/briefs/SHADOW_SPEC.md. Clarification R12 (gate meaning):
  artifacts/ontology/phase-3/integration/clarification-R12.md. Judge whether R12 is a faithful reading of the design's
  exit gate "all current critical retrieval cases remain green", or a weakening. Say which, with reasons.
- Approval, manifest, tasks: artifacts/ontology/phase-3/{approval-evidence.json,manifest.json,tasks/};
  digests artifacts/ontology/phase-3/integration/bundle-validation.json; receipts artifacts/ontology/phase-3/receipts/.

Under review (five workstreams):
1. ontology-phase-3-channel: palimnex/ontology_shadow.py, its test, palimnex/schemas/ontology-shadow-comparison.v1.schema.json, docs/ONTOLOGY_SHADOW.md
2. ontology-phase-3-cohort: palimnex/evaluation/ontology-shadow.v1.json, palimnex/tests/test_ontology_shadow_cohort.py
3. ontology-phase-3-retrieval: palimnex/retrieval.py (refactor + shadow_retrieve), palimnex/tests/test_retrieval_shadow.py
4. ontology-phase-3-evaluation: palimnex/ontology_eval.py, palimnex/tests/test_ontology_eval.py
5. ontology-phase-3-integration (coordinator): evaluate-ontology-shadow in palimnex/core.py,
   palimnex/tests/test_evaluate_ontology_shadow_cli.py, .palimnex.json, pyproject.toml, CHANGELOG, COMPATIBILITY
   (use `git diff` for tracked files).

For each workstream: run its focused tests (skip the full suite and palimnex_check.sh, which need sockets) and, for
lanes 1-4, the receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-3/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-3/receipts/<ws>.implementation-receipt.json
Then probe adversarially under /tmp (at least 3 per workstream). Priorities:
- BASELINE IDENTITY is the core safety claim. Independently compare the committed retrieve_sources
  (`git show HEAD:palimnex/retrieval.py`; extract the committed package with `git archive HEAD palimnex | tar -x -C /tmp/x`
  and import it with PYTHONPATH) against the working tree over your own queries and settings (limits, budgets,
  include_graph, empty or no-match queries, error paths). Any byte difference is a BLOCKER.
- The shadow never leaks into returned results: search, context, explain-search unchanged; nothing imports
  shadow_retrieve except ontology_eval and tests (grep); no config switch enables influence.
- Ambiguous, stale, uncovered and candidate concepts never contribute; a candidate_set registry is refused; R7
  refusals; secret in query or bound source refused with no echo.
- Fusion parity: the shadow uses the same RRF_K, tie-break, 512 cap, budget_items and limit as the baseline; channel
  ranks for all four channels visible.
- Comparison document: pointers only (no query text or excerpts); validator-versus-schema parity; tamper detection.
- Cohort: evaluation-only, never loaded by explain-search; bindings point at the code their concept names; placeholder
  materialization changes only version, digest and registry_digest; it is excluded from the index.
- Evaluation: metrics match palimnex/core.py evaluate definitions; gates computed from data; promotion_authorized always
  false; deterministic; a stale cohort binding is reported rather than crashing. Run evaluate-ontology-shadow and
  check every gate and regressed_case_ids yourself.
- CLI exit codes 0/2/1.

Output: concise summary, then ONE fenced ```json block with exactly FIVE review receipts matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the task card
and task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR or
NOTE. Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
