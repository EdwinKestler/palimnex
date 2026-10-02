# Ledger migration framework proposal

Status: proposal awaiting owner decision; not indexed (see AGENTS.md).

This document proposes a general, explicit framework for durable-ledger schema
migrations. It does not approve or implement a migration. Repository source and
the live ledger remain authoritative in their respective domains, and no plan,
snapshot, marker, pack, or historical record grants authority to apply a
migration.

## Goals and non-goals

The framework should provide one reviewed path for every future durable-ledger
schema change:

1. read-only plan;
2. verified pre-migration snapshot;
3. one SQLite transaction for all schema and data changes;
4. exact structural, semantic, and integrity verification;
5. durable marker publication.

Every apply remains explicit, is bound to `--expected-digest`, and runs under
the ledger's exclusive owner lock. Opening a ledger, starting Palimnex, or
installing a newer package must never migrate it automatically.

This proposal does not change the Redis cache, pack v2, retention behavior,
erasure rules, or any `project-memory:*` identifier. It does not define the
next ledger schema. It also does not make downgrade safe: a writer that stores
new semantics can make older readers fail closed, but cannot teach an already
released reader to understand them.

## Current state

### Exact reader selection and validation

- The ordinary ledger identifies itself as `project-memory:ledger:v1`
  (`palimnex/durable.py:27`). `MemoryLedger.connection()` calls
  `MemoryLedger._require_schema()` on every open before semantic use
  (`palimnex/durable.py:815-846`).
- `_require_schema()` requires the exact metadata key set, exact
  `ledger_schema`, exact project identity and codec, exact SQLite object set,
  and exact column order (`palimnex/durable.py:895-925`). This is deliberately
  fail-closed rather than best-effort compatibility.
- `retention.open_ledger()` reads only `metadata.ledger_schema` to select
  `RetentionLedger`; all other schemas continue through the ordinary reader
  and are rejected by its exact check (`palimnex/retention.py:619-625`).
- The retention profile is `project-memory:retention-ledger:v2`, adds the
  `retention_control` table, and requires the first control entry to be the
  migration record (`palimnex/retention.py:14,24-30,89-111`). A reader without
  that profile refuses the migrated ledger as unsupported.

### Current retention migration

`retention.migrate()` is the only durable schema migration
(`palimnex/retention.py:654-685`):

1. It returns current retention status when the Python object is already a
   `RetentionLedger`.
2. It takes the same exclusive file lock used by ledger writers.
3. It refuses a pending pack-import intent, exact-checks the source schema,
   refuses semantic corruption, and compares the current logical digest with
   `expected_digest`.
4. When requested, it calls `durable.write_snapshot()` under that lock before
   changing the ledger. `write_snapshot()` uses SQLite online backup, produces
   an owner-only self-contained file, fsyncs it and its directory, and verifies
   both `PRAGMA integrity_check` and the logical digest
   (`palimnex/durable.py:535-581`). The CLI supplies a default
   `backups/*-pre-retention-v2.sqlite3` path; the SDK currently makes snapshots
   opt-in.
5. It writes and fsyncs `<ledger>.retention-v2`, whose bytes are exactly
   `project-memory:retention-ledger:v2`.
6. It begins one immediate transaction, creates `retention_control`, changes
   `metadata.ledger_schema`, records the source digest in the first migration
   control entry, and commits.
7. It reopens through `RetentionLedger` and reports status.

The successful final state is sound, but marker publication currently happens
before the SQLite transaction. A process exit after marker creation but before
commit can therefore leave a retention marker beside an unchanged v1 ledger.
That state fails closed for pack replacement, and rerunning the current
migration can complete it, but the marker does not mean verification completed.
The generalized pipeline should make that distinction explicit.

`migration_preview()` is the current dry run
(`palimnex/retention.py:636-651`). It reports the source and target schemas,
digest match, pending-import refusal, snapshot policy, and effects without
writing. CLI parsing and dispatch are specific to `retention-migrate`
(`palimnex/core.py:2799-2806,3026-3043`).

### Existing downgrade boundary

The retention schema identifier did not change when `adapter_receipt` was
added. Version 2.7.0's allowed retention-control kinds do not include it, so
its semantic validation refuses the entire ledger. Version 2.8.0 is the first
release whose `RetentionLedger` validates and reads that control kind
(`palimnex/retention.py:28-30,99-105,166-185`; see also
`docs/UPGRADING.md:141-153`). This is safe failure, but its message is generic
because 2.7.0 cannot know the future meaning.

