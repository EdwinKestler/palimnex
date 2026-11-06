# Lane brief: ontology-phase-0-registry-contract

Read `COMMON.md` in this folder first. You own
`artifacts/design/ontology-phase-0/registry/` and your receipt file.

## Deliverables

1. `registry/concept-registry.v1.schema.json`, the draft schema for
   `palimnex:concept-registry:v1`. It must cover every field in the design's
   "`palimnex:concept-registry:v1`" section:
   - project identity (match `.palimnex.json` `project_slug`/`project_id`) and
     registry version;
   - concepts with a stable `concept_id` pattern, `canonical_name`, bounded
     normalized `aliases`, `definition`, and optional typed relations from a
     small closed vocabulary that you propose;
   - `source_bindings` as `palimnex:source-locator:v1` objects. Reuse the
     existing shape: `$ref` the `$id` of `palimnex/schemas/source-locator.v1.schema.json`,
     loaded into a local registry by the check script. Do not invent a locator.
   - lifecycle `candidate | approved | superseded | withdrawn`, predecessor or
     supersession identity, provenance `manual | deterministic | model_candidate`;
   - `registry_digest`, `authority: historical_only`, `authorizes_actions: false`.
   Bound every size (concept count, aliases per concept, string lengths,
   bindings per concept, total file bytes noted in the semantics).
2. `registry/SEMANTICS.md`, covering:
   - lifecycle transitions and what "approved" means: a reviewed, committed
     repository change, never a runtime badge or boolean set by a tool;
   - candidate and approved separation: candidates live outside the approved
     read path, and a model_candidate cannot become approved except through a
     reviewed change;
   - alias normalization (Unicode normalization form, case folding, whitespace,
     punctuation) defined precisely enough to implement deterministically;
   - ambiguity: when two approved concepts share a normalized alias the loader
     keeps both and the match is `ambiguous`; decide and justify whether the
     loader also rejects such registries or only reports them;
   - supersession: an acyclic chain, superseded and withdrawn concepts never
     match, and what happens to bindings;
   - source drift: how `palimnex/locators.py` already detects digest change,
     and that a drifted binding makes the concept stale (never covered);
   - canonical digest: Palimnex canonical JSON (`palimnex/durable.py`
     `canonical_json`) over the registry with `registry_digest` excluded;
   - privacy: source bytes pass `palimnex/security.py` scanning before any
     alias or definition derivation, and refusals never echo values;
   - open questions for the owner.
3. `registry/examples/valid/*.json` (at least 3: minimal; multi-concept with
   relations; supersession chain) and `registry/examples/invalid/*.json` (at
   least 6, each failing for one stated reason, such as an extra field, a bad
   concept ID, an oversize alias list, a bad locator digest, wrong
   `authorizes_actions`, or an unknown status). Name each invalid file after
   its reason.
4. `registry/check_registry_contract.py`, offline: checks the schema with
   `Draft202012Validator.check_schema`, requires every valid example to pass
   and every invalid example to fail, and recomputes `registry_digest` for
   the valid examples with `canonical_json`, failing on mismatch. Exit 0 only
   when everything holds. Log clearly.

Coverage-receipt work belongs to another lane; reference it, don't define it.
