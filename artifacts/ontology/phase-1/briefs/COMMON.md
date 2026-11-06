# Phase 1 lane brief: rules common to every lane

You are a bounded implementer under `.agents/skills/palimnex-ontology-workstream/SKILL.md`.
Phase 1 is approved: you WRITE PRODUCT CODE, but only inside your task card's
`owned_paths`. Other lanes run in parallel in this same working tree. Where a
`read_only_paths` entry is a parent of one of your owned paths, ownership wins
for that exact path only.

## Sources of truth, in order

1. `docs/ONTOLOGY_ADOPTION.md`: the approved design, especially "Phase 1",
   "Safety and authority invariants" and "Accepted Phase 0 decisions". Do not
   edit it.
2. The accepted Phase 0 contract under `artifacts/design/ontology-phase-0/`:
   `registry/concept-registry.v1.schema.json`, `registry/SEMANTICS.md`, the
   registry examples, `frozen-cases/`, `threat-model/THREAT_MODEL.md` and
   `CONTRACT_FREEZE.md`. These are accepted. Do not change contract meaning; if
   you believe the contract is wrong, implement it as written and raise the issue
   in `unresolved_risks`.
3. `artifacts/ontology/phase-0/integration/reconciliation-decisions.v1.md`
   (R1-R7, accepted).
4. Current source: `palimnex/locators.py`, `security.py`, `durable.py`
   (`canonical_json`), `identity.py`, and existing tests for repository style.

## Engineering rules

- Runtime code is standard library plus `palimnex.*` only (`pyproject.toml`
  has `dependencies = []`). `jsonschema` and `referencing` are allowed in tests
  only.
- Match repository style: small functions, typed signatures (strict mypy:
  `disallow_untyped_defs`), frozen dataclasses for results, a `ValueError`
  subclass for refusals, explicit bounds, and deterministic ordering.
- Refusals and errors never echo source bytes, alias values from rejected
  input, or secret findings. Report the field or path and a reason code.
- Tests use `unittest`, are offline and hermetic (temporary directories, no
  Redis, no network), and build secret canaries at runtime with
  `"".join((...))`.
- Do not change any existing identifier, schema, test expectation, CLI command,
  MCP tool, configuration key or retrieval behavior.
- Run the full unittest suite once before finishing
  (`./.venv/bin/python -m unittest discover -s palimnex/tests -p 'test_*.py'`)
  so you know you broke nothing. Report the count.

## Authority

No Git writes, network, installs, model calls, Redis or SQLite writes, and no
palimnex commands that write. Never read `forbidden_paths`.

## Handoff (required)

1. Run your task card's acceptance commands except the receipt validator.
2. Get digests:
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-1/tasks/<ws>.json`
3. Write `artifacts/ontology/phase-1/receipts/<ws>.implementation-receipt.json`
   (schema: `.agents/skills/palimnex-ontology-workstream/assets/implementation-receipt.v1.schema.json`).
   `files_changed` lists owned roots (decision R8 is not applied).
   `compatibility_effect` states exactly what public surface you added.
   `status` is `tested` only if every focused test passed and the full suite
   passed.
4. Run the receipt validator and `git status --short --untracked-files=all`.
5. Print a short summary: the public API or contract you added, tests (counts),
   deviations, and open risks.
