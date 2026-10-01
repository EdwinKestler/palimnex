# Palimnex installation and upgrade review

- Date: 2026-10-01
- Code reviewed: `main` at `0f61049` (2.7.0 line, plus unreleased audit-graph work)
- Scope: first install in a new repository, configuration, Redis setup, ledger
  initialization, code upgrades, cache and ledger migrations, rollback and
  downgrade, uninstall, release and distribution.
- Authority: findings are evidence for proposals. Nothing here was implemented,
  no live ledger was touched, and every rehearsal ran in disposable
  repositories that were deleted afterwards.

## Summary

Palimnex's upgrade *safety* is strong. Every durable change is explicit and
digest-bound. The ledger refuses unknown schemas, and a code upgrade
invalidates the cache instead of trusting it. In the rehearsal, a ledger
created by `2.6.0-rc.1` opened unchanged under 2.7.0, and recall still worked.

The *installation experience* is the weak side. A new adopter who follows the
documentation exactly gets:
- a plaintext source cache;
- a ledger that `git add -A` will commit;
- no supported way to start the owner-only Redis;
- a corpus that silently skips their application code;
- an evaluation configuration that cannot work.

None of this breaks the safety model. It undercuts it, because the safe path
is not the documented path.

Top five proposals:

1. Fix the adoption template and add an `.gitignore` snippet (docs only).
2. Add `palimnex init` (explicit, previewed config writer) and a read-only
   `palimnex doctor`.
3. Ship the Redis launcher with the package and handle long socket paths.
4. Write `docs/UPGRADING.md` with per-release upgrade notes. Add a
   pre-migration ledger snapshot and a `--dry-run` for `retention-migrate`.
5. Publish to PyPI through the existing Trusted Publishing workflow. Add CI
   jobs for every supported Python version and for an upgrade from the
   previous release.

## How installation and upgrade work today

| Path | How | Status |
|---|---|---|
| Source checkout | `pip install -e '.[crypto,mcp,test]'` (README, `docs/SDK.md`) | Works; documented |
| Wheel / PyPI | `pip install palimnex` | Not available: PyPI returns 404 although tag `v2.7.0` and `publish.yml` exist |
| Git URL | `pip install "palimnex @ git+https://github.com/EdwinKestler/palimnex@v2.7.0"` | Would work; not documented |
| Copied bundle | Copy `palimnex.py`, `palimnex/`, `.palimnex.json` (`palimnex/README.md:11-17`) | Works; upgrade means re-copying with no version or integrity check |

| Layer | Upgrade behavior |
|---|---|
| Code | Version in `pyproject.toml`, `core.BUNDLE_VERSION`, and twice in `scripts/package_smoke.py` |
| Redis v3 cache | Manifest stores `bundle_version`; any version change makes it invalid (`cache_v3.py:561`), so a reindex is required |
| Cache mode | `off → shadow → on`, gated by `migration-shadow` for v2 baselines |
| Ledger schema v1 | Exact schema, project and slug checks on every open (`durable.py:749-782`); no automatic migration |
| Retention profile | Optional `retention-migrate --expected-digest`, in place, writes a marker and switches `ledger_schema` to `project-memory:retention-ledger:v2` |
| Packs | Encrypted pack v2 unchanged; import quarantined |
| Rollback | Manual Git operation; "never downgrade across the retention migration" (`docs/RUNBOOK.md` §14) |

## What I exercised

