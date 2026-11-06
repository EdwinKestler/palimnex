# Lane brief: ontology-phase-1-registry-schema

Read `COMMON.md` first. You own
`palimnex/schemas/concept-registry.v1.schema.json`,
`palimnex/tests/test_concept_registry_schema.py`,
`palimnex/tests/fixtures/concept_registry/` and `docs/CONCEPT_REGISTRY.md`.

## Deliverables

1. **Public schema.** Promote
   `artifacts/design/ontology-phase-0/registry/concept-registry.v1.schema.json`
   to `palimnex/schemas/concept-registry.v1.schema.json`. Keep `$id`, `$defs`
   names (`conceptId`, `alias`, `projectIdentity`) and the meaning unchanged.
   Only make edits needed to sit with the existing public schemas: match their
   style and `$id` conventions, and confirm the `$ref` to
   `source-locator.v1.schema.json` resolves against the existing
   `palimnex/schemas/source-locator.v1.schema.json`. List every edit in your
   receipt.
2. **Fixtures.** Copy the accepted valid and invalid registry examples into
   `palimnex/tests/fixtures/concept_registry/{valid,invalid}/`, byte-identical
   where possible. Valid examples bind real repository sources, so check their
   locators and digests still match current files. If one has drifted, record
   it, and replace that binding with a test-owned approach (for example a
   documented placeholder flag) rather than editing repository docs.
3. **Schema tests** (`test_concept_registry_schema.py`): `check_schema`; every
   valid fixture passes and every invalid fixture fails, with resolution through
   a local `referencing.Registry` (no network); recompute `registry_digest` with
   `palimnex.durable.canonical_json`; assert the `conceptId` pattern accepts
   `concept.source_locator` and rejects `a__b`, `A.b` and `-x`. Follow the style
   of the wire-schema tests in `palimnex/tests/test_sdk.py`.
4. **Reader documentation** (`docs/CONCEPT_REGISTRY.md`): a public, concise
   version of the accepted SEMANTICS.md for registry authors and readers. Cover
   identity, lifecycle and what "approved" means; normalization; ambiguity;
   supersession; source bindings and drift; the canonical digest; bounds;
   privacy; non-authority; and the fact that Phase 1 has no default location and
   no retrieval influence. Link to `docs/ONTOLOGY_ADOPTION.md`. Do not copy the
   Phase 0 open-questions list; mention "registry location is not yet decided".
   Match the tone of the existing `docs/`.

You do not touch `palimnex/concepts.py`. If the runtime module needs a constant
from the schema, say so in `integration_patch_proposals`.
