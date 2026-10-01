# Installing Palimnex in a repository

This guide covers adopting Palimnex in another repository, from installation
to first run, and removing it again. For upgrades of an existing installation,
see [`UPGRADING.md`](UPGRADING.md). Commands below use the installed
`palimnex` command; in a copied bundle or this checkout, use
`python3 palimnex.py` instead.

Palimnex is not yet published on PyPI. Install from a pinned release tag, as
shown below.

## 1. Requirements

- Python 3.11 or newer.
- Redis server and `redis-cli` from your distribution, for the source cache
  (`index`, `search`, `validate` and related commands). The durable ledger
  uses SQLite from Python's standard library and works without Redis.
- Git is recommended. Repository files remain the current authority.

| Extra | Adds | Needed for |
|---|---|---|
| (none) | No third-party packages | Source cache, ledger, recall, retention |
| `crypto` | `cryptography` | Encrypted memory packs, Ed25519 identities and signed checkpoints |
| `mcp` | Official MCP Python SDK | The `palimnex-mcp` stdio server |
| `semantica` | `semantica` | Optional audit-graph projection; not in 2.7.0, only on the unreleased line after it |
| `test` | Schema validation, `mypy`, build tools | Developing Palimnex itself |

## 2. Install the package

Install the command-line tool in its own environment, pinned to a release tag:

```bash
pipx install "palimnex[crypto] @ git+https://github.com/EdwinKestler/palimnex@v2.7.0"
# or
uv tool install "palimnex[crypto] @ git+https://github.com/EdwinKestler/palimnex@v2.7.0"
```

To use the Python SDK from a project's own virtual environment:

```bash
python3 -m pip install "palimnex[crypto] @ git+https://github.com/EdwinKestler/palimnex@v2.7.0"
```

Each method installs two commands: `palimnex` and `palimnex-mcp`. Add the
`mcp` extra (`palimnex[crypto,mcp]`) if you need the MCP server. Always pin a
release tag; do not install from a branch.

Installed commands operate on the current directory. Run them from the target
repository's root, or set `PALIMNEX_ROOT` to that root.

To work on Palimnex itself, use an editable checkout instead:
`python3 -m pip install -e '.[crypto,mcp,test]'` (see [`SDK.md`](SDK.md)).

