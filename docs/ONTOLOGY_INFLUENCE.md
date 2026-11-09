# Ontology retrieval influence

Ontology retrieval influence is an explicit, repository-local promotion of the
approved ontology channel into `retrieve_sources` ranking. Registry presence
does not enable it. Activation requires an owner setting that binds one current
approved registry and one promotable evaluation document by digest.

The governing design is [ONTOLOGY_ADOPTION.md](ONTOLOGY_ADOPTION.md). Registry,
source-binding, and ambiguity rules remain those in
[CONCEPT_REGISTRY.md](CONCEPT_REGISTRY.md); answerability evidence remains
defined by [COVERAGE_RECEIPT.md](COVERAGE_RECEIPT.md); and the promoted channel
uses the deterministic ranking described in
[ONTOLOGY_SHADOW.md](ONTOLOGY_SHADOW.md).

## Compatibility boundary

Influence changes only `retrieve_sources` and its direct consumers, including
assembled context and `explain-search`. These module functions are not new
methods on the public `Palimnex` SDK v1 class. The
cache-backed `search`, `symbols`, `impact`, and `palimnex evaluate` surfaces are
unchanged. Shadow evaluation still measures an uninfluenced baseline.

With the setting absent, `off`, or `shadow`, existing retrieval and v1 outputs
remain unchanged. Enabled results are additive, versioned results; Palimnex
does not silently add influence fields to an existing v1 contract.

Influence remains deterministic, offline, source-backed, bounded, and
non-authorizing. It does not grant network, provider, Git, deployment, cache,
ledger, migration, retention, erasure, or pack authority.

## Modes

The optional `.palimnex.json` member is `ontology_influence`:

- Missing, or `{"mode": "off"}`, disables influence. This is also the
  rollback setting.
- `{"mode": "shadow"}` preserves the same ranking and outputs as `off`.
  `palimnex ontology-status` may report whether activation prerequisites are
  ready, but shadow mode does not activate them.
- `{"mode": "enabled", ...}` requests fail-closed activation. It must bind
  the approved registry digest, a repository-relative promotion-evidence path,
  and the exact SHA-256 digest of that evidence file. `registry` is optional
  and defaults to `ontology/concept-registry.v1.json`.

Unknown keys, wrong types, unknown modes, non-lowercase SHA-256 digests,
absolute paths, traversal, and malformed paths are typed setting errors in all
modes.

An enabled setting has this shape:

```json
{
  "ontology_influence": {
    "mode": "enabled",
    "registry": "ontology/concept-registry.v1.json",
    "registry_digest": "<lowercase 64-hex registry digest>",
    "promotion_evidence": "artifacts/ontology/promotion-evidence.json",
    "promotion_evidence_digest": "<SHA-256 of the exact evidence file bytes>"
  }
}
```

## Owner activation procedure

1. Review the approved registry and verify that all active concepts and source
   bindings are current and unambiguous.
2. Run `palimnex evaluate-ontology-promotion --registry
   ontology/concept-registry.v1.json --limit 5`. The command prints evidence
   and never writes it.
3. Review a `promotable` result covering both the `local` and `cache` backends,
   then save the exact output at a repository-relative path. Saving evaluation
   evidence does not itself authorize activation.
4. Record the registry's canonical `registry_digest` and the SHA-256 of the
   exact saved evidence file in the enabled setting above. The latter is
   distinct from the evidence document's canonical `evidence_digest`.
5. Run `palimnex ontology-status`. Activation succeeds only if every binding
   still matches current source and the evidence binds the current
   implementation digest.

Run steps 2-5 immediately before every activation. Promotion evidence v1
proves that its source snapshot stayed stable during evaluation, but the saved
document does not contain a corpus fingerprint and activation cannot compare
it with the current corpus. Regenerate and review the complete output after
**any indexed-corpus change**, including documentation, even when the registry
bindings, frozen fixtures, and influence implementation are unchanged. Do not
bind a filtered, reformatted, or partial diagnostic; bind the SHA-256 of the
exact complete saved bytes.

The implementation digest is SHA-256 over canonical JSON containing the source
digests of `palimnex.concepts`, `palimnex.ontology_shadow`,
`palimnex.ontology_influence`, and `palimnex.retrieval`, sorted by module name.
A change to any of those modules invalidates older promotion evidence.

To roll back, set `ontology_influence` to `{"mode": "off"}`. Removing the
setting has the same runtime effect. Evidence and registry files may remain as
historical data; their presence never turns influence on.

## Fail-closed activation

Enabled activation performs these checks in order and never silently falls
back to uninfluenced retrieval:

1. The configured registry must load as an `approved_registry`, pass privacy
   admission, match the current project, and match the configured registry
   digest. Candidate registries cannot activate influence.
2. No normalized alias or canonical-name matching key may belong to multiple
   active concepts.
3. Every active concept's applicable source bindings must verify against
   current source.
4. Promotion evidence must exist, pass privacy admission and its exact-file
   digest, satisfy the bounded `palimnex:ontology-promotion-evidence:v1`
   contract, bind the same registry and current implementation digests, have
   `status: promotable`, and include complete `local` and `cache` results.

Stable influence-specific refusal reasons include:

- `setting_invalid` for any malformed mode, field, digest, or path;
- registry parser and source-verification refusals such as
  `registry_read_refused`, `registry_kind_mismatch`, `project_mismatch`,
  `registry_privacy_refused`, `source_path_refused`,
  `source_symlink_refused`, `source_project_mismatch`, and
  `source_privacy_refused`;
- `registry_digest_mismatch`, `registry_ambiguous`, and `registry_stale`;
- `evidence_missing`, `evidence_digest_mismatch`,
  `evidence_privacy_refused`, and `evidence_invalid`;
- `evidence_registry_mismatch`, `evidence_implementation_mismatch`,
  `evidence_not_promotable`, and `evidence_backends_incomplete`; and
- `implementation_source_unavailable` if the shipped source bytes needed for
  the implementation binding cannot be read within their bound.

Errors report only a stable reason and field. They do not echo rejected source,
aliases, evidence bytes, privacy findings, or credential values.

## Versioned influenced results

An enabled retrieval result discloses the ontology channel, registry digest,
promotion-evidence file digest, implementation digest, and bounded contributing
concept IDs. The disclosure states `mode: enabled`, `channel: ontology`, and
`retrieval_influence: true`.

`assemble_context` returns `project-memory:context:v2` only when its source
result carries that disclosure. Context v2 preserves every v1 field and adds
`ontology_influence`.

`explain-search` returns `palimnex:explain-search:v2` only when ranking was
influenced. Explain-search v2 preserves every v1 field and adds
`ranking_influence`.

Both wrappers deep-copy their inputs. They do not mutate v1 documents or the
shared disclosure object. Their disclosures remain evidence-only and never
authorize actions.
