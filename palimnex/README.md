# Portable Palimnex v2.9.0 bundle and Python SDK

Status: version 2.9.0 package implementation; see `docs/SDK.md` for public API v1
and publication requirements. This includes explicit local retention and
authorized-erasure functionality; it
does not activate a live retention policy, migrate or delete a live ledger, or
claim deletion from external copies.
Existing SQLite schema v1, Redis cache v3 and encrypted pack v2 formats remain
the compatibility baseline.

To adopt Palimnex in another repository, follow `docs/INSTALL.md`: install
the published package at an exact version (or from its pinned release tag),
add the `.gitignore` lines for
`.palimnex/`, `*.pmem` and `*.key`, create `.palimnex.json`, and start Redis
with the guarded launcher. In 2.8.0 and later,
`palimnex init --write` creates the configuration and `.gitignore` lines,
`palimnex redis start` runs the packaged launcher, and `palimnex doctor`
checks the result. Upgrades are covered in `docs/UPGRADING.md`.

The older portable-bundle layout is deprecated: it keeps working through
2.x, but it has no version or integrity check, `palimnex doctor` warns about
it, and its instructions are removed in 3.0.0. Move existing copies to the
package with "Copied bundle to package" in `docs/UPGRADING.md`. A copy keeps
these paths in their relative layout, with `scripts/palimnex_redis.sh` if it
uses the launcher.

```text
palimnex.py
palimnex/
.palimnex.json
```

The copied root entrypoint discovers the repository from its script location.
Installed console/module entrypoints use the current directory. `PALIMNEX_ROOT`
can explicitly override either; SDK clients always receive an explicit root.
Source indexing and the ledger use Python 3.11+ standard-library modules.
Pack v2 additionally requires the reviewed distribution
`python3-cryptography` package for ChaCha20-Poly1305. SQLite is the durable
memory authority; Redis is an optional, rebuildable discovery and hot-projection
cache. The full test gate also requires the `jsonschema` distribution for
Draft 2020-12 schema-conformance tests.

Release and schema compatibility are recorded in [CHANGELOG.md](CHANGELOG.md).
This repository's full design and operator guide are
`docs/DESIGN.md` and `docs/RUNBOOK.md`.

## Configuration

A repository needs a committed `.palimnex.json` with a stable random UUID and
an explicit slug:

```json
{
  "project_slug": "my-repository",
  "project_id": "REPLACE-WITH-A-NEW-UUID",
  "cache_mode": "on",
  "redis_socket_path": ".palimnex/redis/redis.sock",
  "durable_ledger_path": ".palimnex/memory.sqlite3",
  "include_patterns": ["docs/**/*.md", "src/**/*.py", "tests/**/*.py"],
  "semantic_provider": {"mode": "disabled"}
}
```

Generate a real UUID for each project
(`python3 -c "import uuid; print(uuid.uuid4())"`); never reuse the example or
another project's identity. Preserve it across authorized clones of that
project, but do not point concurrent divergent checkouts at one Redis
endpoint. Set `project_slug` explicitly: it defaults to the directory name,
and the ledger refuses to open under a different slug. Redis and ledger paths
must be repository-relative and ignored by Git.

`include_patterns` replaces the default corpus patterns, which cover
`src/**`, `docs/**/*.md`, `tests/**` and root configuration files but not
directories such as `app/` or `scripts/`. Check `status --verbose`
(`manifest.files`) after the first index. `docs/INSTALL.md` lists the defaults
and the always-skipped paths.

Evaluation is optional. `evaluate` needs a fixture written for your own
corpus, excluded from the index and pinned with `evaluation_fixture` and
`evaluation_fixture_sha256`; the fixtures bundled under
`palimnex/evaluation/` describe Palimnex's own files. See `docs/INSTALL.md`
for the fixture format.

`redis_url_envs` is optional and defaults to `["PALIMNEX_URL"]`; list any
legacy repository-specific URL variables there. Configuration files must not
contain credentials.

