# Phase 4 lane brief: rules common to every lane

You are a bounded implementer under `.agents/skills/palimnex-ontology-workstream/SKILL.md`.
Phase 4 (local semantic shadow experiment) is approved: you WRITE PRODUCT CODE,
but only inside your task card's `owned_paths`. Other lanes may run in parallel
in this same working tree. Where a `read_only_paths` entry is a parent of one of
your owned paths, ownership wins for that exact path only.

## Sources of truth, in order

1. `docs/ONTOLOGY_ADOPTION.md`: the approved design, especially "Phase 4 —
   Optional local semantic experiment", the "Phase 4 provider" and "Phase 4
   thresholds" rows of "Accepted Phase 0 decisions", the scope paragraph and
   "Safety and authority invariants". Do not edit it.
2. `artifacts/ontology/phase-4/briefs/SEMANTIC_SPEC.md`: the shared interface,
   including coordinator decisions R14 (channel policy) and R15 (benchmark
   protocol). Follow it exactly. If you believe it is wrong, implement it as
   written and raise the issue in `unresolved_risks`.
3. Committed code you build on, read-only: `palimnex/core.py` (`embedding`,
   `tokenize`, `TOKEN_RE`, `DIMENSIONS`, `encode_vector`, `split_chunks`),
   `palimnex/semantic.py` (the v1 provider protocol, unchanged),
   `palimnex/retrieval.py` (`_retrieve_sources_with_state`, `_fuse_rankings`,
   `RRF_K`, `retrieve_sources`), `palimnex/ontology_shadow.py` and
   `palimnex/ontology_eval.py` (patterns, metric helpers), `palimnex/cache_v3.py`
   (`source_snapshot`), `palimnex/security.py` (`scan_text`, `scan_bytes`),
   `palimnex/durable.py` (`canonical_json`), `palimnex/_offline_fixtures.py`
   (`write_project`), and existing tests for repository style.

## Engineering rules

- Runtime code is standard library plus `palimnex.*` only (`pyproject.toml`
  has `dependencies = []`). `jsonschema` and `referencing` are allowed in tests
  only.
- Match repository style: small functions, typed signatures (strict mypy:
  `disallow_untyped_defs`), frozen dataclasses for results, a `ValueError`
  subclass with `reason` and `field` for refusals, explicit bounds and
  deterministic ordering.
- Refusals and errors never echo query text, source bytes or secret findings.
  Report a field and a reason code.
- Tests use `unittest`, are offline and hermetic (temporary directories, no
  Redis, no network, no sleeping: use the `FakeClock` double), and build secret
  canaries at runtime from fragments with `"".join((...))`. Never write a
  secret-shaped literal in any file.
- Do not change any existing identifier, schema, test expectation, CLI command,
  MCP tool, configuration key or retrieval behavior. `palimnex/retrieval.py`
  and `palimnex/semantic.py` are read-only for every lane.
- Do NOT run the full unittest suite or `scripts/palimnex_check.sh`. Their
  Unix-socket and MCP subprocess tests cannot pass in this sandbox, and you must
  not try to escape it. The coordinator runs them unsandboxed. Run your task
  card's focused commands.

## Authority

No Git writes, network, installs, model downloads or model calls, Redis or
SQLite writes, and no palimnex commands that write. Never read
`forbidden_paths`. Phase 4 is evidence only: nothing you write may change
production retrieval or claim promotion.

## Handoff (required)

1. Run your task card's acceptance commands except the receipt validator.
2. Get digests:
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/<ws>.json`
3. Write `artifacts/ontology/phase-4/receipts/<ws>.implementation-receipt.json`
   (schema: `.agents/skills/palimnex-ontology-workstream/assets/implementation-receipt.v1.schema.json`).
   `files_changed` lists owned roots (decision R8 is not applied).
   `compatibility_effect` states exactly what public surface you added.
   `status` is `tested` only if every focused acceptance command passed. Record
   that the full suite and standard gate are delegated to the coordinator.
4. Run the receipt validator and `git status --short --untracked-files=all`.
5. Print a short summary: the public API or contract you added, tests (counts),
   deviations, and open risks.