## Proposed invariants

1. **Explicit only.** Only an apply command can migrate. Constructors, open,
   status, doctor, import, and package upgrade remain non-migrating.
2. **Digest-bound.** Plan and apply both require the caller's
   `--expected-digest`. Apply recomputes it after acquiring the exclusive lock.
3. **Exact source and target.** The source reader must pass its exact structural
   and semantic checks before planning or applying. The target reader must pass
   its exact checks after commit and before marker publication.
4. **One transaction.** Every registered step in the selected path mutates one
   connection inside one `BEGIN IMMEDIATE` transaction. Migration functions may
   not commit, checkpoint, vacuum, call external systems, or publish markers.
5. **Verified snapshot first.** The canonical apply path creates and verifies a
   source-schema snapshot under the exclusive lock before beginning the
   transaction.
6. **Marker last.** A marker records a verified committed target, not intent.
7. **Recoverable and idempotent.** A process exit at every boundary either
   leaves the source unchanged or leaves a committed target that can be
   verified and completed without applying transformations twice.
8. **No automatic rollback.** Recovery finishes or reports the migration. It
   never silently restores a snapshot, because restoration discards later
   writes and can resurrect data removed after the snapshot.
9. **No authority transfer.** A plan, snapshot, marker, migration receipt, pack,
   or recalled record is evidence only. Current owner authorization is still
   required for apply or restore.

## Ordered migration registry

Use one ordered registry whose key is the exact source `ledger_schema`:

```python
MIGRATIONS = OrderedDict((
    ("project-memory:ledger:v1", Migration(
        target_schema="project-memory:retention-ledger:v2",
        plan=plan_retention_v2,
        apply=apply_retention_v2,
        verify=verify_retention_v2,
        marker_suffix=".retention-v2",
        marker_bytes=b"project-memory:retention-ledger:v2",
    )),
))
```

The concrete shape is illustrative. Registry validation at import/test time
must require:

- a unique source key and one unambiguous successor per source;
- a target different from its source;
- an acyclic, contiguous order;
- versioned source and target identifiers;
- pure planning and transaction-local apply callbacks;
- an exact target reader/verification callback;
- a declared marker policy and user-visible effects.

Given an observed source and requested target, the engine walks the ordered
successors and refuses missing links, cycles, ambiguous paths, backward paths,
or an unknown schema. A multi-step path is planned as a unit, receives one
source snapshot, and applies all steps in one SQLite transaction. Each step
still records its own source/target identity in the target's migration audit
where that schema supports one.

The registry is executable policy shipped with the selected Palimnex version;
it is not loaded from configuration, a pack, a plan file, Redis, or the ledger.

## Plan contract

`ledger-migrate --plan` returns a versioned machine-readable document, proposed
as `project-memory:ledger-migration-plan:v1`, containing at least:

- observed source and requested target schemas;
- ordered migration steps and their user-visible effects;
- current logical digest and whether it matches `--expected-digest`;
- structural, semantic, import-intent, marker, and snapshot preconditions;
- proposed snapshot location and the snapshot-retention warning;
- whether an interrupted migration intent exists and its recoverable phase;
- `will_write: false`, `authority: historical_only`, and
  `authorizes_actions: false`.

The plan is not an apply token. `--apply` recomputes the plan under the lock and
does not trust a saved JSON document or its digest.

## Apply pipeline

The proposed engine performs these phases:

1. **Plan again under the exclusive lock.** Guard paths; open the live ledger;
   exact-check source metadata, objects, columns, semantics, foreign keys and
   integrity; reject pending import; recompute the logical digest; and compare
   it with `--expected-digest`.
2. **Record transient intent.** Create an owner-only, no-follow, fsynced
   `<ledger>.migration-intent` containing a versioned intent, source, target,
   expected digest, exact snapshot path, registry/path identity, and phase.
   The intent is recovery state, never authority. It is removed after success,
   so the completed retention migration has no new persistent object.
3. **Write and verify the snapshot.** Call `durable.write_snapshot()` while the
   lock remains held. Record the verified path, schema, and digest in the
   transient intent and fsync it. The snapshot is not modified again.
4. **Apply once.** Begin one immediate transaction. Run every selected registry
   callback on the same connection, update `ledger_schema`, and record each
   migration audit entry. Commit once. SQLite rollback handles a process exit
   before commit.
