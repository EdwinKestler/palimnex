# Wave 2 brief: ontology-phase-0-threat-cases (after registry)

The rules in `../COMMON.md` still apply. Your task card was reissued, so get
fresh digests from the validator before writing your receipt. Overwrite your
receipt at the same path. The registry lane has already finished wave 2; its
schema at `artifacts/design/ontology-phase-0/registry/` is read-only to you.

Apply from `integration/reconciliation-decisions.v1.md`:
- **R1:** concept IDs must match the registry `conceptId` pattern. Drop the
  `startswith("concept.")` rule.
- **R2:** fixtures store normalized aliases (registry SEMANTICS algorithm).
  Display forms go in `canonical_name` and in the query. Resolve ONT-NORM-002 and
  ONT-NORM-003 if R2 settles them; otherwise keep them disputed with the reason.
- **R4:** every `registry_fixture` is a complete `palimnex:concept-registry:v1`
  document with `status`, full `source-locator.v1` bindings and a correct
  `registry_digest`, and `check_cases.py` validates each one with the registry
  schema through a local `referencing.Registry`. Mark placeholder digests with a
  case-level `binding_digests_are_placeholders: true`. Prove that the wave-1
  probe (a digest-only locator) now fails.
- **R5:** add `expected_stale_concept_ids` to every case, and move drifted IDs in
  ONT-STALE-001 and ONT-STALE-002 into it.
- **R6:** replace "ambiguous requires empty covered" with "ambiguous and covered
  are disjoint".
- **R7:** add `expected_outcome: "error" | "receipt"`. Error-class cases keep
  `expected_status_disputed: true` with a reason citing R7.
- Update THREAT_MODEL.md and README.md only where these changes affect them.
- Address your wave-1 review findings (MAJOR and MINOR) in
  `wave-1/reviews/ontology-phase-0-threat-cases.review-receipt.json`.
