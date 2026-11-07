Implemented `ontology-influence-retrieval`.

- Public API: `retrieve_sources(..., influence="config" | "off" | ActiveInfluence)`.
- Enabled mode fuses the ontology channel and discloses influence; context upgrades to `project-memory:context:v2`.
- Missing/off/shadow remain byte-identical; shadow evaluation is pinned to `influence="off"`.
- Tests: 18 focused + 98 regression tests passed; strict mypy passed.
- Receipt: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-3-promotion/receipts/ontology-influence-retrieval.implementation-receipt.json) validated successfully.
- Deviations: none.
- Open risks: Redis was unavailable (`cache_consulted: false`); full gate, reindex, and evaluation remain delegated to the coordinator. No real registry activation was attempted.
- Git state: no staging, commits, pushes, or writes outside the six owned paths.