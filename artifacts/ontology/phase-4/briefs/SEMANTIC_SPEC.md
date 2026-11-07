# Phase 4 shared interface: local semantic shadow experiment (v1.1)

v1.1 (before the cohort freeze, after the wave-1 review): A1 canary rule names
match `security.py`; A2 makes the paraphrase isolation rule testable.

This is the shared contract for every Phase 4 lane. Follow it exactly. The
owner's decisions are in `docs/ONTOLOGY_ADOPTION.md` ("Phase 4 provider" and
"Phase 4 thresholds" rows). The coordinator decisions R14 (channel policy) and
R15 (benchmark protocol) are recorded here **before any semantic measurement**
and must not be tuned after the cohort is frozen.

Phase 4 is evidence only. Nothing in Phase 4 changes `retrieve_sources`,
`palimnex/retrieval.py`, context v1/v2, explain-search, cache `search`,
`symbols`, `impact`, `palimnex evaluate`, `palimnex/semantic.py`
(`project-memory:semantic-provider:v1`, its +0.05/2x helper and
`semantic-status`/`semantic-gate`), or any configuration key. A `promotable`
report is not promotion authority.

## 1. Provider: `palimnex/semantic_local.py` (provider lane)

```python
PROVIDER_IDENTITY_SCHEMA = "palimnex:semantic-provider-identity:v1"
PROVIDER_ID = "palimnex-hashed-embedding"      # distinct from core.EMBEDDING_ID and cache_v3.EMBEDDING_ID
PROVIDER_REVISION = "1"
PROVIDER_DIMENSIONS = 384                      # must equal core.DIMENSIONS (assert in tests)
EMBED_TIMEOUT_MS = 2000                        # per checked_embed call
MAX_EMBED_BATCH = 1024                         # texts per call
MAX_EMBED_TEXT_BYTES = 65536                   # UTF-8 bytes per text

class SemanticProviderError(ValueError):
    reason: str; field: str                    # message: f"semantic provider refused: {reason} at {field}"

class HashedEmbeddingProvider:                 # satisfies palimnex.semantic.SemanticProvider structurally
    model_id -> PROVIDER_ID; revision -> PROVIDER_REVISION; dimensions -> PROVIDER_DIMENSIONS
    artifact_digest -> implementation_digest()
    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]
        # exactly tuple(core.embedding(text, PROVIDER_DIMENSIONS) for text in texts)

def implementation_digest() -> str
def provider_identity(provider: object) -> dict[str, Any]
def identity_digest(identity: Mapping[str, Any]) -> str
def checked_embed(provider: object, texts: Sequence[str], *, expected_dimensions: int,
                  timeout_ms: int = EMBED_TIMEOUT_MS,
                  clock: Callable[[], float] = time.monotonic) -> tuple[tuple[float, ...], ...]
```

- `implementation_digest()` is behavioural, not source-based: the SHA-256 of
  `durable.canonical_json` of
  `{"provider_id", "revision", "dimensions", "token_pattern": core.TOKEN_RE.pattern,
  "features": "unigram+adjacent-bigram", "hash": "sha256-index-mod-dimensions-sign-bit",
  "normalization": "l2", "probe_vectors": [core.encode_vector(core.embedding(p, 384)) for p in PROBES]}`
  with four fixed probe strings defined in the module (plain English, no
  secret-shaped text). Any change to tokenization, hashing or normalization
  changes it.
- `provider_identity(provider)` reads `model_id`, `revision`, `dimensions`,
  `artifact_digest` once and returns
  `{"schema": PROVIDER_IDENTITY_SCHEMA, "interface": "project-memory:semantic-provider:v1",
  "provider_id", "revision", "dimensions", "implementation_digest",
  "execution": "in_process", "network": False, "model_download": False,
  "persistent_store": False, "retrieval_influence": False}`.
  Refuse with `identity_invalid` unless `provider_id` and `revision` are
  non-empty printable strings of at most 128 characters with no secret-scan
  finding, `dimensions` is an `int` (not bool) in 8..4096, and
  `artifact_digest` is 64 lowercase hex characters. An exception raised by a
  property is `identity_invalid` (chained, not echoed).
