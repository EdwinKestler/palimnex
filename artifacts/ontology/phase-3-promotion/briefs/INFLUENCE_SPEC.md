# Ontology influence specification (coordinator, shared by all promotion lanes)

Owner decisions (2026-11-06, recorded in `docs/ONTOLOGY_ADOPTION.md`):
- Influence is opt-in through `.palimnex.json` `ontology_influence.mode`; a
  missing key means `off`.
- `enabled` binds the registry digest and the promotion evidence it was
  approved on.
- Any activation failure is an explicit error; there is never a silent fallback.
- Only `retrieve_sources` and its direct consumers change, and influenced
  results use new versioned contracts.
- Promotion evidence covers the local and cache backends.
- Registry presence is data, not authority.

## 1. Setting

`.palimnex.json` key `ontology_influence`:
- absent, or `{"mode": "off"}`: off;
- `{"mode": "shadow"}`: rankings and outputs identical to off; `ontology-status`
  reports activation readiness;
- `{"mode": "enabled", "registry": "ontology/concept-registry.v1.json",
  "registry_digest": "<64 hex>", "promotion_evidence": "<repo-relative path>",
  "promotion_evidence_digest": "<64 hex>"}`: `registry` is optional and
  defaults to `ontology/concept-registry.v1.json`; the other keys are required.

Anything else (unknown keys, a wrong type, an unknown mode, a malformed or
absolute or `..` path, a non-hex digest) is a typed error in every mode. Paths
are repository-relative and traversal-free.

## 2. `palimnex/ontology_influence.py` (gate lane)

```python
INFLUENCE_MODES = ("off", "shadow", "enabled")
PROMOTION_EVIDENCE_SCHEMA = "palimnex:ontology-promotion-evidence:v1"
CONTEXT_V2_SCHEMA = "project-memory:context:v2"
EXPLAIN_SEARCH_V2_SCHEMA = "palimnex:explain-search:v2"

class OntologyInfluenceError(ValueError):          # .reason, .field; never echoes values

@dataclass(frozen=True)
class InfluenceSetting:
    mode: str; registry_path: str | None; registry_digest: str | None
    promotion_evidence: str | None; promotion_evidence_digest: str | None

@dataclass(frozen=True)
class ActiveInfluence:
    setting: InfluenceSetting; registry: ConceptRegistry
    evidence_digest: str; implementation_digest: str

def read_influence_setting(root: Path) -> InfluenceSetting
def activate_influence(setting: InfluenceSetting, *, root: Path,
                       resolvers: Mapping[str, SourceResolver] | None = None) -> ActiveInfluence | None
def influence_implementation_digest() -> str
def validate_promotion_evidence(document: Mapping[str, Any]) -> None
def influence_disclosure(active: ActiveInfluence, channel: OntologyChannel) -> dict[str, Any]
def context_v2(context_v1: Mapping[str, Any], disclosure: Mapping[str, Any]) -> dict[str, Any]
def explain_search_v2(explain_v1: Mapping[str, Any], disclosure: Mapping[str, Any]) -> dict[str, Any]
```

`activate_influence` returns `None` for `off` and `shadow`. For `enabled` it
refuses with a typed reason, in this order, unless every check holds:
1. The registry loads (`palimnex.concepts.load_registry`, kind
   `approved_registry`, privacy admission, project match) and its
   `registry_digest` equals the setting's.
2. No normalized matching key belongs to two or more approved concepts
   (`registry_ambiguous`).
3. `verify_source_bindings` reports no stale concept (`registry_stale`).
4. The evidence file (bounded read, privacy-scanned) has SHA-256 equal to the
   setting, passes `validate_promotion_evidence`, has
   `registry.digest == registry_digest`, has
   `implementation_digest == influence_implementation_digest()`, has
   `status == "promotable"`, and covers both the `local` and `cache` backends.

