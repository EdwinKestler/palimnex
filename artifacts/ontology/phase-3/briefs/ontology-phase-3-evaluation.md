# Lane brief: ontology-phase-3-evaluation (wave C, after retrieval and cohort)

Read `COMMON.md` and `SHADOW_SPEC.md` section 5 first. You own
`palimnex/ontology_eval.py` and `palimnex/tests/test_ontology_eval.py`.
`shadow_retrieve`, the channel module and the cohort file are finished and
read-only to you.

## Implement `evaluate_ontology_shadow(root, *, limit=5)`

- Load the cohort and report its SHA-256 as `cohort_digest`. Materialize the
  placeholder `version`, `digest` and `registry_digest` against `root`: version
  per the repository resolver's semantics, digest of the selected range, and a
  recomputed registry digest. Then parse it as an approved registry. If a
  bound file or range no longer exists, the concept becomes stale (report it)
  rather than failing the whole evaluation.
- Suites, in local mode only (`client=None`):
  - `v27`: the frozen `palimnex/evaluation/v27.json` cases with mode `search`
    (read-only; check its pinned digest as `palimnex/core.py` does), through
    `shadow_retrieve` with the cohort registry;
  - `challenges_v26`: write the v26 synthetic project to a temporary checkout as
    `palimnex/challenge.py` does (reuse its helpers read-only), with
    `registry=None`. Shadow must equal baseline, and abstention is measured;
  - `cohort`: every cohort case through `shadow_retrieve` with the cohort
    registry.
- Metrics per suite, for baseline and shadow: as in SHADOW_SPEC section 5, with
  definitions matching the existing evaluation code (`palimnex/core.py`
  `evaluate`) for recall, MRR, critical and forbidden. Also report per-case
  rows (`id`, `category`, baseline and shadow pass, first relevant rank,
  `ontology_contributed`), and say how many cases changed ranking.
- Gates, computed from the data: `critical_green` (every critical case passes
  under the shadow); `no_new_forbidden` (shadow forbidden hits <= baseline);
  `abstention_not_regressed` (shadow abstains wherever the baseline does);
  `ambiguity_never_contributes` (ambiguity cases have no ontology contribution);
  `channels_visible` (every shadow item names its channel ranks);
  `bounded` (caps, budget and limit respected).
  `promotion_authorized` is always false. The report is canonical JSON-safe and
  deterministic.
- Fail visibly on a corrupt cohort or fixture digest mismatch with a typed
  error. Never silently skip a suite.

## Tests: `palimnex/tests/test_ontology_eval.py`

A run over the real repository asserts report structure, determinism (two runs
are equal), the always-false authority fields, and that gates are booleans; it
records but does not hard-assert their values (the coordinator reviews them).
Also test: a corrupt-cohort refusal; that a stale binding is reported rather
than raising; that v26 shadow equals baseline; and the metric functions on small
synthetic inputs, including MRR and abstention edge cases.
