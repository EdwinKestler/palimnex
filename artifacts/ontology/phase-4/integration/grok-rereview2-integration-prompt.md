You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 4, second focused RE-REVIEW of
`ontology-phase-4-integration` under `.agents/skills/palimnex-ontology-review/SKILL.md`. Do not modify, create or delete
any repository file; scratch work under /tmp only. No network, no Git writes, no palimnex commands that write. Never read
.env*, .palimnex/, secrets/, benchmark/.

Your round-4 review (artifacts/ontology/phase-4/round-4/ontology-phase-4-integration.review-receipt.json) resolved every
round-3 finding and raised, against the handoff and receipt records only:
- MAJOR: PHASE4_HANDOFF.md pointed to a non-existent integration review receipt;
- MAJOR: PHASE4_HANDOFF.md said all Phase 4 files are untracked, but four tracked files are modified;
- MINOR: the handoff described the cohort round-1 findings as four paraphrase queries (two were synonym queries);
- MINOR: the receipt asserted the content of an unsaved audit window without a file.
The coordinator revised artifacts/ontology/phase-4/integration/PHASE4_HANDOFF.md, saved the recovered printout of the
unsaved window in artifacts/ontology/phase-4/integration/ownership-audit.wave1-review.recovered.json (copied from the
device's Desktop Commander tool history) and regenerated the integration receipt
artifacts/ontology/phase-4/receipts/ontology-phase-4-integration.implementation-receipt.json. No product file changed.

Check:
1. Each round-4 finding: RESOLVED or NOT RESOLVED, with evidence. For the recovered audit, check that the receipt claims
   only what the recovered printout shows (you may read ~/.claude-server-commander/tool-history.jsonl read-only to
   confirm the copy is faithful; do not print unrelated entries).
2. Re-read the whole handoff and receipt: every claim supported by a file and matching it exactly; nothing overstated
   (for example about approvals the owner has not given).
3. Product files unchanged since round 4 (`git diff --stat`, file hashes).
4. Run the receipt validator:
   ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/ontology-phase-4-integration.json --implementation-receipt artifacts/ontology/phase-4/receipts/ontology-phase-4-integration.implementation-receipt.json

Output: concise summary with the finding dispositions, then ONE fenced ```json block containing a JSON ARRAY with exactly
ONE review receipt matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy
design_identity from the task card and task_digest/approval_evidence_digest from
artifacts/ontology/phase-4/integration/bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR, NOTE or
RESOLVED. Status: rejected for any BLOCKER; accepted only if no MAJOR remains; accepted_with_limits if only limits remain.