| Rehearsal | Result |
|---|---|
| Built the wheel in an isolated venv and listed its contents | Package, schemas and fixtures present. No Redis launcher, config template, `.gitignore` or agent-instruction template. Test modules are shipped |
| Fresh repo, installed wheel, no config: `status`, `ledger-status`, `ledger-init` | Fails safely, but `status` reports "Redis connection refused" (silent fallback to `127.0.0.1:6379`) instead of "no `.palimnex.json`" |
| Fresh repo with the README template exactly (`cache_mode: "off"`) | Redis stored raw source text and plaintext token lists (`"text": "# Acme ...", "tokens": [...]`) |
| Same repo, default corpus | Indexed only `README.md`, `docs/design.md` and `.palimnex.json`; `app/payments.py` and `scripts/deploy.sh` silently skipped |
| Repository path of 125 bytes with the template socket path | Redis failed ("unix socket path too long (125), must be under 108"); Palimnex reported "Redis Unix socket is missing" |
| `ledger-init`, then `git add -A --dry-run` | Would stage `.palimnex/memory.sqlite3`, its lock, and the Redis log and pid |
| `evaluate` with the template's fixture in a wheel install | Failed with "bounded source could not be opened without following symlinks" (the file does not exist) |
| Switch `off → on` | v3 works; the plaintext v2 keys stay in Redis (`legacy_namespace_preserved: true`) |
| `2.6.0-rc.1` bundle with a promoted durable decision, upgraded in place to `main` | Ledger opened, integrity `ok`, recall intact. Cache `missing_or_invalid` (exit 2); `search` said "active cache generation is missing or malformed"; `retention-status` said `migration_required: true` with no next step |
| `retention-migrate` with a wrong digest, then the right one | Wrong digest refused (`DIGEST_MISMATCH`); right one migrated in place with no backup made |
| Writes after migration | Commits succeed, but every write reports `projection_pending: true`; `project-hot` and `hot-events` exit 1 ("adapter required") |
| Downgrade the migrated ledger to `2.6.0-rc.1` code | Reads fine (that version already contains the retention profile). A 2.5 reader could not be tested; by inspection it refuses the changed schema id |

## Strengths to keep

- **Explicit, fail-closed migrations.** `retention-migrate` requires the
  current logical digest and refuses a pending import or a corrupt ledger
  (`retention.py:627-655`). Nothing migrates on open.
- **Schema self-defense.** Every ledger open checks the exact metadata keys,
  table and column sets, project id, slug and codec (`durable.py:749-782`).
  A mismatch is treated as corruption, not as a migration hint.
- **Version-bound cache.** The manifest's `bundle_version` invalidates stale
  caches automatically, so an upgrade can never serve an incompatible index.
- **Durable compatibility in practice.** The rehearsal upgrade kept every
  durable record readable and recallable.
- **Release hygiene.** `publish.yml` pins action SHAs, uses OIDC Trusted
  Publishing, rebuilds from the reviewed tag, re-runs the full gate, and
  smoke-tests the installed wheel outside the checkout.
- **Zero runtime dependencies** for core paths, so environments are easy to
  reproduce.

## Findings

Severity reflects user impact during installation or upgrade.

### High

**F1. The adoption template steers new users to the plaintext v2 cache.**
`palimnex/README.md` (configuration example) sets `"cache_mode": "off"`. In
`off` mode the legacy v2 cache stores complete source chunks and plaintext
token lists in Redis, which the v3 design exists to avoid (`docs/DESIGN.md`
§3). `docs/RUNBOOK.md` already says a new cache with no v2 baseline should use
`on`. Reproduced: Redis held `README.md` text verbatim. Also, switching to `on`
later leaves the plaintext v2 keys in place until an explicit `off`-mode
`clear` or a Redis `reset`.

**F2. Nothing protects adopters from committing the ledger.**
Ignoring `.palimnex/` and `*.pmem` is a hard rule in this repository, but it
is enforced only by this repository's own `.gitignore`. Adopters get no
snippet, no check and no warning. Reproduced: after `ledger-init`,
`git add -A` would stage the SQLite ledger, its lock, and the Redis log and
pid. The ledger can contain restricted session memory.

**F3. The supported Redis launcher does not reach adopters.**
The quick start runs `./scripts/palimnex_redis.sh start`, but the script is
neither in the wheel nor in the copy-bundle file list, and it resolves the
repository from its own location (`cd "$(dirname "$0")/.."`). Adopters must
hand-roll an owner-only, socket-only Redis (`--port 0`, `unixsocketperm 600`)
or fall back to TCP, where writes are refused unless authenticated
(`core.py:1129-1141`).

