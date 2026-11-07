# Lane brief: ontology-influence-schemas (wave 1, parallel with the gate lane)

Read `COMMON.md` and `INFLUENCE_SPEC.md` (sections 2 and 4) first. You own the
three new public schemas, `palimnex/tests/test_influence_schemas.py` and
`palimnex/tests/fixtures/ontology_influence/`.

## Deliverables

1. **`palimnex/schemas/context.v2.schema.json`** for
   `project-memory:context:v2`: exactly the keys `assemble_context` in
   `palimnex/experience.py` returns today (read it; do not edit it), with
   `schema` const `project-memory:context:v2`, plus a required
   `ontology_influence` object with the exact disclosure keys of section 2
   (`mode` const `enabled`, `channel` const `ontology`, `retrieval_influence`
   const true, three 64-hex digests, `contributing_concept_ids` as a bounded,
   unique array of registry `conceptId`s by `$ref`). Items stay
   `type: object`. Use `additionalProperties: false` at the top level, and keep
   `authorizes_actions` const false. No context v1 schema exists, and you must
   not create one.
2. **`palimnex/schemas/explain-search.v2.schema.json`** for
   `palimnex:explain-search:v2`: the v1 schema's keys and rules (read
   `palimnex/schemas/explain-search.v1.schema.json`), `schema` const v2, plus a
   required `ranking_influence` object with the same disclosure shape (define it
   once and `$ref` it, or `$ref` the context v2 `$defs`; choose one shared
   definition).
3. **`palimnex/schemas/ontology-promotion-evidence.v1.schema.json`** per
   section 4: exact keys, a `status` enum, digests, and `backends` with exactly
   `local` and `cache`. Each backend has `suites`, with exactly `v27`,
   `challenges_v26` and `cohort`, each holding `baseline` and `influenced`
   metric objects with bounded numbers (rates 0-1, counts bounded) plus
   `changed_ranking_count` and `regressed_case_ids`; and `gates`, with exactly
   the ten booleans named in section 4. Constants: `activation_authorized`
   false, `authority` `evidence_only`, `authorizes_actions` false.
4. **Fixtures** in `palimnex/tests/fixtures/ontology_influence/{valid,invalid}/`:
   at least one valid document per schema, and at least three invalid ones per
   schema, each named after its single failure (for example
   `context-v2-missing-disclosure`, `explain-v2-influence-false`,
   `evidence-missing-cache-backend`, `evidence-activation-authorized`). Correct
   any digests you include.
5. **Tests**: `check_schema`; every valid fixture passes and every invalid one
   fails, through a local `referencing.Registry` loading every related public
   schema (no network); recompute `evidence_digest` in the evidence fixtures with
   `canonical_json`. Follow `palimnex/tests/test_retrieval_coverage_schema.py`.

You do not edit runtime code or existing schemas. If you find the spec
inconsistent with existing code, implement the spec and raise it in
`integration_patch_proposals`.
