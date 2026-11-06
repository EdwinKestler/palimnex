Implemented Phase 1 FIX ROUND 2 within owned paths only.

- Query whitespace: [concepts.py](/home/kestl/github/palimnex/palimnex/concepts.py:671) maps every `str.isspace()` character to U+0020 before normalizing.
- Control handling: TAB/LF/CR queries now match; U+0007 remains a typed `forbidden_unicode` refusal. Stored aliases still reject TAB/LF/CR, covered in [test_concepts.py](/home/kestl/github/palimnex/palimnex/tests/test_concepts.py:353).
- Fix-1 privacy and cycle behavior remains unchanged.
- Receipt updated with R9 and validated: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-registry-core.implementation-receipt.json:1).

Tests:

- Focused tests: 24/24 passed.
- Strict mypy: passed.
- Frozen conformance: 4/4 passed, including ONT-NORM-003.
- Receipt validation: passed.

The full suite and standard gate were not run per the fix brief. Indexed files changed; coordinator reindex/evaluation remains required after integration. `cache_consulted: false` because Redis was unavailable.