`cache_mode` is the explicit cutover flag. Use `on` for a new repository.
`off` indexes and reads the legacy v2 cache, which stores complete source text
and plaintext token lists in Redis; `shadow` builds both caches while reads
remain v2-authoritative. Missing means `off` for backward compatibility.
Advance an existing v2 deployment only after `migration-shadow` passes over a
fresh equal-corpus v2 baseline. If you started a new repository with `off`,
run `clear` while still in `off` mode to delete the plaintext v2 cache, then
switch to `on` and run `index --incremental`.

## Redis endpoints

The default may be an owner-only `redis+unix://` socket. Plain
`redis://HOST:PORT/DB` is restricted to explicit loopback hosts, and cache
writes additionally require authentication. Remote access requires
`rediss://[USER:]PASSWORD@HOST:PORT/DB`; the standard TLS context validates the
CA and hostname. Prefer injecting the URL through a protected environment or
file mechanism and never print it.

## Source discovery

```bash
python3 palimnex.py --version
python3 palimnex.py status
python3 palimnex.py status --verbose
python3 palimnex.py migration-shadow --limit 5
python3 palimnex.py index --incremental
python3 palimnex.py index --incremental --repair-deep
python3 palimnex.py validate --deep
python3 palimnex.py search "authentication boundary" --limit 5
python3 palimnex.py symbols "qualified.name" --limit 20
python3 palimnex.py impact "symbol_name" --limit 20
python3 palimnex.py path "source.name" "target.name" --edge-kind calls
python3 palimnex.py evaluate --limit 5
```

`status` and `validate` are compact by default and retain
`manifest.chunk_count`; `--verbose` exposes the complete active manifest.
Exit `0` means success/fresh, `2` means missing/stale or a failed quality gate,
and `1` means operational or validation error.

Frozen evaluation passes only when every critical case passes, aggregate
Recall@limit is at least 0.95, and `forbidden_clear` is true. Reported MRR is
diagnostic, not a pass/fail threshold. See `docs/DESIGN.md` section 10.

The v3 namespace includes the stable project UUID. Index builds scan source
content before deriving anything, stage an immutable generation, activate it
with a fenced writer lock, and retain three complete generations. Renewable
reader leases and a grace interval prevent post-activation garbage collection
from deleting records used by an in-flight reader.

Redis v3 records contain compact digested lexical postings, paths, hashes, line
bounds, keyed term digests and packed quantized vectors. They contain no raw
source text and no plaintext lexical-token list. Graph records do retain
plaintext structural names for symbols, headings and links. Search scores and
fetches at most 512 chunk candidates and reopens digest-verified source to
preserve the result `text` field; snapshot and graph verification still scan
the admitted checkout.

Python/Rust symbols plus deterministic Markdown and generic-document structure
form the graph. Extractor identity `document-structure:v2` resolves a
root-looking reference to an exact admitted corpus path first, then uses
Markdown-relative resolution only if that path is absent; this avoids false
`docs/docs/...` targets. `path` traverses strong links by default; probable
heuristic links require `--include-probable`.

`migration-shadow` builds and evaluates v3 beside a required fresh v2 baseline.
It never writes to the legacy namespace, proves its bytes unchanged, fills all
three retained v3 generations, and requires an equal corpus, Recall at least
0.95, zero forbidden hits, total retained-v3 Redis size at most `0.60x` v2,
and shipped `search()` p95 at most `10.0x` v2. The retired in-process hot
scorer used `1.20x`; that is not the current executable gate. With `cache_mode`
`shadow` or `on`, `clear` deletes only this project's v3 cache and reports that
both the durable ledger and v2 were untouched. With `off` (the default), it
deletes this project's legacy v2 cache namespace instead. Neither mode touches
the durable ledger.

