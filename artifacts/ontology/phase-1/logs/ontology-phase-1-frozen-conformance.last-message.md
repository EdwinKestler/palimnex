Implemented the frozen-conformance lane within owned paths only.

- Contract: byte-exact frozen matrix plus conformance for `parse_registry`, `match_aliases`, `verify_source_bindings`, and JSON-Schema parity. No new runtime API.
- Focused tests: 26 passed, covering 15 Phase 1 cases, 30 frozen registries, and 11 schema fixtures.
- Broader unaffected suite: 266 passed.
- Receipt: [implementation receipt](/home/kestl/github/palimnex/artifacts/ontology/phase-1/receipts/ontology-phase-1-frozen-conformance.implementation-receipt.json) validates successfully.
- Status: `partial`. The full gate is blocked by sandbox-denied AF_UNIX sockets and an MCP stdio hang; system Python also lacks `referencing`.
- Open risk: coordinator must rerun the full suite and standard gate with isolated-socket permission, then reindex/evaluate indexed files. No Git writes occurred.