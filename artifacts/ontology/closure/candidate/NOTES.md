# Candidate concept registry notes

This is a source-derived candidate set, not an approved registry. The source files were privacy-scanned before concept and alias derivation. Bindings use inclusive one-based line ranges, the full-file SHA-256 as `version`, and the selected-range SHA-256 as `digest`.

## Fix round 2 re-pin

- After removal of the unused later-file `NO_SNAPSHOT_DEPRECATION` constant, all three `palimnex/retention.py` bindings were re-pinned from full-file version `ff7df852a49646f7648d02c98d5b71c55925a931ee32314da79e1ef35d491846` to `a79c1c3381e5954a0559d5fc199a7c5e563846e3af79c1ab8677e011001c40e9`. The ranges still cover `validate_policy` at lines 63-86, `RetentionLedger.authorize_erasure` at lines 284-313, and `RetentionLedger._propose` at lines 349-455. Recomputed selected-range digests remain `5fa2afb54f1f31b86bfe5fe4f09ad8e044f0f0ebd08a8ce29b0ac23ba1626616`, `5b36bffab1cfd4f21ed8ab4abd12decc79419ba4a58702f9dba217c334ed4681`, and `1c84db450724dfe7b7cb54c1eacc6e0a2580566a1ab81bb496962f9deef61208`, respectively. All 45 bindings were then re-verified, and the candidate registry digest was recomputed as `475877f3c486959cf11fc778ff18ce83584a2a477758808a8287d3978ce435fd`.

## Fix round 1 changes

- `source binding verification` -> `locator version digest check`: limits the phrase to `resolve_locator`'s version and selected-range digest checks instead of also describing concept-registry binding verification.
- `retrieval channel ranking` -> `baseline channel score fusion`: identifies the deterministic baseline fusion step rather than any channel that happens to rank results.
- `signed audit graph export` -> `private audit graph export`: `_write_new_private_file` is mandatory for export, while signing is optional.
- `candidate registry parser` -> `candidate approved registry parser`: `parse_registry` accepts both registry kinds rather than candidates alone.
- `covered uncovered concepts` -> `coverage receipt classification sets`: names the receipt's disjoint covered, uncovered, ambiguous, and stale classifications without reading like a query fragment.
- `shadow rank diff` -> `ontology pointer rank changes`: identifies the ontology comparison's bounded pointer-rank changes instead of using a generic shadow phrase.
- `enabled ontology channel` -> `ordered influence activation checks`: names the activation gate's ordered validation sequence instead of the retrieval channel it may enable.
- All three `palimnex/retention.py` bindings were re-pinned from full-file version `9ff7c7af7df05014c8f3a773d594c593e28cb96861f99afc2ce8ee4a9f10b5cf` to `ff7df852a49646f7648d02c98d5b71c55925a931ee32314da79e1ef35d491846`. The bound symbols and line ranges did not move, and all three selected-range digests are unchanged.

## `concept.source_admission` — Source admission and privacy scanning

- `palimnex/security.py:242-256` (`scan_text`): authoritative deterministic scanner entry point for credential-shaped text findings.
- `palimnex/security.py:282-333` (`read_bounded_file`): authoritative bounded, regular-file, no-symlink repository reader used before admission.
- `palimnex/cache_v3.py:190-218` (`source_snapshot`): authoritative corpus admission path that reads, scans, decodes, bounds, and fingerprints repository files.
- Aliases: `repository privacy scan` names the repository-specific scan; `credential shaped content scan` names the scanner's finding class without using a generic standalone term; `admitted source snapshot` names the accepted corpus result; `bounded repository file read` names the safe read boundary.

## `concept.source_locator` — Structured source locators

- `palimnex/locators.py:36-78` (`SourceLocator`): authoritative locator shape, validation, and canonical encoding.
- `palimnex/locators.py:109-121` (`select_range`): authoritative bounded line/byte selection and pre-selection privacy admission.
- `palimnex/locators.py:124-139` (`resolve_locator`): authoritative version and selected-byte digest verification path.
- Aliases: `versioned source locator` names object identity; `repository range locator` names the built-in scheme and range; `locator version digest check` names `resolve_locator`'s locator-specific integrity checks; `digest bound source range` names the integrity property.

## `concept.retrieval_fusion` — Retrieval-channel fusion

