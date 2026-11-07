# Lane brief: ontology-phase-4-channel (wave 2, after the provider lane)

Read `COMMON.md` and `SEMANTIC_SPEC.md` section 2 first. You own
`palimnex/semantic_shadow.py`, `palimnex/tests/test_semantic_shadow.py` and
`palimnex/schemas/semantic-shadow-comparison.v1.schema.json`. The provider
module (`palimnex/semantic_local.py`) and its doubles are finished and
read-only. `palimnex/retrieval.py` is read-only: do not edit it; import its
helpers.

## Implement

`SemanticShadowError`, `SemanticChannel`, `EmbeddingMemo`, `semantic_channel`,
`semantic_shadow_retrieve`, `validate_semantic_comparison`, `policy_digest` and
the R14 constants, exactly as section 2 specifies. The comparison validator
checks the full field set, types, bounds, sorted diff lists and the constant
authority fields, and raises `SemanticShadowError("comparison_invalid", <field>)`.

## Tests: `palimnex/tests/test_semantic_shadow.py`

Use small temporary projects (`write_project`) and the doubles:
- `baseline` equals `retrieve_sources(influence="off")` byte for byte, for
  several queries and limits, local backend.
- The fused ranking equals a manual `_fuse_rankings` with the semantic channel
  added; ties break by pointer; ranking capped at `SEMANTIC_TOP_K` with
  `truncated` reported.
- Candidates require similarity strictly above 0.0.
- Abstention: a query with no baseline candidates suppresses the channel and
  the provider records no calls.
- Privacy: a runtime-built canary in the query raises
  `query_privacy_refused`, the `RecordingProvider` recorded nothing, and the
  error does not contain the canary.
- Provider failures from each double surface as `SemanticShadowError` with the
  provider reason; never a fallback.
- Memo: a second call reuses vectors (count provider calls); changing a file's
  text re-embeds only changed chunks; capacity overflow clears the memo.
- The comparison validates against its schema and the validator rejects
  tampered documents (extra field, wrong constant, unsorted diff, bad digest).
- Determinism: two calls with fresh memos give identical canonical JSON.
- `palimnex/retrieval.py` is unchanged by your work (no edits).