5. **Verify the committed target.** Select the target reader from the committed
   `ledger_schema`; require its exact structural and semantic checks, SQLite
   integrity, foreign keys, project identity, and migration audit continuity.
   Verification happens under the same exclusive lock. Failure leaves the
   intent and withholds the marker.
6. **Publish the marker.** Create an owner-only temporary marker, fsync it,
   atomically install the declared marker without overwriting a conflicting
   file, then fsync the directory. An existing exact marker is idempotent; a
   mismatched or unsafe marker is an error.
7. **Finish.** Mark the intent complete, fsync, then remove it and fsync the
   directory. Return the target status plus the verified snapshot receipt and
   whether recovery completed any prior phase.

The intent contains no payloads, credentials, keys, or authorization. It should
use a new versioned identifier such as
`project-memory:ledger-migration-intent:v1` and bounded canonical JSON.

### Retention migration registration

The first registry entry is the existing v1-to-retention-v2 transformation.
Its successful persistent result must remain the same:

- the live SQLite ledger has the existing `retention_control` table;
- `metadata.ledger_schema` is exactly
  `project-memory:retention-ledger:v2`;
- the first control entry is the existing `migration` record with
  `from_schema`, `before_digest`, and `at`;
- `<ledger>.retention-v2` contains exactly the current schema bytes;
- the verified pre-migration snapshot remains outside the live database;
- no registry table, new metadata key, or completed intent remains.

"Same result" means the same schema objects, metadata, logical content,
control record shape, marker, and compatibility behavior. It cannot mean
byte-for-byte SQLite identity: timestamps, page layout, WAL/checkpoint state,
and snapshot filenames are not stable today.

`retention-migrate` remains a compatibility alias:

- `retention-migrate --dry-run --expected-digest D` maps to
  `ledger-migrate --plan --to project-memory:retention-ledger:v2
  --expected-digest D`;
- `retention-migrate --expected-digest D` maps to the corresponding
  `--apply` command;
- output retains the current fields where possible and may add the generic
  plan/step envelope additively.

The current `--no-snapshot` option conflicts with the strict safe pipeline.
The recommendation is to deprecate it, keep it only on the legacy alias for a
documented compatibility window, and never offer it on new migration targets.
Owner direction is required before implementation.

## CLI shape

Proposed commands:

```text
palimnex ledger-migrate --list
palimnex ledger-migrate --plan  --to TARGET --expected-digest DIGEST
palimnex ledger-migrate --apply --to TARGET --expected-digest DIGEST
```

- `--list` is read-only and lists source, target, effects, snapshot policy,
  marker, and whether the current ledger has a path to each target.
- Exactly one of `--list`, `--plan`, or `--apply` is required.
- `--to` is mandatory for plan/apply; the engine never assumes "latest".
- `--expected-digest` is mandatory for plan/apply even when resuming. A resume
  matches it against the intent and committed migration audit.
- `--plan` performs no filesystem writes, including no backup-directory or
  intent creation.
- `--apply` does not accept a plan file. It reports whether it started new work
  or resumed a recognized intent.
- An optional future `--recover` should be unnecessary: rerunning the exact
  `--apply` is the recovery operation. A separate inspection-only
  `--recovery-status` could be added if operators need it.

## Crash points and recovery

| Crash or failure point | Durable state | Idempotent rerun behavior |
|---|---|---|
| Before intent creation | Source unchanged | Replan normally |
| After intent, before snapshot | Source unchanged; prepared intent | Validate intent and continue snapshot phase |
| During snapshot | Source unchanged; possible incomplete intent-owned file | Verify it; reuse only if schema/digest/integrity match, otherwise quarantine it and allocate a new recorded path |
| After verified snapshot, before transaction | Source unchanged; verified snapshot retained | Reuse the verified snapshot; do not create another |
| During transaction, before commit | SQLite rolls back to source | Exact-check source, then rerun the transaction once |
| After commit, before intent phase update | Target schema and migration audit committed | Infer committed completion from exact target schema plus audit entry matching source and expected digest; never reapply SQL |
| Target verification failure | Committed target; no marker; intent retained | Fail closed and report verification errors; rerun verification after an approved code fix, never auto-restore |
| After verification, before marker | Verified target; no marker; intent retained | Verify again, then publish marker |
| During marker publication | Verified target; only temp or exact final marker | Remove/quarantine only the intent-owned temp; accept exact final marker, refuse conflicts |
| After marker, before intent removal | Verified target and exact marker; completed intent | Verify both, remove stale completed intent, return success |
| Rerun after success | Target schema, migration audit and marker | Return `already_migrated`; do not snapshot or mutate again |