### Medium

**F4. Long repository paths break the socket, with a misleading error.**
`redis_socket_path` must be repository-relative, and Linux limits socket
paths to 107 bytes (macOS to 103). A repository deeper than about 80
characters cannot use the template. The error is "Redis Unix socket is
missing", not "path too long".

**F5. There is no `init`, and first-run errors don't guide.**
Configuration is hand-written, including a fresh UUID. Without config,
`status` reports a TCP connection failure, and `ledger-init` reports
"`project_id` must be a committed UUID" without saying how to create one.

**F6. A clone into a renamed directory can lock users out of the ledger.**
`project_slug` falls back to the directory name (`core.py:257-261`), but every
ledger open checks it exactly (`durable.py:758`), and it is part of the
Redis namespace. A repository adopted without an explicit slug and then
cloned into a differently named directory gets "durable ledger project slug
does not match this repository". `palimnex/README.md` says the slug is
required; `docs/SDK.md` (correctly) says it defaults.

**F7. The default corpus silently misses common layouts.**
The default patterns cover `src/**`, `docs/**/*.md`, `tests/**`, and root
configuration files (`core.py:64-121`). `data/`, `fixtures/` and `images/` are
excluded. Code in `app/`, `lib/`, `scripts/` or a root-level package is not
indexed, and `index` gives no coverage summary or warning.

**F8. Evaluation configuration is unusable for adopters.**
The template points `evaluation_fixture` at Palimnex's own
`palimnex/evaluation/v25.json`, whose cases name Palimnex files, with an
all-zero digest. In a wheel install the file does not exist, and the error is
about symlinks. No tool helps an adopter create a fixture for their own
corpus.

**F9. Not published, and installation docs are developer-only.**
PyPI has no `palimnex` project. The docs only describe an editable install
from a checkout. There is no documented pinned `git+https` install, and no
guidance for installing the CLI in isolation with `pipx` or `uv tool`.

**F10. There is no upgrade guide, and the consequences are scattered.**
The only upgrade note in the changelog is for 2.4.0. An operator upgrading
2.6 → 2.7 meets, with no explanation:
- an invalid cache, with a misleading `search` error;
- `migration_required: true` from `retention-status`.

If they then migrate the retention profile, three things change permanently:
- `project-hot` and `hot-events` stop working;
- every write reports `projection_pending: true`;
- activating an imported pack over the migrated ledger is refused
  (`portable.py:766-815`); validate-only quarantine still works. This
  prevents resurrecting erased data.

All of this is fail-closed by design, but it is documented only in one
paragraph of `docs/RETENTION.md` ("Conservative exclusions").

**F11. The retention migration has no built-in snapshot or dry run.**
It rewrites the live ledger in place. The docs say to rehearse on a copy but
give no command, and a plain file copy of a WAL-mode database can be
inconsistent. SQLite's online backup API, `sqlite3.Connection.backup` in
Python's standard library, makes a consistent snapshot while the database is
in use.

### Low

**F12. The version string is defined in three files.** It appears in
`pyproject.toml`, `core.BUNDLE_VERSION`, and twice in
`scripts/package_smoke.py`, and is restated in READMEs and the init prompt.
Only `publish.yml` checks that they agree; no unit test does.

**F13. Only Python 3.11 is tested.** CI and publish run 3.11 only, while
`requires-python = ">=3.11"`. Interpreter upgrades to 3.12–3.14 are untested,
and macOS (with its smaller socket limit) is not covered.

**F14. Test code is shipped as runtime.** The wheel ships `palimnex.tests`,
including the `test_*.py` modules, because `challenge.py` imports
`tests.fake_redis` and `tests.support` at runtime.

