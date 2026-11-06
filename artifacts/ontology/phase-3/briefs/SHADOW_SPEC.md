# Phase 3 shadow specification (coordinator, shared by all Phase 3 lanes)

The design says to "add an optional concept/alias channel to the existing
rank-fusion design. Shadow mode calculates comparison output but cannot alter
returned ranking." Owner decisions (2026-11-06): the shadow is visible only
through `palimnex evaluate-ontology-shadow`, and it is evaluated against a
frozen, evaluation-only test registry.

## 1. Ontology channel (`palimnex/ontology_shadow.py`, channel lane)

```python
MAX_ONTOLOGY_CANDIDATES = 512

@dataclass(frozen=True)
class OntologyChannel:
    ranking: tuple[int, ...]                 # chunk indexes into `chunks`, best first, len <= 512
    recognized_concept_ids: tuple[str, ...]
    ambiguous_concept_ids: tuple[str, ...]
    contributing_concept_ids: tuple[str, ...]
    excluded_ambiguous: tuple[str, ...]
    excluded_stale: tuple[str, ...]
    excluded_uncovered: tuple[str, ...]
    candidate_count: int                     # qualifying chunks before the cap
    truncated: bool

def ontology_channel(registry: ConceptRegistry | None, query: str,
                     chunks: Sequence[Mapping[str, Any]], *, root: Path,
                     resolvers: Mapping[str, SourceResolver] | None = None) -> OntologyChannel
```

- `registry is None` gives an empty channel (all tuples empty, 0, False).
- The registry must have kind `approved_registry`; otherwise a typed refusal.
  Candidates never influence anything.
- Recognition is `palimnex.concepts.match_aliases`, and verification is
  `verify_source_bindings`, applied to recognized, non-ambiguous concepts.
  A contributing concept is recognized, not ambiguous, and has at least one
  verified binding (the same meaning as "covered" in coverage SEMANTICS.md).
  Ambiguous, stale and uncovered concepts contribute nothing and are listed in
  `excluded_*`. R7 typed refusals propagate.
- `chunks` are the `retrieve_sources` chunk dicts (`path`, `start_line`,
  `end_line`, `pointer`). A chunk qualifies when a contributing concept has a
  verified `repo` binding with `source_id == path` whose range overlaps the
  chunk's lines. Line ranges are inclusive; byte ranges are converted to line
  numbers deterministically from the current file bytes. Non-`repo` schemes map
  to no chunk.
- A chunk's score is the number of distinct contributing concepts whose
  verified bindings overlap it. The ranking is sorted by (-score, pointer) and
  capped at 512; `truncated` is set when the cap is applied.
- Pure, deterministic and offline.

## 2. Shadow fusion (`palimnex/retrieval.py`, retrieval lane)

- `retrieve_sources` stays byte-identical in output and behavior for every
  input.
- `shadow_retrieve(query, *, registry, root=core.ROOT, limit=5, byte_budget=8192,
  include_graph=True, client=None, snapshot=None, resolvers=None) -> dict`
  returns `{"baseline": B, "comparison": C}`:
  - `B` equals `retrieve_sources(query, root=..., limit=..., byte_budget=...,
    include_graph=..., client=..., snapshot=...)` exactly;
  - the shadow fusion reuses the same lexical, symbol and graph rankings and
    adds `("ontology", channel.ranking)` with the same `RRF_K`, the same
    `(-score, pointer)` tie-break, the same 512 cap, the same `budget_items`
    and the same `[:limit]`. Shadow items carry `channels` including `ontology`;
  - `C` is `build_shadow_comparison(...)` (section 3).
- The channel is computed once per call; nothing is cached or persisted.

## 3. `palimnex:ontology-shadow-comparison:v1` (channel lane: builder, validator, public schema)

```python
def build_shadow_comparison(*, query: str, registry: ConceptRegistry | None,
                            channel: OntologyChannel, baseline: Mapping[str, Any],
                            shadow_results: Sequence[Mapping[str, Any]],
                            shadow_candidate_count: int, shadow_items_bytes: int,
                            limit: int) -> dict[str, Any]
def validate_shadow_comparison(document: Mapping[str, Any]) -> None
```