- `identity_digest` is the SHA-256 hex of `canonical_json(identity)`.
- `checked_embed` refusals, in this order:
  `invalid_input` (not a sequence of `str`, empty batch, more than
  `MAX_EMBED_BATCH` texts, a text over `MAX_EMBED_TEXT_BYTES`);
  `provider_failed` (any `Exception` from `embed`; chained; message never
  echoed); `provider_timeout` (`clock()` difference across the call is greater
  than `timeout_ms / 1000`; the output is discarded);
  `count_mismatch` (a different number of vectors);
  `invalid_vector` (a vector that is not a sequence of real numbers; `bool` is
  not a number); `dimension_mismatch` (length differs from
  `expected_dimensions`); `non_finite` (NaN or ±Inf). It returns tuples of
  `float`. It never retries and never substitutes a fallback vector.
- Test doubles live in `palimnex/tests/semantic_doubles.py` (not a test module):
  `FakeClock`, `WrongDimensionProvider`, `NonFiniteProvider(value)`,
  `FailingProvider`, `SlowProvider(clock, advance_seconds)`,
  `WrongCountProvider`, `NonNumericProvider`, `BadIdentityProvider(field)`, and
  `RecordingProvider(inner)` which records every text it is asked to embed.
  Each double has a distinct `model_id` and a valid `artifact_digest` unless it
  is testing identity refusal.
- Schema `palimnex/schemas/semantic-provider-identity.v1.schema.json`
  (draft 2020-12, `additionalProperties: false`, constants for the boolean and
  interface fields).

## 2. Semantic channel and shadow: `palimnex/semantic_shadow.py` (channel lane)

`palimnex/retrieval.py` is **not edited** (it is covered by the ontology
influence implementation digest). The channel module imports
`retrieval._retrieve_sources_with_state` and `retrieval._fuse_rankings`
read-only.

### R14 — channel policy, fixed before measurement

```python
COMPARISON_SCHEMA = "palimnex:semantic-shadow-comparison:v1"
POLICY_SCHEMA = "palimnex:semantic-channel-policy:v1"
SEMANTIC_TOP_K = 64          # ranked candidates contributed to fusion
SIMILARITY_FLOOR = 0.0       # a chunk is a candidate only if cosine > 0.0 (strict)
MEMO_CAPACITY = 20000        # in-process vectors; cleared entirely when full; never persisted
CHANNELS = ("lexical", "symbol", "graph", "semantic")
```

- Cosine similarity is `dot(q, c) / (|q| * |c|)` in float arithmetic, summed in
  ascending dimension index order; a zero-norm vector has similarity 0.0. The
  implementation may skip zero query components, provided the summation order
  stays ascending and results are identical.
- Candidates are chunks with similarity `> SIMILARITY_FLOOR`, ordered by
  `(-similarity, pointer)`; the channel ranking is the first `SEMANTIC_TOP_K`
  chunk indices. `candidate_count` counts all candidates before the cap;
  `truncated` is `candidate_count > SEMANTIC_TOP_K`.
- **Abstention rule:** if the uninfluenced baseline has `candidate_count == 0`,
  the semantic channel is suppressed (empty ranking, `suppressed:
  "baseline_abstained"`) and the provider is not called. Otherwise
  `suppressed` is `null`.
- **Privacy rule:** the query is checked with `security.scan_text` before any
  provider call; a finding raises `SemanticShadowError("query_privacy_refused",
  "query")` and the provider is never called. Chunks come only from the admitted
  `cache_v3.source_snapshot`, whose admission scan already ran.
- **Fusion:** the shadow ranking is `_fuse_rankings(state.chunks,
  state.rankings + (("semantic", channel.ranking),), limit=..., byte_budget=...)`:
  the same RRF K=60, `(-score, pointer)` tie-break, 512 cap and byte budget as
  production.
- **Memo:** `EmbeddingMemo` maps `(provider identity digest, sha256(chunk text))`
  to a vector. Misses are embedded with `checked_embed` in batches of at most
  `MAX_EMBED_BATCH`. Query vectors are not memoized. Because keys are content
  digests, a changed chunk is always re-embedded (source-drift safety).
- `policy_digest()` = SHA-256 of `canonical_json` of `{"schema": POLICY_SCHEMA,
  "top_k", "similarity_floor", "memo_capacity", "rrf_k": retrieval.RRF_K,
  "abstention": "suppress_when_baseline_has_no_candidates",
  "privacy": "scan_query_before_provider", "channels": list(CHANNELS)}`.

