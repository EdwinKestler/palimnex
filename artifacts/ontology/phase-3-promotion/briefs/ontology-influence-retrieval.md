# Lane brief: ontology-influence-retrieval (wave 2, after the gate lane)

Read `COMMON.md` and `INFLUENCE_SPEC.md` (sections 1-3) first. You own
`palimnex/retrieval.py`, `palimnex/experience.py`, `palimnex/ontology_eval.py`,
`palimnex/tests/test_retrieval_influence.py` and
`palimnex/tests/test_ontology_eval.py`. `palimnex/ontology_influence.py` is
finished and read-only to you. `retrieval.py` and `experience.py` serve
`context` and `explain-search`: when the setting is missing, off or shadow,
their output must not change by a single byte.

## Step 0: capture golden outputs BEFORE editing

As in Phase 3, before touching any file record canonical-JSON SHA-256 digests
of today's `retrieve_sources` and `assemble_context` (without a ledger) over a
fixed temporary corpus (at least 10 queries; graph on and off; two limits and
budgets) and embed them as test constants. Repository-corpus results are a
same-run equality check, not pinned constants.

## Implement

- `retrieve_sources(..., influence="config")` per section 3. `"config"` uses
  `read_influence_setting(root)`. `off`, `shadow` and `"off"` follow today's
  exact path. For `enabled`, call `activate_influence` (its errors propagate,
  never caught), compute `ontology_channel` with the active registry, and fuse
  the four channels with the existing shared fusion helper. Add
  `"ontology_influence": influence_disclosure(...)`. An `ActiveInfluence`
  instance may also be passed directly (the promotion evaluation does this).
- `shadow_retrieve`: its baseline is always uninfluenced (pass `"off"`
  internally).
- `assemble_context`: return `context_v2(...)` when the sources carry
  `ontology_influence`; otherwise return v1 unchanged.
- `palimnex/ontology_eval.py`: pass `influence="off"` to every direct
  `retrieve_sources` call. Change nothing else; the Phase 3 gates must keep the
  same values. Update `test_ontology_eval.py` only where needed, and add one test
  proving the evaluation baseline stays uninfluenced when the checkout's setting
  is `enabled`.

## Tests: `palimnex/tests/test_retrieval_influence.py`

- Golden digests match for both functions.
- A missing setting, explicit off and shadow give outputs equal to the golden
  outputs and contain no `ontology_influence` key.
- In a temporary checkout with a real approved registry and a real promotion
  evidence document (build a minimal valid one with the gate lane's validator;
  set `implementation_digest` to `influence_implementation_digest()`):
  - enabled changes ranking where a concept binds a low-ranked chunk;
  - the output carries the disclosure and `ontology` channel ranks;
  - `context` returns v2 with every v1 key;
  - the `limit`, budget and cap are respected.
- Every activation refusal propagates out of `retrieve_sources` and
  `assemble_context` (stale, ambiguous, digest mismatch, missing evidence);
  never a fallback.
- `shadow_retrieve` baseline unchanged under an enabled setting.
- Cache backend: with an offline `palimnex._offline_redis.FakeRedis` index
  (`cache_v3.build_index`), enabled influence works and discloses, and off is
  identical to today.
- `test_explain_search`, `test_coverage`, `test_experience` and
  `test_challenge` are in your acceptance commands. Keep them green.
