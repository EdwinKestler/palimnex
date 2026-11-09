# Ontology shadow channel

Palimnex Phase 3 adds a deterministic ontology channel beside the existing
lexical, symbol, and graph retrieval channels. It is evidence-only: shadow
calculation never changes the result returned by `retrieve_sources`, `search`,
`context`, or `explain-search`. Promotion to retrieval influence requires a
separate owner approval and is not represented by this contract.

The versioned 2.10 module contract is `palimnex.ontology_shadow`; it is not an
addition to the public `Palimnex` SDK v1 class:

- `ontology_channel(registry, query, chunks, *, root, resolvers=None)` returns
  a frozen `OntologyChannel` whose ranking contains indexes into `chunks`;
- `build_shadow_comparison(...)` produces
  `palimnex:ontology-shadow-comparison:v1`; and
- `validate_shadow_comparison(document)` applies the runtime structural,
  boundedness, digest, ordering, and cross-field checks.

The public Draft 2020-12 schema is
`palimnex/schemas/ontology-shadow-comparison.v1.schema.json`.

## Channel ranking

The channel accepts only an `approved_registry`. An absent registry produces an
empty channel. Alias recognition uses `palimnex.concepts.match_aliases`, and
current source support uses `verify_source_bindings`; the channel does not
reimplement normalization or source verification.

A concept contributes when it is recognized, unambiguous, and has at least one
applicable binding that reopens, passes privacy admission, and verifies its
version, range, and digest. A chunk qualifies when a verified `repo` binding
for a contributing concept has the same source path and an overlapping line
range. Line ranges and chunk ranges are inclusive. Source-locator byte ranges
remain half-open; a non-empty byte range maps from the line containing its
first byte through the line containing its final included byte. A newline byte
belongs to the line it terminates. Empty byte ranges overlap no chunk.

Each chunk scores by the number of distinct contributing concepts that overlap
it. Ranking is deterministic: descending score, then ascending pointer. At
most 512 chunk indexes are returned, with `candidate_count` recording the
pre-cap count and `truncated` disclosing whether the cap applied. Verified
non-`repo` bindings can establish concept coverage but do not map to repository
chunks.

Ambiguous concepts never contribute. A recognized concept with no applicable
binding is listed in `excluded_uncovered`; one with applicable binding material
but no verified binding is listed in `excluded_stale`. Candidate registries are
refused. Unsafe paths, project mismatches, symlinks, and privacy refusals remain
typed failures rather than being converted into an exclusion state.

## Comparison document

The comparison document contains only query and registry digests, result
pointers, channel ranks, bounded counts, and the baseline-versus-shadow diff.
It never contains the raw query, source text, or excerpts. Its canonical
`comparison_digest` is SHA-256 over canonical JSON with only that digest field
removed.

Every comparison states:

- `retrieval_influence: false`;
- `returned_ranking_changed: false`;
- `authority: "evidence_only"`; and
- `authorizes_actions: false`.

The runtime validator additionally checks that pointer ranks are one-based and
unique, channel ranks are valid, membership and overlap diffs agree with both
rankings, ontology classifications are disjoint and complete, and the digest
matches the document.

Shadow evidence is visible only through `palimnex evaluate-ontology-shadow`.
It is not added to ordinary retrieval output. The coordinator-owned evaluation
command compares the frozen baseline and shadow cohorts; passing that
evaluation is evidence, not promotion authority.

See the approved [ontology adoption design](ONTOLOGY_ADOPTION.md), the
[concept-registry contract](CONCEPT_REGISTRY.md), and the
[coverage-receipt semantics](COVERAGE_RECEIPT.md).
