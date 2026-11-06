Implemented and tested `ontology-phase-0-coverage-contract`.

- Added the [draft schema](/home/kestl/github/palimnex/artifacts/design/ontology-phase-0/coverage/retrieval-coverage.v1.schema.json), [semantics](/home/kestl/github/palimnex/artifacts/design/ontology-phase-0/coverage/SEMANTICS.md), offline checker, and 12 examples.
- Defined integer coverage arithmetic, ambiguity precedence, stale-source handling, and independent truncation/byte-budget disclosures.
- Both acceptance validators pass; 6 valid examples pass and 6 invalid examples are rejected.
- Wrote the validated [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-0/receipts/ontology-phase-0-coverage-contract.implementation-receipt.json).
- Open owner decisions are recorded in `SEMANTICS.md`.
- Redis was unavailable (`cache_consulted: false`); ledger integrity is healthy. No indexing, Git writes, network calls, or foreign-path edits were performed.