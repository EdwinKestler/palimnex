You are the INDEPENDENT, READ-ONLY reviewer for the Palimnex ontology adoption CLOSURE, workstream
`ontology-closure-integration` (the coordinator's own work), under `.agents/skills/palimnex-ontology-review/SKILL.md`.
Do not modify, create or delete any repository file; scratch work under /tmp only. No network, no Git writes, no
palimnex commands that write (index, ledger, feedback, redis are writes; do not run them). Read-only commands such as
`python3 palimnex.py ontology-status`, `explain-search` and `evaluate-ontology-promotion` (slow, about ten minutes) are
allowed. Never read .env*, .palimnex/, secrets/, benchmark/. A release-check script may be running under /tmp; ignore it.

The registry is now frozen, so the evaluation sets are no longer blind; you may read them.

Contract: docs/ONTOLOGY_ADOPTION.md (status paragraph; rows "Approved registry v1 scope", "Registry approval path",
"Release candidate"), docs/CONCEPT_REGISTRY.md, the task card artifacts/ontology/closure/tasks/ontology-closure-integration.json,
digests artifacts/ontology/closure/integration/bundle-validation.json, receipt
artifacts/ontology/closure/receipts/ontology-closure-integration.implementation-receipt.json.

Review:
1. ontology/concept-registry.v1.json against the reviewed candidate (artifacts/ontology/closure/candidate/
   concept-registry.candidate.json, review artifacts/ontology/closure/reviews/ontology-closure-registry.review-receipt.json):
   only registry_kind, concept status and registry_digest differ (diff the two documents); it loads as an approved
   registry for this project, unambiguous, all bindings current; artifacts/ontology/closure/integration/registry-freeze.json
   is accurate. tools/approve_registry.py does what it claims.
2. Promotion evidence artifacts/ontology/closure/integration/promotion-evidence.json: valid against
   palimnex/schemas/ontology-promotion-evidence.v1.schema.json and palimnex.ontology_influence.validate_promotion_evidence;
   bound to the approved registry digest and the current implementation digest; status promotable; activation_authorized
   false. Optionally reproduce it read-only.
3. Activation is off: .palimnex.json unchanged (`git diff`), ontology-status reports mode off.
4. Coordinator changes outside the lane: palimnex/CHANGELOG.md registry bullet; docs/CONCEPT_REGISTRY.md and
   docs/ONTOLOGY_ADOPTION.md closure text (accurate, not overclaiming: the registry becomes approved on the owner's merge;
   adoption complete only then); R18 (artifacts/release/2.10.0/evidence/R18-fixture-repin.md and .json: only binding
   versions and fixture registry digests changed in palimnex/tests/fixtures/concept_registry/valid/, every selected-range
   digest unchanged); palimnex/tests/test_ontology_promotion.py (the real-checkout missing-registry refusal now uses an
   explicit absent path; is the test intent preserved?); the skipped test test_explain_search.test_cli_on_repository_without_registry
   (pre-existing conditional skip).
5. Production identity: retrieval.py, durable.py, semantic.py, cache_v3.py, ontology_influence.py, ontology_shadow.py,
   concepts.py and experience.py unchanged against HEAD.
6. Records: integration/gate.log every step exit 0; every receipt claim supported by a file and matching exactly.
Run: ./.venv/bin/python -m unittest palimnex.tests.test_concept_registry_schema palimnex.tests.test_concepts
palimnex.tests.test_ontology_promotion palimnex.tests.test_explain_search palimnex.tests.test_ontology_influence -v;
./.venv/bin/python artifacts/ontology/closure/candidate/check_candidate.py; and the receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/closure/tasks/ontology-closure-integration.json --implementation-receipt artifacts/ontology/closure/receipts/ontology-closure-integration.implementation-receipt.json
Skip the full suite and palimnex_check.sh (sockets); gate.log covers them.

Output: concise summary, then ONE fenced ```json block containing a JSON ARRAY with exactly ONE review receipt matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the task card and
task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR or NOTE.
Status: rejected for any BLOCKER; accepted only if no MAJOR remains; accepted_with_limits if only limits remain.
