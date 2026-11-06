Implemented `ontology-phase-0-registry-contract` entirely within owned paths.

- Draft [schema](/home/kestl/github/palimnex/artifacts/design/ontology-phase-0/registry/concept-registry.v1.schema.json)
- [Semantics and owner questions](/home/kestl/github/palimnex/artifacts/design/ontology-phase-0/registry/SEMANTICS.md)
- 3 valid and 6 invalid examples
- Offline [contract checker](/home/kestl/github/palimnex/artifacts/design/ontology-phase-0/registry/check_registry_contract.py)
- Validated [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-0/receipts/ontology-phase-0-registry-contract.implementation-receipt.json)

All three acceptance commands passed. The checker verified schema validity, examples, source bindings, canonical digests, and privacy refusal. Parallel-lane and unrelated files were untouched.

The standard repository gate was not run because it creates a temporary Redis index, which this task card explicitly forbids.