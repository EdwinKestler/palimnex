# Contributing to Palimnex

Palimnex keeps repository source authoritative and treats cache and ledger data
as discovery or historical evidence only. Contributions must preserve that
authority boundary and must not include live runtime state or secrets.

## Development setup

Use Python 3.11 or newer in an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[crypto,mcp,test]'
```

Read `AGENTS.md`, `docs/COMPATIBILITY.md`, `docs/DESIGN.md`, and the documents
for the subsystem being changed. Start non-trivial work with:

```bash
python3 palimnex.py status
python3 palimnex.py validate --deep
python3 palimnex.py search "exact implementation vocabulary" --limit 5
```

If the cache is missing or stale, run `index --incremental` before validation.
Do not use `FLUSHDB`, `FLUSHALL`, raw Redis-key deletion, or another project's
namespace.

## Change discipline

- Keep each change to one coherent behavior and update code, schemas, tests,
  compatibility notes, operations, and rollback together.
- Preserve `project-memory:*` identifiers unless the change includes a
  versioned migration with reader compatibility and recovery evidence.
- Treat privacy admission, source reopening, project identity, migration
  intents, retention controls, deletion suppression, and tombstones as
  correctness and security boundaries.
- Do not infer authority for ledger migration, policy activation, erasure,
  pack activation, Git writes, network calls, provider use, or publication.
- Never commit `.palimnex/`, SQLite/WAL files, Redis state, packs, keys,
  credentials, raw private source, generated logs, or production data.

## Documentation and evaluation

Markdown documentation is part of Palimnex's indexed corpus. A documentation
edit can change retrieval ranking even when no Python code changes. After an
indexed-file edit, run:

```bash
python3 palimnex.py index --incremental
python3 palimnex.py validate --deep
python3 palimnex.py evaluate --limit 5
```

Review per-case movement and forbidden paths. Do not reword accurate
documentation to avoid relevant vocabulary, and do not change frozen labels or
expected paths merely to make a result pass.

Some ontology conformance fixtures bind exact versions of documentation files.
R18 permits re-pinning fixture file versions and registry digests only when the
selected range, its digest, and the intended label are unchanged. Any semantic
change or moved range requires independent review. Before ontology activation,
regenerate full promotion evidence after any indexed-corpus change.

## Validation and pull requests

Run focused tests while developing, then the standard gate for a material
change:

```bash
./scripts/palimnex_check.sh
```

Also run strict typing and packaging checks when changing public Python
surfaces, package data, release metadata, or build configuration. Pull requests
should state the exact scope, commands and results, compatibility and rollback
effects, cache/ledger state, known limitations, and what remains separately
unauthorized.

Do not stage, commit, push, tag, publish, deploy, or alter external systems
without explicit authority for that action. See `docs/RELEASING.md` for the
release transaction and `SECURITY.md` for private vulnerability reporting.