`influence_implementation_digest()` is the SHA-256 of canonical JSON over
`[[module, sha256(source bytes)], ...]` for `palimnex.concepts`,
`palimnex.ontology_shadow`, `palimnex.ontology_influence` and
`palimnex.retrieval`, sorted by module name. Any code change invalidates old
evidence.

Disclosure (exact keys): `{"mode": "enabled", "channel": "ontology",
"retrieval_influence": true, "registry_digest", "promotion_evidence_digest",
"implementation_digest", "contributing_concept_ids": [...]}`.

- `context_v2(v1, d)`: every v1 key and value, with `schema` replaced by
  `project-memory:context:v2`, plus `ontology_influence: d`.
- `explain_search_v2(v1, d)`: every explain-search v1 key, with `schema`
  replaced by `palimnex:explain-search:v2`, plus `ranking_influence: d`.

## 3. Retrieval (`palimnex/retrieval.py`, `palimnex/experience.py`; retrieval lane)

- `retrieve_sources(..., influence: Literal["config", "off"] | ActiveInfluence = "config")`.
  `"config"` reads the setting from `root`. `off`, `shadow` and `"off"` follow
  exactly today's path, byte-identical with no new key. `enabled` activates
  (errors propagate) and fuses the ontology channel exactly as the Phase 3
  shadow fusion does (same RRF_K, tie-break, cap, `budget_items` and limit).
  The output is today's dict plus `"ontology_influence": disclosure`, and
  items carry an `ontology` channel rank when that channel ranked them.
- `shadow_retrieve` always uses the uninfluenced baseline.
  `palimnex/ontology_eval.py` passes `influence="off"` to every direct
  `retrieve_sources` call, so Phase 3 evaluation measures the true baseline
  under any setting.
- `assemble_context`: if the sources carry `ontology_influence`, it returns
  `context_v2(v1, disclosure)`; otherwise it returns v1 unchanged.

## 4. `palimnex:ontology-promotion-evidence:v1` (promotion lane builds; schemas lane publishes; gate lane validates)

```json
{
  "schema": "palimnex:ontology-promotion-evidence:v1",
  "status": "promotable",
  "registry": {"path": "ontology/concept-registry.v1.json", "digest": "<hex>"},
  "implementation_digest": "<hex>",
  "fixture_digests": {"v27": "<hex>", "v26": "<hex>", "cohort": "<hex>"},
  "limit": 5,
  "backends": {
    "local": {"suites": {"v27": {}, "challenges_v26": {}, "cohort": {}}, "gates": {}},
    "cache": {"suites": {}, "gates": {}}
  },
  "activation_authorized": false,
  "authority": "evidence_only",
  "authorizes_actions": false,
  "evidence_digest": "<sha256 of canonical JSON without this key>"
}
```

- Each suite reports `baseline` and `influenced` metrics (`case_count`,
  `cases_passed`, `critical_case_count`, `critical_pass_count`,
  `forbidden_path_hits`, `recall_at_limit`, `mrr`, `negative_abstention`,
  `negative_case_count`) plus `changed_ranking_count` and `regressed_case_ids`.
  Definitions are as in `palimnex/ontology_eval.py`.
- Per-backend gates (all booleans): `off_identical`,
  `no_critical_regression`, `no_case_regression`, `no_new_forbidden`,
  `abstention_not_regressed`, `registry_unambiguous`, `registry_current`,
  `channels_visible`, `bounded`, `deterministic`.
- `status` is `promotable` exactly when every gate on both backends is true;
  otherwise `held`.
- Bounds on every list; at most 64 regressed IDs, each 1-128 characters.

## 5. CLI (coordinator)

- `palimnex evaluate-ontology-promotion [--registry PATH] [--limit N]` prints
  the evidence (never writes it). Exit 0 for promotable, 2 for held, 1 for an
  error.
- `palimnex ontology-status` prints the parsed setting and, for `enabled`, the
  activation result. It never mutates anything.
- `explain-search` emits v2 when the search result carries
  `ontology_influence`.
