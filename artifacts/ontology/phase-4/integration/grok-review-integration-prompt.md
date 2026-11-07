You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 4, workstream `ontology-phase-4-integration`
(the coordinator's own work), under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You did not
write it. Do not modify, create or delete any repository file; scratch work under /tmp only. No network, no Git writes,
no palimnex commands that write (index is a write; do not run it). Read-only commands such as `python3 palimnex.py
semantic-status`, `ontology-status`, `status` are allowed. Never read .env*, .palimnex/, secrets/, benchmark/.

Contract: docs/ONTOLOGY_ADOPTION.md (Phase 4 rows), artifacts/ontology/phase-4/briefs/SEMANTIC_SPEC.md v1.1, task card
artifacts/ontology/phase-4/tasks/ontology-phase-4-integration.json, digests in
artifacts/ontology/phase-4/integration/bundle-validation.json, the four accepted lane review receipts in
artifacts/ontology/phase-4/reviews/, and the integration implementation receipt
artifacts/ontology/phase-4/receipts/ontology-phase-4-integration.implementation-receipt.json.

Review:
1. palimnex/core.py (`git diff`): the evaluate-semantic-shadow subcommand is read-only, takes no options, refuses
   without .palimnex.json, prints the report, exits 0 promotable / 2 held / 1 refused; nothing else in core.py changed.
2. palimnex/tests/test_semantic_cli.py, pyproject.toml (mypy list), palimnex/CHANGELOG.md and docs/COMPATIBILITY.md
   (`git diff`): accurate, no overclaiming (held is not hidden; promotable would not be promotion; v1 semantic
   interface and its +0.05/2x rule unchanged).
3. Production identity: `git diff --stat` shows no change to palimnex/retrieval.py, semantic.py, cache_v3.py,
   experience.py, ontology_influence.py or any other existing runtime module except core.py.
4. Records: artifacts/ontology/phase-4/integration/cohort-freeze.json (digest matches the cohort file now; recorded
   after the accepted re-review and before any semantic measurement; compare file timestamps and logs),
   integration/gate.log (every step exit 0, 523 tests, standard gate passed), integration/semantic-evaluation.json
   (validate it against palimnex/schemas/semantic-shadow-evaluation.v1.schema.json; confirm status held, the held
   reasons and the numbers quoted in the integration receipt match the file exactly), ownership audits.
5. Does the integration receipt state every review limit and close each one explicitly and accurately? Any claim in it
   not supported by a file is MAJOR.
6. Run: ./.venv/bin/python -m unittest palimnex.tests.test_semantic_cli palimnex.tests.test_semantic_eval
   palimnex.tests.test_semantic_shadow palimnex.tests.test_semantic_local palimnex.tests.test_semantic_cohort -v;
   ./.venv/bin/python -m mypy; and the receipt validator:
   ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/ontology-phase-4-integration.json --implementation-receipt artifacts/ontology/phase-4/receipts/ontology-phase-4-integration.implementation-receipt.json
   Skip the full suite and palimnex_check.sh (sockets); the coordinator's gate.log covers them.

Output: concise summary, then ONE fenced ```json block containing a JSON ARRAY with exactly ONE review receipt matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the task card and
task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR or NOTE.
Status: rejected for any BLOCKER; accepted only if no MAJOR remains; accepted_with_limits if only limits remain.
