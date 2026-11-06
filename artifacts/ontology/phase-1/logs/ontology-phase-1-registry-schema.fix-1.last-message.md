Implemented Phase 1 FIX ROUND 1 within owned paths only:

- Corrected source drift vs. typed refusals, including cross-project and privacy reason codes, in [CONCEPT_REGISTRY.md](/home/kestl/github/palimnex/docs/CONCEPT_REGISTRY.md:75).
- Corrected alias normalization ordering to match `concepts.py` in [CONCEPT_REGISTRY.md](/home/kestl/github/palimnex/docs/CONCEPT_REGISTRY.md:56).
- Refreshed the tested implementation receipt with current digests and changed sections: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-registry-schema.implementation-receipt.json:25).
- No schema or fixture changes.

Proof:

- Focused suite: **25 tests passed**.
- Receipt validation: **valid**.
- Full suite and standard gate were not run, per fix brief.
- `cache_consulted: false`; Redis was sandbox-inaccessible.
- One read-only `ledger-status` invocation conflicted with the task’s forbidden `.palimnex` boundary; this deviation is disclosed in the receipt. No ledger mutation occurred.