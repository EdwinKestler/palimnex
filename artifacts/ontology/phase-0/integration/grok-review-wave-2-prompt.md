You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology Phase 0, RECONCILIATION WAVE 2
(skill: `.agents/skills/palimnex-ontology-review/SKILL.md`; read it first). You implemented none of this.
Do not modify, create or delete any file inside the repository. Scratch copies under /tmp are fine.
No network, no Git writes, no palimnex commands that write. Never read .env*, .palimnex/, secrets/ or benchmark/.

Context:
- Your wave-1 review receipts: artifacts/ontology/phase-0/wave-1/reviews/*.review-receipt.json
- Coordinator decisions that wave 2 had to implement:
  artifacts/ontology/phase-0/integration/reconciliation-decisions.v1.md (R1-R7; R8 is deferred)
- Wave-1 drafts for diffing: artifacts/ontology/phase-0/wave-1/drafts/
- Current (wave-2) drafts: artifacts/design/ontology-phase-0/{registry,coverage,threat-model,frozen-cases}
- Reissued task cards: artifacts/ontology/phase-0/tasks/; receipts: artifacts/ontology/phase-0/receipts/
- Task and approval digests: artifacts/ontology/phase-0/integration/bundle-validation.wave-2.json
- Ownership audit: artifacts/ontology/phase-0/integration/ownership-audit.wave-2.json

For each lane (registry-contract, coverage-contract, threat-cases):
1. Re-run its check script and the contract validator with its receipt:
   ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-0/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-0/receipts/<ws>.implementation-receipt.json
2. For every MAJOR and MINOR finding in your wave-1 receipt for that lane, state RESOLVED,
   PARTIALLY RESOLVED or UNRESOLVED, with file evidence.
3. Verify that each applicable decision R1-R7 is implemented as written, not reinterpreted.
4. Repeat your wave-1 adversarial probes (including the digest-only locator probe against
   check_cases.py) and add at least one new probe per lane against the wave-2 changes
   (for example a doubled separator in a concept ID, a stale concept also listed as covered,
   an ambiguous concept also listed as covered, a fixture with `lifecycle_status`).
5. Look for any NEW cross-lane inconsistency the reconciliation introduced.

Output: a concise human summary, then ONE fenced ```json block with a JSON array of exactly
three review receipts matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json.
Copy `design_identity` from the task card and `task_digest`/`approval_evidence_digest` from
bundle-validation.wave-2.json. Prefix each `evidence` item with BLOCKER, MAJOR, MINOR, NOTE,
RESOLVED or UNRESOLVED. Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