- `palimnex/retrieval.py:64-171` (`_rank_channels`): authoritative lexical, symbol, and structural-graph channel construction.
- `palimnex/retrieval.py:174-188` (`_fuse_rankings`): authoritative reciprocal-rank fusion, deterministic ordering, and output budgeting.
- `palimnex/retrieval.py:263-278` (`retrieve_sources`): authoritative public source-retrieval entry point and no-silent-downgrade boundary.
- Aliases: `reciprocal rank fusion` names the algorithm; `lexical symbol graph fusion` names the three baseline channels; `baseline channel score fusion` names the deterministic score-combination step.

## `concept.context_assembly` — Context assembly and byte budgets

- `palimnex/retrieval.py:50-61` (`budget_items`): authoritative serialized UTF-8 byte-budget selection primitive.
- `palimnex/experience.py:202-247` (`assemble_context`): authoritative interleaving of current sources and eligible history into the versioned context result.
- Aliases: `context byte budget` names the enforced bound; `source history context assembly` names the two evidence classes; `interleaved context items` names the fairness mechanism used before selection.

## `concept.cache_generation` — Cache generations and reader leases

- `palimnex/cache_v3.py:638-686` (`generation_reader`): authoritative atomic active-generation selection and reader-lease lifetime.
- `palimnex/cache_v3.py:731-741` (`_activate`): authoritative lock-fenced active-generation swap.
- `palimnex/cache_v3.py:1311-1388` (`_collect_garbage`): authoritative retention and deletion decision for complete, staging, grace-period, and leased generations.
- Aliases: `immutable cache generation` names the cache layout; `reader generation lease` names reader protection; `active generation swap` names activation; `leased generation garbage collection` names the lease-aware cleanup rule.

## `concept.durable_ledger` — Durable historical ledger

- `palimnex/durable.py:816-846` (`MemoryLedger.connection`): authoritative guarded transaction, schema, semantic validation, commit, and rollback boundary.
- `palimnex/durable.py:1465-1505` (`MemoryLedger.append_event`): authoritative event append entry point with evidence and temporal relationships.
- `palimnex/durable.py:2112-2245` (`MemoryLedger.recall`): authoritative bounded historical recall and filtering path.
- Aliases: `durable memory history` names the subsystem's role; `sqlite historical event ledger` names storage and record model; `source verified event recall` names its current-evidence check; `hash bound ledger events` names event integrity.

## `concept.retention_eligibility` — Retention eligibility and exclusions

- `palimnex/retention.py:63-86` (`validate_policy`): authoritative accepted policy fields, modes, durations, and expiry rules.
- `palimnex/retention.py:284-313` (`RetentionLedger.authorize_erasure`): authoritative explicit, expiring authority rule for durable or imported records.
- `palimnex/retention.py:349-455` (`RetentionLedger._propose`): authoritative eligibility, exclusion, dependency-closure, blocker, and cleanup-plan computation.
- Aliases: `retention cleanup eligibility` names the decision; `preservation hold exclusion` names a principal blocker; `durable erasure authorization` names the explicit-authority branch; `temporal dependency closure` names linked-record handling.

## `concept.ledger_migration` — Ledger migration registry

- `palimnex/migrations.py:66-85` (`Migration`): authoritative adjacent-step contract and apply/audit callbacks.
- `palimnex/migrations.py:98-136` (`validate_registry`): authoritative registry validation for continuity, readers, cycles, suffixes, effects, and callbacks.
- `palimnex/migrations.py:172-198` (`resolve_step`): authoritative immediate-successor resolution and backward/skip refusal.
- Aliases: `ledger schema migration registry` names the exact subsystem; `adjacent schema migration` names the one-step invariant; `migration step resolution` names target selection.

## `concept.memory_pack` — Portable memory packs

- `palimnex/portable.py:518-580` (`export_pack`): authoritative privacy-scanned, bounded, authenticated-encryption export path.
- `palimnex/portable.py:583-675` (`validate_pack`): authoritative format, identity, signature, authentication, decompression, selection, and privacy validation.
- `palimnex/portable.py:900-993` (`import_pack`): authoritative quarantine-first import and explicit replacement protocol.
- Aliases: `encrypted memory export` names confidentiality; `authenticated portable history` names integrity and content; `quarantined pack import` names the default trust boundary; `portable ledger archive` names the artifact's use.

## `concept.audit_graph` — Audit graph and projections

- `palimnex/audit.py:66-340` (`build_audit_graph`): authoritative deterministic projection of ledger and retention history into bounded nodes, edges, omissions, and tombstones.
- `palimnex/audit.py:343-374` (`export_audit_graph`): authoritative private-file export and graph summary.
- Aliases: `historical audit projection` distinguishes this graph from repository structure; `audit node edge projection` names its shape; `forgotten event tombstones` names non-reconstructive residue; `private audit graph export` names the mandatory private-file output boundary without implying an optional signature.