There are two legacy recovery cases:

- A v1 ledger with an exact `.retention-v2` marker can be the result of the
  current marker-before-transaction ordering. An explicitly authorized apply
  may treat it as a resumable pre-commit marker only after exact-checking v1
  and matching the expected digest. It must never treat the marker alone as
  proof of migration.
- A retention-v2 ledger with a missing marker is still discoverable from
  `metadata.ledger_schema` and its first migration control entry. Pack recovery
  already inspects actual schema when the marker is missing. The new engine
  should exact-verify that state and repair only the missing marker.

An intent whose source, target, digest, registry identity, snapshot path, or
live ledger does not match is not resumable. It is reported for manual review
without guessing or overwriting files.

## Clear downgrade messages for future schemas

A future version may add `minimum_reader_version` to the metadata of a new
versioned ledger schema. New readers should perform a bounded raw metadata
probe before selecting an exact reader and emit, for example:

```text
ledger requires Palimnex >= 3.1.0; this reader is 3.0.2
```

The exact schema reader must still validate that field and the complete object
set. The field is diagnostic and fail-closed; it does not negotiate features or
authorize conversion. An incompatible semantic addition should normally use a
new ledger schema identifier and migration rather than silently extending the
allowed values inside an existing schema.

This cannot improve already released readers. They may reject the new metadata
as an unexpected field, reject the new schema as unsupported, or fail semantic
validation as 2.7.0 does for `adapter_receipt`. They cannot display a future
message they were never programmed to parse. A new writer can only ensure that
they fail closed and document the downgrade boundary before the write.

The `adapter_receipt` example also shows that a schema-level minimum alone is
not sufficient when writers add incompatible record kinds without changing
the schema. Future policy should require either:

1. a new schema and migration for a reader-breaking record kind; or
2. a schema-defined, exact-validated feature/minimum-reader field that the
   already-supported readers were designed to inspect.

Option 1 is the recommended default.

## Packs, snapshots, and authority

- Migration changes only the live SQLite ledger. It never rewrites, upgrades,
  activates, deletes, or registers a `.pmem` pack. Encrypted pack v2 bytes and
  `project-memory:memory-pack:*` contracts remain unchanged.
- Pack import/activation continues to inspect actual ledger schema and markers.
  A migrated retention ledger refuses replacement without a
  deletion-registry-aware adapter. A pack is untrusted historical content and
  cannot request or authorize migration.
- A pre-migration snapshot is an unmanaged full copy. Later authorized erasure
  of the live ledger does not remove it. The plan and result must repeat
  `durable.SNAPSHOT_ERASURE_NOTE`; operators must protect and deliberately
  retire snapshots under their own retention policy.
- Snapshot restoration is not migration rollback. It replaces the whole live
  history, can discard post-snapshot writes, and can resurrect erased data.
  It therefore requires separate, current owner authorization and must never be
  an automatic crash-recovery action.
- Redis, recall, migration audit entries, markers, intents, and snapshots are
  evidence, not authority. Only the explicit current CLI invocation with the
  owner-supplied expected digest authorizes this local migration attempt.

## Compatibility identifiers

All existing `project-memory:*` identifiers remain byte-for-byte unchanged,
including the v1 ledger, retention-ledger v2, policies, cleanup plans,
deletion contracts, tombstones, packs, and cache schemas.

Any implemented generic documents must receive new versioned identifiers, for
example:

- `project-memory:ledger-migration-plan:v1`;
- `project-memory:ledger-migration-intent:v1`.

Their exact fields, bounds, canonical encoding, persistence rules, and reader
behavior must be documented in `docs/COMPATIBILITY.md` in the same PR as the
implementation. Renaming or reusing an existing identifier is forbidden.

## Test plan

### Registry and planning

- Reject duplicate sources, duplicate/ambiguous successors, cycles, gaps,
  backward paths, unknown schemas, and unversioned identifiers.
- Prove deterministic path ordering and list output.
- Prove `--plan` leaves the complete ledger directory tree byte-for-byte
  unchanged, including no backups, marker, lock residue, or intent.
- Test digest match/mismatch, corrupt source, wrong project, pending import,
  unsafe paths, existing exact marker, and conflicting marker.

### Retention compatibility

- Run the legacy alias and generic command on equivalent fixtures and compare
  target SQLite object sets, metadata, logical documents, first migration
  control entry, status, and exact marker bytes.
- Preserve the current default verified snapshot name, mode `0600`, source
  schema, integrity, and logical digest.
