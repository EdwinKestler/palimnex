Implemented Phase 4 cohort fix round 1 within the four owned paths.

Rewritten queries:

- `paraphrase-active-reader`
  - Old: “Which code keeps an older in-memory search generation available until an active reader finishes?”
  - New: “What preserves an obsolete search view while an ongoing lookup is still using it?”
- `paraphrase-portable-rescan`
  - Old: “Which code rechecks every variable historical payload before a protected export is accepted or restored?”
  - New: “What screens stored user content again before a protected archive crosses between machines?”
- `synonym-sealed-archive`
  - Old: “How is a sealed archive of durable history authenticated before it can replace local storage?”
  - New: “How is an encrypted bundle of long-lived records verified prior to exchanging local data?”
- `synonym-tamper-evident-record`
  - Old: “Where is a tamper-evident snapshot of historical records checked against an external trust anchor?”
  - New: “How is a signed historical milestone compared with a separately retained reference?”
- `synonym-secret-detector`
  - Old: “Which secret detector rejects credential-like content without returning the matched value?”
  - New: “What blocks leaked authentication material yet discloses just a category and source position?”
- `synonym-database-upgrade`
  - Old: “How is a one-step database upgrade selected and checked before any replacement?”
  - New: “What validates the immediately following database upgrade before storage is exchanged?”

Also completed:

- Renamed `openai-key` to `openai-token` in the [cohort](/home/kestl/github/palimnex/palimnex/evaluation/semantic-shadow.v1.json:361), [schema](/home/kestl/github/palimnex/palimnex/schemas/semantic-shadow-cohort.v1.schema.json:98), and tests.
- Added the A2 structural isolation test in [test_semantic_cohort.py](/home/kestl/github/palimnex/palimnex/tests/test_semantic_cohort.py:123).
- Updated and validated the [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-4/receipts/ontology-phase-4-cohort.implementation-receipt.json:37).

Acceptance results:

- Cohort tests: 11 passed.
- Legacy ontology cohort tests: 6 passed.
- Contract and implementation receipt: valid.
- Final Git status completed; owned files remain untracked alongside preserved unrelated work.
- No Palimnex, retrieval, evaluation, embedding, provider, network, or Git-write action was run. `cache_consulted: false`.
- Indexed Palimnex paths changed; reindexing/evaluation remains delegated until independent re-review and freeze.