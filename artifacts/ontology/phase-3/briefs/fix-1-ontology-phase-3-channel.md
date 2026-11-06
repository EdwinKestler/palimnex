# Fix round 1: ontology-phase-3-channel (validator/schema parity)

Same task card and owned paths. Read the independent review
`artifacts/ontology/phase-3/reviews/ontology-phase-3-channel.review-receipt.json`
(MINOR).

**Defect.** `validate_shadow_comparison` checks concept IDs with
`_CONCEPT_ID_RE` but no length bound. The public schema
(`$defs.conceptId`, from the concept registry) requires 3-128 characters, so the
runtime validator accepts `ab` and a 129-character ID that Draft 2020-12
rejects.

**Fix.** Enforce the same 3-128 bound wherever the validator checks a concept
ID. Reuse the registry's existing constant or validator from
`palimnex.concepts` if one is exposed; otherwise define one constant and cite
the schema. Keep the stricter sorted/duplicate rule; it is an intended
cross-field rule that JSON Schema cannot express. Say so in a comment.

**Tests.** Add parity cases: a 2-character and a 129-character concept ID are
each rejected by both the runtime validator and the schema (rehash the digest
so only the ID is wrong), and 3-character and 128-character IDs are accepted by
both.

Run your focused tests and strict mypy, plus
`./.venv/bin/python -m unittest palimnex.tests.test_retrieval_shadow palimnex.tests.test_ontology_eval`.
Do not run the full suite. Overwrite your receipt (fresh digests), status
`tested`.
