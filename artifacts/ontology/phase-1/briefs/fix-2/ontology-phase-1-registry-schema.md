# Fix round 2: ontology-phase-1-registry-schema

Same task card and owned paths. Read
`artifacts/ontology/phase-1/integration/clarification-R9.md` first.

Change only the normalization section of `docs/CONCEPT_REGISTRY.md`:

- State that the six-step procedure governs registry keys (canonical names and
  stored aliases), and that any C* code point there, TAB, LF and CR included,
  is refused.
- Add the query rule from R9: in query text, whitespace characters (including
  TAB, LF and CR) are treated as spaces, then the same procedure applies, so any
  other control character in a query is refused.
- The core lane is implementing exactly R9 in parallel. Describe R9, not the
  current code. Do not describe any other query detail.

Also, the `ledger-status` call you made in fix 1 read `.palimnex/`, a forbidden
path. Do not repeat it.

Run your focused tests. Overwrite your receipt (fresh digests), status
`tested`. Cite R9.
