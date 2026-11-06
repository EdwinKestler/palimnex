# Ontology Phase 0 — contract freeze for owner exit gate (v1.0 · 2026-11-05 21:29 CST)

Status: **ready for owner decision. Nothing here is approved until the owner accepts it.**
Approved design: `docs/ONTOLOGY_ADOPTION.md` (sha256 `9bfdb51d…690686c2`), Phase 0 only.
Approval evidence: `artifacts/ontology/phase-0/approval-evidence.json` (digest `a6c83307…b042760`).

## What was produced

| Deliverable | Path | sha256 (prefix) |
| --- | --- | --- |
| `palimnex:concept-registry:v1` schema (draft) | `registry/concept-registry.v1.schema.json` | `20d12e2675118530` |
| Registry semantics | `registry/SEMANTICS.md` | `d5a4a239f15d6cb0` |
| `palimnex:retrieval-coverage:v1` schema (draft) | `coverage/retrieval-coverage.v1.schema.json` | `4062e26f2d810018` |
| Coverage semantics and decision table | `coverage/SEMANTICS.md` | `9b9b0ebdaf6fbb22` |
| Frozen case matrix (29 cases, 30 registry fixtures) | `frozen-cases/cases.v0.json` | `a64be4f15fdfb664` |
| Threat model | `threat-model/THREAT_MODEL.md` | `11f8b87ef41cf128` |

Paths are relative to `artifacts/design/ontology-phase-0/`. Each lane also has
valid and invalid examples and an offline check script that passes.

## How it was produced

- Wave 1: three parallel Codex lanes (gpt-5.6-sol, high), with disjoint ownership
  validated as one bundle by `validate_contract.py`.
- Independent review 1 (Grok 4.6, xhigh, read-only): all three lanes
  `accepted_with_limits`, 0 blockers, 9 major and 4 minor findings. All were
  cross-lane inconsistencies (ID patterns, `status` vs `lifecycle_status`,
  stale and ambiguity semantics, locator shape, one weak check).
- Reconciliation (`artifacts/ontology/phase-0/integration/reconciliation-decisions.v1.md`,
  R1-R8), then wave 2: registry first (it owns the shared `$defs`), then
  coverage and cases in parallel.
- Independent review 2: registry **accepted**, coverage **accepted**,
  threat-cases **accepted_with_limits** (1 minor). All 13 wave-1 findings were
  resolved.
- Ownership audits clean after every wave, and the reviewer wrote nothing.

## Compatibility and rollback decision

- No existing identifier, schema, reader, CLI, cache, ledger or config changed.
  The drafts live under unindexed `artifacts/`. The only indexed change is
  `docs/ONTOLOGY_ADOPTION.md`.
- Both new contracts are additive identifiers. `project-memory:context:v1`,
  `cache:v3`, `ledger:v1`, `pack:v2` and `semantic-provider:v1` are untouched;
  coverage is a separate result and is never embedded in context.
- Rollback for Phase 0: delete `artifacts/design/ontology-phase-0/`,
  `artifacts/ontology/` and `docs/ONTOLOGY_ADOPTION.md`, then reindex.
  There is no durable state to undo.

## Gate results (integration)

`index` fresh (97 files) · `validate --deep` pass · `evaluate --limit 5`: 20 cases,
critical passed, Recall@5 1.0, MRR 0.8917 (unchanged) · standard gate
`scripts/palimnex_check.sh` passed · ledger integrity ok, 0 events, no ledger
writes · contract regressions 9/9 · no model calls from Palimnex, no Git writes.

## Decisions requested from the owner

1. **Accept or revise the reconciliation decisions R1-R7** (concept-ID pattern
   with `_`; shared alias, ID and project `$defs` owned by the registry; fixtures
   as full registries; separate stale collection; ambiguous wins but is disjoint
   from covered; the R7 error-versus-receipt split).
2. **R8, validator patch:** let receipts list files beneath directory-valued
   owned paths. All three lanes asked for it; it is not applied.
3. **Working defaults from the design:** `concepts.py`, `explain-search`,
   shadow-only aliases through Phase 3, remote providers disabled by default,
   query-history feedback out of scope.
4. **Numeric bounds:** registry 1,000,000 bytes and 512 concepts; alias max 128;
   coverage collections 256 visible and 4096 total.
5. **Normalization:** NFKC + casefold + punctuation-to-space + whitespace
   collapse.
6. **Registry location and indexing**, and the candidate/approved path mechanism
   (`registry_kind`).
7. **Lane-raised questions:** `explain-search` output shape, checkout identity
   form, stale-reason categories, project binding for external resolvers.
8. **Frozen matrix:** record its digest as frozen; 8 cases remain
   `expected_status_disputed`. Open minor finding: ONT-NORM-001 should put a
   mixed-case form in its query.

On acceptance: record the frozen-matrix digest, then Phase 1 (registry
foundation) needs its own named approval before any product code is written.
