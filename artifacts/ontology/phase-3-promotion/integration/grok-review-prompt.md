You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology RETRIEVAL INFLUENCE (the owner-approved move from
shadow to influence) under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented none of it,
including the coordinator's integration work, which you also review. Do not modify, create or delete any repository
file; scratch work under /tmp (you may build temporary checkouts there with their own .palimnex.json, registry and
evidence). No network, no Git writes, no palimnex commands that write. Read-only commands such as `python3 palimnex.py
ontology-status`, `explain-search`, `evaluate-ontology-shadow` and `evaluate-ontology-promotion` are allowed. Never read
.env*, .palimnex/, secrets/, benchmark/.

Authority and contract:
- Approved design: docs/ONTOLOGY_ADOPTION.md (scope paragraph; accepted-decision rows "Influence activation",
  "Influence surfaces"). The owner's exact requirements are recorded there: opt-in off|shadow|enabled, missing means off;
  enabled binds registry digest and promotion evidence; missing, corrupt, stale, ambiguous or privacy-refused registry
  data is an explicit error, never a silent fallback; influenced results use new versioned contracts and never silently
  change context v1; only retrieve_sources and its direct consumers change; cache search, symbols, impact and palimnex
  evaluate unchanged; promotion tested on local and cache backends; registry presence is data, not authority.
- Coordinator spec: artifacts/ontology/phase-3-promotion/briefs/INFLUENCE_SPEC.md.
- Approval, manifest, tasks: artifacts/ontology/phase-3-promotion/{approval-evidence.json,manifest.json,tasks/};
  digests artifacts/ontology/phase-3-promotion/integration/bundle-validation.json; receipts .../receipts/.

Under review (five workstreams):
1. ontology-influence-gate: palimnex/ontology_influence.py, its test, docs/ONTOLOGY_INFLUENCE.md
2. ontology-influence-schemas: palimnex/schemas/{context.v2,explain-search.v2,ontology-promotion-evidence.v1}.schema.json,
   palimnex/tests/test_influence_schemas.py, palimnex/tests/fixtures/ontology_influence/
3. ontology-influence-retrieval: palimnex/retrieval.py, palimnex/experience.py, palimnex/ontology_eval.py and tests
4. ontology-influence-promotion: palimnex/ontology_promotion.py and its test
5. ontology-influence-integration (coordinator): explain_search v2, ontology_status, the two new subcommands in
   palimnex/core.py, palimnex/tests/test_ontology_influence_cli.py, pyproject.toml, CHANGELOG, COMPATIBILITY,
   docs/CONCEPT_REGISTRY.md (use `git diff` for tracked files)

For each: run its focused tests (skip the full suite and palimnex_check.sh, which need sockets) and, for lanes 1-4, the
receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-3-promotion/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-3-promotion/receipts/<ws>.implementation-receipt.json
Probe adversarially under /tmp (at least 3 per workstream). Priorities:
- OFF IDENTITY (any difference is a BLOCKER): compare committed code (`git archive HEAD palimnex | tar -x -C /tmp/x`, import
  via PYTHONPATH) and the working tree for retrieve_sources and assemble_context (no ledger) on your own queries and
  settings, with the influence key absent, `off` and `shadow`. Also confirm explain-search stays v1 and that search,
  symbols, impact and evaluate code paths are untouched (`git diff --stat`, grep).
- NO SILENT FALLBACK (a fallback is a BLOCKER): in a temp checkout with mode enabled, each failure must raise from
  retrieve_sources, context and explain-search: missing registry; wrong registry digest; candidate registry; foreign
  project; alias collision (including a canonical-name collision); stale binding; missing evidence; tampered evidence;
  evidence for another registry; held evidence; evidence missing the cache backend; evidence from different code (edit a
  copy of a module); malformed setting; a privacy canary in the registry or evidence (no echo).
- HAPPY PATH: build a real promotable evidence with evaluate_ontology_promotion in a temp checkout, activate it, and confirm
  rankings change only via the ontology channel, the disclosure is present and exact, context is v2 with every v1 key,
  explain-search is v2, and both validate against their public schemas. Rollback with mode off restores identity.
- PROMOTION: local and cache (offline FakeRedis) both evaluated; gates computed from data; status promotable only when all
  gates on both backends hold; activation_authorized always false; deterministic; nothing written; never touches real
  Redis.
- Registry presence alone (with no setting) changes nothing.
- CLI exit codes for ontology-status (0, 2, 1) and evaluate-ontology-promotion (0, 2, 1).

Output: concise summary, then ONE fenced ```json block with exactly FIVE review receipts matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the task card and
task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR or NOTE.
Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
