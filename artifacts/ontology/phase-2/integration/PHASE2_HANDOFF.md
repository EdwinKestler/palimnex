# Ontology Phase 2 — handoff (v1.0 · 2026-11-06)

Status: **implemented, tested and independently accepted. Nothing is committed or pushed.**
Approval: `artifacts/ontology/phase-2/approval-evidence.json`. Phase 1 exit gate: `artifacts/ontology/phase-1/exit-gate.json`.

## Delivered

| Path | What |
| --- | --- |
| `palimnex/coverage.py` | Deterministic `palimnex:retrieval-coverage:v1` engine: query digest, classification (covered, uncovered, stale, ambiguous), status table, integer coverage, bounds, canonical digest, `validate_receipt`, explain-search builder |
| `palimnex/schemas/retrieval-coverage.v1.schema.json`, `explain-search.v1.schema.json` | Public schemas (the coverage schema is identical to the accepted draft except the title) |
| `palimnex explain-search` (in `palimnex/core.py`) | Read-only command: `QUERY [--limit 5] [--byte-budget 8192] [--backend local\|cache] [--no-graph] [--registry PATH]` |
| `docs/COVERAGE_RECEIPT.md`, `docs/CONCEPT_REGISTRY.md` | Reader documentation and the registry location |
| Tests | `test_coverage`, `test_retrieval_coverage_schema`, `test_coverage_frozen` (12 frozen Phase 2 cases, no label changes), `test_explain_search`, plus the R11 test in `test_concepts` |
| `palimnex/concepts.py` | R11 defect fix (query length) |

## Evidence

- Full suite: 361 tests OK. Strict mypy: 14 files clean. Standard gate passed.
  Ledger integrity ok with 0 events. Redis restored to stopped.
- Retrieval: Recall@5 1.0 and critical cases pass. MRR is 0.9 (was 0.8917):
  `cache-reader-lease` moved from rank 3 to 2 because corpus statistics changed.
  The ranking code is unchanged.
- Independent review (Grok 4.6 xhigh): round 1 found 0 blockers, 0 majors and 2
  minors. One minor was fixed (byte-budget attribution) and the other declined
  with the reviewer's agreement. The three implementation-lane receipts are
  `accepted`; the integration receipt is `accepted_with_limits` because its
  reviewer intentionally did not run socket-backed gates. The coordinator and
  a later Codex technical review closed those environment limits with the full
  suite, standard gate, evaluation, ledger check, and both local and cache
  backends.
- Ownership audits were clean in every run. No sandbox escapes.

## For the owner

1. **R10:** `explain-search` embeds the unchanged `retrieve_sources` result
   (the bounded retrieval `context` uses), not the cache-only `search` output,
   which lacks the identity and budget fields the contract needs.
2. **R11:** queries are bounded at 8 KiB rather than refused above 128
   characters. This corrects my R9 wording, and the fix touched committed Phase 1
   code via an amended integration lane.
   Codex technical review confirmed both R10 and R11 on 2026-11-06.
3. **Declined minor:** both truncation disclosures may be true at once
   (independent per the contract).
4. **Known limits:** when `--limit` binds, any further byte-budget drops can't
   be attributed. Mixed stale reasons aggregate to `unavailable`.
5. **No approved registry exists yet**, so `explain-search` reports
   `registry_absent` until a reviewed `ontology/concept-registry.v1.json` is
   committed.
6. **Not committed.** Phase 3 (shadow retrieval) needs its own approval.
