# Lane brief: ontology-phase-2-coverage-schema

Read `COMMON.md` and `EXPLAIN_SEARCH_SPEC.md` first. You own both new public
schemas, `palimnex/tests/test_retrieval_coverage_schema.py`,
`palimnex/tests/fixtures/retrieval_coverage/` and `docs/COVERAGE_RECEIPT.md`.

## Deliverables

1. **`palimnex/schemas/retrieval-coverage.v1.schema.json`**: promote the
   accepted `artifacts/design/ontology-phase-0/coverage/retrieval-coverage.v1.schema.json`.
   Keep `$id`, `$defs` names, the `$ref`s into
   `concept-registry.v1.schema.json` (`conceptId`, `alias`, `projectIdentity`)
   and `source-locator.v1.schema.json`, and the meaning, unchanged. Only make
   edits needed to sit with the existing public schemas, and list each one in
   your receipt (Phase 1 changed only the title).
2. **`palimnex/schemas/explain-search.v1.schema.json`**: new, exactly per
   `EXPLAIN_SEARCH_SPEC.md`. Use `additionalProperties: false`, the seven keys,
   `search` as `type: object`, `coverage` as a `$ref` to the coverage schema or
   `null`, and an `if/then` tying `coverage: null` to
   `coverage_state: "registry_absent"`. `registry.path` uses the repository's
   traversal-free path pattern (max 512) and `registry.source` the enum. Use the
   `$id` conventions of the existing schemas.
3. **Fixtures** in `palimnex/tests/fixtures/retrieval_coverage/{valid,invalid}/`:
   copy the accepted coverage examples (byte-identical where possible, with
   `receipt_digest` still correct) and add explain-search wrapper examples. At
   least two are valid (enabled, registry_absent) and at least four invalid:
   an extra key; coverage null while enabled; coverage present while
   registry_absent; and `authorizes_actions: true`. Name each invalid fixture
   after its reason.
4. **Tests** (`test_retrieval_coverage_schema.py`): `check_schema` for both;
   every valid fixture passes and every invalid one fails, using a local
   `referencing.Registry` that loads all four related public schemas (no
   network); recompute `receipt_digest` with `palimnex.durable.canonical_json`.
   Follow `palimnex/tests/test_concept_registry_schema.py`.
5. **`docs/COVERAGE_RECEIPT.md`**: a public, concise reader version of the
   accepted coverage SEMANTICS.md plus the explain-search document. Cover the
   reader obligation (coverage is not correctness), the query digest, identities,
   classification, the status table, truncation versus byte budget, ordering
   and digest, semantic disclosure, privacy and persistence (the raw query
   appears only inside the unchanged `search` object), typed refusals (R7), and
   the default registry path with `--registry`. Do not invent CLI flags beyond
   `--registry`; the coordinator owns the CLI. Link to `docs/CONCEPT_REGISTRY.md`
   and `docs/ONTOLOGY_ADOPTION.md`.

You do not touch `palimnex/coverage.py`. If it needs something from you, put
it in `integration_patch_proposals`.
