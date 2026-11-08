You are the INDEPENDENT, READ-ONLY reviewer for the first Palimnex concept registry, workstream
`ontology-closure-registry`, under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You drafted none
of it. Do not modify, create or delete any repository file; scratch work under /tmp only. No network, no Git writes, no
palimnex commands. Never read .env*, .palimnex/, secrets/, benchmark/.

BLIND RULE: do not open palimnex/evaluation/, palimnex/tests/test_ontology_shadow_cohort.py,
palimnex/tests/test_semantic_cohort.py, artifacts/ontology/phase-3/, artifacts/ontology/phase-3-promotion/ or
artifacts/ontology/phase-4/, and do not run evaluate-* commands, retrieval or explain-search. Those evaluation sets are
used only after this registry is frozen. Judge the registry from the source code alone.

THIS REGISTRY WILL BE FROZEN AND APPROVED AFTER YOUR REVIEW. Contract: docs/ONTOLOGY_ADOPTION.md (rows "Approved
registry v1 scope" and "Registry approval path"; safety invariants), docs/CONCEPT_REGISTRY.md,
palimnex/schemas/concept-registry.v1.schema.json, palimnex/concepts.py, and the brief
artifacts/ontology/closure/briefs/REGISTRY_BRIEF.md. Task card artifacts/ontology/closure/tasks/ontology-closure-registry.json;
digests artifacts/ontology/closure/integration/bundle-validation.json.

Under review: artifacts/ontology/closure/candidate/concept-registry.candidate.json, NOTES.md, check_candidate.py, and the
receipt artifacts/ontology/closure/receipts/ontology-closure-registry.implementation-receipt.json.

For EVERY one of the 16 concepts, read each bound range in the source and decide:
- Is the binding the authoritative implementation of the concept (right symbol, complete enough, not incidental, not a
  test or doc)? Is an essential implementation missing? A wrong or misleading binding is MAJOR.
- Is the definition accurate to what the code does? An inaccurate definition is MAJOR.
- Aliases: specific multi-word phrases a developer would type; no standalone generic word; no alias that would also
  plausibly describe a different concept in this repository (ambiguity risk even if the normalizer finds no exact
  collision); no alias that misdescribes the concept. A misleading or ambiguous alias is MAJOR; a weak one MINOR.
- Bindings are current (run check_candidate.py and, independently, palimnex.concepts verification in a /tmp copy).
Also check: registry structure and digest, candidate_set kind, model_candidate provenance, project identity matches
.palimnex.json, no secret-shaped text, the checker enforces the alias policy, and the lane log
artifacts/ontology/closure/logs/ontology-closure-registry.log shows no read of the blind paths (report what you find).
Run the receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/closure/tasks/ontology-closure-registry.json --implementation-receipt artifacts/ontology/closure/receipts/ontology-closure-registry.implementation-receipt.json

Output: a concise per-concept verdict table, then ONE fenced ```json block containing a JSON ARRAY with exactly ONE review
receipt matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from
the task card and task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR,
MINOR or NOTE and name the concept id. Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
