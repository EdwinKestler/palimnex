Implemented `ontology-phase-1-registry-schema`.

- Added public `palimnex:concept-registry:v1` [schema](/home/kestl/github/palimnex/palimnex/schemas/concept-registry.v1.schema.json) and [reader documentation](/home/kestl/github/palimnex/docs/CONCEPT_REGISTRY.md).
- Added 4 valid and 7 invalid fixtures plus local-reference, digest, locator, and concept-ID tests.
- Focused acceptance: 25/25 passed.
- Full suite: 318/318 passed.
- [Implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-registry-schema.implementation-receipt.json) validated successfully.

Deviation: the promoted schema changes only the draft title. Ten fixtures remain byte-identical; one stale Phase 0 locator was rebound to test-owned source with recomputed digests.

Open risks: registry location remains undecided. Indexed files changed, but Redis was unavailable (`cache_consulted: false`), and this lane cannot index/evaluate; coordinator integration must perform that gate. No Git or live-state writes were made.