The preserved legacy v2 namespace still contains full source chunks and
plaintext lexical-token lists. It remains sensitive rollback state until a
separately authorized retirement or lower-level local Redis reset; v3 `clear`
does not remove it.

The repository launcher's lower-level `reset` is deliberately different: it
stops only its verified Redis process and removes that instance's Redis log,
RDB dump and temporary RDB files. It preserves the SQLite ledger and adjacent
WAL, lock, import, backup and pack files, but every cache namespace that lived
only in the removed RDB needs rebuilding.

## Durable session memory

```bash
python3 palimnex.py ledger-init
python3 palimnex.py ledger-status
python3 palimnex.py session-start --task "TASK"
python3 palimnex.py remember --session ID --kind decision \
  --subject "SUBJECT" --payload '{"value":"small typed fact"}' \
  --retention durable \
  --evidence docs/file.md:1-5
python3 palimnex.py session-close ID --outcome "OUTCOME" \
  --evidence docs/file.md:1-5
python3 palimnex.py consolidate ID
python3 palimnex.py recall "QUERY" --promoted-only
python3 palimnex.py hot-events --limit 100
python3 palimnex.py audit-graph
```

SQLite uses WAL, full synchronous writes, foreign keys, process locking and
canonical-JSON-plus-zlib payloads. The event transaction creates an outbox row
before Redis projection. A Redis failure leaves durable data intact; use
`project-hot` to retry idempotently.

`remember` defaults to `retention=session`. SQLite is crash-safe local
staging/audit for all classes, but only explicit durable events can promote or
leave the machine in a pack. The v2.6 release candidate adds explicit,
operator-authorized local retention migration and cleanup; nothing is
forgotten automatically.

## Retention and authorized erasure

Inspect ordinary state with `retention-status`. On an isolated private ledger,
an operator may explicitly migrate the retention schema, activate a reviewed
policy, place or release holds, authorize an eligible record, register derived
fact support, review a digest-bound cleanup plan, apply it with a separate
forget key, and finalize compaction. See
`docs/RETENTION.md` for the complete runbook and policy rules.

Cleanup is an orchestrated local transaction, not `delete_node()`: it removes
eligible content and local derivatives, recomputes or withdraws dependent
facts, verifies affected local stores, and retains only a non-reconstructive,
hash-chained audit tombstone. Durable and imported records require explicit,
expiring per-event authorization. Session audit anchors remain protected.
`audit-graph` exports `palimnex:audit-graph:v1` of eligible memory and
tombstones. Pack v2 bytes stay unchanged; `--include-audit-graph` writes a
sibling JSON. Optional `palimnex.semantica` projects that graph as untrusted
history with TTL disabled; fail-closed adapter receipts hash onto the control
chain and do not claim forensic erasure. See `docs/SDK.md`.

Previously attempted Redis projections and managed packs fail closed until a
verified invalidation or regeneration adapter exists. SQLite compaction cannot
prove forensic erasure from SSDs, snapshots, backups, or third-party systems.
Migration, policy activation, cleanup application and finalization are
explicit writes and must never be inferred from installing this bundle.

After complete loss of the disposable hot namespace, `project-hot --rebuild`
resets delivered flags and force-replays all ledger-committed metadata in
bounded batches. This includes local audit events of every retention class but
does not promote or export `volatile`/`session` records. It does not project
payload bodies.

Events distinguish observation and validity time and may explicitly supersede
or contradict one same-subject event. Supersession changes current selection;
contradiction is additive and leaves both records visible. Recall supports
`--known-at`, `--valid-at`, and `--include-history`. Normal recall abstains from
claimed-untrusted/imported events; `--include-untrusted` is an explicit
historical-inspection mode. Promotion requires a closed session,
`retention=durable`, and current, locally-verified source evidence. All output
is `historical_only` and cannot authorize actions.

