# R9: query whitespace versus the alias normalization procedure (coordinator clarification, Phase 1)

**Finding.** Fix round 1 applied SEMANTICS.md step 3 (reject C* code points)
to query text. Frozen case ONT-NORM-003 (`source\t binding\nverification`
must recognize the alias `source binding verification`) then failed.

**Reading.** The procedure in
`artifacts/design/ontology-phase-0/registry/SEMANTICS.md` ("Deterministic alias
normalization") is defined for matching keys derived from canonical names and
stored aliases. The contract defines no separate query-tokenization rule. The
frozen matrix is the only accepted artifact that specifies query behavior, and
its labels are authoritative (they never change to make an implementation pass).
The round-1 review finding that "tabbed queries match as spaces" violates step 3
over-applied a registry-key rule to queries. The coordinator's fix-1 brief
passed that error along.

**Clarification (no contract change).**
- Registry keys (canonical names and stored aliases) follow SEMANTICS.md steps
  1-6 exactly: any C* code point, including TAB, LF and CR, is refused.
- Query text is admitted first: every code point for which `str.isspace()` is
  true (including TAB, LF, CR, VT and FF) becomes U+0020. Then the same steps
  1-6 apply unchanged, so any other C* code point left in a query is refused by
  step 3 with the typed error and no echo.
- ONT-NORM-003 passes again; no frozen label changes.

Listed for the owner at Phase 1 handoff.

## Codex technical confirmation (2026-11-06)

Confirmed after reviewing the accepted Phase 0 semantics, frozen case
ONT-NORM-003, the Phase 1 implementation, focused tests, and independent review
receipts. The distinction above is the narrow reading that satisfies both
authoritative artifacts: stored registry keys still refuse every `C*` code
point, while query whitespace is admitted as U+0020 before the unchanged
normalizer runs. No frozen label, wire identifier, authority boundary, or
retrieval behavior is changed by this confirmation.

This is a technical confirmation of R9, not approval for Phase 2 or for any
registry-location wiring.
