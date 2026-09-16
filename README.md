# Palimnex

Palimnex is a repository-local memory system for coding agents. It combines a
rebuildable Redis source-discovery cache with a durable SQLite historical
ledger, encrypted portable packs, evidence-aware retrieval, and explicit
retention and authorized-erasure controls.

This repository is the independent continuation of the portable Project Memory
bundle originally developed inside `btc-usdt-atomic-swap`. Product-facing
development now belongs here. No live Redis data, SQLite ledger, credentials,
wallet material, atomic-swap implementation, or repository-specific rollback
snapshot was copied.

The initial independent release line is `2.6.0-rc.1`.

## Quick start

Requirements are Python 3.11+, Redis server/CLI for cache-backed integration,
and the distribution `cryptography` package for encrypted packs.

```bash
./scripts/palimnex_redis.sh start
python3 palimnex.py status
python3 palimnex.py index --incremental
python3 palimnex.py validate --deep
python3 palimnex.py evaluate --limit 5
python3 palimnex.py ledger-status
```

Run the standalone gate with:

```bash
./scripts/palimnex_check.sh
```

Repository source is authoritative. Cache and ledger results are discovery or
historical evidence, never authorization to execute external actions.

## Layout

- `palimnex.py` — repository-root CLI.
- `palimnex/` — engine, schemas, fixtures, and tests.
- `docs/` — design, operations, retention, and evaluation contracts.
- `scripts/palimnex_redis.sh` — owner-only Unix-socket Redis launcher.
- `.palimnex.json` — this repository's safe local configuration.
- `LICENSE` — MIT license.
- `.github/workflows/palimnex-check.yml` — CI for the standalone gate.
- `docs/index.html` — dependency-free GitHub Pages architecture site.

See [the operator runbook](docs/RUNBOOK.md), [retention policy](docs/RETENTION.md),
[compatibility policy](docs/COMPATIBILITY.md), [maintainer initialization prompt](docs/AGENT_INIT_PROMPT.md),
and [extraction record](docs/PROVENANCE.md).

The Pages source can be previewed locally and published from `docs/` by an
authorized maintainer. See [the Pages guide](docs/PAGES.md) for the workflow
and branch-source options.

## Safety boundary

Palimnex never forgets durable data automatically. Cleanup is a separate,
authorized transaction that resolves derivatives, enforces holds, removes
eligible local content and indexes, recomputes dependent facts, verifies local
stores, and writes a non-reconstructive audit tombstone. It does not claim
forensic deletion from SSDs, backups, snapshots, third-party systems, or
unmanaged exported copies.

## License

Palimnex is released under the MIT License. See [LICENSE](LICENSE).
