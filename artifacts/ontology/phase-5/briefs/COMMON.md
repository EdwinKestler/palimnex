# Phase 5 lane brief: rules common to every lane

You are a bounded implementer under `.agents/skills/palimnex-ontology-workstream/SKILL.md`.
Phase 5 (reviewed retrieval feedback records only) is approved: you WRITE PRODUCT
CODE, but only inside your task card's `owned_paths`. Another lane may run in
parallel in this same working tree. Where a `read_only_paths` entry is a parent
of one of your owned paths, ownership wins for that exact path only.

## Sources of truth, in order

1. `docs/ONTOLOGY_ADOPTION.md`: the approved design, especially "Phase 5", the
   Phase 5 rows of "Accepted Phase 0 decisions", the scope paragraph and
   "Safety and authority invariants" (8: history stays non-authorizing). Do not
   edit it.
2. `artifacts/ontology/phase-5/briefs/FEEDBACK_SPEC.md`: the shared interface.
   Follow it exactly; if you believe it is wrong, implement it as written and
   raise the issue in `unresolved_risks`.
3. Committed code, read-only: `palimnex/durable.py` (`MemoryLedger`,
   `append_event`, `_source_evidence_digest`, `connection`, `unpack_payload`,
   `canonical_json`, `EVENT_KINDS`, supersession rules), `palimnex/experience.py`
   (read-only ledger access pattern), `palimnex/cache_v3.py` (`source_snapshot`,
   `MAX_QUERY_BYTES`, `MAX_QUERY_TERMS`), `palimnex/security.py` (`scan_text`),
   `palimnex/core.py` (`tokenize`), existing ledger tests (for temporary-ledger
   fixtures, e.g. `palimnex/tests/test_durable.py`).

## Engineering rules

- Runtime code is standard library plus `palimnex.*` only. `jsonschema` and
  `referencing` are allowed in tests only.
- Repository style: small typed functions (strict mypy), frozen dataclasses
  where useful, a `ValueError` subclass with `reason` and `field`, explicit
  bounds, deterministic ordering, refusals that never echo query, note, reason
  or source text.
- Tests are offline and hermetic: temporary repositories and **temporary
  ledgers only** (never the repository's own `.palimnex/` ledger), no Redis, no
  network, runtime-built canaries (`"".join((...))`), no secret-shaped literal
  in any file.
- Do not change any existing identifier, schema, event kind, test expectation,
  CLI command, MCP tool, configuration key or retrieval behaviour.
  `palimnex/durable.py`, `retrieval.py` and `experience.py` are read-only.
- Do NOT run the full unittest suite or `scripts/palimnex_check.sh`; the
  coordinator runs them unsandboxed. Run your task card's focused commands.

## Authority

No Git writes, network, installs, model calls, Redis writes, and no write to the
repository's real ledger: no `palimnex remember`, `session-*`, `capture-*`,
`ledger-*` or feedback command against this checkout. Never read
`forbidden_paths`.

## Handoff (required)

1. Run your task card's acceptance commands except the receipt validator.
2. Get digests:
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-5/tasks/<ws>.json`
3. Write `artifacts/ontology/phase-5/receipts/<ws>.implementation-receipt.json`
   (schema: `.agents/skills/palimnex-ontology-workstream/assets/implementation-receipt.v1.schema.json`).
   `files_changed` lists owned roots. `status` is `tested` only if every focused
   acceptance command passed. Record that the full suite and standard gate are
   delegated to the coordinator.
4. Run the receipt validator and `git status --short --untracked-files=all`.
5. Print a short summary: public API or contract added, tests (counts),
   deviations, open risks.
