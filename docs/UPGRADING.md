# Upgrading Palimnex

This guide covers moving an existing Palimnex installation to a newer
version: the code, the Redis cache, and the durable SQLite ledger. For a new
installation, see [`INSTALL.md`](INSTALL.md). Commands use the installed
`palimnex` command; in a copied bundle or this checkout, use
`python3 palimnex.py` instead.

Upgrades never migrate durable state on their own. A new version number
invalidates the disposable Redis cache, which you rebuild with
`index --incremental`. The ledger keeps its format unless you explicitly run a
migration.

## Before every upgrade

1. Read the notes for every version between yours and the target, in the
   table below and in `palimnex/CHANGELOG.md`.
2. Stop agents and other clients that write to Palimnex.
3. Run `palimnex ledger-status`. It must report `"status": "ready"`. Note its
   `counts` and `logical_digest`.
4. Take a consistent snapshot of the ledger with SQLite's online backup API,
   and keep it outside the repository or under the ignored `.palimnex/`
   directory:

   ```bash
   (umask 077; python3 - <<'PY'
   import sqlite3
   source = sqlite3.connect("file:.palimnex/memory.sqlite3?mode=ro", uri=True)
   target = sqlite3.connect("/secure/location/memory-before-upgrade.sqlite3")
   source.backup(target)
   target.close()
   source.close()
   PY
   )
   ```

   Use your configured `durable_ledger_path` if it differs. Do not copy the
   database file directly while it is in use. A plain copy of a WAL-mode
   database can miss committed data.

   In 2.8.0 and later, `palimnex ledger-backup` does this for you. It
   writes a new `0600` snapshot under `backups/` beside the ledger, or to
   `--output PATH`, and verifies its integrity and logical digest. Later
   authorized erasure does not remove snapshots, so protect and delete them
   deliberately.

## Install the new version

Reinstall the exact published version from PyPI (replace `X.Y.Z`):

```bash
pipx install --force "palimnex[crypto]==X.Y.Z"
uv tool install --force "palimnex[crypto]==X.Y.Z"
python3 -m pip install --upgrade "palimnex[crypto]==X.Y.Z"
```

The matching Git release tag remains an alternative:

```bash
pipx install --force "palimnex[crypto] @ git+https://github.com/EdwinKestler/palimnex@vX.Y.Z"
uv tool install --force "palimnex[crypto] @ git+https://github.com/EdwinKestler/palimnex@vX.Y.Z"
python3 -m pip install --upgrade "palimnex[crypto] @ git+https://github.com/EdwinKestler/palimnex@vX.Y.Z"
```

Use the command that matches how you installed it, and keep the same extras.
For a copied bundle, delete the old `palimnex.py` and `palimnex/` and copy the
new ones from the tag. Do not copy on top of the old directory, because files
removed in the new version would otherwise remain. Update
`scripts/palimnex_redis.sh` from the same tag.

## After every upgrade

```bash
palimnex --version
palimnex ledger-status       # still "ready", same counts
palimnex status              # exit 2 if an older version built the cache
palimnex index --incremental
palimnex validate --deep
palimnex recall "a subject you know is in memory"
palimnex retention-status
palimnex doctor              # 2.8.0 and later: all checks in one report
```

What to expect:

- The cache manifest records the version number that built it. The 2.7 to 2.8
  version change invalidates the cache: `status` reports `missing_or_invalid`
  and `search` identifies the older builder until you run
  `index --incremental`.
- `retention-status` may report `"migration_required": true` on a ledger that
  was never retention-migrated. That is information, not an instruction. The
  retention migration is optional; see below before running it.
- If `ledger-status` reports `"status": "missing"`, the configured ledger
  path no longer points at your ledger. This happens, for example, after a
  default path change or a moved configuration. Do not run `ledger-init` or
  `session-start`: either one creates a new empty ledger at the new path. Set
  `durable_ledger_path` in `.palimnex.json` to the existing ledger's
  repository-relative path instead.
- If the ledger reports "project slug does not match this repository", the
  checkout's directory name changed and `project_slug` was never set. Add the
  original slug to `.palimnex.json`.

## Version notes

| From → to | Code and cache | Ledger | Notes |
|---|---|---|---|
| 2.4 → 2.5 | New compact v3 cache beside v2; `cache_mode` missing means `off` (v2) | New SQLite ledger (`project-memory:ledger:v1`) | Migrate the cache only through `migration-shadow` (below) |
| 2.5 → 2.6 | Product renamed to Palimnex; reindex | Unchanged schema v1 | Configuration and naming changes below; optional retention migration added |
| 2.6 → 2.7 | Installable package and SDK v1; reindex | Unchanged schema v1, pack v2 unchanged | Structured source locators; SDK pack import requires a signature by default |
| 2.7 → 2.8 | Audit graph, optional Semantica extra; version change invalidates the cache, so reindex | Unchanged schema v1; new retention-control kind `adapter_receipt` | Downgrade hazard below |

### 2.5 → 2.6: Palimnex naming

Identifiers beginning with `project-memory:` are storage formats and stay
unchanged (see [`COMPATIBILITY.md`](COMPATIBILITY.md)). Around them:

- The configuration file is `.palimnex.json`. A repository that still has only
  `.project-memory.json` keeps working, because Palimnex reads it when
  `.palimnex.json` is absent. `include_project_memory` is still honored when
  `include_palimnex` is absent.
- `PALIMNEX_URL` is the built-in Redis URL variable. `PROJECT_MEMORY_URL` is
  read only if `.palimnex.json` lists it in `redis_url_envs`.
