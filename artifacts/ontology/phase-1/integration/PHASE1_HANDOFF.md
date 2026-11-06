# Ontology Phase 1 — handoff (v1.0 · 2026-11-05)

Status: **implemented, tested and independently accepted. Nothing is committed.**
Approval: `artifacts/ontology/phase-1/approval-evidence.json`. Design: `docs/ONTOLOGY_ADOPTION.md`.

## Delivered

| Path | What |
| --- | --- |
| `palimnex/concepts.py` (820 lines) | Stdlib-only registry loader and validator: canonical digest, normalization, exact-alias matching with explicit ambiguity, candidate/approved separation, supersession and withdrawal, privacy admission before derivation, source-binding verification (drift becomes stale; R7 typed refusals) |
| `palimnex/schemas/concept-registry.v1.schema.json` | Public `palimnex:concept-registry:v1`, identical to the accepted draft except the title |
| `docs/CONCEPT_REGISTRY.md` | Reader documentation, including R9 query normalization |
| `palimnex/tests/test_concepts.py`, `test_concept_registry_schema.py`, `test_concepts_frozen.py`, `fixtures/` | Unit, schema, frozen-conformance (15 Phase 1 cases) and runtime/schema parity tests; frozen matrix byte-exact |
| `pyproject.toml`, `palimnex/CHANGELOG.md`, `docs/COMPATIBILITY.md` | mypy file list; Unreleased entry; additive-compatibility note |

## Evidence

- Full suite: 324 tests OK (baseline 291). Strict mypy: 13 files clean.
- Retrieval unchanged: Recall@5 1.0, MRR 0.8917, critical cases pass.
- Standard gate passed. Ledger integrity ok with 0 events. Redis restored to stopped.
- Independent review (Grok 4.6 xhigh): round 1 gave 1 major and 4 minors.
  After two fix rounds all three lanes were **accepted** with 0 open findings.
- Ownership audits clean across every run.

## For the owner

1. **R9** (`integration/clarification-R9.md`): registry keys refuse all control
   characters, while query whitespace is treated as spaces. Independent review
   accepted it, and Codex technical review confirmed it on 2026-11-06. This is
   not Phase 2 approval.
2. **Accepted residual:** `concepts.py` imports `cache_v3.project_id` and
   `core.project_slug`, as SEMANTICS.md names them.
3. **Still open:** owner decision on the non-authorizing recommendation in
   `integration/registry-location-recommendation.md` (needed before Phase 2
   wiring), and validator patch R8.
4. **Governance:** one Codex lane escalated outside its sandbox to run socket
   tests. No harm was done, and later lanes ran with `approval_policy="never"`.
5. **Nothing committed:** commit the plan, skills, Phase 0/1 records and code
   when ready. Phase 2 (coverage receipt) needs its own named approval.
