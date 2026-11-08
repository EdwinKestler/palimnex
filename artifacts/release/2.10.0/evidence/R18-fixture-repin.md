# R18 — re-pin concept-registry test fixtures after the 2.10.0 doc edits (coordinator decision)

`palimnex/tests/test_concept_registry_schema.py` checks that the valid fixtures
in `palimnex/tests/fixtures/concept_registry/valid/` bind current repository
bytes. Three fixtures bind `README.md` lines 3-6 and 8-12 and `docs/DESIGN.md`
lines 37-41 and 43-47. Each binding records the whole file's version, so the
2.10.0 version and documentation edits made five subtests fail with "source
unavailable or version/digest mismatch".

Decision (same rule as R13): re-pin only the whole-file `version` of each
affected binding and recompute each fixture's `registry_digest`. The script
`artifacts/release/2.10.0/tools/repin_registry_fixtures.py` refuses if any
bound range's selected-byte digest changed, so what each fixture binds is
unchanged; every label, concept, alias and range stays frozen. Report:
`artifacts/release/2.10.0/evidence/R18-fixture-repin.json`. After the re-pin
the schema, concepts and frozen-concept tests pass (34 tests).

Note for the future: these fixtures (and the shipped registry) go stale with
any edit to a bound file; a release that edits `README.md` or
`docs/DESIGN.md` must re-pin them the same way.
