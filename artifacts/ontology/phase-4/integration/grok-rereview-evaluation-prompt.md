You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 4, focused RE-REVIEW of one workstream,
`ontology-phase-4-evaluation`, under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented
none of it. Do not modify, create or delete any repository file; scratch work under /tmp only. No network, no Git writes,
no palimnex commands. Never read .env*, .palimnex/, secrets/, benchmark/. Do NOT run the real-repository evaluation (the
coordinator runs the official one); synthetic /tmp probes are fine.

Context: your review (artifacts/ontology/phase-4/reviews/ontology-phase-4-evaluation.review-receipt.json) accepted the
lane with three MINOR findings. The lane ran fix round 1 (prompt
artifacts/ontology/phase-4/prompts/ontology-phase-4-evaluation.fix-1.md, log
artifacts/ontology/phase-4/logs/ontology-phase-4-evaluation.fix-1.log). Contract: artifacts/ontology/phase-4/briefs/
SEMANTIC_SPEC.md v1.1 section 4 and the owner's thresholds in docs/ONTOLOGY_ADOPTION.md ("Phase 4 thresholds").

Check:
1. Each round-1 MINOR: RESOLVED or NOT RESOLVED, with evidence. The 1e-12 tolerance must remain only on cohort_gain;
   protected recall, per-suite negative abstention and latency must be exact. The whole-report canonical JSON canary
   check must exist and turn privacy_canary false and status held on a leak; describe exactly what the new "redaction"
   does and confirm it cannot hide a leak from the gate or turn a held report into a promotable one.
2. No regression: PROMOTION_POLICY values, gate set and meanings, COHORT_SHA256 (artifacts/ontology/phase-4/integration/
   cohort-freeze.json), R15 protocol, report schema and authority fields unchanged; promotable only if every gate holds.
3. Run ./.venv/bin/python -m unittest palimnex.tests.test_semantic_eval -v, strict mypy on palimnex/semantic_eval.py, and
   the receipt validator:
   ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/ontology-phase-4-evaluation.json --implementation-receipt artifacts/ontology/phase-4/receipts/ontology-phase-4-evaluation.implementation-receipt.json
4. At least 3 adversarial probes of the fixed behaviour under /tmp.

Output: concise summary with the finding dispositions, then ONE fenced ```json block containing a JSON ARRAY with exactly
ONE review receipt matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy
design_identity from the task card and task_digest/approval_evidence_digest from
artifacts/ontology/phase-4/integration/bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR, NOTE or
RESOLVED. Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
