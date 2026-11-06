# Fix round 1: ontology-phase-1-registry-schema

Same task card, same owned paths, and `../COMMON.md` still applies. Your round-1
receipt and the independent review are archived in
`artifacts/ontology/phase-1/round-1/`. Read
`round-1/reviews/ontology-phase-1-registry-schema.review-receipt.json`.

Fix exactly this MAJOR finding in `docs/CONCEPT_REGISTRY.md`:

- The doc says symlinked (and some other) sources make a concept stale. Accepted
  decision R7 (`artifacts/ontology/phase-0/integration/reconciliation-decisions.v1.md`)
  and `palimnex/concepts.py` (read it, read-only) say malformed or traversal
  paths, symlinks, cross-project bindings and privacy refusals are typed
  operation errors with no result, while stale means the source drifted (its
  digest or version no longer matches, or it is missing, exactly as the code
  classifies it). Rewrite the section so every condition sits in the category
  the code actually uses. Verify each one against `concepts.py` and cite the
  reason codes. Add the missing typed refusals for cross-project bindings and
  privacy.
- Re-read the whole doc once for any other statement the code or the accepted
  contract contradicts, and fix only those.

No schema or fixture change is expected. If you find one is needed, stop and put
it in `integration_patch_proposals`.

Testing: run your focused tests
(`./.venv/bin/python -m unittest palimnex.tests.test_concept_registry_schema palimnex.tests.test_sdk`).
Do NOT run the full suite or the standard gate (the coordinator runs them
unsandboxed). Overwrite your receipt (fresh digests), status `tested`, and
record the doc sections you changed.
