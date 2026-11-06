You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology Phase 0
(skill: `.agents/skills/palimnex-ontology-review/SKILL.md`; read it first).
You did not implement any of this work. Do not modify, create or delete any file inside the
repository. You may create scratch copies under /tmp to probe check scripts adversarially.
No network, no Git writes, no palimnex commands that write (index, remember, session-*,
capture-*, retention-*, memory-*, cleanup-*, workflow-put, ledger-init). Never read .env*,
.palimnex/, secrets/ or benchmark/.

Authority and identity inputs:
- Approved design: docs/ONTOLOGY_ADOPTION.md (compare with the source proposal
  artifacts/design/Ontologyadoptionplan.md; confirm the only differences are the Phase 0
  status, scope paragraph, Semantica note, source-locator reuse, and provisional defaults).
- Approval evidence: artifacts/ontology/phase-0/approval-evidence.json
- Manifest and bundle validation: artifacts/ontology/phase-0/manifest.json,
  artifacts/ontology/phase-0/integration/bundle-validation.json (task and approval digests)
- Ownership audit: artifacts/ontology/phase-0/integration/ownership-audit.json
- Lane briefs: artifacts/ontology/phase-0/briefs/

Review these three implementation lanes, each against its task card in
artifacts/ontology/phase-0/tasks/, its brief, the approved design, and CURRENT SOURCE
(not the implementer's summary):
1. ontology-phase-0-registry-contract -> artifacts/design/ontology-phase-0/registry/
2. ontology-phase-0-coverage-contract -> artifacts/design/ontology-phase-0/coverage/
3. ontology-phase-0-threat-cases -> artifacts/design/ontology-phase-0/threat-model/ and frozen-cases/
Each lane's receipt is in artifacts/ontology/phase-0/receipts/.

For every lane:
- Re-run its check script and the contract validator with its receipt, from the repo root:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-0/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-0/receipts/<ws>.implementation-receipt.json
- Probe the check script adversarially: copy the lane folder to /tmp, break one invariant
  (for example an ambiguous concept counted as covered, a float ratio, a literal secret, a
  wrong digest, an unbounded list), and confirm the check fails. Report any check that
  passes when it should fail.
- Verify claims about existing code (palimnex/locators.py, security.py, durable.py, vcs.py,
  identity.py, semantic.py, cache_v3.py, core.py) against the source.
- Check cross-lane consistency: the status vocabulary, concept-ID pattern, locator shape and
  digest rules must agree between registry, coverage and frozen cases. Report every
  mismatch with exact file references.
- Check the authority boundaries: drafts only, no influence for candidate entries,
  ambiguity never counted as covered, coverage is not correctness, no raw query persisted,
  `authorizes_actions: false`.
- Separate confirmed defects (with severity: blocker, major, minor) from open questions.

Output: finish with ONE fenced ```json block containing a JSON array of exactly three
objects. Each is a review receipt matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json: `schema`
"palimnex:ontology-review-receipt:v1", `workstream_id`, `design_identity` (copy from the
task card), `task_digest` and `approval_evidence_digest` (copy from bundle-validation.json),
`reviewed_scope` (paths), `evidence` (findings, each prefixed with BLOCKER/MAJOR/MINOR/NOTE),
`commands` (exact commands you ran with their outcome), the six `*_result` strings,
`limitations`, `cache_and_ledger_state`, `git_state` (objects with observed facts), and
`status` (accepted | accepted_with_limits | rejected | blocked). Use `rejected` for any
BLOCKER. Before the JSON block, write a concise human-readable summary.
