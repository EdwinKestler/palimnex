You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 4 (local semantic shadow experiment), wave 1,
under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented none of it. Do not modify,
create or delete any repository file; scratch work under /tmp only. No network, no Git writes, no palimnex commands that
write. Never read .env*, .palimnex/, secrets/, benchmark/.

Authority and contract:
- Approved design: docs/ONTOLOGY_ADOPTION.md ("Phase 4 — Optional local semantic experiment", accepted-decision rows
  "Phase 4 provider" and "Phase 4 thresholds", scope paragraph).
- Coordinator spec: artifacts/ontology/phase-4/briefs/SEMANTIC_SPEC.md (sections 1 and 3 for this wave), COMMON.md and
  the lane briefs in the same directory.
- Approval, manifest, tasks: artifacts/ontology/phase-4/{approval-evidence.json,manifest.json,tasks/}; digests in
  artifacts/ontology/phase-4/integration/bundle-validation.json; receipts in artifacts/ontology/phase-4/receipts/.

Under review (two workstreams):
1. ontology-phase-4-provider: palimnex/semantic_local.py, palimnex/tests/test_semantic_local.py,
   palimnex/tests/semantic_doubles.py, palimnex/schemas/semantic-provider-identity.v1.schema.json
2. ontology-phase-4-cohort: palimnex/evaluation/semantic-shadow.v1.json,
   palimnex/schemas/semantic-shadow-cohort.v1.schema.json, palimnex/tests/test_semantic_cohort.py

For each: run its focused tests and the receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-4/receipts/<ws>.implementation-receipt.json
Probe adversarially under /tmp (at least 3 per workstream).

Provider priorities:
- embed equals core.embedding exactly; identity fields distinct (PROVIDER_ID differs from core.EMBEDDING_ID and
  cache_v3.EMBEDDING_ID); implementation_digest behavioural and sensitive to tokenizer, hashing and normalization
  changes; no caching, persistence, network, subprocess or download anywhere (grep imports).
- Every checked_embed refusal in spec order; no fallback vector; no echo of provider exception text; timeouts via the
  injected clock; bool is not a number; NaN/+Inf/-Inf; nested or ragged vectors; generators and huge inputs bounded.
- palimnex/semantic.py and project-memory:semantic-provider:v1 unchanged (`git diff --stat`).

Cohort priorities (THIS COHORT WILL BE FROZEN AFTER YOUR REVIEW; label quality is the main risk):
- Read each repository case's query and the expected file(s). Is the expected path a correct, defensible answer? Is a
  different runtime module an equally good or better answer that is missing (for ambiguity cases, are all plausible
  modules listed)? Flag each wrong or doubtful label as MAJOR with the case id and the reason.
- Paraphrase and synonym queries must not copy identifiers or distinctive phrases from the expected file; negatives must
  be clearly unrelated; controls must be direct; only controls critical (at least two).
- Category minimums, limit 5, query bounds, no duplicate of an ontology-shadow.v1.json query, unique ids.
- Drift projects: the topic genuinely moves between files; expected/forbidden paths are right. Privacy cases: one
  `{canary}` placeholder each, correct placement and rule names, at least two query rules and one corpus case.
- The raw file has no secret-shaped text (security.scan_bytes), and the tests enforce the structure.
- The cohort author was required to work blind (no retrieval, evaluation or embedding runs). Check the cohort lane log
  artifacts/ontology/phase-4/logs/ontology-phase-4-cohort.log for any such command and report what you find.
Do NOT run retrieval, embedding or evaluation on the cohort yourself either: judge labels from the source.

Output: concise summary, then ONE fenced ```json block with exactly TWO review receipts matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the task card and
task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR or NOTE.
Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