Keys, exactly:
`schema`; `query_digest` and `query_digest_policy` (from `palimnex.coverage`);
`registry` (`{"schema", "digest"}` or `null`); `channels`
(`["lexical", "symbol", "graph", "ontology"]`); `ontology_channel` (the
`OntologyChannel` fields except `ranking`, as sorted lists); `limit`;
`byte_budget`; `baseline` (`{"pointers", "candidate_count"}`); `shadow`
(`{"items": [{"pointer", "rank", "channels": {name: rank}}], "candidate_count",
"items_bytes"}`); `diff` (`{"identical", "overlap_count", "entered", "left",
"rank_changes": [{"pointer", "baseline_rank" | null, "shadow_rank" | null}]}`);
`retrieval_influence: false`; `returned_ranking_changed: false`;
`authority: "evidence_only"`; `authorizes_actions: false`; and
`comparison_digest` (SHA-256 of canonical JSON with that key removed).

Pointers only: no raw query, source text or excerpts. Every list is bounded
(at most 100 items, matching the limit range). Ordering is deterministic. The
validator also enforces cross-field rules: `identical` matches the pointer
lists, `entered`/`left`/`overlap` are consistent, ranks are 1-based and unique,
and the `channels` names come from the four.

## 4. Cohort (`palimnex/evaluation/ontology-shadow.v1.json`, cohort lane)

```json
{
  "schema": "palimnex:ontology-shadow-cohort:v1",
  "status": "frozen",
  "binding_digests_are_placeholders": true,
  "registry": { "...": "palimnex:concept-registry:v1, registry_kind approved_registry, project = this repository's .palimnex.json identity" },
  "cases": [ { "id": "...", "category": "...", "query": "...", "limit": 5,
               "expected_paths": [], "forbidden_paths": [], "critical": false,
               "expect_ontology_contribution": true, "note": "..." } ]
}
```

- Hand-written evaluation-only concepts about this repository, bound with
  `repo` line ranges to real files. Every binding uses placeholder `version` and
  `digest` (64 zeros), and `registry_digest` is a placeholder too. The harness
  materializes them against the current checkout at evaluation time; this is
  allowed only because the file sets `binding_digests_are_placeholders` (R4).
- Categories: `alias` (the query contains an approved alias; expected paths
  include the bound file); `paraphrase` (meaning without the alias; no
  contribution expected); `ambiguity` (an alias shared by two concepts; no
  contribution); `negative` (unrelated; no contribution, and
  `expected_paths: []`); `control` (ordinary queries; no contribution).
- It is never the approved registry and never loaded by `explain-search`.

## 5. Evaluation (`palimnex/ontology_eval.py`, evaluation lane)

`evaluate_ontology_shadow(root: Path = core.ROOT, *, limit: int = 5) -> dict`,
returning `palimnex:ontology-shadow-evaluation:v1`, local mode only (no Redis):

- suites: `v27` (the frozen `palimnex/evaluation/v27.json` cases with mode
  `search`, run through `shadow_retrieve` with the materialized cohort
  registry); `challenges_v26` (the v26 synthetic project written to a
  temporary checkout, as `palimnex/challenge.py` does, with `registry=None`,
  measuring abstention parity); and `cohort`;
- per suite and for each of `baseline` and `shadow`: case count, critical pass
  count, forbidden-path hits, recall at limit, MRR and negative abstention;
  plus identical-ranking and changed-ranking counts;
- `gates` (amended by `integration/clarification-R12.md`): `baseline_identical`,
  `no_critical_regression`, `no_case_regression`, `no_new_forbidden`, `abstention_not_regressed`,
  `ambiguity_never_contributes`, `channels_visible` and `bounded`, each a
  boolean computed from the data;
- `cohort_digest`, `registry_digest` (after materialization), `limit`,
  `promotion_authorized: false`, `retrieval_influence: false`,
  `authority: "evidence_only"`, `authorizes_actions: false`;
- deterministic: the same checkout gives the same report.
