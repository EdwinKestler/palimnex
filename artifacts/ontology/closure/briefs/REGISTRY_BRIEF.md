# Lane brief: ontology-closure-registry (draft the candidate concept registry)

You are a bounded implementer under `.agents/skills/palimnex-ontology-workstream/SKILL.md`.
You write ONLY inside your task card's `owned_paths`:
`artifacts/ontology/closure/candidate/` and your implementation receipt.

## Goal

Draft a **candidate** concept registry for the Palimnex checkout,
`artifacts/ontology/closure/candidate/concept-registry.candidate.json`, that a
reviewer and the owner can approve. You never write `ontology/` (the approved
path) and never mark anything approved.

## Sources of truth

- `docs/ONTOLOGY_ADOPTION.md` (the "Approved registry v1 scope" row records the
  owner's decision), `docs/CONCEPT_REGISTRY.md`,
  `palimnex/schemas/concept-registry.v1.schema.json`, `palimnex/concepts.py`
  (parsing, alias normalization, ambiguity, canonical digest, source-binding
  verification), `palimnex/locators.py`, and the runtime source files below.

## Blind rule (mandatory)

Concepts are derived from the source code only. **Do not open** anything under
`palimnex/evaluation/`, `palimnex/tests/test_ontology_shadow_cohort.py`,
`palimnex/tests/test_semantic_cohort.py`,
`artifacts/ontology/phase-3/`, `artifacts/ontology/phase-3-promotion/` or
`artifacts/ontology/phase-4/` (they hold the evaluation questions that will be
used only after this registry is frozen). Do not run `evaluate-*` commands,
retrieval, `explain-search` or embeddings.

## Content: 16 concepts, one per row, owner-chosen

| concept_id | Concept | Primary source |
| --- | --- | --- |
| `concept.source_admission` | Source admission and privacy scanning | `palimnex/security.py`, `palimnex/cache_v3.py` |
| `concept.source_locator` | Structured source locators | `palimnex/locators.py` |
| `concept.retrieval_fusion` | Retrieval-channel fusion | `palimnex/retrieval.py` |
| `concept.context_assembly` | Context assembly and byte budgets | `palimnex/experience.py` |
| `concept.cache_generation` | Cache generations and reader leases | `palimnex/cache_v3.py` |
| `concept.durable_ledger` | Durable historical ledger | `palimnex/durable.py` |
| `concept.retention_eligibility` | Retention eligibility and exclusions | `palimnex/retention.py` |
| `concept.ledger_migration` | Ledger migration registry | `palimnex/migrations.py` |
| `concept.memory_pack` | Portable memory packs | `palimnex/portable.py` |
| `concept.audit_graph` | Audit graph and projections | `palimnex/audit.py` |
| `concept.concept_registry` | Concept-registry validation | `palimnex/concepts.py` |
| `concept.coverage_receipt` | Coverage and answerability receipts | `palimnex/coverage.py` |
| `concept.ontology_shadow` | Ontology shadow ranking | `palimnex/ontology_shadow.py` |
| `concept.ontology_activation` | Ontology activation gate | `palimnex/ontology_influence.py`, `palimnex/ontology_promotion.py` |
| `concept.semantic_shadow` | Semantic shadow evaluation | `palimnex/semantic_local.py`, `palimnex/semantic_shadow.py`, `palimnex/semantic_eval.py` |
| `concept.retrieval_feedback` | Reviewed retrieval feedback | `palimnex/feedback.py` |

For each concept:

- `canonical_name`: the concept name above (you may tighten wording).
- `definition`: one or two accurate sentences describing what the code does,
  written from reading it.
- `aliases`: 2–5 **conservative, specific multi-word** phrases a developer
  would actually type for this concept. Never a standalone generic word such as
  "memory", "search", "graph", "registry", "cache", "ledger", "index",
  "context", "source", "feedback", "evaluation", "shadow", "migration",
  "retention", "pack", "audit", "concept", "coverage", "semantic", "ontology".
  No alias may normalize to the same key as another concept's alias or
  canonical name (`palimnex.concepts` reports collisions and ambiguity: there
  must be none).
- `source_bindings`: 1–3 bindings, scheme `repo`, to the specific function,
  class or constant ranges that implement the concept (not whole files, not
  tests, not docs), with the real `version` and `digest` computed exactly as
  `palimnex.concepts` / `palimnex.locators` verify them for the current
  working tree. Prefer stable, central definitions over incidental lines.
- `status`: `candidate`; `provenance`: `{"origin": "model_candidate"}`.
- Registry: `registry_kind` `candidate_set`, `registry_version` 1, the project
  slug and id from `.palimnex.json`, and a correct `registry_digest`.

## Deliverables (all under `artifacts/ontology/closure/candidate/`)

1. `concept-registry.candidate.json`.
2. `NOTES.md`: for each concept, one line per binding saying what the bound
   range is (symbol name) and why it is the authoritative implementation, and
   the reasoning behind each alias.
3. `check_candidate.py` (standard library plus `palimnex.*`): parses the file
   with `palimnex.concepts` as a `candidate_set`, verifies every binding is
   current against the working tree, recomputes the registry digest, asserts
   16 concepts with the ids above, enforces the alias policy (the forbidden
   standalone words, 2–5 aliases, multi-word, no collisions or ambiguity
   between concepts, no `security.scan_text` finding), and prints a JSON
   summary. Exit 0 only if everything holds.

## Acceptance and handoff

Run the task card's acceptance commands, then write and validate your
implementation receipt as COMMON practice requires
(`artifacts/ontology/closure/receipts/ontology-closure-registry.implementation-receipt.json`,
schema `.agents/skills/palimnex-ontology-workstream/assets/implementation-receipt.v1.schema.json`).
No Git writes, network, installs, Redis or ledger writes. Do not run the full
test suite or `scripts/palimnex_check.sh`. Print a short summary when done.
