# Fix round 1: ontology-phase-2-frozen-conformance

Same task card and owned path. The core lane fixed byte-budget versus limit
attribution: `palimnex.coverage.build_coverage_receipt` now takes a
keyword-only `retrieval_limit`, the `limit` used for the search (read its
docstring and `_retrieval_state`). Without it, omission is attributed to
retrieval truncation. `explain-search` now passes it.

Change only `palimnex/tests/test_coverage_frozen.py`: pass `retrieval_limit`
equal to the limit your synthetic search result models, for every case, so
that the truncation and byte-budget cases (ONT-TRUNC-*, ONT-BUDGET-*) express
their `runtime_condition` faithfully. A byte-budget case must model fewer
results than the limit; a truncation case must model exactly the limit. Never
change a label or the frozen fixture. Keep everything else.

Run `./.venv/bin/python -m unittest palimnex.tests.test_coverage_frozen palimnex.tests.test_coverage palimnex.tests.test_concepts_frozen -v`,
which must all pass. Do not run the full suite. Overwrite your receipt (fresh
digests), status `tested`.