- New state defaults to `.palimnex/`, with the ledger at
  `.palimnex/memory.sqlite3`. If your ledger lives elsewhere, set
  `durable_ledger_path` before running any write command (see "After every
  upgrade").
- Redis state from an older launcher directory is not migrated. The cache is
  disposable: start the launcher and reindex.

### 2.6 → 2.7

- Palimnex becomes an installable package with the `palimnex` and
  `palimnex-mcp` commands. A copied bundle keeps working.
- Events can carry structured `palimnex:source-locator:v1:` locators. Older
  readers do not verify those locators, so after a downgrade such events stay
  unverified.
- `Palimnex.import_pack` in the SDK requires a pack signature by default. The
  CLI `memory-import` keeps the v2 behavior.

### 2.7 → 2.8: downgrade hazard

Version 2.8.0 adds the retention-control kind `adapter_receipt`, which
is written when a fail-closed Semantica (or other) erasure adapter records its
receipt. Version 2.7.0 does not know this kind. Once a ledger contains one,
2.7.0 refuses the whole ledger:

```text
durable ledger failed semantic validation: retention control or tombstone validation failed
```

Recall, status and every other ledger command then fail under 2.7.0. Do not
record adapter receipts until you no longer need to run 2.7.0 against that
ledger.

### 2.7 → 2.8: ledger creation guard

Inside a Git work tree, version 2.8.0 refuses to create a ledger at a
path Git does not ignore. This applies to `ledger-init`, the first
`session-start` or other write, SDK `initialize()`, and pack activation. The
refusal happens before any directory, lock or database file is created. An
existing ledger is not affected. Add `.palimnex/` to `.gitignore` (or run
`palimnex init --write` in a new repository); the explicit overrides are
`ledger-init --allow-unignored-ledger` and SDK
`initialize(allow_unignored_ledger=True)`. `palimnex redis start` also
requires `redis_socket_path` in `.palimnex.json`.

## Cache migration from v2 to v3

Only repositories that still run the legacy v2 cache (`cache_mode` missing or
`off`) need this. New repositories start with `on`.

1. With `cache_mode` `off`, build a fresh v2 index: `palimnex index --incremental`.
2. Run `palimnex migration-shadow --limit 5`. It builds v3 beside the v2
   baseline, refuses if v2 changes, and requires an equal corpus. It checks
   that v3 uses at most `0.60x` the Redis bytes of v2 and has a p95 latency of
   at most `10.0x` v2.
3. Only after it passes, move `cache_mode` to `shadow` (both caches are built,
   v2 stays authoritative) if you want an observation period, then to `on`.
   Run `palimnex index --incremental` and `palimnex validate --deep`.

The legacy v2 namespace stays in Redis as a rollback source. It contains
complete source text and plaintext token lists, so treat it as sensitive.
`clear` in `shadow` or `on` mode does not touch it. When you no longer need
it, remove all Redis state with `./scripts/palimnex_redis.sh reset` (2.8.0
and later: `palimnex redis reset`), then start Redis again and reindex. If you never needed a v2 rollback (for
example, a new repository that started with `off` by mistake), run
`palimnex clear` while still in `off` mode, then switch to `on` and reindex.

## The optional retention migration

`retention-migrate` converts the ledger to the retention profile
(`project-memory:retention-ledger:v2`). That profile is required for retention
policies, holds and authorized erasure (see [`RETENTION.md`](RETENTION.md)).
The migration is explicit, rewrites the live ledger in place, and is bound to
the current logical digest:

```bash
palimnex ledger-status          # copy logical_digest
palimnex retention-migrate --expected-digest LOGICAL_DIGEST --dry-run   # 2.8.0 and later
palimnex retention-migrate --expected-digest LOGICAL_DIGEST
```

A wrong digest is refused with `DIGEST_MISMATCH`. Rehearse on a copy of the
repository first. With 2.7.0, take the snapshot described in "Before every
upgrade" yourself.

In 2.8.0 and later:
- `--dry-run` writes nothing. It reports the current and target schema,
  whether the digest matches, what would be refused, and the effects listed
  below.
- A real migration first writes a verified snapshot of the unmigrated
  ledger, named `*-pre-retention-v2.sqlite3` under `backups/` beside the
  ledger. It is taken under the exclusive lock and reported in the output.
  `--no-snapshot` skips it.
- The SDK takes the snapshot only with `migrate_retention(..., snapshot=True)`.
- Later authorized erasure does not remove these snapshots.

The migration's effects are permanent:

- Hot projection stops. `project-hot` and `hot-events` exit `1` ("adapter
  required"), and every later write reports `projection_pending: true`. The
  durable write itself still commits.
- Events whose hot projection was attempted before the migration cannot be
  erased (`store_not_adapted`) until an adapter can retire that projection.
  Migration does not remove the old Redis projection.
- `memory-import` is refused, even without `--activate`, with "retention
  ledger replacement requires a deletion-registry-aware adapter". Imported
  history therefore cannot revive erased records. Validate packs on an
  unmigrated copy if you need to inspect them.
- A marker file `<ledger>.retention-v2` is written beside the ledger. Never
  delete it to force compatibility.
- Readers without the retention profile (2.5 and earlier) refuse the
  migrated ledger with "durable ledger schema is unsupported".

## Rolling back

Code rollback is a manual Git or package operation. The runtime never
performs it. Follow `docs/RUNBOOK.md` section 14 and these limits:

- The Redis cache can always be rebuilt with `index --incremental` after
  reinstalling the older version.
- An older version can open the ledger only if it understands everything in
  it. After a retention migration, 2.5 and earlier cannot. After an adapter
  receipt, 2.7.0 cannot (see above).
- Restoring a ledger snapshot also restores everything erased after the
  snapshot was taken. Never restore a pre-erasure snapshot unless that
  resurrection is explicitly authorized. Palimnex provides no runtime data
  rollback for this reason.
