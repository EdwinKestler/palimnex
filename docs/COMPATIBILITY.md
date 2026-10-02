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

The unreleased line adds two read-only command documents,
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
Redis or the ledger. No ledger, pack or cache identifier changes.