### Public API

```python
class SemanticShadowError(ValueError): reason, field   # "semantic shadow refused: {reason} at {field}"
@dataclass(frozen=True) class SemanticChannel:
    ranking: tuple[int, ...]; candidate_count: int; truncated: bool; suppressed: str | None
class EmbeddingMemo: def __init__(self, capacity: int = MEMO_CAPACITY) -> None; def __len__(self) -> int
def semantic_channel(provider, query, chunks, *, memo, baseline_candidate_count) -> SemanticChannel
def semantic_shadow_retrieve(query, *, provider, root=core.ROOT, limit=5, byte_budget=8192,
        include_graph=True, client=None, snapshot=None, memo=None) -> dict   # {"baseline", "comparison"}
def validate_semantic_comparison(document: Mapping[str, Any]) -> None
def policy_digest() -> str
```

- `semantic_shadow_retrieve` computes the baseline with
  `_retrieve_sources_with_state(..., influence="off")`; `baseline` in the
  result must equal `retrieve_sources(..., influence="off")` byte for byte.
  Provider errors (`SemanticProviderError`) are re-raised as
  `SemanticShadowError` with the same `reason`; there is no fallback.
  `memo=None` means a fresh memo for that call.
- `comparison` (`palimnex:semantic-shadow-comparison:v1`), all keys required,
  `additionalProperties: false` at every level:
  `schema`, `query_digest` (SHA-256 hex of the UTF-8 query; the query text is
  not repeated), `limit`, `byte_budget`, `channels` (= `CHANNELS`), `provider`
  (the identity document), `provider_identity_digest`, `policy_digest`,
  `semantic_channel` `{candidate_count, ranked_count, truncated, suppressed,
  top_k, similarity_floor}`, `baseline` `{pointers, candidate_count,
  items_bytes}`, `shadow` `{items, candidate_count, items_bytes}` where each item
  is `{pointer, path, start_line, end_line, content_digest, score, channels}`
  (no chunk text), `diff` `{identical, added, removed}` (pointer lists, sorted),
  `corpus_fingerprint`, `retrieval_influence: false`,
  `promotion_authorized: false`, `authorizes_actions: false`.
- Schema `palimnex/schemas/semantic-shadow-comparison.v1.schema.json`.

## 3. Frozen semantic cohort: `palimnex/evaluation/semantic-shadow.v1.json` (cohort lane)

Schema id `palimnex:semantic-shadow-cohort:v1`; JSON Schema
`palimnex/schemas/semantic-shadow-cohort.v1.schema.json`.

```json
{
  "schema": "palimnex:semantic-shadow-cohort:v1",
  "status": "frozen",
  "description": "...",
  "cases": [ /* repository cases */ ],
  "projects": { "<project-id>": { "documents": {"path": "text"}, "after": {"path": "text or null"} } },
  "project_cases": [ /* drift and privacy cases */ ]
}
```

- **Repository case:** `{id, category, query, limit: 5, expected_paths,
  forbidden_paths, critical, note}`. Categories and minimum counts:
  `paraphrase` ≥ 8, `synonym` ≥ 6, `ambiguity` ≥ 3 (two or more expected paths;
  the query plausibly refers to each), `negative` ≥ 5 (no expected paths;
  unrelated to the repository), `control` ≥ 4 (direct, lexical questions; at
  least two `critical: true`). Only `control` cases may be critical. Expected
  paths are runtime files under `palimnex/*.py` (not tests, not docs) that a
  reader would agree answer the query. Queries must not copy identifiers or
  distinctive phrases from the expected file (paraphrase and synonym cases
  should use different words from the code), must be at most 200 characters,
  must not repeat any query from `palimnex/evaluation/ontology-shadow.v1.json`,
  and must be written from the source alone. Amendment A2 (v1.1): a
  paraphrase or synonym query shares no identifier-shaped token (containing
  `_` or an internal capital) and no run of three consecutive lowercase words
  with its expected file, and avoids distinctive two-word phrases from that
  file's docstrings, error messages and names; the structural tests enforce the
  first two rules. **Do not run any retrieval,
  evaluation, embedding or palimnex command to choose or tune cases.**
