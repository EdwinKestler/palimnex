# Fix round 1: ontology-phase-2-coverage-core

Same task card and owned paths. Read the independent review
`artifacts/ontology/phase-2/reviews/ontology-phase-2-coverage-core.review-receipt.json`
(MINOR 1) and `palimnex/retrieval.py` `retrieve_sources` / `budget_items`
(read-only).

**Defect.** `_retrieval_state` attributes omission with
`byte_omitted = omitted > 0 and used >= budget`. `retrieve_sources` applies
`budget_items` and then `[:limit]`, and recomputes `items_bytes` on the final
list, so `used >= budget` is almost never true. Reviewer probe: with
`byte_budget=128`, `omitted=1`, `used=2` and 0 results, the only candidate was
dropped by the byte budget, yet the receipt says `retrieval_truncated: true`
and `byte_budget_omission.omitted: false`.

**Fix (exact rule).** Add a keyword-only parameter to
`build_coverage_receipt`: `retrieval_limit: int | None = None` (the `limit`
passed to `retrieve_sources`, 1-100; refuse anything else with a typed
`CoverageError`). Let `n = len(search_result["results"])` and
`omitted = search_result["omitted_count"]`:
- `omitted == 0`: both disclosures false, `omitted_item_count` 0.
- `retrieval_limit` given and `n < retrieval_limit`: the limit did not bind, so
  every omission is a byte-budget omission. `byte_budget_omission.omitted`
  true, `omitted_item_count = omitted`, `retrieval_truncated` false.
- `retrieval_limit` given and `n == retrieval_limit`: the limit bound.
  `retrieval_truncated` true; `byte_budget_omission.omitted` false and
  `omitted_item_count` 0, because further budget drops cannot be attributed
  from `retrieve_sources` fields. Say this in a code comment.
- `n > retrieval_limit`: typed refusal (an inconsistent search result).
- `retrieval_limit is None` (cause unknown): `retrieval_truncated` true when
  `omitted > 0`, byte omission false, and a comment saying the cause cannot be
  attributed.
Remove the `used >= budget` heuristic. `byte_budget` and `used_bytes` are still
copied as today. Do not change the schema, `validate_receipt` semantics, or any
other behavior. Both disclosures may legitimately be true in general, so do not
add an exclusivity check (the reviewer's MINOR 2 is declined by the
coordinator for that reason).

**Tests.** Reproduce the reviewer probe with a real `retrieve_sources` call in a
temporary checkout (a tiny `byte_budget`) and `retrieval_limit=5`, and assert
byte-budget omission. Add a case where the limit binds (assert retrieval
truncation), no omission, `retrieval_limit=None`, an invalid `retrieval_limit`,
and `n > retrieval_limit`.

The coordinator will pass `retrieval_limit=limit` from `explain-search`. Run
your focused tests, strict mypy, and
`./.venv/bin/python -m unittest palimnex.tests.test_coverage_frozen`. Do not run
the full suite. Overwrite your receipt (fresh digests), status `tested`.
