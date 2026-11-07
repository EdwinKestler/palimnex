You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 4, focused RE-REVIEW of
`ontology-phase-4-integration` under `.agents/skills/palimnex-ontology-review/SKILL.md`. Do not modify, create or delete
any repository file; scratch work under /tmp only. No network, no Git writes, no palimnex commands that write. Never read
.env*, .palimnex/, secrets/, benchmark/.

Your previous review (artifacts/ontology/phase-4/round-3/ontology-phase-4-integration.review-receipt.json) rejected the
integration receipt with two MAJOR and one MINOR finding. The coordinator changed only records, not product code:
- the receipt now reports each saved ownership audit with its true exit code and the exact unowned paths, and the
  receipt writer (artifacts/ontology/phase-4/tools/write_integration_receipt.py) refuses if any violation lies outside
  the coordinator-record prefixes; one audit window that was printed but not saved is disclosed;
- the reviewer launch commands are recorded in artifacts/ontology/phase-4/integration/reviewer-launch.md (copied from
  the device's tool history) and the write-restriction statement now cites it;
- the accepted provider limit (generator, nested and ragged vector refusals probed only under /tmp) is now listed among
  the closed review limits.
A new audit window covering your previous review is saved as integration/ownership-audit.integration-review.json.
The integration handoff draft is artifacts/ontology/phase-4/integration/PHASE4_HANDOFF.md.

Check:
1. Each round-3 finding: RESOLVED or NOT RESOLVED, with evidence from files.
2. Every claim in the integration receipt and in PHASE4_HANDOFF.md is supported by a repository file and matches it
   exactly (numbers from integration/semantic-evaluation.json and integration/gate.log; statuses from reviews/ and
   round-*/). Any unsupported or overstated claim is MAJOR.
3. Product files are unchanged since your previous review (compare with your round-3 notes; `git diff --stat`).
4. Run the receipt validator:
   ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/ontology-phase-4-integration.json --implementation-receipt artifacts/ontology/phase-4/receipts/ontology-phase-4-integration.implementation-receipt.json

Output: concise summary with the finding dispositions, then ONE fenced ```json block containing a JSON ARRAY with exactly
ONE review receipt matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy
design_identity from the task card and task_digest/approval_evidence_digest from
artifacts/ontology/phase-4/integration/bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR, NOTE or
RESOLVED. Status: rejected for any BLOCKER; accepted only if no MAJOR remains; accepted_with_limits if only limits remain.
