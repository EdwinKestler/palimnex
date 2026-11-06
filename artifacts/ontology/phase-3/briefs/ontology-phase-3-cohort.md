# Lane brief: ontology-phase-3-cohort (wave A, parallel with the channel lane)

Read `COMMON.md` and `SHADOW_SPEC.md` section 4 first. You own
`palimnex/evaluation/ontology-shadow.v1.json` and
`palimnex/tests/test_ontology_shadow_cohort.py`. This is evaluation-only test
data. It is never the approved registry, and you write no runtime code.

## Author the cohort

1. **Test registry.** Use 10-16 hand-written concepts about this repository's
   real subsystems. Ground each in current source by reading the file. Examples
   of the kind wanted: source locators (`palimnex/locators.py`), the privacy
   scanner (`palimnex/security.py`), the retention policy
   (`palimnex/retention.py`), the ledger migration registry
   (`palimnex/migrations.py`), audit graph projection (`palimnex/audit.py`),
   the concept registry (`palimnex/concepts.py`), the coverage receipt
   (`palimnex/coverage.py`), RRF fusion in `palimnex/retrieval.py`, and Redis
   reader leases in `palimnex/cache_v3.py`.
   - Bind each with `repo` line ranges around the defining code or docstring.
     Prefer ranges that are stable, such as a class or function definition.
   - Aliases must be stored normalized (registry SEMANTICS). An alias must not
     repeat its canonical-name key.
   - Include exactly one intentional alias collision between two concepts, for
     the ambiguity cases.
   - Use this repository's project identity from `.palimnex.json`, kind
     `approved_registry`, placeholder `version`, `digest` and `registry_digest`
     (64 zeros), and `binding_digests_are_placeholders: true` at the top level.
2. **Cases (about 24-30):** alias (at least 8), paraphrase (at least 4),
   ambiguity (at least 2), negative (at least 4: unrelated questions with no
   alias, `expected_paths: []`), and control (at least 4). Every case has
   `id`, `category`, `query`, `limit` (5), `expected_paths`, `forbidden_paths`,
   `critical`, `expect_ontology_contribution` and `note`.
   - Expected paths for alias cases include the bound file; for others, the
     file a careful reader would expect, or `[]`.
   - Mark as `critical` only cases whose baseline should already pass. Check by
     running `palimnex.retrieval.retrieve_sources(query, limit=5)` locally on the
     repository; that is read-only and offline.
   - Never echo secrets; no secret-like content.

## Test: `palimnex/tests/test_ontology_shadow_cohort.py`

Structure and uniqueness; category minimums; vocabulary; every bound path
exists and every line range is within the current file; the registry parses
with `palimnex.concepts.parse_registry(..., allow_placeholder_digests=True)`
(read its signature); exactly one alias collision; alias-category queries
contain an approved alias (use `match_aliases`); negative and paraphrase
queries recognize nothing; and the file contains no literal secret-pattern
content (`palimnex.security.scan_bytes`). Record the file's SHA-256 in your
receipt.