For local writes the ledger stamps `observed_at`; callers may supply only
`valid_from`. Only quarantined imports preserve a foreign recorded time.
Event, evidence, verification and verification-attempt chronology is
validated, and an append-only attempt timestamp is the ledger-clock check
time, clamped so it never precedes the event's previous attempt
(`attempt_sequence` breaks ties).

Verification attempts are append-only. Current verification is re-derived
from repository bytes: changed, unavailable or older-policy evidence makes the
ledger stale, excludes the event from current recall/consolidation, and a stale
`reverify` removes its current verification/promotion without erasing history.
`--include-history` retains stale observed events; imported/untrusted history
also requires `--include-untrusted`.

The Redis hot stream is notification metadata only. `hot-events` validates the
entire bounded batch and each field against SQLite before filtering/limiting;
it never returns payloads. `latest-projected` is only an expiring
delivery-order pointer, never a current-fact pointer. No Redis `active` pointer
exists.

## Workflows and packs

`workflow-put` accepts a bounded JSON file matching
`schemas/workflow-spec.v1.schema.json` and requires local source evidence.
`workflow-dry-run` reports every step with `will_execute: false`. There is no
workflow execution command.

Workflow specifications and semantic metrics JSON must be bounded regular,
non-symlink files inside the repository; the CLI opens them with no-follow
semantics.

```bash
python3 palimnex.py memory-keygen PRIVATE_KEY_FILE.key
python3 palimnex.py memory-export NEW_FILE.pmem --key-file PRIVATE_KEY_FILE.key
python3 palimnex.py memory-import FILE.pmem --key-file PRIVATE_KEY_FILE.key
python3 palimnex.py memory-import FILE.pmem --key-file PRIVATE_KEY_FILE.key --activate --replace
python3 palimnex.py memory-recover-import
```

Pack validation is the default. Activation is explicit, crash-recoverable and
retains the replaced database as a uniquely named backup. Pack v2 is
ChaCha20-Poly1305 authenticated and encrypted, but imported records remain
untrusted historical context; promotion and verification state are not
imported. Those records are absent from normal recall until matching local
source evidence is reverified; use `--include-untrusted` only for explicit
inspection.

The manifest selection is `retention-durable-closed-sessions:v1`: only closed
sessions with explicit durable non-anchor events, their durable anchors and
selected workflows are exported. Sequences are compacted; volatile/session
events, orphaned relations and empty selections are excluded or refused.
Each event also carries authenticated, sorted, unique, bounded term digests so
subject-only recall remains available after import; import validates and
restores those exact derived terms.

Pack and raw 32-byte key inputs must be private owner-controlled, one-link
regular files reached without symlinks. New keys and packs are mode `0600`.
Encrypted export permits `restricted` events, refuses selected `secret`
events, and rescans selected content with the current privacy policy. The outer
manifest contains no plaintext-content size or digest.

Shared-key authentication proves integrity and key possession, not sender
identity. Transfer key and pack separately, back up the key separately, and
rotate by generating a new key plus a new export. Key loss makes the pack
unrecoverable; there is no in-place rekey command. Key bytes must never enter
configuration, logs, Git or memory records. `PALIMNEX_PACK_KEY_FILE` may
hold only an injected path.

## Semantic hold

`semantic-status` reports disabled. The bundle defines only an in-process local
provider protocol and a metrics promotion gate. It installs no model, makes no
network call, builds no HNSW index, and gives semantic scores no retrieval
influence.

## Privacy boundary

Mandatory path, type, symlink and size checks still apply. In addition, exact
UTF-8 bytes are scanned for credential/key/token/WIF/mnemonic shapes before
indexing or persistence. Diagnostics return only a rule and line number. A
content exception is permitted only by exact reviewed SHA-256.

Derived hashes and vectors remain sensitive. Never expose Redis, commit its
state, commit SQLite or packs, use raw keys, reuse another project's namespace,
or run `FLUSHDB`/`FLUSHALL`.

Repository files remain authoritative. Redis and durable recall provide
candidates and history, never current operational authorization.
