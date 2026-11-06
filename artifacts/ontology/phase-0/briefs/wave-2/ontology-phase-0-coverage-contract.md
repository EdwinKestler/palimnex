# Wave 2 brief: ontology-phase-0-coverage-contract (after registry)

The rules in `../COMMON.md` still apply. Your task card was reissued, so get
fresh digests from the validator before writing your receipt. Overwrite your
receipt at the same path. The registry lane has already finished wave 2; its
schema at `artifacts/design/ontology-phase-0/registry/` is read-only to you and
is the source of the shared definitions.

Apply from `integration/reconciliation-decisions.v1.md`:
- **R1, R2, R3:** delete your local `conceptId`, `alias` and project UUID/slug
  definitions. `$ref` the registry's
  `https://palimnex.dev/schemas/concept-registry.v1.schema.json#/$defs/conceptId`,
  `#/$defs/alias` and `#/$defs/projectIdentity` instead. Your check script loads
  the registry schema (and source-locator.v1) into its local
  `referencing.Registry`.
- **R5:** keep R = C + U + S + A. Add a valid example with a nonempty
  `stale_concepts` that exercises the stale branch of the decision table.
- **R6:** keep the decision table (ambiguous wins; covered may be nonempty;
  ambiguous and covered are disjoint). Make sure the cross-field check enforces
  disjointness.
- **R7:** record in SEMANTICS.md that malformed or traversal paths, symlinks,
  cross-project bindings and privacy refusals are typed operation errors with no
  receipt, while stale source is a receipt state.
- Re-check that every example ID still matches the registry pattern.
- Address your wave-1 review findings (MAJOR and MINOR) in
  `wave-1/reviews/ontology-phase-0-coverage-contract.review-receipt.json`.
