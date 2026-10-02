# Ledger migration framework proposal

Status: proposal; owner decisions recorded; awaiting approval.

This proposal is not indexed (see AGENTS.md).

This document proposes a general, explicit framework for durable-ledger schema
migrations. It does not approve or implement a migration. Repository source and
the live ledger remain authoritative in their respective domains, and no plan,
snapshot, marker, pack, or historical record grants authority to apply a
migration.

## Goals and non-goals

The framework should provide one reviewed path for every future durable-ledger
schema change:

1. read-only plan;
2. durable replacement-guard publication;
3. verified pre-migration snapshot;
4. one SQLite transaction for one adjacent schema step;
5. exact structural, semantic, and integrity verification recorded in the
   transient intent before it is removed.

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
5. It creates and fsyncs `<ledger>.retention-v2`, whose bytes are exactly
   `project-memory:retention-ledger:v2`, before beginning the SQLite
   transaction. This marker is a durable replacement guard: it means that the
   ledger is, or may become, the retention schema, so legacy pack replacement
   must be refused.
6. It begins one immediate transaction, creates `retention_control`, changes
   `metadata.ledger_schema`, records the source digest in the first migration
   control entry, and commits.
7. It reopens through `RetentionLedger` and reports status.

Marker-before-transaction ordering is deliberate and load-bearing, not a
defect. `portable._refuse_retention_replacement()` checks the marker before it
returns early for a missing live database (`palimnex/portable.py:767-781`), and
`recover_import()` documents that the marker survives a damaged or missing
live database (`palimnex/portable.py:808-819`). `RetentionLedger` does not
consult this sidecar. If the guard were marker-last, a crash after SQLite
commit would leave a usable retention ledger without the guard; erasure could
then run, and later ledger loss followed by legacy pack activation could
resurrect erased data. A v1 ledger plus an exact marker is therefore an
intentional fail-closed, resumable state, not evidence that migration
verification completed.

The real legacy crash gap is inside marker creation. Current
`retention.migrate()` opens the final marker with `O_EXCL` and then writes its
bytes (`palimnex/retention.py:670-674`). A process exit between those operations
leaves a zero-length marker; current reruns see an existing marker and fail
with `invalid retention marker`. The generic engine must atomically publish
the guard and define a narrow recovery for this legacy empty-marker state.

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
   its exact checks after commit and before the intent records verified
   completion.
4. **One adjacent step, one transaction.** An invocation may apply only the
   immediate registered successor of the observed schema. That step mutates one
   connection inside one `BEGIN IMMEDIATE` transaction. Migration functions may
   not commit, checkpoint, vacuum, call external systems, or publish markers.
5. **Verified snapshot first.** The canonical apply path creates and verifies a
   source-schema snapshot under the exclusive lock before beginning the
   transaction.
6. **Replacement guard first; verification in the intent.** The target marker
   is durably and atomically published before `BEGIN IMMEDIATE` and is never
   removed. It means "this ledger is, or may become, the target schema; refuse
   legacy replacement." It does not attest to migration completion. The
   transient intent records the verified-target phase; success requires a
   verified target, the exact marker, and then removal of the intent.
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

The registry validates the whole graph and can report the ordered successor
chain, but one invocation applies exactly one adjacent edge. `--to` must equal
the immediate registered successor of the observed source schema. A farther
target is refused with the exact next step named. Missing links, cycles,
ambiguous paths, backward paths, and unknown schemas are also refused.
Multi-step composition is deferred until a second migration edge exists and is
separately designed and approved.

The registry is executable policy shipped with the selected Palimnex version;
it is not loaded from configuration, a pack, a plan file, Redis, or the ledger.

## Plan contract

`ledger-migrate --plan` returns a versioned machine-readable document, proposed
as `project-memory:ledger-migration-plan:v1`, containing at least:

