# Compatibility policy

Palimnex is the product and repository name beginning with `2.6.0-rc.1`.
Its Python package, CLI, configuration file, state directory, scripts, and
environment variables use the `palimnex` name.

Existing serialized identifiers beginning with `project-memory:` are protocol
and storage format identifiers. They remain unchanged so compatible Redis v2/v3
records, SQLite schema v1 ledgers, encrypted pack v2 files, workflows,
retention plans, and tombstones are not silently reinterpreted.

`PROJECT_MEMORY_URL` remains a secondary Redis URL alias for migrations;
`PALIMNEX_URL` is preferred. New state defaults to `.palimnex/` and new
repositories use `.palimnex.json`. Renaming a format identifier requires a
new schema version and an explicit migration, not a search-and-replace.

Version 2.7.0 adds Python SDK v1, derivative/source/signer protocols v1,
`palimnex:source-locator:v1`, `palimnex:event-checkpoint:v1`, and detached
`palimnex:signature:v1` attestations. Existing ledger and encrypted pack bytes
keep their original formats. Structured locators occupy the existing string
field; old readers abstain from verifying their unknown prefix. SDK import
requires a signature by default; legacy CLI import remains explicitly v2.

Unreleased additive schemas on this line are `palimnex:audit-graph:v1` and
retention-control kind `adapter_receipt`. Pack v2 field sets are unchanged; an
optional sibling `.audit-graph.json` is a separate document. Semantica is an
optional extra and is never imported by core Palimnex.
See `docs/SDK.md` for trust roots, downgrade behavior and checkpoint limitations.
