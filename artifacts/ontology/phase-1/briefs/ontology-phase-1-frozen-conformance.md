# Lane brief: ontology-phase-1-frozen-conformance (after core and schema)

Read `COMMON.md` first. You own `palimnex/tests/test_concepts_frozen.py` and
`palimnex/tests/fixtures/ontology/`. The registry-core lane
(`palimnex/concepts.py`) and the schema lane
(`palimnex/schemas/concept-registry.v1.schema.json` and
`palimnex/tests/fixtures/concept_registry/`) have already finished. Their files
are read-only to you; read their code and receipts in
`artifacts/ontology/phase-1/receipts/`.

## Deliverables

1. **Frozen fixture.** Copy
   `artifacts/design/ontology-phase-0/frozen-cases/cases.v0.json` byte-for-byte
   to `palimnex/tests/fixtures/ontology/cases.v0.json`. A test asserts its
   SHA-256 equals
   `a64be4f15fdfb664b3142706e5cef35d10fbaa4ed340aea38f22388404f7314b`. Never edit
   labels to make code pass.
2. **Conformance tests** for every case with `gates_phase: 1`. Each case gets
   its own `subTest`, using only `palimnex.concepts`' public API:
   - the fixture registry parses with placeholder digests allowed (the case
     flag), and expected rejections fail with a typed error;
   - exact-alias matching on the case query yields exactly
     `expected_recognized_concept_ids` and `expected_ambiguous_concept_ids`;
     ambiguous and covered stay disjoint;
   - `expected_outcome: "error"` cases raise the typed refusal (R7) and do not
     echo values;
   - secret cases build their canary from the recipe at runtime and assert
     refusal before derivation, with no echo;
   - coverage `status` labels are Phase 2 territory: do not assert them, but do
     assert they belong to the vocabulary.
   Cases marked `expected_status_disputed` still run their Phase 1 assertions.
   If a Phase 1 expectation is itself disputed, mark that subtest with
   `expectedFailure`-style handling only if the label demands it, and explain
   in the receipt.
3. **Parity tests.** For every frozen registry fixture and every fixture under
   `palimnex/tests/fixtures/concept_registry/`, the runtime validator in
   `palimnex.concepts` and the public JSON Schema must agree on accept versus
   reject. Report any disagreement as a failing test plus an
   `integration_patch_proposals` entry naming the lane and the exact
   difference. Do not hide it.

If a gates-phase-1 case fails because `palimnex/concepts.py` is wrong, the test
stays failing and you report it. You do not edit the core module. Set receipt
status `partial` in that case.
