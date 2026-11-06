# Lane brief: ontology-phase-3-channel (wave A, parallel with the cohort lane)

Read `COMMON.md` and `SHADOW_SPEC.md` first. You own
`palimnex/ontology_shadow.py`, `palimnex/tests/test_ontology_shadow.py`,
`palimnex/schemas/ontology-shadow-comparison.v1.schema.json` and
`docs/ONTOLOGY_SHADOW.md`. The retrieval lane builds on your API next, so match
SHADOW_SPEC sections 1 and 3 exactly: names, signatures and fields.

## Implement

1. `ontology_channel(...)` and `OntologyChannel` per section 1. Reuse the
   public APIs of `palimnex.concepts` (`match_aliases`, `verify_source_bindings`)
   and the query-digest helpers of `palimnex.coverage`. Do not reimplement
   normalization or source verification. Byte-range bindings map to lines from
   the current file bytes; document the rule.
2. `build_shadow_comparison(...)` and `validate_shadow_comparison(...)` per
   section 3, including the cross-field rules and `comparison_digest`, with a
   stable `ShadowComparisonError(ValueError)` that carries a `reason` and never
   echoes values.
3. The public Draft 2020-12 schema for `palimnex:ontology-shadow-comparison:v1`,
   with `additionalProperties: false` and explicit bounds, matching the $id
   conventions of the existing schemas in `palimnex/schemas/`.
4. `docs/ONTOLOGY_SHADOW.md`: what shadow mode is and is not (it never alters
   returned results; promotion needs separate owner approval), how the channel
   ranks chunks, which concepts never contribute, the comparison document, and
   that it is visible only through `palimnex evaluate-ontology-shadow` (the
   coordinator adds that command). Link the design and the coverage and
   registry docs.

## Tests: `palimnex/tests/test_ontology_shadow.py`

Use temporary checkouts with real bound files and real digests. Cover: no
registry gives an empty channel; candidate-kind refusal; a contributing concept
ranks the overlapping chunks; ambiguous, stale and uncovered concepts excluded
and listed; overlap edge cases (inclusive lines, byte ranges, adjacent
non-overlap, a non-`repo` scheme); two concepts on one chunk rank it first;
deterministic order; the 512 cap sets `truncated`; R7 refusals with no echo; a
secret query refused with no echo. For the comparison: identical rankings,
entered and left items, rank changes, a digest tamper caught,
validator-versus-schema parity on valid and invalid documents (local
`referencing.Registry`), and no query text anywhere in the document.
