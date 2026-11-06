Completed reconciliation wave 2 within the five owned deliverables, including the tested [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-0/receipts/ontology-phase-0-threat-cases.implementation-receipt.json).

- R1: Removed the `concept.` prefix rule; concept IDs now validate through the registry schema.
- R2: Stored normalized aliases and resolved ONT-NORM-002/003 disputes.
- R3: Fixtures consume the registry’s project-identity definition; no foreign coverage files changed.
- R4: All fixtures are complete registries with `status`, direct source locators, canonical digests, and case-level placeholder flags. The digest-only locator probe now fails.
- R5: Added stale collections and moved both drift cases out of uncovered.
- R6: Enforced disjoint ambiguity while allowing covered concepts; ONT-AMB-002 exercises this.
- R7: Added `expected_outcome`; six refusal cases expect errors and two stale cases expect receipts. All eight remain disputed pending owner confirmation.

Review findings resolved:

- Incompatible IDs → R1.
- Reduced fixtures and renamed lifecycle fields → R4.
- Stale/uncovered conflation and empty-covered ambiguity rule → R5/R6.
- Digest-only locator passing → explicit rejected adversarial probe.
- Display-case aliases and normalization disputes → R2.

All acceptance commands passed: 29 cases, 14 categories, 30 registry fixtures, matrix SHA-256 `a64be4f…7314b`, valid receipt/task digest `93b79d…ae35`. Redis remained unavailable (`cache_consulted: false`); no indexing, Git writes, network, or live-state changes occurred.