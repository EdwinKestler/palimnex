---
name: palimnex-ontology-workstream
description: >-
  Implement one explicitly assigned and approved Palimnex ontology-adoption
  workstream, such as registry validation, retrieval coverage, shadow ranking,
  or a gated semantic-provider experiment. Use only with a bounded coordinator
  task card; not for approval, coordination, release, or unrelated changes.
---

# Palimnex ontology workstream

Load the base `palimnex` skill first. Read the approved ontology design and the
coordinator task card before editing.

## Preconditions

Require all of the following:

- an explicitly approved phase;
- the approved design path and digest;
- bounded approval evidence matching that design and phase;
- exact owned, read-only, and forbidden paths;
- dependency receipts;
- acceptance commands; and
- explicit network, Git-write, and live-state authority fields.

If the only design remains proposal-only under `artifacts/design/`, or a task
card is incomplete, perform analysis only and return `refused` or `blocked`.

## Implement the bounded workstream

- Search current source using exact implementation vocabulary before editing.
- Touch only `owned_paths`. Return foreign/shared changes as an
  `IntegrationPatchProposal` bound to the validated task, approval-evidence,
  and design digests. Its target must be a repository-relative,
  traversal-free path.
- Preserve every existing `project-memory:*` identifier unless the task card
  includes an approved versioned migration design.
- Keep the default path deterministic, offline, source-backed, bounded, and
  non-authorizing.
- Generated ontology entries remain candidates. Persistence, model output, or
  child-agent completion does not approve them.
- Scan admitted bytes before deriving aliases, concepts, embeddings, or model
  inputs. Never echo or persist credential values.
- Distinguish ambiguity, uncovered concepts, truncation, and byte-budget
  omission. None is silently converted to full coverage.
- An explicitly enabled channel fails visibly on corruption or provider error;
  it does not silently downgrade.
- Do not commit, stage, push, publish, call an unapproved provider, mutate live
  Redis/ledgers, migrate, activate policies, erase, or activate packs.

## Validate and hand off

Run focused tests from the task card. State whether indexed files changed so
the coordinator can reindex and evaluate after integration.

Return an implementation receipt matching both
[the runtime contract](assets/runtime-contract.yaml) and
[the receipt schema](assets/implementation-receipt.v1.schema.json), including exact files,
commands and results, compatibility impact, authority used, unresolved risks,
integration proposals, cache/ledger state, and Git state.
