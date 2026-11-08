# Lane brief: ontology-phase-5-feedback-schemas

Read `COMMON.md` and `FEEDBACK_SPEC.md` (sections 1 and 2). You own
`palimnex/schemas/retrieval-feedback.v1.schema.json`,
`palimnex/schemas/retrieval-feedback-withdrawal.v1.schema.json`,
`palimnex/schemas/retrieval-feedback-report.v1.schema.json`,
`palimnex/tests/fixtures/retrieval_feedback/` and
`palimnex/tests/test_feedback_schemas.py`. The core lane implements
`palimnex/feedback.py` in parallel; your tests must not import it.

## Write

- Three draft 2020-12 schemas with `$id`, `additionalProperties: false` at every
  object level, constants for `schema`, `authority`, `authorizes_actions` and
  `retrieval_influence`, enums for judgement, origin, method and report state,
  64-hex digest patterns, line bounds (1 ≤ start ≤ end), string byte bounds
  approximated with `maxLength`, and nullable `note`.
- Valid fixtures (one per payload type, plus a report with every state) and
  invalid fixtures (one per rule: extra key, wrong constant, bad digest, end
  before start, unknown judgement, oversized note, missing field). No
  secret-shaped text in any fixture.

## Tests: `palimnex/tests/test_feedback_schemas.py`

Valid fixtures pass and each invalid fixture fails for its rule, using a local
`referencing.Registry` (no network); schema `$id`s are unique; every fixture is
free of `security.scan_bytes` findings; existing schemas are unchanged.