- **Projects** are small synthetic repositories (2–6 files, each under 4 KiB)
  for drift and privacy cases; `after` lists the file changes applied for the
  drift step (`null` deletes the file).
- **Project case:** `{id, category, project, query, expected_paths,
  forbidden_paths, note}` plus:
  - `drift` (≥ 2): the topic moves from one file to another between
    `documents` and `after`; `expected_paths` is the post-drift location and
    `forbidden_paths` the pre-drift location.
  - `privacy_canary` (≥ 3): `canary_kind` is `"query"` or `"corpus"` and
    `canary_rule` is one of `aws-access-key`, `github-token`, `openai-token`
    (the `palimnex/security.py` rule names; amendment A1, v1.1).
    The string `{canary}` appears exactly once, in the query (query kind) or in
    one project document (corpus kind). At least two query cases with different
    rules and at least one corpus case. `expected_paths` and `forbidden_paths`
    are empty for query cases; for corpus cases, `forbidden_paths` lists the
    canary file.
- The file contains **no secret-shaped text**: `security.scan_bytes` on the raw
  file returns no findings. Canaries are built only at runtime by the evaluator.
- Ids are unique lowercase `[a-z0-9-]+`. The file is UTF-8 with sorted keys
  and a trailing newline.
- After review, the coordinator records its SHA-256 in
  `artifacts/ontology/phase-4/integration/cohort-freeze.json`; from then on the
  cohort is immutable (labels, queries, paths, categories) and the evaluator
  pins that digest.

## 4. Evaluation: `palimnex/semantic_eval.py` (evaluation lane)

```python
EVALUATION_SCHEMA = "palimnex:semantic-shadow-evaluation:v1"
PROMOTION_POLICY = {"schema": "palimnex:semantic-promotion-policy:v2", "limit": 5,
    "min_mrr_gain": 0.02, "min_recall_gain": 0.02, "min_additional_passes": 1,
    "max_p95_multiplier": 1.5, "gain_rule": "mrr_or_recall"}
COHORT_PATH = Path("palimnex/evaluation/semantic-shadow.v1.json"); COHORT_SHA256 = "<from cohort-freeze.json>"
class SemanticEvaluationError(ValueError): reason, field
def evaluate_semantic_shadow(root: Path = core.ROOT, *, provider: object | None = None,
                             benchmark: bool = True,
                             clock_ns: Callable[[], int] = time.perf_counter_ns) -> dict[str, Any]
```

`provider=None` means `HashedEmbeddingProvider()`. The limit is fixed at 5.
The new policy is a new contract; `palimnex/semantic.py` is unchanged.

### Suites (local backend, `client=None`)

| Suite | Cases | Role |
| --- | --- | --- |
| `v27` | frozen search-mode cases, pinned digest (reuse `ontology_eval._load_v27_cases`) | protected |
| `challenges_v26` | synthetic project (reuse `ontology_eval._load_v26`, `write_project`) | protected |
| `ontology_cohort` | Phase 3 cohort queries and labels (`ontology_eval._load_cohort_document`, `_cohort_cases`), no registry | protected |
| `semantic_cohort` | repository cases of the frozen cohort | gain + regression |
| `drift` | project cases, run on `documents` then on `after` | source-drift gate |
| `privacy` | project cases with runtime canaries | privacy gate |

For each case: `semantic_shadow_retrieve` plus a direct
`retrieve_sources(influence="off")` at the same arguments. Outcomes reuse
`ontology_eval._variant_outcome` (baseline vs shadow paths). Use one memo per
suite run. Pin the cohort digest (`fixture_digest_mismatch` refusal).

### Gates (all must be true for `status: "promotable"`; otherwise `"held"`)

1. `baseline_identical` — every comparison baseline equals the direct
   `retrieve_sources(influence="off")` result (canonical JSON).
2. `no_critical_regression` — no critical case in any suite passes in baseline
   and fails in shadow.
3. `no_case_regression` — no case in any suite passes in baseline and fails in
   shadow.
4. `protected_recall_not_reduced` — on `v27`, `challenges_v26` and
   `ontology_cohort`, shadow `recall_at_limit` ≥ baseline.
5. `cohort_gain` — on the semantic cohort's scored cases (categories
   `paraphrase`, `synonym`, `ambiguity`, `control`): MRR gain ≥ 0.02 **or**
   recall gain ≥ 0.02 (compare with a 1e-12 tolerance).
