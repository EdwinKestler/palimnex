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
