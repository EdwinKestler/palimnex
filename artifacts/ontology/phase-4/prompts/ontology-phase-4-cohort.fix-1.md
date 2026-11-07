You are the bounded implementer for Palimnex ontology workstream `ontology-phase-4-cohort`, Phase 4, fix round 1.
You write only inside your task card's owned_paths. The same rules apply as before: read AGENTS.md,
.agents/skills/palimnex-ontology-workstream/SKILL.md, artifacts/ontology/phase-4/tasks/ontology-phase-4-cohort.json,
artifacts/ontology/phase-4/briefs/COMMON.md, artifacts/ontology/phase-4/briefs/SEMANTIC_SPEC.md (now v1.1: read
amendments A1 and A2) and artifacts/ontology/phase-4/briefs/ontology-phase-4-cohort.md.

The cohort is still blind: do NOT run retrieval, evaluation, embedding, core.embedding or any palimnex command.

The independent review (artifacts/ontology/phase-4/round-1/reviews/ontology-phase-4-cohort.review-receipt.json) rejected
the cohort before freeze. Fix exactly these and nothing else in the labels:
1. MAJOR paraphrase-active-reader copies cache_v3.py vocabulary ("generation", "active reader"). Rewrite the query.
2. MAJOR paraphrase-portable-rescan copies portable.py "variable payload". Rewrite the query.
3. MAJOR synonym-tamper-evident-record copies integrity.py "external trust anchor". Rewrite the query.
4. MAJOR synonym-secret-detector copies security.py "the matched value". Rewrite the query.
5. A1: rename canary_rule `openai-key` to `openai-token` in the cohort, the schema enum and the tests.
6. MINOR / A2: add a structural test that, for every paraphrase and synonym case, the query shares no
   identifier-shaped token (contains `_` or an internal capital) and no run of three consecutive lowercase words
   (after tokenizing on [A-Za-z0-9_]+) with the expected file's text. Then re-check ALL paraphrase and synonym queries
   by reading the expected files, and rewrite any other query that copies a distinctive two-word phrase from that
   file's docstrings, error messages or names. Keep each case's id, category, expected and forbidden paths, critical
   flag and intent unchanged; change only query text (and the note if needed).

Then rerun your acceptance commands, update your implementation receipt (list every rewritten case id in
unresolved_risks or compatibility notes as appropriate), validate it, run git status, and print a short summary listing
each changed case id with its old and new query.
