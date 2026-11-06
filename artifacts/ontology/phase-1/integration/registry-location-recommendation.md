# Registry location recommendation (non-authorizing)

Date: 2026-11-06

## Recommendation

Use this committed repository-relative path for the reviewed approved registry:

```text
ontology/concept-registry.v1.json
```

Keep generated or imported candidate sets under:

```text
artifacts/ontology/candidates/
```

The approved registry should **not** be added to Palimnex's ordinary source
index. Phase 2 should load it directly and explicitly as
`palimnex:concept-registry:v1`; absence means ontology coverage is disabled.
Candidate sets remain outside both the approved read path and the ordinary
source index.

## Rationale

- The path is stable, visible, repository-local, and separate from code,
  documentation, disposable `.palimnex/` state, and generated candidates.
- The versioned filename makes a future reader-breaking registry format an
  explicit new artifact rather than an in-place reinterpretation.
- Direct loading preserves the registry digest, project identity, privacy
  admission, and source-binding checks implemented in Phase 1.
- Excluding the registry from the ordinary source index avoids counting the
  ontology's own labels as independent source evidence and avoids a circular
  source-search signal. Source files named by registry bindings remain indexed
  under the existing policy.
- Candidate-to-approved promotion remains a reviewed repository change that
  rewrites selected entries into the single approved registry; persistence or
  agent output alone cannot promote them.

## Authority boundary

This recommendation does not create the path, alter `.palimnex.json`, add a
configuration key or CLI command, enable coverage, influence retrieval, or
approve Phase 2. Those changes require the repository owner's explicit
registry-location decision and separate Phase 2 approval.
