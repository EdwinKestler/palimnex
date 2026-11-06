Implemented the three requested fixes within owned paths:

- Normalization: `C*` rejection now precedes whitespace handling; TAB/LF/CR alias and query tests added.
- Privacy: `parse_registry` scans in-memory registry bytes before field/alias derivation; definition and alias canaries prove typed, non-echoing refusal.
- Cycles: added a genuine two-node supersession cycle test proving `supersession_cycle`.

Validation:

- Focused tests: 24 passed
- Strict mypy: passed
- Receipt validation: passed
- Frozen suite: 3/4 passed; `ONT-NORM-003` conflicts with SEMANTICS by expecting TAB/LF query matching. Recorded as unresolved and receipt status `partial`.
- Full suite and standard gate were delegated per the fix brief.

Receipt: [ontology-phase-1-registry-core.implementation-receipt.json](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-registry-core.implementation-receipt.json)