6. `cohort_additional_pass` — at least one scored cohort case fails in
   baseline and passes in shadow.
7. `no_new_forbidden` — per case, shadow forbidden hits ⊆ baseline forbidden
   hits.
8. `abstention_not_regressed` — per case, baseline abstained ⇒ shadow
   abstained; and per suite, shadow `negative_abstention` ≥ baseline.
9. `ambiguity_not_collapsed` — on ambiguity cases, shadow found count ≥
   baseline found count.
10. `source_drift` — for every drift case, after applying `after` in the same
    temporary checkout with the **same memo**: the corpus fingerprint changed;
    every shadow item's `content_digest` equals the SHA-256 of the current chunk
    text at its pointer; no shadow result is on a `forbidden_paths` file; and the
    shadow passes whenever the baseline passes.
11. `privacy_canary` — query cases raise `SemanticShadowError` with reason
    `query_privacy_refused`, a `RecordingProvider` wrapper recorded no text
    containing the canary, and the error string does not contain it. Corpus
    cases: the snapshot refusal is raised before any provider call and its string
    does not contain the canary. The canonical JSON of the whole report never
    contains any canary.
12. `deterministic` — re-running the semantic cohort with a fresh memo yields
    identical canonical comparison digests.
13. `provider_identity_bound` — the identity is valid, identical before and
    after the run, and every comparison carries the same identity digest; for
    `HashedEmbeddingProvider`, `artifact_digest == implementation_digest()`.
14. `latency_within_bound` — semantic p95 ≤ 1.5 × baseline p95 under R15.
    When `benchmark=False` the gate is `false` and `held_reasons` includes
    `benchmark_not_run`.
15. `channels_visible` and `bounded` — comparisons validate, item channels ⊆
    `CHANNELS`, ranks are in 1..512, and counts are within limits.

Canaries are built at runtime from fragments (never a literal in source or
fixtures), for example `"".join(("AK", "IA")) + 16 fixed uppercase or digit
characters`, and checked to match `security.scan_text` for their rule.

### R15 — benchmark protocol, fixed before measurement

`palimnex:semantic-benchmark-protocol:v1`: local backend; queries are the
semantic cohort repository cases in file order; one shared memo; one warm-up
pass over all queries for both variants (discarded); then 3 measured
repetitions; within each repetition, for each query, run baseline
(`retrieve_sources(influence="off")`) and candidate (`semantic_shadow_retrieve`)
back to back, baseline first on even repetitions and candidate first on odd
ones; time each call with `clock_ns`; p95 is the nearest-rank 95th percentile
(`ceil(0.95 * n)`-th smallest) over all measured samples of a variant. The
report records the protocol, sample counts and p95 values in milliseconds.
Timings are excluded from the determinism comparison.

### Report (`palimnex:semantic-shadow-evaluation:v1`)

`{schema, cohort_digest, provider, provider_identity_digest, policy_digest,
promotion_policy, benchmark_protocol, benchmark` (`{run, baseline_p95_ms,
semantic_p95_ms, multiplier_limit, samples_per_variant}` or nulls when not run)`,
suites` (per suite `{baseline, shadow` metric summaries as in
`ontology_eval._metric_summary`, plus `cases` rows with `id, category, critical,
baseline_pass, shadow_pass, baseline_first_relevant_rank,
shadow_first_relevant_rank, semantic_candidate_count, suppressed}`)`,
cohort_scored` `{baseline_mrr, shadow_mrr, mrr_gain, baseline_recall,
shadow_recall, recall_gain, additional_pass_ids}`, `gates`, `held_reasons`
(sorted names of false gates plus `benchmark_not_run` when applicable),
`status`, `promotion_authorized: false`, `retrieval_influence: false`,
`authority: "evidence_only"`, `authorizes_actions: false}`. It validates against
`palimnex/schemas/semantic-shadow-evaluation.v1.schema.json` and is canonical
JSON safe. Nothing is written to disk except temporary checkouts.

## 5. Integration (coordinator, not delegated)

`palimnex evaluate-semantic-shadow` prints the report (exit 0 promotable, 2
held, 1 refused); mypy list; CHANGELOG; COMPATIBILITY; full gate.
