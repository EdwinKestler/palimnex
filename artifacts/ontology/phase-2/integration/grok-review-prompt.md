You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 2 (deterministic coverage receipt and
`explain-search`) under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented none of
it, and that includes the coordinator's integration work, which you also review. Do not modify, create or delete any
repository file; scratch work goes under /tmp. No network, no Git writes, no palimnex commands that write (running
`python3 palimnex.py explain-search ...` is read-only and allowed). Never read .env*, .palimnex/, secrets/, benchmark/.

Authority and contract inputs:
- Approved design: docs/ONTOLOGY_ADOPTION.md ("Phase 2", invariants, "Accepted Phase 0 decisions" including the
  registry location and explain-search output decisions). Phase 1 exit gate: artifacts/ontology/phase-1/exit-gate.json.
- Accepted coverage contract: artifacts/design/ontology-phase-0/coverage/ (schema, SEMANTICS.md, examples).
- Coordinator spec and clarifications: artifacts/ontology/phase-2/briefs/EXPLAIN_SEARCH_SPEC.md,
  artifacts/ontology/phase-2/integration/clarification-R10.md (explain-search embeds retrieve_sources) and
  clarification-R11.md (query length; corrects R9; amends the integration lane to own palimnex/concepts.py).
  Judge whether R10 and R11 are faithful to the accepted contract and owner decisions, or unauthorized changes.
- Approval, manifest, tasks: artifacts/ontology/phase-2/{approval-evidence.json,manifest.json,tasks/}.
  Digests: artifacts/ontology/phase-2/integration/bundle-validation.r11.json. Receipts: artifacts/ontology/phase-2/receipts/.

Under review (four workstreams):
1. ontology-phase-2-coverage-core: palimnex/coverage.py, palimnex/tests/test_coverage.py
2. ontology-phase-2-coverage-schema: palimnex/schemas/retrieval-coverage.v1.schema.json,
   palimnex/schemas/explain-search.v1.schema.json, palimnex/tests/test_retrieval_coverage_schema.py,
   palimnex/tests/fixtures/retrieval_coverage/, docs/COVERAGE_RECEIPT.md
3. ontology-phase-2-frozen-conformance: palimnex/tests/test_coverage_frozen.py
4. ontology-phase-2-integration (coordinator): the explain-search parts of palimnex/core.py
   (concept_registry_selection, explain_search, the subparser and dispatch), palimnex/tests/test_explain_search.py,
   the R11 change in palimnex/concepts.py (normalize_query, match_aliases) and its new test in
   palimnex/tests/test_concepts.py, docs/CONCEPT_REGISTRY.md, palimnex/CHANGELOG.md, docs/COMPATIBILITY.md,
   pyproject.toml. Use `git diff` for the tracked files.

For each workstream:
- Run its focused tests (task card acceptance commands; skip the full suite and palimnex_check.sh, which need sockets)
  and, for lanes 1-3, the receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-2/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-2/receipts/<ws>.implementation-receipt.json
- Contract fidelity against coverage SEMANTICS.md: status decision table and ambiguity precedence; R = C+U+S+A with
  integer coverage; disjointness; stale-reason mapping (is aggregating mixed stale reasons to `unavailable` faithful?);
  R7 typed refusals produce no receipt; query digest policy vectors; ordering; canonical receipt digest; bounds and
  truncation; semantic disclosure; nothing raw persisted; retrieval truncation versus byte-budget omission (assess the
  heuristic `byte_omitted = omitted > 0 and used >= budget` against palimnex/retrieval.py budget_items and limit).
- Adversarial probes (at least 3 per workstream), scripted under /tmp against the real modules and CLI. Ideas: a
  receipt with an ambiguous concept also covered passing validate_receipt; status inconsistent with counts; tampered
  digest; float coverage; 0/0; a registry whose project differs from the checkout; a candidate_set registry; a
  symlinked or traversal registry path or binding; a query over 8 KiB; a 1,000-character query that should match; a
  secret canary in the query (no echo in errors or output); search_result mutation; `--registry` absolute, `..`,
  backslash; a missing explicit registry vs an absent default; explain-search output vs the explain-search schema.
- Authority: no change to `search` output, context v1, cache, ledger, MCP or config; no ranking influence; no approved
  registry created; nothing imports palimnex.coverage outside core.py's explain_search and tests (grep).
- Frozen conformance: all 12 gates_phase 2 cases run without label changes (fixture sha256
  a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b); materialization changes only placeholders,
  digests and synthetic inputs; no skips or expected failures hide failures.

Output: a concise human summary, then ONE fenced ```json block with a JSON array of exactly FOUR review receipts
matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the
task card and task_digest/approval_evidence_digest from bundle-validation.r11.json. Prefix each evidence item with
BLOCKER, MAJOR, MINOR or NOTE. Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
