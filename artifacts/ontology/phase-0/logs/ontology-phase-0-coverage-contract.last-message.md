Implemented and validated Wave 2 within the owned paths only.

- R1–R3: coverage schema now references the registry’s canonical `conceptId`, `alias`, and `projectIdentity`; the checker resolves registry and locator schemas locally.
- R4: no change—complete registry fixtures belong to the frozen-cases lane, outside this task’s ownership.
- R5: added `partial-stale.json`, preserving `R = C + U + S + A` and exercising nonempty stale coverage.
- R6: ambiguity still wins while covered concepts may coexist; the mixed example and disjointness checks enforce this.
- R7: documented typed no-receipt errors and limited stale receipt reasons to admitted source-state failures.

Review findings:

- Concept-ID and alias drift: resolved through shared registry definitions.
- Stale taxonomy mismatch: contract retained the stale collection and now tests it; frozen-case edits remain with their owner.
- Ambiguous/covered mismatch: resolved with a valid mixed example.
- Synthetic source evidence: valid examples now bind current project, checkout, corpus, policy, and resolvable source locators.
- Missing stale example: resolved.
- Existing privacy, authority, truncation, omission, and status protections were preserved.

All acceptance commands passed: 7 valid examples, 6 invalid examples rejected, and the [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-0/receipts/ontology-phase-0-coverage-contract.implementation-receipt.json) validated. No Git, network, cache, ledger, or live-state writes were performed; `cache_consulted: false`.