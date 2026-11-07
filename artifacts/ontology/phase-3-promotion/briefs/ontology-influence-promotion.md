# Lane brief: ontology-influence-promotion (wave 3, after retrieval and schemas)

Read `COMMON.md` and `INFLUENCE_SPEC.md` (sections 2-5) first. You own
`palimnex/ontology_promotion.py` and `palimnex/tests/test_ontology_promotion.py`.
Everything else is finished and read-only to you: `ontology_influence.py`,
`retrieval.py`, `experience.py`, `ontology_eval.py` and the new schemas.

## Implement `evaluate_ontology_promotion(root, *, registry_path=None, limit=5) -> dict`

- **Registry.** Use `registry_path`, default `ontology/concept-registry.v1.json`.
  Load it as an approved registry. Refuse with a typed error if it is missing,
  ambiguous or stale: report those as `registry_unambiguous` and
  `registry_current` gate values when the registry loads, and refuse when it
  does not load at all.
- **Active influence.** Build the `ActiveInfluence` used for measurement
  directly from the loaded registry, without evidence; this is a measurement,
  not activation. Bind `implementation_digest` from
  `influence_implementation_digest()`.
- **Backends.** `local` (`client=None`) and `cache`: an offline
  `palimnex._offline_redis.FakeRedis` indexed with `cache_v3.build_index` over
  the same checkout (as `palimnex/challenge.py` does for its synthetic
  project). Never touch real Redis.
- **Suites, per backend.**
  - `v27`: the frozen search-mode cases, pinned digest checked.
  - `challenges_v26`: the synthetic project. Use the registry only if its
    project matches, which it will not, so the influenced run must equal the
    baseline.
  - `cohort`: the Phase 3 cohort cases, with the cohort's expected paths.
    Influence comes from the registry under evaluation, not the cohort's test
    registry, so this measures the real registry on those queries.
  Baseline is `retrieve_sources(influence="off")`; influenced passes the
  `ActiveInfluence`. Metric definitions are reused from `palimnex/ontology_eval.py`
  (import its helpers read-only rather than duplicating them).
- **Gates, per backend,** exactly as section 4: `off_identical` (a
  `retrieve_sources(influence="off")` call equals a fresh baseline call);
  `deterministic` (two influenced runs give identical documents); the
  regression, forbidden and abstention gates from the data; `registry_*` from
  the activation preconditions; `channels_visible`; and `bounded`.
- **Result.** The evidence document per section 4, validated with
  `validate_promotion_evidence` before returning, with `evidence_digest`,
  `status` and `activation_authorized: false`. Deterministic. Nothing is
  written to disk.

## Tests: `palimnex/tests/test_ontology_promotion.py`

Use temporary checkouts with their own approved registry and a small corpus,
plus the v27 and v26 fixtures as shipped:
- the evidence validates and its schema checks (local `referencing.Registry`);
- the document is deterministic;
- `promotable` when every gate holds; `held` when you construct a regression
  (a concept binding that pushes a critical expected path out of the top
  results);
- ambiguous, stale or missing registries handled as specified;
- an `enabled` setting activated with the produced evidence succeeds, and fails
  after any of the four implementation modules' digest changes (monkeypatch);
- the cache backend runs offline with no real Redis;
- `activation_authorized` is always false.
A real-repository run is not possible yet, because no approved registry exists;
assert that the typed error is raised.
