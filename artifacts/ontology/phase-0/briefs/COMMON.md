# Phase 0 lane brief: rules common to every lane

You are a bounded implementer under the `palimnex-ontology-workstream` skill
(`.agents/skills/palimnex-ontology-workstream/SKILL.md`). Read that skill, the
approved design `docs/ONTOLOGY_ADOPTION.md`, and your task card under
`artifacts/ontology/phase-0/tasks/` before writing anything.

## Authority

- Phase 0 is contract drafting only. Your deliverables are drafts awaiting the
  owner's exit-gate decision. They are not approved contracts.
- Write only inside your task card's `owned_paths`. Other lanes run in
  parallel in the same working tree; touching their paths corrupts their work.
- Do not edit `docs/ONTOLOGY_ADOPTION.md`: its digest binds every task card.
- Never read `forbidden_paths`. No Git writes, no network, no installs, no
  `palimnex.py` commands that write (index, remember, session-*, capture-*,
  retention-*, memory-*, cleanup-*, workflow-put, ledger-init). Read-only
  commands (`status`, `search`, `symbols`, `ledger-status`) are fine; Redis may
  be stopped, which is acceptable.
- Use the repository venv (`./.venv/bin/python`), which already has
  `jsonschema` and `referencing`. Check scripts must work offline, use only the
  stdlib plus those two packages and `palimnex.*` imports, and resolve `$ref`s
  through a local `referencing.Registry` (no network retrieval).

## Quality bar

- Ground every claim in current source. Search before asserting how existing
  code behaves, and cite file paths.
- Draft JSON Schemas use Draft 2020-12, `additionalProperties: false`, explicit
  bounds on every string, array and integer, and a `$id` under
  `https://palimnex.dev/schemas/`. Do not place them in `palimnex/schemas/`.
- Prefer the Phase 0 working defaults in the design; record disagreements as
  open questions instead of silently deviating.
- Secret canaries are never stored literally. Represent them as construction
  recipes and build them at test time, as `palimnex/tests/test_durable.py` does
  with `"".join((...))`.

## Handoff (required)

1. Run your lane check script and fix failures.
2. Get your digests:
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-0/tasks/<your-workstream>.json`
3. Write `artifacts/ontology/phase-0/receipts/<your-workstream>.implementation-receipt.json`
   matching `.agents/skills/palimnex-ontology-workstream/assets/implementation-receipt.v1.schema.json`:
   `design_identity` copied from the task card; `task_digest` and
   `approval_evidence_digest` from step 2; `files_changed` lists every file you
   created, including the receipt; `commands` holds exact commands, exit codes
   and short results; `cache_and_ledger_state` and `git_state` are observed
   facts (for example the `git status --short` lines inside your paths);
   `status` is `tested` only when the check script passed.
4. Run every acceptance command in your task card and confirm they pass.
5. End with a short plain-text summary: files, decisions made, open questions.
