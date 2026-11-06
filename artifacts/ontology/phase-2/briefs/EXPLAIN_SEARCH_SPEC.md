# `palimnex:explain-search:v1` (coordinator specification, shared by all Phase 2 lanes)

Owner decision (2026-11-06): `palimnex explain-search` prints ONE new document
in which the unchanged `search` result and the coverage receipt are sibling
objects. The registry is loaded from `ontology/concept-registry.v1.json` by
default, or from `--registry PATH`. A missing file means coverage is disabled.

```json
{
  "schema": "palimnex:explain-search:v1",
  "search": { "...": "the unchanged palimnex.retrieval.retrieve_sources result for the same query (R10)" },
  "coverage_state": "enabled",
  "coverage": { "schema": "palimnex:retrieval-coverage:v1", "...": "..." },
  "registry": { "path": "ontology/concept-registry.v1.json", "source": "default" },
  "authority": "evidence_only",
  "authorizes_actions": false
}
```

Rules:
- Exactly these seven keys; no others.
- `search` is an object, consumed and emitted unchanged, never re-ranked,
  filtered or annotated. The wrapper schema constrains it only as `type: object`.
- `coverage_state` is `"enabled"` or `"registry_absent"`. `coverage` is a full
  `palimnex:retrieval-coverage:v1` receipt when enabled, and `null` exactly when
  `registry_absent`.
- `registry.path` is the repository-relative, traversal-free path that was
  used, or would have been used (max 512). `registry.source` is `"default"` or
  `"argument"`. An absent default file gives `registry_absent`. An explicit
  `--registry` that does not exist is a typed error, not `registry_absent`.
- Any typed refusal (an invalid registry, a non-approved `registry_kind`, a
  cross-project registry, a privacy refusal, a traversal or symlink binding, or
  a malformed query) produces no document and a non-zero exit with a
  non-echoing error. This is R7.
- The raw query appears only inside `search` (existing behavior). It is not
  added anywhere else, and the coverage receipt carries only `query_digest`.
- The document is printed, never persisted.