- observed source and requested immediate target schemas;
- the single adjacent migration step and its user-visible effects;
- current logical digest and whether it matches `--expected-digest`;
- structural, semantic, import-intent, migration-intent, replacement-guard,
  Git-ignore, and snapshot preconditions;
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
   integrity; reject `<ledger>.import-intent`; require `--to` to be the source's
   immediate registered successor; recompute the logical digest; and compare
   it with `--expected-digest`. Before creating either an intent or snapshot,
   require `git_ignore_state(...)` to be `ignored` or `not_applicable`, using
   the same explicit override semantics as ledger creation.
2. **Publish the replacement guard.** Create an owner-only temporary marker,
   write the exact declared bytes, fsync it, install it at the final name with
   `os.link` so an existing file is never overwritten, unlink the temporary
   name, and fsync the directory. An existing exact, private marker is
   idempotent; any other content or unsafe object is refused. A legacy
   zero-length regular marker is the sole replacement exception: after
   rechecking its identity and size, atomically replace it with the fsynced
   temporary marker only while the exclusive lock is held, after the ledger
   exact-checks as the source v1 schema and its logical digest matches
   `--expected-digest`. Every other empty-marker case refuses. The exact final
   guard is never removed.
3. **Record transient intent.** Create an owner-only, no-follow, fsynced
   `<ledger>.migration-intent` containing a versioned intent, source, target,
   expected digest, exact snapshot path, registry/path identity, and phase.
   The intent is recovery state, never authority. It is removed after success,
   so the completed retention migration has no new persistent object.
4. **Write and verify the snapshot.** Call `durable.write_snapshot()` while the
   lock remains held. Record the verified path, schema, and digest in the
   transient intent and fsync it. The snapshot is not modified again.
5. **Apply once.** Begin one immediate transaction. Run the selected adjacent
   registry callback on the same connection, update `ledger_schema`, and record
   its migration audit entry. Commit once. SQLite rollback handles a process
   exit before commit.
6. **Verify the committed target and record completion.** Select the target reader from the committed
   `ledger_schema`; require its exact structural and semantic checks, SQLite
   integrity, foreign keys, project identity, and migration audit continuity.
   Verification happens under the same exclusive lock. Require the exact guard
   marker, write the `target_verified` phase to the intent, and fsync it.
   Failure leaves both the guard and intent so replacement remains refused and
   recovery can diagnose the unfinished migration.
7. **Finish.** After rechecking the verified-target intent and exact marker,
   remove the intent and fsync the directory. Return the target status plus the
   verified snapshot receipt and whether recovery completed any prior phase.

The intent contains no payloads, credentials, keys, or authorization. It should
use a new versioned identifier such as
`project-memory:ledger-migration-intent:v1` and bounded canonical JSON. Pack
import, pack activation, and `recover_import` must refuse while this generic
intent exists. Migration continues to refuse while the existing
`<ledger>.import-intent` exists.

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

`ledger-migrate --apply` always creates a verified snapshot and has no
`--no-snapshot` option. The legacy `retention-migrate --no-snapshot` escape
remains through the 2.9.x line, emits a stderr deprecation warning, and adds a
machine-readable `deprecations` field to JSON output. It is removed in 2.10.0.

The public API v1 method `migrate_retention(..., snapshot=False)` keeps that
default because changing it would be a breaking SDK change under
`docs/SDK.md`. When `snapshot is not True`, it emits `DeprecationWarning`.
`snapshot=True` routes to the mandatory-snapshot engine path. No new generic
public SDK method is introduced in the first release; the CLI and internal
engine are the generic surface, while `api.migrate_retention` continues to
route through that engine without otherwise changing its API v1 signature.

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
- `--to` must be the immediate registered successor of the observed schema; a
  farther target is refused and the response names the required next step.
- `--expected-digest` is mandatory for plan/apply even when resuming. A resume
  matches it against the intent and committed migration audit.
- `--plan` performs no filesystem writes, including no backup-directory or
  intent creation.
- `--apply` does not accept a plan file. It reports whether it started new work
  or resumed a recognized intent.