**F15. No uninstall or teardown guidance.** Nothing says how to stop Redis,
archive or export the ledger, and remove configuration without losing history.

**F16. Copied-bundle upgrades are unverifiable.** A partial copy can mix
versions undetected (the `palimnex/` directory is excluded from indexing).
`docs/AGENT_INIT_PROMPT.md` hard-codes `/home/kestl/github/palimnex`, and
adopters get no `AGENTS.md` or skill template.

## Proposals

Each proposal keeps Palimnex's rules: explicit writes, fail-closed defaults,
no automatic durable mutation, and repository source as the authority.

### Phase 1: documentation and configuration (low risk, about a day)

| # | Change | Fixes |
|---|---|---|
| 1.1 | Template: `cache_mode: "on"`, explicit `project_slug`, `include_patterns` example, evaluation fields removed or marked optional | F1, F6, F7, F8 |
| 1.2 | `.gitignore` snippet in every install path (`.palimnex/`, `*.pmem`, key files) | F2 |
| 1.3 | New `docs/UPGRADING.md`: per-release table (2.4 → 2.5 reindex; 2.5 → 2.6 optional retention migration and its permanent consequences; 2.6 → 2.7 reindex only), pre-flight checklist, rollback limits. Add an "Upgrade notes" subsection to each changelog release | F10 |
| 1.4 | Install section: pinned `git+https://…@v2.7.0` until PyPI exists; `pipx` / `uv tool install` for the CLI; extras matrix | F9 |
| 1.5 | Uninstall and teardown section: stop Redis, export a pack or archive the ledger, remove configuration | F15 |
| 1.6 | Make the init prompt path a placeholder; document the agent-instruction template | F16 |

### Phase 2: small additive commands (low to medium risk)

**2.1 `palimnex init` (an explicit write, previewed by default).**
- Without `--write` it only prints the proposed `.palimnex.json`: a fresh
  `uuid4`, the slug pinned to the current directory name, `cache_mode: "on"`,
  and `include_patterns` proposed from the directories it finds.
- It also prints the `.gitignore` lines it would add.
- With `--write` it creates the files exclusively and refuses to overwrite.
- It never creates the ledger, starts Redis, or contacts the network.

Fixes F1, F2, F5, F6, F7.

**2.2 `palimnex doctor` (read-only; exit `0` healthy, `2` action needed, `1`
error).** It checks:
- that the configuration is present and valid, and the slug is pinned;
- that `.palimnex/` is git-ignored (`git check-ignore`, skipped without Git);
- the socket path length against the platform limit;
- that the Redis socket exists and is owner-only, plus which version built
  the cache ("reindex required");
- whether a legacy v2 plaintext namespace is present;
- the ledger schema or profile, and the retention-migration status with its
  consequences;
- corpus coverage: indexed versus skipped files per top-level directory;
- the Python version and which optional extras are installed.

Fixes F2, F4, F6, F7, F10, F12.

**2.3 Actionable error messages.**
- "no `.palimnex.json`; run `palimnex init`";
- "socket path is N bytes; the limit is 107; set `PALIMNEX_URL` or a shorter
  state directory";
- "cache was built by 2.6.0-rc.1; run `index --incremental`".

Fixes F4, F5, F10.

**2.4 Ship the launcher.** Either port `scripts/palimnex_redis.sh` to a
`palimnex redis start|stop|status|reset` subcommand, or package it with a
console entry point. When the repository-relative socket path is too long,
fall back to an owner-only runtime directory such as `$XDG_RUNTIME_DIR`, and
tell the client through `PALIMNEX_URL`. Fixes F3, F4.

**2.5 Commit guard.** `ledger-init` refuses to create a ledger at a path Git
does not ignore, with an explicit override flag; `status` and `doctor` warn.
Fixes F2.

**2.6 Migration safety.**
- `retention-migrate --dry-run` prints the effects (hot projection disabled,
  pack import disabled, marker written) and the digest it would bind.
