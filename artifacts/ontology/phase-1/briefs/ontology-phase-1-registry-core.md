# Lane brief: ontology-phase-1-registry-core

Read `COMMON.md` first. You own `palimnex/concepts.py` and
`palimnex/tests/test_concepts.py`. The frozen-conformance lane builds on your
public API after you finish, so make the API explicit, documented and stable.

## Implement `palimnex/concepts.py`

Implement the behavior specified by the accepted `registry/SEMANTICS.md` and
the registry schema. At minimum, provide:

- Constants: `REGISTRY_SCHEMA = "palimnex:concept-registry:v1"` and the
  accepted bounds (registry bytes, concept count, alias and field limits) as
  module constants taken from the accepted contract.
- `ConceptRegistryError(ValueError)` with a stable `reason` code and no echoed
  values.
- `normalize_alias(text: str) -> str`: NFKC, `str.casefold`, punctuation to
  space and whitespace collapse, exactly as SEMANTICS.md defines.
- `canonical_registry_digest(document) -> str`: SHA-256 of
  `palimnex.durable.canonical_json` over the document with `registry_digest`
  excluded.
- A structural validator in plain Python that mirrors the JSON Schema: exact
  key sets, types, patterns (the R1 concept ID), bounds, lifecycle values,
  provenance, `authority`, `authorizes_actions: false`, source bindings as
  `palimnex:source-locator:v1` objects (reuse `palimnex.locators.SourceLocator`
  parsing where possible), stored aliases already normalized, and supersession
  rules. Placeholder digests are accepted only behind an explicit keyword-only
  flag used by fixtures, never by default.
- Frozen dataclasses for the parsed registry and concepts, and a parser that
  enforces `registry_kind` candidate/approved separation as the contract
  defines.
- `load_registry(path, *, root, ...)`: bounded read through
  `palimnex.security.read_bounded_file` (or the equivalent bounded helper),
  privacy scan before any derivation, then parse and verify the digest. The path
  is passed explicitly; no default location, config key or environment lookup.
- Exact-alias matching over a query: tokenize and normalize deterministically,
  match only approved, non-superseded, non-withdrawn concepts, and return
  recognized concepts with matched aliases plus explicit ambiguity (an alias
  that resolves to two or more concepts is never silently resolved).
  Deterministic ordering everywhere.
- Source-binding verification through `palimnex.locators` resolvers: a drifted
  or missing binding marks the concept stale and is reported, never raised as a
  generic failure and never silently dropped. Traversal, symlink and
  cross-project bindings are typed refusals (R7).
- Shadow-only: nothing in the module touches retrieval, cache, ledger, CLI or
  config.

## Tests: `palimnex/tests/test_concepts.py`

Cover the Phase 1 exit gate in the design: exact fields, sizes, identity, alias
normalization (Unicode, case, whitespace), canonical digest stability and
tamper detection, candidate/approved separation, conflicting aliases reported as
ambiguity, supersession and withdrawal exclusion, source drift reported as
stale, traversal and symlink refusal, a secret canary refused before derivation
without echo, oversize input refusal, and deterministic ordering. Use temporary
directories as roots.

Acceptance also runs strict mypy on `palimnex/concepts.py`.
