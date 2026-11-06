# Fix round 2: ontology-phase-1-registry-core

Same task card and owned paths. Read
`artifacts/ontology/phase-1/integration/clarification-R9.md` first. It
resolves the ONT-NORM-003 conflict you correctly reported.

Change only this:

- Keep your fix-1 behavior for registry keys: canonical names and stored
  aliases reject any C* code point, TAB, LF and CR included, exactly per
  SEMANTICS.md.
- Queries: before the procedure, map every code point where `str.isspace()`
  is true to U+0020, then apply the same steps 1-6 unchanged. Any other C*
  code point left in a query is refused by step 3 with the typed error and no
  echo.
- Update the fix-1 query tests: TAB, LF and CR in a query now match like
  spaces; a non-whitespace control character in a query (for example U+0007) is
  refused; the same whitespace characters in a stored alias are still refused.
- Keep the privacy and cycle fixes from fix-1 unchanged.

Run: focused tests, strict mypy, and
`./.venv/bin/python -m unittest palimnex.tests.test_concepts_frozen`, which must
now pass 4/4. Do not run the full suite or the standard gate. Overwrite your
receipt (fresh digests): status `tested` only if all three pass. Cite R9.