## `concept.concept_registry` — Concept-registry validation

- `palimnex/concepts.py:570-657` (`parse_registry`): authoritative exact-field, kind, project, lifecycle, digest, and non-authority validation.
- `palimnex/concepts.py:696-731` (`match_aliases`): authoritative normalized exact-token-sequence matching and ambiguity reporting.
- `palimnex/concepts.py:802-841` (`verify_source_bindings`): authoritative current/stale binding classification after safe reopening.
- Aliases: `source bound concept validation` names the central trust property; `normalized alias matching` names query recognition; `candidate approved registry parser` names both accepted registry kinds; `concept source drift check` names binding verification.

## `concept.coverage_receipt` — Coverage and answerability receipts

- `palimnex/coverage.py:352-567` (`build_coverage_receipt`): authoritative matching, binding verification, category construction, answerability, truncation, and canonical receipt creation.
- `palimnex/coverage.py:884-946` (`validate_receipt`): authoritative structure, ordering, arithmetic, category-disjointness, decision-table, and digest validation.
- Aliases: `retrieval coverage receipt` names the versioned output; `concept answerability status` names its decision; `coverage receipt classification sets` names its disjoint outcome collections; `stale binding diagnosis` names drift reporting.

## `concept.ontology_shadow` — Ontology shadow ranking

- `palimnex/ontology_shadow.py:141-233` (`ontology_channel`): authoritative concept matching, verification, exclusion classification, and binding-overlap ranking.
- `palimnex/ontology_shadow.py:311-458` (`build_shadow_comparison`): authoritative bounded pointer-only comparison beside the unchanged baseline.
- `palimnex/ontology_shadow.py:472-610` (`validate_shadow_comparison`): authoritative cross-field and non-influence validation.
- Aliases: `ontology channel comparison` names the evidence artifact; `non influencing ontology rank` states the safety boundary; `source binding chunk overlap` names rank derivation; `ontology pointer rank changes` names the bounded comparison detail.

## `concept.ontology_activation` — Ontology activation gate

- `palimnex/ontology_influence.py:225-233` (`read_influence_setting`): authoritative strict configuration read with missing configuration resolving to off.
- `palimnex/ontology_influence.py:489-578` (`activate_influence`): authoritative ordered gate over setting, approved registry, ambiguity, current bindings, promotion evidence, and implementation identity.
- `palimnex/ontology_promotion.py:500-602` (`evaluate_ontology_promotion`): authoritative local and offline-cache evidence construction; the result remains non-authorizing.
- Aliases: `ontology influence activation` names the opt-in operation; `promotion evidence gate` names the required evidence; `registry digest activation` names binding to reviewed content; `ordered influence activation checks` names the gate's fail-closed validation sequence.

## `concept.semantic_shadow` — Semantic shadow evaluation

- `palimnex/semantic_local.py:188-249` (`checked_embed`): authoritative bounded provider call and response validation for failures, timeout, count, dimensions, and finite values.
- `palimnex/semantic_shadow.py:309-392` (`semantic_shadow_retrieve`): authoritative unchanged-baseline semantic comparison and non-influence disclosure.
- `palimnex/semantic_eval.py:727-935` (`evaluate_semantic_shadow`): authoritative fixed evaluation gates, provider binding, privacy checks, deterministic repeat, gain, regression, and latency evidence.
- Aliases: `semantic channel comparison` names the isolated channel; `in process embedding shadow` names execution and mode; `provider identity bound evaluation` names reproducibility; `semantic promotion gates` names the held/promotable criteria.

## `concept.retrieval_feedback` — Reviewed retrieval feedback

- `palimnex/feedback.py:203-270` (`validate_feedback_payload`): authoritative payload, query, judgement, source binding, reviewer, provenance, and non-influence validation.
- `palimnex/feedback.py:435-457` (`record_feedback`): authoritative append path for a reviewed feedback fact.
- `palimnex/feedback.py:629-734` (`feedback_report`): authoritative read-only classification of current, stale, superseded, withdrawn, and invalid feedback history.
- Aliases: `reviewed retrieval judgement` names the manual decision; `source bound retrieval feedback` names evidence binding; `feedback correction withdrawal` names lifecycle operations; `retrieval feedback report` names inspection output.