- A real migration first writes an owner-only snapshot with the SQLite online
  backup API under `.palimnex/backups/`, verifies the snapshot's integrity and
  logical digest, and reports its path.
- A standalone `ledger-backup` command reuses the same code.

Fixes F10, F11.

### Phase 3: release engineering (medium effort)

**3.1 Publish to PyPI.** Configure the PyPI Trusted Publisher, then dispatch
`publish.yml` for `2.7.0`. The pinned `pypa/gh-action-pypi-publish` v1.13.0
produces PEP 740 attestations by default. This needs owner authority. Fixes
F9.

**3.2 One version source.** Derive `BUNDLE_VERSION` from
`importlib.metadata`, with a fallback for the copied bundle. Have
`package_smoke.py` read the expected version from `pyproject.toml`, and add a
unit test that they agree. Fixes F12.

**3.3 CI matrix.** Python 3.11–3.14 on Ubuntu, plus one macOS job for the
socket limit and permission behavior. Fixes F13.

**3.4 Upgrade-from-previous-release job.** In CI:
1. Install the previous tag.
2. Create a ledger with sessions, a promoted durable event and a cache.
3. Upgrade to `HEAD`.
4. Assert the ledger opens, its integrity is `ok`, recall is unchanged, and
   the cache reports "reindex required".
5. Run `retention-migrate` on a copy and assert the documented consequences.

This automates the rehearsal in this review. Fixes F10, F16.

**3.5 Move the test doubles.** Move `fake_redis` and `support` into a private
runtime module (for example `palimnex._offline`) and exclude `palimnex.tests`
from the wheel. Fixes F14.

### Phase 4: structural (design work first)

**4.1 One migration framework.** An ordered registry keyed by the existing
`ledger_schema` metadata. Every migration (retention v2 and future ones) goes
through the same `plan → snapshot → apply → verify → marker` steps, uses
`--expected-digest`, and is never automatic.

**4.2 Restore the hot view after migration.** A hot-projection adapter for the
retention profile, so migrating no longer costs `hot-events`.

**4.3 Retire or verify the copied bundle.** Either publish an integrity
manifest (file digests) that `doctor` verifies, or deprecate the copied-bundle
mode in favor of the package.

## Suggested order

1. Phase 1 in one documentation PR, re-checked with the doc claim workflow.
2. `doctor`, then `init`, then error messages and the commit guard (2.2,
   2.1, 2.3, 2.5). Each is additive and testable in isolation.
3. Snapshot and dry run for migrations (2.6), then the launcher (2.4).
4. Version single-sourcing and the CI matrix (3.2, 3.3), the upgrade job
   (3.4), then PyPI publication (3.1) once the install path is smooth.
5. Phase 4 after a design note.

## Sources

- [PyPI: digital attestations (PEP 740) announcement](https://blog.pypi.org/posts/2024-11-14-pypi-now-supports-digital-attestations/)
- [pypa/gh-action-pypi-publish v1.11.0: attestations on by default](https://github.com/pypa/gh-action-pypi-publish/releases/tag/v1.11.0)
- [SQLite Online Backup API](https://www.sqlite.org/backup.html)
- [How to back up a WAL-mode SQLite database](https://oneuptime.com/blog/post/2026-09-08-back-up-wal-mode-sqlite-safely/view)
- [Versioning and migrating an embedded SQLite schema](https://oneuptime.com/blog/post/2026-09-08-version-migrate-embedded-sqlite-schema/view)
- [How do `uv tool` and `pipx` compare?](https://pydevtools.com/handbook/explanation/how-do-uv-tool-and-pipx-compare/)
- [Why Unix socket paths are limited to 108 bytes](https://linuxvox.com/blog/why-is-the-maximal-path-length-allowed-for-unix-sockets-on-linux-108/)
- [Configuring Redis for Unix socket connections](https://oneuptime.com/blog/post/2026-03-31-redis-how-to-configure-redis-for-unix-socket-connections/view)
