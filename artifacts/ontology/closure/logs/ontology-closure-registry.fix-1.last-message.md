Implemented and tested fix round 1 within owned paths only.

Changed aliases:

- `source binding verification` → `locator version digest check`
- `enabled ontology channel` → `ordered influence activation checks`
- `shadow rank diff` → `ontology pointer rank changes`
- `retrieval channel ranking` → `baseline channel score fusion`
- `signed audit graph export` → `private audit graph export`
- `candidate registry parser` → `candidate approved registry parser`
- `covered uncovered concepts` → `coverage receipt classification sets`

All changes and reasons are recorded in [NOTES.md](/home/kestl/github/palimnex/artifacts/ontology/closure/candidate/NOTES.md:7).

Re-pinned `palimnex/retention.py` bindings from version `9ff7c7…b5cf` to current version `ff7df8…1846`:

- `validate_policy`, lines 63–86, digest `5fa2afb5…26616`
- `RetentionLedger.authorize_erasure`, lines 284–313, digest `5b36bff…4681`
- `RetentionLedger._propose`, lines 349–455, digest `1c84db4…1208`

The symbols and ranges did not move; their selected-range digests remain unchanged. All other 42 bindings were current, and all 45 now verify.

[check_candidate.py](/home/kestl/github/palimnex/artifacts/ontology/closure/candidate/check_candidate.py:79) now scans the complete serialized document with `security.scan_text` and rejects aliases containing another concept’s canonical name or alias.

Validation passed:

- Candidate: 16 concepts, 61 aliases, 45/45 bindings verified
- Registry digest: `0bb4a6add1a4418373f99c69e8df4fb88b407a7e7e18f100204fd8f85b98c8ce`
- Concept tests: 25 passed
- Implementation receipt: valid
- Final Git status captured; unrelated dirty files preserved
- No Git writes, network, cache, Redis, ledger, evaluation, retrieval, or forbidden-path access
- `cache_consulted: false`

Updated [candidate registry](/home/kestl/github/palimnex/artifacts/ontology/closure/candidate/concept-registry.candidate.json:293) and [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/closure/receipts/ontology-closure-registry.implementation-receipt.json:1).