- An optional future `--recover` should be unnecessary: rerunning the exact
  `--apply` is the recovery operation. A separate inspection-only
  `--recovery-status` could be added if operators need it.

## Doctor diagnostics

`palimnex doctor` remains read-only and never creates, repairs, replaces, or
removes a marker, intent, snapshot, or ledger. It reports these states with an
exact next-step hint:

| State | Doctor classification and next step |
|---|---|
| pending `<ledger>.migration-intent` | action required; rerun the same `ledger-migrate --apply --to TARGET --expected-digest DIGEST` after reviewing the recorded phase |
| exact guard marker beside an exact v1 ledger | resumable; rerun the same adjacent apply with the matching v1 logical digest |
| zero-length marker | legacy interrupted publication; rerun apply only if the exact v1 source and expected digest can be confirmed under the lock |
| invalid, unsafe, or conflicting marker | refused; preserve files and obtain manual review rather than overwriting |
| exact retention ledger without marker | guard repair required; rerun the matching apply so it exact-verifies the target and atomically publishes the missing guard |

Hints must not imply that doctor performed verification under an apply lock or
that a marker alone proves migration completion.

## Crash points and recovery

| Crash or failure point | Durable state | Idempotent rerun behavior |
|---|---|---|
| Before guard publication | Source unchanged; no generic intent | Replan normally |
| During atomic guard publication | Source unchanged; only engine-owned temp or exact final marker | Remove only a safely identified temp; accept an exact final marker; refuse conflicts |
| After exact guard, before intent creation | Exact source plus durable replacement guard | Exact-check source and digest, then create the intent and continue; legacy replacement remains refused |
| After intent, before snapshot | Exact source and guard; prepared intent | Validate intent, source, digest, guard, and Git-ignore state; continue snapshot phase |
| During snapshot | Source and guard unchanged; possible incomplete intent-owned file | Verify it; reuse only if schema/digest/integrity match, otherwise quarantine it and allocate a new recorded path |
| After verified snapshot, before transaction | Source plus guard; verified snapshot retained | Reuse the verified snapshot; do not create another |
| During transaction, before commit | SQLite rolls back to source; guard and intent remain | Exact-check source and digest, then rerun the adjacent transaction once |
| After commit, before intent phase update | Target schema and migration audit committed; guard and intent remain | Infer committed completion from exact target schema plus audit entry matching source and expected digest; never reapply SQL |
| Target verification failure | Committed target; exact guard and intent retained | Fail closed and report verification errors; rerun verification after an approved code fix, never auto-restore |
| After target verification, before verified phase fsync | Target and guard present; intent may still show the earlier phase | Verify target and guard again, then record and fsync `target_verified` |
| After verified intent, before intent removal | Verified target, exact guard, completed intent | Verify all three, remove the completed intent, fsync the directory, return success |
| Rerun after success | Target schema, migration audit and marker | Return `already_migrated`; do not snapshot or mutate again |

There are three legacy recovery cases:

- A v1 ledger with an exact `.retention-v2` marker can be the result of the
  deliberate current marker-before-transaction ordering. It is a valid
  fail-closed replacement guard and resumable pre-commit state, not a crash
  defect. Rerunning the same authorized `--apply` with the same digest may
  continue only after exact-checking v1 and matching `--expected-digest`. The
  marker alone never proves migration completion.
- A zero-length `.retention-v2` marker can be the result of the current
  `O_EXCL`-then-write crash gap. It may be rewritten atomically only while the
  exclusive lock is held, after the live ledger exact-checks as v1 and its
  logical digest matches `--expected-digest`. If the ledger is missing,
  damaged, already target-schema, mismatched, or otherwise uncertain, preserve
  the empty guard and refuse legacy replacement and migration.
- A retention-v2 ledger with a missing marker is still discoverable from
  `metadata.ledger_schema` and its first migration control entry. The new
  engine exact-verifies the target, its audit entry, and the expected source
  digest, then atomically publishes the missing replacement guard. It does not
  rerun the transformation.

