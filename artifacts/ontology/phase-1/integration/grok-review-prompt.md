You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 1 (reviewed concept-registry
foundation) under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented none of it.
Do not modify, create or delete any file inside the repository. Scratch work goes under /tmp; to exercise the
code, copy what you need there or import it read-only from the repo. No network, no Git writes, no palimnex
commands that write. Never read .env*, .palimnex/, secrets/ or benchmark/.

Authority and contract inputs:
- Approved design: docs/ONTOLOGY_ADOPTION.md ("Phase 1", "Safety and authority invariants",
  "Accepted Phase 0 decisions"). Phase 0 exit gate: artifacts/ontology/phase-0/exit-gate.json.
- Accepted contract: artifacts/design/ontology-phase-0/registry/ (schema, SEMANTICS.md),
  frozen-cases/, threat-model/THREAT_MODEL.md, and
  artifacts/ontology/phase-0/integration/reconciliation-decisions.v1.md (R1-R7).
- Phase 1 approval, manifest and tasks: artifacts/ontology/phase-1/{approval-evidence.json,manifest.json,tasks/}
- Digests: artifacts/ontology/phase-1/integration/bundle-validation.json
- Receipts: artifacts/ontology/phase-1/receipts/

Implementation under review (three lanes):
1. ontology-phase-1-registry-core: palimnex/concepts.py, palimnex/tests/test_concepts.py
2. ontology-phase-1-registry-schema: palimnex/schemas/concept-registry.v1.schema.json,
   palimnex/tests/test_concept_registry_schema.py, palimnex/tests/fixtures/concept_registry/, docs/CONCEPT_REGISTRY.md
3. ontology-phase-1-frozen-conformance: palimnex/tests/test_concepts_frozen.py, palimnex/tests/fixtures/ontology/

Review each lane against its task card, the accepted contract and CURRENT SOURCE:
- Run its focused tests and the contract validator with its receipt:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-1/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-1/receipts/<ws>.implementation-receipt.json
- Contract fidelity: does palimnex/concepts.py implement SEMANTICS.md exactly (normalization, ambiguity,
  supersession and withdrawal, candidate/approved separation, canonical digest with registry_digest excluded,
  bounds, R1 ID pattern, R7 typed refusals)? Does the public schema match the accepted draft? Does
  docs/CONCEPT_REGISTRY.md say anything the contract does not?
- Phase 1 exit gate (design): exact field, size, identity, alias and digest validation; candidate and
  approved paths separate; conflicting aliases reported as ambiguity; source-drift and secret non-echo tests;
  no change to existing retrieval output when the feature is absent; stdlib-only runtime; strict mypy.
- Adversarial probes, at least 3 per lane, scripted under /tmp against the real module. Ideas: a registry
  with a homoglyph or NFKC-colliding alias; an alias that differs only in punctuation; a supersession cycle; a
  withdrawn concept still matched; a placeholder digest accepted without the fixture flag; an oversize
  registry; a symlinked or traversal binding; a secret canary in a definition or alias (assert no echo in the
  exception text or repr); a digest computed with registry_digest included; a candidate registry passed as
  approved; mutation of returned dataclasses; non-deterministic ordering.
- Architecture: palimnex/concepts.py imports project_id from palimnex.cache_v3 and project_slug from
  palimnex.core. Assess whether that couples the standalone registry to cache or CLI code, risks import
  cycles, or should use palimnex.identity. Report your severity judgment.
- Authority: no CLI, config, retrieval, cache, ledger or MCP change; no default registry location; nothing
  imports palimnex.concepts outside tests. Check with grep.
- Tests are real: no skips or expected failures hiding failures; the frozen fixture is byte-identical
  (sha256 a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b).

Output: a concise human summary, then ONE fenced ```json block with a JSON array of exactly three review
receipts matching .agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy
design_identity from the task card and task_digest/approval_evidence_digest from bundle-validation.json.
Prefix each evidence item with BLOCKER, MAJOR, MINOR or NOTE. Status: rejected for any BLOCKER; accepted
only if no MAJOR remains.