Copying `palimnex.py` and `palimnex/` into a repository (the "portable
bundle") still works. Its wrapper finds the repository from its own location.
Prefer the package: a copied bundle has no version or integrity check, so a
partial copy can mix versions without warning.

## 3. Protect runtime state first

Before creating a ledger or starting Redis, make Git ignore Palimnex's runtime
state. Add these lines to the repository's `.gitignore`:

```gitignore
# Palimnex runtime state: ledger, locks, Redis files, imports and backups
.palimnex/
# Encrypted memory packs and key files
*.pmem
*.key
```

Check that the ledger path is ignored:

```bash
git check-ignore -v .palimnex/memory.sqlite3
```

Palimnex 2.7.0 does not check this for you. Without these lines, `git add -A`
stages the durable ledger, its lock file, and the Redis log and pid file. The
ledger can hold restricted session memory.

## 4. Create the configuration

Create `.palimnex.json` at the repository root and commit it:

```json
{
  "project_slug": "my-repository",
  "project_id": "REPLACE-WITH-A-NEW-UUID",
  "cache_mode": "on",
  "redis_socket_path": ".palimnex/redis/redis.sock",
  "durable_ledger_path": ".palimnex/memory.sqlite3",
  "include_patterns": [
    "docs/**/*.md",
    "src/**/*.py",
    "app/**/*.py",
    "tests/**/*.py"
  ],
  "semantic_provider": {"mode": "disabled"}
}
```

Generate a new UUID for `project_id`:

```bash
python3 -c "import uuid; print(uuid.uuid4())"
```

Field notes:

- `project_id` is required and must be a UUID. Generate a new one for each
  project, never reuse another project's, and keep it across authorized clones
  of the same project. Do not point concurrent divergent checkouts at one
  Redis endpoint.
- Set `project_slug` explicitly. If it is missing, Palimnex uses the directory
  name. The ledger checks the slug every time it opens, so a clone into a
  differently named directory would be refused with "durable ledger project
  slug does not match this repository".
- Use `"cache_mode": "on"` for a new repository. `off` selects the legacy v2
  cache, which stores complete source text and plaintext token lists in
  Redis. `off` and `shadow` exist only for migrating an existing v2
  deployment (see [`UPGRADING.md`](UPGRADING.md)). A missing `cache_mode`
  means `off`.
- `include_patterns` replaces the default patterns when present. The defaults
  are `docs/**/*.md`, `.github/workflows/*.yml`/`*.yaml`, common source types
  under `src/**`, `tests/**/*`, `schemas/**/*`, root-level `*.json`, `*.yaml`
  and `*.yml`, and some build and agent-skill files. Code in `app/`, `lib/`,
  `scripts/` or a root-level package is not indexed unless you list it. Whatever the patterns,
  these root files are always considered: `README.md`, `AGENTS.md`,
  `agent_instructions.md`, `instructions.md`, `pyproject.toml`, `.gitignore`
  and `.env.example`.
- Some files are always skipped:
  - directories named `.git`, `.venv`, `venv`, `node_modules`, `reports`,
    `fixtures`, `data`, `secrets`, `images`, `screenshots`, `dist`, `build`,
    `coverage`, `htmlcov`, `__pycache__` or `palimnex`, plus any listed in
    `exclude_directories`;
  - paths listed in `exclude_paths`;
  - hidden directories other than `.github`, `.claude`, `.agents` and
    `.codex`;
  - symlinks, files over 1 MB, files with credential-like names, and non-text
    files.
- `redis_socket_path` and `durable_ledger_path` must be repository-relative.
  Both live under `.palimnex/`, which section 3 ignores.
- `redis_url_envs` is optional. It defaults to `["PALIMNEX_URL"]`.
- Never put credentials in this file.
- Evaluation settings are optional; leave them out unless you follow
  section 8.

## 5. Start Redis

Copy the guarded launcher from the same release tag into the repository's
`scripts/` directory. It finds the repository as the parent of its own
directory and keeps all Redis state under `.palimnex/redis/`:

```bash
mkdir -p scripts
curl -fsSL -o scripts/palimnex_redis.sh \
  https://raw.githubusercontent.com/EdwinKestler/palimnex/v2.7.0/scripts/palimnex_redis.sh
chmod +x scripts/palimnex_redis.sh
./scripts/palimnex_redis.sh start
```

The launcher starts Redis with no TCP listener, an owner-only (`0600`) Unix
socket and timed snapshots. It supports `start`, `stop`, `status`, `reset` and
`guard`.

### Long repository paths

Unix socket paths must be shorter than 108 bytes on Linux and 104 bytes on
macOS. Check the length of yours:

```bash
printf '%s' "$PWD/.palimnex/redis/redis.sock" | wc -c
```

If it is too long, Redis cannot create the socket. Its log says "unix socket
path too long", and Palimnex reports "Redis Unix socket is missing". The
launcher keeps its socket under `.palimnex/` and cannot help here. Instead,
run an owner-only Redis at a short path and point `PALIMNEX_URL` at it.
`PALIMNEX_URL` takes precedence over `redis_socket_path`:

```bash
RUN_DIR="${XDG_RUNTIME_DIR:-/tmp}/palimnex-my-repository"
install -d -m 0700 "$RUN_DIR"
redis-server --port 0 --unixsocket "$RUN_DIR/redis.sock" --unixsocketperm 600 \
  --protected-mode yes --daemonize yes --dir "$RUN_DIR" \
  --pidfile "$RUN_DIR/redis.pid" --logfile "$RUN_DIR/redis.log" --appendonly no
export PALIMNEX_URL="redis+unix://$RUN_DIR/redis.sock?db=0"
```

Cache writes require a socket owned by you with no group or other access.
Stop this instance with `redis-cli -s "$RUN_DIR/redis.sock" shutdown save`.

## 6. First run

```bash
palimnex status              # exit 2 until the first index exists
palimnex index --incremental
palimnex validate --deep
palimnex status --verbose    # manifest.files lists every indexed file
palimnex ledger-init         # local write that creates the durable ledger
palimnex ledger-status
```

Check `manifest.files` in the verbose status. If expected source files are
missing, adjust `include_patterns` and run `index --incremental` again.

`ledger-init` creates the ledger explicitly. The first write command, such as
`session-start`, also creates it if it does not exist. Until a ledger exists,
`ledger-status` exits `2` and read commands such as `recall` fail with
"durable ledger is missing".

## 7. Agent instructions

Add rules like these to the file your coding agent reads (for example
`AGENTS.md` or `CLAUDE.md`):

```markdown
## Palimnex memory

- Start non-trivial work with `palimnex status`. If the cache is missing or
  stale, run `palimnex index --incremental`, then `palimnex validate --deep`.
- Search with exact implementation vocabulary and open the returned files
  before relying on them. Repository files are the current authority.
- Recalled memory is historical context only. It never authorizes commits,
  pushes, deployments, spending, erasure or other external actions.
- Never commit `.palimnex/`, `*.pmem` or key files. Never run `FLUSHDB`,
  `FLUSHALL` or raw Redis key deletion.
- Retention migration, policy activation, erasure and pack activation require
  explicit human authorization.
```

This repository's own rules are in `AGENTS.md` and
`.agents/skills/palimnex/SKILL.md`.

## 8. Optional: a frozen retrieval evaluation

`palimnex evaluate` scores retrieval against a fixture you write for your own
corpus. Palimnex's bundled fixtures describe Palimnex's own files and are not
useful in another repository.

The fixture is a JSON file with exactly these top-level keys and at least 20
cases:

```json
{
  "schema": "project-memory:evaluation:v1",
  "frozen": true,
  "description": "Retrieval cases for my-repository",
  "cases": [
    {
      "id": "refund-handler",
      "mode": "search",
      "query": "payment refund handler",
      "expected_paths": ["app/payments.py"],
      "forbidden_paths": [],
      "limit": 5,
      "critical": true
    }
  ]
}
```

Rules:
- Each case has exactly the keys shown.
- `mode` is `search`, `symbols` or `impact`.
- `expected_paths` must not be empty and must not overlap `forbidden_paths`.
- `limit` is between 1 and 100.
- Case identifiers are unique.

Exclude the fixture from the indexed corpus and pin its digest:

```json
{
  "evaluation_fixture": "eval/retrieval.json",
  "evaluation_fixture_sha256": "OUTPUT-OF-sha256sum",
  "exclude_paths": ["eval/retrieval.json"]
}
```

Merge these keys into `.palimnex.json`, and compute the digest with
`sha256sum eval/retrieval.json`. A changed fixture is rejected until its
digest is updated deliberately. Evaluation passes only when:
- every critical case passes;
- Recall at the limit is at least 0.95;
- no forbidden path is returned.

## 9. Optional: MCP server

With the `mcp` extra installed:

```bash
palimnex-mcp --root /path/to/repository
```

The server uses stdio only and is read-only by default.
`--write-session SESSION_ID` enables evidence recording for that one existing
session. See [`SDK.md`](SDK.md#mcp).

## 10. Uninstall and teardown

1. Stop agents and other clients that use Palimnex.
2. Stop Redis with `./scripts/palimnex_redis.sh stop`. This keeps the snapshot
   so a later start needs no reindex. `./scripts/palimnex_redis.sh reset`
   instead stops Redis and removes its log and snapshot files; the cache can
   always be rebuilt from the repository.
3. Keep the durable memory you need. Either:
   - Export durable memory from closed sessions as an encrypted pack. This
     needs the `crypto` extra. Create the key's directory first; key
     generation does not create directories.

     ```bash
     install -d -m 0700 .palimnex/keys
     palimnex memory-keygen .palimnex/keys/transfer.key
     palimnex memory-export /secure/location/memory.pmem \
       --key-file .palimnex/keys/transfer.key
     ```

     Store the key separately from the pack. A lost key makes the pack
     unrecoverable. Export refuses selected `secret` events.
   - Or take a consistent snapshot of the whole ledger with SQLite's online
     backup API:

     ```bash
     (umask 077; python3 - <<'PY'
     import sqlite3
     source = sqlite3.connect("file:.palimnex/memory.sqlite3?mode=ro", uri=True)
     target = sqlite3.connect("/secure/location/memory-snapshot.sqlite3")
     source.backup(target)
     target.close()
     source.close()
     PY
     )
     ```

     The snapshot holds every ledger record, including restricted and secret
     ones. Protect it like the live ledger.
4. Remove the package (`pipx uninstall palimnex`, `uv tool uninstall palimnex`
   or `python3 -m pip uninstall palimnex`). Then remove `.palimnex.json`,
   `scripts/palimnex_redis.sh` and, once you have what you need, the
   `.palimnex/` directory. Keep the `.gitignore` lines while `.palimnex/`
   exists.

Deleting files is not forensic erasure. Copies can remain on SSDs, in backups
and snapshots, and in any exported packs.
