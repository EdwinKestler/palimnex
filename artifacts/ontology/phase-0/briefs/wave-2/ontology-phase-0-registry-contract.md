# Wave 2 brief: ontology-phase-0-registry-contract (runs first)

The rules in `../COMMON.md` still apply. Your task card was reissued, so get
fresh digests from the validator before writing your receipt. Overwrite your
receipt at the same path. Your wave-1 receipt is archived under `wave-1/`.

The coverage and threat-cases lanes start after you finish and will `$ref` your
schema, so your `$defs` are the shared source of truth.

Apply from `integration/reconciliation-decisions.v1.md`:
- **R1:** change `$defs.conceptId` to `^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$`,
  length 3-128. Keep the name `conceptId`.
- **R2:** keep `$defs.alias` (max 128) and state in SEMANTICS.md that it is the
  single alias definition other contracts `$ref`.
- **R3:** keep `$defs.projectIdentity` and state the same for it.
- **R4:** document fixture use in SEMANTICS.md. Frozen cases embed full registry
  documents, and the declared placeholder digest is allowed only in fixtures
  flagged `binding_digests_are_placeholders: true`; it is never valid in a
  committed registry.
- Add a valid example whose concept ID uses `_` and an invalid one with a
  doubled separator (`a__b`).
- Address your wave-1 review findings (MAJOR and MINOR) in
  `wave-1/reviews/ontology-phase-0-registry-contract.review-receipt.json`. Where a
  finding needs a change in another lane, list it in
  `integration_patch_proposals` instead.

Your check script must still pass, and `$defs` names must stay stable.
