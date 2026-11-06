Implemented Phase 3 FIX ROUND 1 within owned paths only.

Binding changes:

- `concept.concept_registry`: `105–121` → `106–121`
- `concept.migration_registry`: `65–130` → `66–130`
- `concept.rrf_fusion`: `128–146` → `167–181`
- `concept.source_locators`: `35–78` → `36–78`

The other eight bindings remain unchanged after source verification. Added per-concept `def`/`class` anchor assertions.

- [Cohort](/home/kestl/github/palimnex/palimnex/evaluation/ontology-shadow.v1.json)
- [Structural test](/home/kestl/github/palimnex/palimnex/tests/test_ontology_shadow_cohort.py)
- [Receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3/receipts/ontology-phase-3-cohort.implementation-receipt.json)

Validation:

- Focused suite: 6/6 passed
- Receipt contract: valid
- Cohort SHA-256: `f71f3fb923c4f9d8084ffc2ae5c450049f692a5ad93e305afedc5a040b2b435c`
- `cache_consulted: false`; Redis was unavailable and indexing was not authorized
- Full suite and standard gate intentionally delegated to the coordinator
- No case, label, alias, concept, placeholder, or expected-path changes