An intent whose source, target, digest, registry identity, snapshot path, or
live ledger does not match is not resumable. It is reported for manual review
without guessing or overwriting files.

## Clear downgrade messages for future schemas

A future version may add `minimum_reader_version` to the metadata of a new
versioned ledger schema as a diagnostic only. New readers could perform a
bounded raw metadata probe before selecting an exact reader and emit, for
example:

```text
ledger requires Palimnex >= 3.1.0; this reader is 3.0.2
```

The exact schema reader must still validate that field and the complete object
set. The field is diagnostic and fail-closed; it does not negotiate features,
authorize conversion, or permit an in-schema reader-breaking change.

This cannot improve already released readers. They may reject the new metadata
as an unexpected field, reject the new schema as unsupported, or fail semantic
validation as 2.7.0 does for `adapter_receipt`. They cannot display a future
message they were never programmed to parse. A new writer can only ensure that
they fail closed and document the downgrade boundary before the write.

The `adapter_receipt` boundary is the governing example: 2.7.0 cannot read the
kind added in 2.8.0 and refuses the ledger generically. Going forward, every
reader-breaking record kind or semantic **must** use a new versioned ledger
schema identifier plus a registered migration. A feature flag or
`minimum_reader_version` cannot substitute for that schema boundary.
`minimum_reader_version` remains future diagnostic work only.

## Packs, snapshots, and authority

- Migration changes only the live SQLite ledger. It never rewrites, upgrades,
  activates, deletes, or registers a `.pmem` pack. Encrypted pack v2 bytes and
  `project-memory:memory-pack:*` contracts remain unchanged.
- Pack import/activation continues to inspect actual ledger schema and markers,
  and must also refuse while `<ledger>.migration-intent` exists.
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
- Prove deterministic graph ordering and list output; prove plan/apply accept
  only the immediate successor and name that next step when a farther target is
  requested.
- Prove `--plan` leaves the complete ledger directory tree byte-for-byte
  unchanged, including no backups, marker, lock residue, or intent.
- Test digest match/mismatch, corrupt source, wrong project, pending import,
  pending migration intent, unsafe paths, ignored/not-applicable/not-ignored
  state and override, existing exact marker, zero-length marker, and conflicting
  marker.
- Test doctor as a read-only observer of pending intent, exact v1 plus guard,
  zero-length/invalid marker, and exact retention ledger without marker, with
  the specified next-step hints and no filesystem changes.

### Retention compatibility

- Run the legacy alias and generic command on equivalent fixtures and compare
  target SQLite object sets, metadata, logical documents, first migration
  control entry, status, and exact marker bytes.
- Preserve the current default verified snapshot name, mode `0600`, source
  schema, integrity, and logical digest.
- Prove `ledger-migrate --apply` always snapshots; prove the legacy alias emits
  stderr plus JSON deprecation output for `--no-snapshot` through 2.9.x and
  removes it in 2.10.0. Prove SDK API v1 keeps `snapshot=False` while emitting
  `DeprecationWarning` unless `snapshot=True`.
- Prove ordinary old readers refuse retention v2 and a 2.7.0 reader refuses a
  retention ledger containing `adapter_receipt`; prove 2.8.0+ reads it.
- Keep the installed-wheel upgrade rehearsal passing through the alias, then
  add the generic command as a second path without touching a live ledger.

### Transaction and crash matrix

- Inject exceptions and real child-process exits at every row in the crash
  table: guard temp write/fsync/link/unlink/directory-fsync, intent fsync,
  snapshot creation/verification, transaction before and after the adjacent
  step, commit, target verification, verified-phase fsync, and intent cleanup.
- After each interruption, assert either the exact source or exact target; no
  partially applied SQLite schema is acceptable.
- Rerun with the same digest and prove completion is idempotent. Rerun with a
  different digest, target, registry identity, or unsafe intent and prove
  refusal.
- Exercise exact v1 plus guard as resumable, the legacy zero-length marker gap,
  and target-without-marker repair. Prove marker-last behavior is never used.

