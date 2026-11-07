# Lane brief: ontology-influence-gate (wave 1, parallel with the schemas lane)

Read `COMMON.md` and `INFLUENCE_SPEC.md` (sections 1, 2 and 4) first. You own
`palimnex/ontology_influence.py`, `palimnex/tests/test_ontology_influence.py`
and `docs/ONTOLOGY_INFLUENCE.md`. The retrieval and promotion lanes build on your
API next, so match section 2 exactly: names, signatures, field order of checks
and disclosure keys.

## Implement

- The setting parser (section 1). It reads `.palimnex.json` through the
  existing `palimnex.core.project_config` or the same bounded JSON read, and
  validates every rule. A malformed setting is a typed error in every mode.
- `activate_influence` with the four ordered checks. Reuse
  `palimnex.concepts` (`load_registry`, `normalize_alias`,
  `verify_source_bindings`), `palimnex.security` (bounded reads and privacy
  scan) and `palimnex.durable.canonical_json`. Never reimplement them.
  Ambiguity means one normalized key on two or more approved concepts,
  canonical-name keys included.
- `influence_implementation_digest()` per section 2: hash the module source
  files as shipped (`importlib`/`__file__`, bounded reads), sorted by module
  name.
- `validate_promotion_evidence` mirrors section 4 in plain Python: exact keys,
  types and bounds, `status` consistent with the gates, `activation_authorized`,
  `authority` and `authorizes_actions` constants, and `evidence_digest`
  recomputation.
- `influence_disclosure`, `context_v2` and `explain_search_v2` per section 2.
  Inputs are deep-copied, never mutated.
- `OntologyInfluenceError(ValueError)` with stable reasons, for example
  `setting_invalid`, `registry_digest_mismatch`, `registry_ambiguous`,
  `registry_stale`, `evidence_missing`, `evidence_digest_mismatch`,
  `evidence_invalid`, `evidence_registry_mismatch`,
  `evidence_implementation_mismatch`, `evidence_not_promotable` and
  `evidence_backends_incomplete`. It never echoes values.

## Tests: `palimnex/tests/test_ontology_influence.py`

Use temporary checkouts with real registries, real digests and real evidence
documents that you build in the test. Cover: a missing key and an explicit off
or shadow return `None`; every malformed-setting variant; a happy enabled path;
and each refusal reason, in the order the spec gives:
- a wrong registry digest, a candidate registry, a foreign project;
- an alias collision, including a canonical-name collision;
- a stale binding (change the source after binding);
- missing evidence, evidence with a tampered byte, evidence for another
  registry, another implementation digest, `held` status, or a missing `cache`
  backend.
Also cover: a privacy canary in a registry definition or in evidence, refused
with no echo; implementation digest stability, and that it changes when any of
the four modules' bytes would differ (monkeypatch the file list into a temporary
copy); the disclosure shape; context and explain-search v2 wrappers keeping every
v1 key; and no input mutated.

## Docs: `docs/ONTOLOGY_INFLUENCE.md`

Cover: what influence changes and what it does not (search, symbols, impact,
palimnex evaluate); the three modes; how the owner activates it (run the
promotion evaluation, save the evidence, set the digests); every refusal; the v2
results; rollback with `mode: off`; and that registry presence never turns it
on. Link the design, CONCEPT_REGISTRY, COVERAGE_RECEIPT and ONTOLOGY_SHADOW docs.
Do not document CLI flags beyond those in section 5.
