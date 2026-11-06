---
name: palimnex-ontology-coordinator
description: >-
  Plan, decompose, coordinate, and integrate approved Palimnex ontology-adoption
  work across parallel agents. Use for ontology workstream sequencing, exclusive
  file ownership, dependency gates, and integration handoff; not for ordinary
  maintenance or unilateral implementation of an unapproved proposal.
---

# Palimnex ontology coordinator

Load the base `palimnex` skill first. Repository source is authoritative;
cache and ledger results are discovery or historical evidence only.

## Design and authority gate

Read `artifacts/design/Ontologyadoptionplan.md` before decomposing work.

- While its status is proposal-only, perform planning and review only.
- Implementation requires explicit owner approval for the named phase.
- Move an approved design into `docs/` only with the implementing change.
- Parallel work never implies authority for Git writes, provider/network
  calls, ledger migration, policy activation, erasure, pack activation,
  publication, deployment, or live-state mutation.
- Spawn subagents only when the user explicitly requests delegation or
  parallel work.

## Coordinate

1. Run the Palimnex freshness and deep-validation workflow, or disclose
   `cache_consulted: false` when Redis is unavailable.
2. Identify the approved phase, design identity, open decisions, and exact
   compatibility boundary.
3. Record bounded approval evidence. Do not infer approval from a generic
   continuation request, proposal existence, or request for parallelism.
4. Produce a workstream manifest using
   [the runtime contract](assets/runtime-contract.yaml). JSON Schema alone
   cannot prove disjoint ownership or an acyclic dependency graph.
5. Assign mutually exclusive writable paths. Keep shared CLI dispatch, public
   compatibility documents, configuration defaults, frozen fixtures, and
   release metadata under one integration owner.
6. Give every implementer an exact task card validated against
   [the task-card schema](assets/workstream-task.v1.schema.json), with objective, exclusions,
   dependencies, owned/read-only/forbidden paths, acceptance commands, output
   receipt, and explicit authority fields.
   From the repository root, run
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py TASK.json`.
   The repository venv and its locked `jsonschema` and `referencing`
   dependencies are required. JSON Schema success alone is
   insufficient because phase, design, action, and authority must match the
   embedded approval evidence.
   When present, validate a foreign/shared-file proposal with
   `--patch-proposal PATCH.json` in the same invocation so its task, approval,
   workstream, and design bindings are checked.
7. Before spawning any implementation agent, validate the manifest and every
   task card as one bundle from the repository root:
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py --manifest MANIFEST.json --task-card TASK1.json --task-card TASK2.json`.
   The bundle must cover every manifest workstream exactly once and bind each
   task's phase, design, writable ownership, and dependency set to the
   manifest.
8. Treat dependency receipts as evidence to review, not verbal assertions.
9. Use a fresh reviewer that did not implement the work when independent
   validation is required.
10. Inspect actual source, diffs, tests, and Git state before integration.
11. Integrate shared files serially, then reindex/evaluate indexed changes and
   run the proportionate full gate.
12. Run the skill contract regressions separately because the repository's
   standard gate does not discover skill-local tests:
   `./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/test_validate_contract.py`.

Read [parallel execution](references/parallel-execution.md) when preparing or
running more than one ontology workstream.

## Stop conditions

Stop or narrow the affected workstream when:

- the design or phase is unapproved;
- file ownership overlaps;
- a dependency receipt is missing or stale;
- a compatibility change lacks a versioned migration design;
- a candidate concept would gain trusted or retrieval-influencing status;
- external/model activity lacks explicit authority; or
- independent validation cannot reproduce a material claim.

## Handoff

Report implemented, tested, integrated, committed, pushed, published, and
live-verified states separately. Include exact files, commands and results,
compatibility effect, unresolved decisions, cache/ledger state, authority used,
and Git state.
