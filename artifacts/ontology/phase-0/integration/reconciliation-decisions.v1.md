# Phase 0 reconciliation decisions v1 (coordinator, provisional)

Authority: `ontology_phase_0_contract` only, under the existing approval evidence.
These are coordinator decisions to make the three drafts agree with each other.
Every item is provisional and is listed for the owner's Phase 0 exit gate.
Inputs: the wave-1 review receipts in `artifacts/ontology/phase-0/wave-1/reviews/`
and the coordinator's own cross-lane check.

## R1. One concept-ID definition

- Canonical pattern `^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$`, length 3-128.
  Underscore becomes a legal segment separator, so `concept.source_locator` is valid.
- It is defined once, as `$defs.conceptId` in
  `registry/concept-registry.v1.schema.json`. The coverage schema `$ref`s
  `https://palimnex.dev/schemas/concept-registry.v1.schema.json#/$defs/conceptId`
  and keeps no copy.
- No required prefix. `check_cases.py` drops its `startswith("concept.")` rule.

## R2. One alias definition, stored normalized

- `$defs.alias` in the registry schema (max 128) is the only alias definition.
  The coverage matched-alias field `$ref`s it.
- Aliases are stored already normalized by the registry SEMANTICS algorithm
  (NFKC, casefold, punctuation to space, whitespace collapse). Display forms
  belong only in `canonical_name`. Frozen fixtures store normalized aliases;
  normalization cases put the display form in the query, not in the fixture.

## R3. One project-identity definition

- The coverage schema `$ref`s the registry's `$defs.projectIdentity` and keeps no
  separate UUID or slug pattern.

## R4. Frozen fixtures are real registries

- Each case's `registry_fixture` is a complete `palimnex:concept-registry:v1`
  document that validates against the registry schema, including `status`
  (not `lifecycle_status`), full `source-locator.v1` bindings and a correct
  `registry_digest`.
- Placeholder locator digests use the declared placeholder value and are flagged
  once per case (`binding_digests_are_placeholders: true`), never by wrapping the
  locator. `check_cases.py` validates every fixture with the registry schema
  through a local `referencing.Registry`. That fixes the wave-1 probe in which a
  digest-only locator passed.

## R5. Stale is its own collection

- The coverage model stays as R = C + U + S + A (covered, uncovered, stale,
  ambiguous). Frozen cases add `expected_stale_concept_ids`, and the stale-source
  cases move drifted IDs there out of `expected_uncovered_concept_ids`.
- Add at least one valid coverage example with a nonempty `stale_concepts`.

## R6. Ambiguity fails closed, but covered can be nonempty

- The coverage decision table stands (design invariant 4): status is `ambiguous`
  whenever any recognized concept is ambiguous, even if others are covered.
- An ambiguous concept never appears in the covered set (disjointness).
  `check_cases.py` replaces its "covered must be empty" rule with that
  disjointness rule.

## R7. Refusal versus receipt (provisional default; disputes stay flagged)

- Typed operation errors, with no receipt: malformed or traversal paths,
  symlinks, cross-project bindings, privacy refusal.
- Receipt state: stale source.
- Affected cases keep `expected_status_disputed: true`, cite R7 in the reason, and
  add `expected_outcome: "error" | "receipt"`.

## R8. Deferred to the owner (not applied in wave 2)

- Validator patch proposal (all three lanes): let `files_changed` list
  descendants of directory-valued owned paths. Accepted in principle; not
  applied, because it changes the authority-enforcing validator. Wave-2 receipts
  keep listing owned roots, as in wave 1.
