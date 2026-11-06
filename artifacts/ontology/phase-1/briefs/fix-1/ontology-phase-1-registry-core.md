# Fix round 1: ontology-phase-1-registry-core

Same task card, same owned paths, and `../COMMON.md` still applies. Your round-1
receipt and the independent review are archived in
`artifacts/ontology/phase-1/round-1/`. Read
`round-1/reviews/ontology-phase-1-registry-core.review-receipt.json`.

Fix exactly these, with the smallest change that makes the code match the
accepted contract:

1. **Normalization order.** `normalize_alias` must follow
   `artifacts/design/ontology-phase-0/registry/SEMANTICS.md` step by step. If
   the contract rejects C* (control) characters before whitespace handling,
   then TAB and LF in input are refused or handled exactly as SEMANTICS.md says.
   Quote the governing SEMANTICS.md lines in your receipt. For queries
   specifically, follow whatever SEMANTICS.md says about query tokenization; do
   not invent a rule. Add tests for TAB, LF and CR in aliases and in queries.
2. **Privacy admission in `parse_registry`.** An in-memory document must be
   privacy-scanned (`palimnex.security`) before any derivation, the same as
   `load_registry`. Refuse with the typed error and no echo. Add a test with a
   runtime-built canary in a definition and one in an alias, asserting refusal
   and that neither the exception text nor its `repr` contains the canary.
3. **Cycle test.** Make
   `test_supersession_forks_cycles_and_missing_relations_are_rejected` (or a new
   test) actually build a supersession cycle and assert the `supersession_cycle`
   refusal.

Do not change anything else. The import of `cache_v3.project_id` and
`core.project_slug` stays (the reviewer judged it residual and contract-named).

Testing: run your focused tests, strict mypy, and
`./.venv/bin/python -m unittest palimnex.tests.test_concepts_frozen`. Do NOT
run the full suite or the standard gate. Their socket tests cannot pass in this
sandbox, and the coordinator runs them unsandboxed. Overwrite your receipt
(fresh digests) with status `tested` if the focused, frozen and mypy checks
pass. Record that the full suite is delegated to the coordinator.
