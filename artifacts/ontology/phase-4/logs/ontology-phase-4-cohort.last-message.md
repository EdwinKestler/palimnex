Implemented `ontology-phase-4-cohort` within the four owned paths.

- Added `palimnex:semantic-shadow-cohort:v1`: 26 repository cases, 2 drift cases, and 3 privacy-canary cases.
- Added its draft 2020-12 JSON Schema and 10 structural tests.
- Compatibility suite: 6 tests passed.
- Implementation receipt validated successfully.
- No retrieval, embeddings, cache/ledger access, network, or Git writes occurred. `cache_consulted: false`.

Open risks: coordinator source-grounding review and digest freeze remain; semantic quality, gain, and latency are intentionally unmeasured until then. Full integration gates are delegated to the coordinator.