### Snapshots, packs, and erasure

- Verify snapshots are made while the exclusive lock prevents concurrent
  writes and match the expected source digest.
- Verify an incomplete snapshot is never reused and a verified one is never
  overwritten.
- Verify later live-ledger erasure leaves the snapshot present and reports the
  unmanaged-copy warning.
- Verify pack bytes are unchanged, pack activation cannot replace a migrated
  ledger, every pack import/activation/recovery path refuses a generic
  migration intent, and no pack can select a migration.

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
  the durable replacement guard is deliberately retained, the verified
  snapshot may remain as an unmanaged copy, and legacy pack replacement stays
  refused. A source v1 ledger plus exact guard remains resumable with the same
  authorized apply and digest.
- After SQLite commit, the migration is logically complete even if verification
  or the intent phase update is pending. The guard was already published.
  Recovery finishes exact target verification, records `target_verified` in
  the intent, and removes the intent; it does not run the transformation again.
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

1. **4.1c: read-only framework.** Add and validate the ordered registry, plus
   `ledger-migrate --list`, `ledger-migrate --plan`, and the migration-specific
   doctor states. This slice performs no migration, marker, intent, or snapshot
   writes and does not move this proposal into the indexed corpus.
2. **4.1d: apply framework.** Add the generic intent, atomic replacement-guard
   publication and legacy empty-marker recovery, mandatory-snapshot apply
   engine, adjacent-step crash matrix, retention registration, alias routing,
   deprecations, pack refusals, and operator/compatibility documentation.
3. In 4.1d, move this approved proposal to `docs/MIGRATIONS.md` with the
   implementation. Because a new indexed documentation file can shift frozen
   retrieval rankings, run incremental indexing, deep validation, and the
   frozen evaluation. `docs/DESIGN.md` section 10 forbids rewording the design
   to dodge query vocabulary or current winners.
4. Extend the installed-wheel upgrade rehearsal through both the alias and
   generic CLI while preserving the live-ledger boundary.
5. Only then consider a second schema edge or future diagnostic
   `minimum_reader_version` metadata.

## Owner decisions

### D1. Snapshot policy and deprecation

`ledger-migrate --apply` always writes a verified snapshot.
`retention-migrate --no-snapshot` stays through 2.9.x with a stderr
deprecation warning and a `deprecations` field in JSON output, and is removed
in 2.10.0. SDK API v1 keeps `migrate_retention(snapshot=False)` as its default;
changing that default would be breaking. It emits `DeprecationWarning` whenever
`snapshot is not True`.

### D2. One adjacent step per invocation

`--to` must be the immediate registered successor of the observed schema.
Otherwise the engine refuses and names the next required step. The registry
still validates the whole graph. Multi-step composition is deferred until a
second edge exists.

### D3. Intent lifecycle

Remove the generic migration intent after verified success and directory
fsync. The target migration audit plus permanent replacement guard are the
persistent evidence.

### D4. One generic sidecar and Git-ignore guard

Use `<ledger>.migration-intent` with schema
`project-memory:ledger-migration-intent:v1`. Pack import, activation, and
`recover_import` refuse while it exists. Migration continues to refuse while
`<ledger>.import-intent` exists. Before creating the migration intent or a
snapshot, require `git_ignore_state(...)` in `{ignored, not_applicable}`, using
the ledger-creation override semantics.

### D5. Reader-breaking changes require a schema migration

Every reader-breaking record kind or semantic requires a new versioned ledger
schema identifier and registered migration. The `adapter_receipt` boundary from
2.7.0 to 2.8.0 demonstrates why an in-schema incompatible addition is not
acceptable policy. `minimum_reader_version` remains a future diagnostic only.

### D6. First-release surface

The first release exposes the generic framework through the CLI and internal
engine only. It adds no generic public SDK surface. Existing
`api.migrate_retention` routes through the engine with its API v1 signature and
default unchanged.
