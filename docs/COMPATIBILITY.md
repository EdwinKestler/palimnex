# Compatibility policy

Palimnex is the product and repository name beginning with `2.6.0-rc.1`.
Its Python package, CLI, configuration file, state directory, scripts, and
environment variables use the `palimnex` name.

Existing serialized identifiers beginning with `project-memory:` are protocol
and storage format identifiers. They remain unchanged so compatible Redis v2/v3
records, SQLite schema v1 ledgers, encrypted pack v2 files, workflows,
retention plans, and tombstones are not silently reinterpreted.

`PALIMNEX_URL` is the built-in Redis URL variable. `PROJECT_MEMORY_URL` is not
a built-in alias: it is honored only when a repository lists it in
`.palimnex.json` `redis_url_envs`, as this repository does for migrations. New state defaults to `.palimnex/` and new
repositories use `.palimnex.json`. Renaming a format identifier requires a
new schema version and an explicit migration, not a search-and-replace.

Version 2.7.0 adds Python SDK v1, derivative/source/signer protocols v1,
`palimnex:source-locator:v1`, `palimnex:event-checkpoint:v1`, and detached
`palimnex:signature:v1` attestations. Existing ledger and encrypted pack bytes
keep their original formats. Structured locators occupy the existing string
field; old readers abstain from verifying their unknown prefix. SDK import
requires a signature by default; legacy CLI import remains explicitly v2.

Version 2.8.0 adds `palimnex:audit-graph:v1` and the
retention-control kind `adapter_receipt`. Pack v2 field sets are unchanged; an
optional sibling `.audit-graph.json` is a separate document. Semantica is an
optional extra and is never imported by core Palimnex.
See `docs/SDK.md` for trust roots, downgrade behavior and checkpoint limitations.

Version 2.9.0 adds the ledger migration framework (`docs/MIGRATIONS.md`)
and four documents. Two are read-only command output,
`project-memory:ledger-migration-list:v1` (`ledger-migrate --list`) and
`project-memory:ledger-migration-plan:v1` (`ledger-migrate --plan`). They are
printed, never persisted, and are not apply tokens: an apply recomputes
everything under the exclusive lock. Both carry `will_write: false`,
`authority: historical_only` and `authorizes_actions: false`. A plan names one
adjacent step from the observed `ledger_schema` to the requested target, the
current `logical_digest`, whether it matches `--expected-digest`, the exact
reader checks, pending import or migration intents, the replacement-guard
state (`absent`, `exact`, `empty`, `invalid` or `unsafe`), Git ignore states,
the required snapshot, effects, `status` and `refusals`. The migration
registry ships with the code and is never read from configuration, packs,
Redis or the ledger.

`ledger-migrate --apply` prints `project-memory:ledger-migration-result:v1`:
`status` (`migrated`, `already_migrated` or `guard_repaired`), `source`,
`target`, `resumed`, `recovery` notes, the `replacement_guard` action
(`published`, `existing`, `replaced_empty` or `unchanged`), the verified
`pre_migration_snapshot` or `null`, `authority: historical_only` and
`authorizes_actions: false`. While an apply is unfinished, it keeps the
transient `<ledger>.migration-intent` (`project-memory:ledger-migration-intent:v1`):
owner-only canonical JSON of at most 4,096 bytes with exactly `schema`,
`ledger`, `source`, `target`, `expected_digest`, `registry` (a digest of the
shipped registry), `snapshot` (`null` or `path` and `verified`), `phase`
(`prepared`, `snapshot_verified` or `target_verified`), `authority` and
`authorizes_actions`. It holds no payload, key or authorization; an intent
that does not match the ledger, step, digest or registry is refused rather
than resumed. Pack import, activation and recovery refuse while it exists, and
it is removed after a verified target. The `<ledger>.retention-v2` guard keeps
its exact bytes; it is published atomically before the schema change and is
never removed. No ledger, pack or cache identifier changes.