- Prove ordinary old readers refuse retention v2 and a 2.7.0 reader refuses a
  retention ledger containing `adapter_receipt`; prove 2.8.0+ reads it.
- Keep the installed-wheel upgrade rehearsal passing through the alias, then
  add the generic command as a second path without touching a live ledger.

### Transaction and crash matrix

- Inject exceptions and real child-process exits at every row in the crash
  table: intent fsync, snapshot creation/verification, transaction before and
  after each step, commit, target verification, marker temp/fsync/rename, and
  intent cleanup.
- After each interruption, assert either the exact source or exact target; no
  partially applied SQLite schema is acceptable.
- Rerun with the same digest and prove completion is idempotent. Rerun with a
  different digest, target, registry identity, or unsafe intent and prove
  refusal.
- Exercise the current orphan-marker state and target-without-marker state.

### Snapshots, packs, and erasure

- Verify snapshots are made while the exclusive lock prevents concurrent
  writes and match the expected source digest.
- Verify an incomplete snapshot is never reused and a verified one is never
  overwritten.
- Verify later live-ledger erasure leaves the snapshot present and reports the
  unmanaged-copy warning.
- Verify pack bytes are unchanged, pack activation cannot replace a migrated
  ledger, and no pack can select a migration.

### Reader floors and portability

- For a future fixture schema, test clear messages above, equal to, and below
  `minimum_reader_version`, malformed versions, and missing fields.
- Retain tests showing old readers fail closed generically; do not claim their
  wording changed.
- Run Linux and macOS tests for owner modes, no-follow paths, atomic marker and
  intent replacement, directory fsync, SQLite WAL behavior, and short temporary
  paths.

The full implementation gate must include unit/adversarial tests, mypy, build,
twine, installed-wheel smoke in both modes, upgrade rehearsal, reindex,
deep validation, and the frozen evaluation without fixture changes.

## Rollback story

- Before SQLite commit, rollback is SQLite rollback plus an idempotent rerun;
  the verified snapshot may remain as an unmanaged copy.
- After SQLite commit, the migration is logically complete even if verification
  or marker publication is pending. Recovery finishes verification and marker
  publication; it does not run the transformations again.
- A verification defect requires a reviewed code fix or explicit owner decision.
  The framework must not restore the snapshot automatically.
- Explicit snapshot restoration is a separate whole-ledger replacement. Stop
  all clients, preserve the failed target for diagnosis, verify the selected
  snapshot and its digest, and obtain separate authorization. Restoring loses
  every later write and may resurrect erased content.
- Code downgrade is allowed only when the selected old reader supports the
  committed schema and every record kind. Retention v2 is refused by readers
  without that profile; 2.7.0 is unsafe after `adapter_receipt` and correctly
  refuses it. Deleting a marker or metadata field to force a downgrade is never
  rollback.

## Recommended implementation order after approval

1. Freeze recovery/CLI choices below and document the accepted contract.
2. Add registry and read-only plan/list support with tests.
3. Add the private transient intent and generic apply engine with fault
   injection tests.
4. Register the existing retention transformation without changing its
   successful persistent result; route the alias through it.
5. Extend upgrade rehearsal, SDK/CLI tests, compatibility documentation, and
   operator documentation.
6. Only then consider a new ledger schema or minimum-reader metadata.

## Open questions for the owner

1. Should the existing `--no-snapshot` escape remain indefinitely, be limited
   to the `retention-migrate` alias for one compatibility release, or be removed
   immediately from apply operations? The recommendation is a one-release
   deprecation followed by a mandatory snapshot.
2. Should one invocation compose every registered edge to the requested target
   in one transaction, as proposed, or require the owner to approve and run
   each adjacent schema step separately? One transaction is simpler; adjacent
   approvals make each irreversible boundary more visible.
3. Should the transient intent be removed after success, preserving the exact
   current final state, or retained as a payload-free audit receipt? The
   recommendation is removal because the target ledger's migration audit and
   marker already record success.
4. Is `<ledger>.migration-intent` an acceptable generic sidecar name, or should
   it be target-specific? A single generic sidecar prevents two migrations from
   being prepared concurrently.
5. Should future reader-breaking record kinds always force a new ledger schema,
   or may a schema-defined feature floor permit some in-schema additions? The
   recommendation is a new schema by default.
6. Should the generic migration engine be exposed through the public SDK in its
   first release, or remain CLI/internal until the crash matrix and one real
   post-retention migration prove the interface?
