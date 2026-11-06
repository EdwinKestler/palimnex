# Fix round 1: ontology-phase-3-evaluation (R12 gates)

Same task card and owned paths. Read
`artifacts/ontology/phase-3/integration/clarification-R12.md` first. Your
implementation followed the spec correctly; the coordinator's gate definition
was wrong.

Change only the gates in `palimnex/ontology_eval.py` and their tests:
- Remove `critical_green`.
- Add `baseline_identical`: for every evaluated case in every suite, the
  `baseline` returned by `shadow_retrieve` equals a direct `retrieve_sources`
  call with the same arguments (compare canonical JSON). Do not double the
  runtime needlessly: compute the direct call once per case and reuse it.
- Add `no_critical_regression`: every critical case that passes under the
  baseline also passes under the shadow.
- Add `no_case_regression`: the same, for every case of any category.
- Keep `no_new_forbidden`, `abstention_not_regressed`,
  `ambiguity_never_contributes`, `channels_visible` and `bounded` unchanged.
- Keep reporting absolute critical counts per suite. Add, per suite, a
  `regressed_case_ids` list (empty when none) so a failing gate names its cases.

Tests: update the gate-name assertions; add synthetic-input tests showing that
a baseline-pass/shadow-fail critical case fails `no_critical_regression`, a
non-critical one fails only `no_case_regression`, a baseline-fail/shadow-pass
case fails nothing, and a mismatching baseline fails `baseline_identical`.
Keep the real-repository determinism test.

Run your focused tests and strict mypy. Do not run the full suite. Overwrite
your receipt (fresh digests), status `tested`, cite R12, and record the gate
values from one real run.
