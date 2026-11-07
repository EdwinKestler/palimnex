# Lane brief: ontology-phase-4-provider (wave 1)

Read `COMMON.md` and `SEMANTIC_SPEC.md` section 1 first. You own
`palimnex/semantic_local.py`, `palimnex/tests/test_semantic_local.py`,
`palimnex/tests/semantic_doubles.py` and
`palimnex/schemas/semantic-provider-identity.v1.schema.json`.

## Implement

- `HashedEmbeddingProvider`, `implementation_digest`, `provider_identity`,
  `identity_digest`, `checked_embed`, `SemanticProviderError` and the constants,
  exactly as section 1 specifies.
- The provider wraps `core.embedding` unchanged. It never caches, persists,
  downloads, opens a network connection or spawns a process.
- The test doubles in `palimnex/tests/semantic_doubles.py`, each small and
  deterministic. `SlowProvider` advances a `FakeClock` instead of sleeping.

## Tests: `palimnex/tests/test_semantic_local.py`

- `HashedEmbeddingProvider().embed(texts)` equals `core.embedding` for a few
  texts; `PROVIDER_DIMENSIONS == core.DIMENSIONS`; the provider satisfies
  `palimnex.semantic.SemanticProvider` structurally (attribute presence and
  types); `PROVIDER_ID` differs from `core.EMBEDDING_ID` and
  `cache_v3.EMBEDDING_ID`.
- `implementation_digest()` is stable across calls and changes when
  `core.embedding` is monkeypatched to behave differently.
- The identity document validates against the schema (local
  `referencing.Registry`, no network) and `identity_digest` is stable.
- Every `checked_embed` refusal reason, using the doubles: `invalid_input`
  (non-list, non-str, empty, too many, too large), `provider_failed` (message
  not echoed: assert a distinctive marker in the double's exception text is
  absent from the refusal string), `provider_timeout` (FakeClock),
  `count_mismatch`, `invalid_vector` (including `bool` and strings),
  `dimension_mismatch`, `non_finite` (NaN, +Inf, -Inf).
- `provider_identity` refusals with `BadIdentityProvider` for each field.
- `palimnex/semantic.py` behaviour is unchanged: `semantic_status` still
  reports `disabled` and `retrieval_influence: false`.
