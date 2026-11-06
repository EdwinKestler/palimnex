# Parallel ontology execution

Use this reference only after the user explicitly requests parallel agents and
the coordinator has identified an approved phase.

## Workstream classes

| Workstream | Typical ownership | Dependency |
| --- | --- | --- |
| Registry/schema | New ontology module, new schemas, registry tests | Approved contract |
| Coverage/evaluation | Coverage engine, isolated fixtures, metric tests | Approved receipt vocabulary |
| Interface/integration | CLI/SDK dispatch, onboarding, shared docs | Registry and coverage receipts |
| Semantic provider | Provider contract/mocks or retrieval fusion, never both concurrently | Accepted deterministic shadow baseline |
| Independent review | Read-only diff, tests, security and compatibility evidence | Implementation receipt |

`palimnex/retrieval.py`, `palimnex/core.py`, `.palimnex.json`, public schemas,
frozen fixtures, compatibility documents, and release metadata are integration
bottlenecks. Assign one owner per wave.

## Task card

```yaml
workstream_id: ontology-phase-N-short-name
phase: N
action_id: ontology_phase_N_name
objective: bounded outcome
exclusions: []
approved_design_identity:
  path: docs/approved-ontology-design.md
  sha256: 64-hex digest
approval_evidence: bounded approval artifact
owned_paths: []
read_only_paths: []
forbidden_paths: []
dependencies: []
acceptance_commands: []
required_output: ImplementationReceipt
network_authority: false
git_write_authority: false
live_state_authority: false
```

Validate implementation task cards with
`../scripts/validate_contract.py`; it applies the JSON Schema and semantic
approval binding without network resolution. Reviewer assignments use the
reviewer's separate input and receipt contract.

No exact task card means analysis only. A child proposes changes needed in a
shared or foreign path through an `IntegrationPatchProposal`; it does not edit
that path.

## Waves

1. Freeze contracts and threat model.
2. Run registry/schema, coverage/evaluation, and independent threat review in
   parallel with disjoint ownership.
3. Review receipts and integrate CLI/config/shared documents serially.
4. Run focused tests, then reindex/deep-validate/evaluate and run the standard
   gate.
5. Start shadow retrieval only after the deterministic layer is accepted.
6. Start semantic-provider work only after the shadow baseline and separate
   semantic cohort are accepted.

## Receipt barrier

Every implementation child returns:

- task-card and design identities;
- exact owned and changed paths;
- dependency receipts consumed;
- exact commands and results;
- compatibility, privacy, and authority effects;
- proposed shared-file integration changes;
- unresolved decisions;
- cache and ledger state;
- Git state; and
- `implemented`, `tested`, `partial`, `blocked`, or `refused`.

Review children return `accepted`, `accepted_with_limits`, `rejected`, or
`blocked` using the review receipt schema.

The coordinator checks the actual diff and source before accepting the receipt.
Completion never grants commit, push, publication, migration, provider, or
live-state authority.

## Conflict behavior

- Stop workstreams with overlapping writable paths.
- Preserve unrelated dirty and untracked files.
- Do not auto-merge conflicting semantic contracts or frozen fixtures.
- Reissue task cards after a contract digest changes.
- A reviewer reports defects; it does not silently change roles and repair them.
