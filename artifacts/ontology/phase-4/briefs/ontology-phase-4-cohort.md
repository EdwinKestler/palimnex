# Lane brief: ontology-phase-4-cohort (wave 1)

Read `COMMON.md` and `SEMANTIC_SPEC.md` section 3 first. You own
`palimnex/evaluation/semantic-shadow.v1.json`,
`palimnex/schemas/semantic-shadow-cohort.v1.schema.json` and
`palimnex/tests/test_semantic_cohort.py`.

## Why this cohort matters

This cohort decides whether a semantic provider is "promotable". It is frozen
before any semantic result exists, so its labels must be honest and written
blind. **Do not run retrieval, evaluation, embedding, `palimnex` commands or
`core.embedding` to choose, check or tune cases.** Read the source files and
write the labels a careful engineer would agree with.

## Write the cohort

- Repository cases with the categories and minimum counts in section 3.
  Spread expected paths across at least eight different runtime modules under
  `palimnex/*.py`. Paraphrase and synonym queries describe behaviour in other
  words than the code uses; a synonym case uses a common synonym for a domain
  term (for example "purge" for "erasure"). Ambiguity cases name something two
  or more modules genuinely implement and list each. Negatives are clearly
  unrelated to this repository. Controls are direct questions using the code's
  own words.
- Every `note` explains in one sentence why the expected path answers the query.
- Synthetic projects for drift and privacy cases, with the `{canary}`
  placeholder rules in section 3. Keep documents small and plain.

## Schema and tests

- The JSON Schema (draft 2020-12, `additionalProperties: false`) enforces the
  structure, enums, id pattern, `limit: 5` and string bounds.
- `palimnex/tests/test_semantic_cohort.py` checks, offline: the document
  validates against the schema (local `referencing.Registry`); ids unique;
  category minimums; only control cases critical, at least two critical;
  expected and forbidden paths exist and are runtime `palimnex/*.py` files (for
  repository cases); queries at most 200 characters and not equal to any
  `ontology-shadow.v1.json` query; `security.scan_bytes` on the raw file finds
  nothing; each privacy case has exactly one `{canary}` in the specified place
  and a valid rule; drift `after` changes reference project files; the file is
  sorted-key canonical with a trailing newline.
