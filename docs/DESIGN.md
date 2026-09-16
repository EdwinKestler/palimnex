# Palimnex v2.5 design

Status: **implemented locally; release candidate.** This is repository-local
memory tooling, not application protocol or deployment authorization.

## 1. Outcome

Palimnex v2.5 separates two jobs that v2.4 put in one Redis database:

```text
repository source ──scan──> disposable Redis v3 discovery cache
agent event ────────scan──> durable SQLite ledger ──outbox──> Redis hot view
                                      │
                                      └── sanitized machine pack
```

- Repository files and Git remain authoritative for source.
- SQLite is authoritative for accepted session memory.
- Redis is a rebuildable projection. It is never the only copy of an
  acknowledged durable event.
- Machine formats are canonical. Human-readable JSON is generated only at the
  CLI boundary.
- Source indexing and ledger operations remain Python-standard-library code.
  Authenticated portable packs use the distribution-provided, reviewed
  `python3-cryptography` ChaCha20-Poly1305 implementation.
- Every recalled event and imported workflow says `authority: historical_only`
  and `authorizes_actions: false`.

The system remembers prior work. It does not restore permission to commit,
push, deploy, spend, create a wallet, contact a public network, install WDK/MCP,
or perform another side effect.

## 2. Identities and storage

The committed configuration supplies both a human project slug and a stable
project UUID. The UUID prevents unrelated projects with the same directory
name from sharing a cache accidentally. Clones of this project intentionally
keep the UUID; they must not point concurrent divergent checkouts at one Redis
endpoint.

| Store | Identity | Default location | Purpose |
|---|---|---|---|
| Legacy cache | `palimnex:project-memory:v2` | Redis | Read-only rollback source during migration |
| Discovery cache | `<slug>:<uuid>:project-memory:cache:v3` | Redis | Hashed postings, quantized vectors, graph records and three immutable generations |
| Hot projection | `<slug>:<uuid>:project-memory:hot:v1` | Redis | Bounded recent notification metadata and delivery-order pointers |
| Durable ledger | `project-memory:ledger:v1` | `.palimnex/project-memory/memory-v25.sqlite3` | Sessions, typed events, temporal history, verification attempts, evidence, workflows and outbox |

The SQLite database and its lock, WAL, import intent, backup and pack files are
private runtime state. SQLite is crash-safe local staging/audit for every
retention class. They must remain ignored by Git and mode `0600`; their parent
directory is mode `0700`. A configured path must stay inside the repository
and may not be a symlink. Repository-local `*.pmem` files are ignored as an
additional staging safeguard.

Every ledger open exact-checks the durable schema, project UUID, project slug
and payload codec. A metadata mismatch is corruption or cross-project state,
not a migration hint, and fails before records are used.

## 3. Source discovery cache

v3 stores no complete source chunk and no plaintext lexical-token list. A
chunk record contains:

- repository-relative path and line bounds;
- file and content digests;
- project-keyed term digests and term count;
- a packed signed-byte feature vector and its policy identity.

Graph records retain plaintext structural metadata such as symbol, heading and
link names so dependency queries remain useful. Paths and that structural
metadata are sensitive even though complete chunks and plaintext lexical token
lists are absent.

Search obtains candidates from bounded BM25-style postings, adds the existing
symbol contribution, and reopens only candidate source from the current
checkout. Candidate scoring and chunk fetch are capped at 512; the source
snapshot and exact graph/source verification intentionally still inspect the
admitted checkout. Returned candidates verify file and chunk digests before
including the familiar `text` field. This preserves the v2 CLI result shape
without retaining source bodies in Redis.

Markdown and generic text now produce deterministic nodes and edges under
extractor identity `document-structure:v2` for headings, links, file
references, configuration keys, commit references and explicit `status`,
`decision`, `supersedes`, `contradicts`, `evidence`, and `rollback` relations.
A root-looking reference resolves to an exact admitted corpus path first and
falls back to Markdown-relative resolution only when that exact path is
absent. This prevents a reference such as `docs/X.md` inside `docs/Y.md` from
silently becoming the false target `docs/docs/X.md`. Python and Rust
extraction remain as before.

### Generation safety

An index build stages a complete immutable generation and atomically changes
the active pointer. Readers acquire a renewable generation lease before loading
records. Garbage collection retains the current three complete generations and
does not remove a leased or grace-period generation. A writer lock and fenced
writes prevent a stale writer from activating or deleting records.

The legacy v2 namespace is not modified by v3 indexing, migration, normal
search, or `clear`.
Unlike v3, that preserved rollback namespace still contains complete source
chunks and plaintext lexical-token lists. Treat it as sensitive until a
separately authorized retirement or lower-level local Redis reset removes it;
v3 `clear` deliberately does not.

### Feature-mode cutover

The committed `cache_mode` is explicit and fail-closed:

| Mode | Indexing | Read authority |
|---|---|---|
| `off` | v2 only | v2 |
| `shadow` | v2 plus observed v3 | v2; v3 is comparison output only |
| `on` | v3 | v3 |

Configurations without the field default to `off`, preserving v2 behavior.
This repository finishes the evidenced migration at `on`. The separate
`migration-shadow` command requires a fresh v2.4 baseline, proves the v2 key
set and bytes unchanged, requires an equal source corpus, fills all three
complete retained v3 generations, and counts shared v3 records once. It gates
the total retained-v3 Redis size at no more than `0.60` of the active v2 baseline.
It also compares 66 samples per backend on the shipped `search()` path
over the same deep-validated corpus and requires v3 p95 at no more than
`10.0` of v2 p95 (the previous `1.20` cap applied to the retired in-process
hot scorer). A new cache with no v2 baseline uses normal `on` indexing;
it cannot claim migration-comparison evidence.

## 4. Privacy admission and Redis transport

Every admitted source byte is scanned before chunking, graph extraction or
vector construction. The scanner covers private-key headers, common provider
tokens, JWTs, Bitcoin WIF, mnemonic/private-key assignments and high-entropy
credential assignments. A refusal reports only rule identifiers and line
numbers, never the matched value. Exact-file exceptions require a reviewed
lowercase SHA-256 digest in configuration.

Derived term digests and vectors can still reveal information and must be
treated as sensitive cache data.

Redis policy is fail closed:

- default local writes use an owner-only Unix socket;
- plaintext TCP is restricted to an explicit loopback host;
- an unauthenticated loopback TCP endpoint is insufficient identity for writes;
- remote Redis requires `rediss://`, ACL authentication, normal CA validation
  and hostname verification;
- Redis URLs and credentials must never appear in committed files or output.

The bundled client has bounded RESP nesting, item sizes, arrays, aggregate
items/bytes, pipelines, total command bytes and one absolute I/O deadline per
operation. The repository still forbids raw keys, wildcard deletion,
`FLUSHDB`, and `FLUSHALL`.

## 5. Durable event model

The ledger is SQLite in WAL mode with foreign keys enabled and
`synchronous=FULL`. Writes use an exclusive process lock plus an immediate
transaction. Payloads use canonical JSON compressed with zlib; IDs and digests
are stored as fixed binary values.

Event kinds are:

```text
session_started task decision failure outcome workflow fact evidence
correction revocation session_closed
```

Each event records project, session, sequence, kind, subject digest,
`observed_at`, `valid_from`, optional superseded or contradicted event, claimed
trust, sensitivity, retention, payload and record digest. Evidence is stored
separately. For a local write, the system stamps `observed_at`; the caller may
set only `valid_from`. Neither the CLI nor the ledger API accepts a caller-set
local recorded/known time. Only an imported historical event may preserve its
foreign `observed_at`, and imports remain quarantined and untrusted. A
repository source locator has the exact form `path:start` or
`path:start-end`;
the referenced UTF-8 lines are hashed and verified before the event commits.

The schema contracts used by portable records are under
`palimnex/schemas/`. They document the wire shapes; SQLite constraints
and the Python validators remain the executable authority.

User-recorded events default to `retention=session`. That classification does
not physically remove the local SQLite audit row. Only an explicit
`retention=durable` event can be promoted or selected for a cross-machine pack.

## 6. Trust, time, supersession and contradiction

`observed_at` means when this memory was recorded. `valid_from` means when the
fact became effective. Recall can independently select `--known-at` and
`--valid-at`.

A superseding event must belong to the same project and subject. Normal recall
omits a predecessor only when the successor was both known and effective at the
requested times. `--include-history` exposes the chain. A contradiction must
also reference the same project and subject, but it is additive: both records
remain visible. Contradiction documents disagreement; only supersession changes
which record is current.

`observed` is a claim by the writer, not proof. `verified` is derived only from
current matching local source evidence. Closing a session does not promote all
of it. `consolidate` promotes only active decision, failure, outcome, workflow,
or fact events with `retention=durable`, evidence and local verification.

Verification is a current derived view over immutable evidence, not a
permanent badge. Each check adds an append-only `verification_attempts` row
whose timestamp is the actual check time. Session, event, evidence,
verification and attempt chronology is validated rather than trusted.
`ledger-status`, recall and consolidation reopen the current source and treat
changed, unavailable or older-policy evidence as stale. `reverify` success
refreshes current verification. A stale reverify returns `verified: false`,
removes the current verification and any promotion, and preserves both the
event and attempt history. Normal recall excludes stale events;
`--include-history` retains stale observed history. Imported/untrusted history
additionally requires `--include-untrusted` until locally reverified.
Promotion and supersession selection apply the requested knowledge/effective
times across sessions, rather than assuming session-local order.

Imported events are rebuilt as untrusted history. Imported verification and
promotion state is intentionally discarded. Normal recall abstains from all
claimed-untrusted events, including imported events. `--include-untrusted` is
an explicit historical-inspection mode. Matching local source evidence may be
reverified to admit an imported event to normal recall, but the result remains
historical-only and non-authorizing.

## 7. Hot projection and failure ordering

An event transaction inserts an outbox row in the same SQLite commit. Only
after that commit may the event be projected to Redis. Projection is
idempotent, bounds the stream to approximately 10,000 entries, and records
delivery notification, supersession and contradiction pointers without the
payload body. The subject pointer is named `latest-projected`: it denotes only
projection delivery order, expires with the projection retention window, and
is never a current-fact or authorization pointer. No Redis `active` key exists.

`hot-events` loads the complete bounded stream, validates its structure and
every metadata field against authoritative SQLite before applying its session
filter or result limit, and never returns payloads. It reports SQLite as the
payload authority. A poisoned, unknown, duplicated, malformed or mismatched
Redis record fails the whole read rather than becoming partial history.

If Redis is unavailable, the durable command succeeds and reports a pending
projection. `project-hot` retries pending outbox rows later. If the whole
disposable hot namespace was lost after delivery, `project-hot --rebuild`
resets this project's delivered flags and force-replays every durable metadata
record in bounded batches. Here, durable metadata means events committed to
the crash-safe ledger across all local retention classes; replay does not make
`volatile` or `session` events promotion-eligible or portable. It never
projects payload bodies. Redis failure
therefore costs immediacy, not acknowledged memory.

## 8. Workflows

A stored workflow requires locally verified source evidence and the exact
machine shape in `palimnex/schemas/workflow-spec.v1.schema.json`.
Every step declares its action, preconditions, expected result, rollback and
side-effect class.

Workflow specifications and semantic metrics JSON are accepted only through
bounded, no-follow file descriptors for regular paths inside this repository.

`workflow-dry-run` never executes a step. It returns:

```text
mode: dry-run
will_execute: false
authority: historical_only
authorizes_actions: false
past_authorization_replayed: false
```

There is deliberately no workflow-execute command.

## 9. Cross-machine packs and keys

A `.pmem` pack is a bounded binary envelope containing a canonical logical
document compressed with zlib, then authenticated and encrypted with
ChaCha20-Poly1305 under a raw 32-byte key. The canonical outer manifest and
framing are associated data. It exposes project/cipher/policy identity,
ciphertext length, nonce and key identifier, but no plaintext-content size or
digest. Parser limits bound the manifest, ciphertext, decrypted payload,
logical payload and compression ratio.

The key is generated as a new owner-only mode-`0600`, one-link regular file.
Input key and pack paths are opened component by component without following
symlinks and must remain owned, private, regular, one-link files throughout the
read. `--key-file` is mandatory unless `PALIMNEX_PACK_KEY_FILE` supplies
the path; key bytes are never printed or placed in configuration.

Shared-key authentication proves integrity and possession of that key. It does
not prove which person or machine created the pack. Transfer the pack and key
through separate protected channels, back up the key separately, and remove or
rotate it according to the receiving environment's retention policy. A lost
key makes the pack unrecoverable. Rotation means generating a new key and
exporting a new pack; there is no in-place rekey command.

The selection policy is `retention-durable-closed-sessions:v1`: export keeps
only closed sessions with at least one explicit durable non-anchor event,
their durable start/close anchors, and workflows bound to selected events. It
compacts per-session sequences and refuses orphaned relations or an empty
selection. Volatile and session-retained events never enter a pack. Encrypted
export permits `restricted` records but still refuses any selected `secret`
event. It rescans every selected task, payload, evidence locator and workflow
against the current privacy policy before encryption. Files are created new
with mode `0600` and an fsynced parent directory.

Each exported event also carries its sorted, unique, bounded 16-byte lexical
term digests. They are authenticated inside the encrypted logical document and
validated before import. Preserving these derived subject/payload terms keeps
subject-only recall stable across machines without inventing a plaintext
subject during reconstruction.

Import authenticates and validates before writing, and defaults to quarantine.
Activation is explicit; replacement uses a durable intent, candidate, backup,
fsync and atomic rename. A correctly authenticated import is still untrusted
historical context: possession of a symmetric key is not source verification,
and import cannot carry promotions or current verifications.

## 10. Evaluation and semantic hold

The frozen repository evaluation lives outside the indexed corpus, is pinned
by SHA-256 in configuration, and must contain at least twenty cases. A changed
fixture is rejected before evaluation until its intentional review updates the
pin. Acceptance requires:

- every critical case passing;
- aggregate expected-path recall at the selected limit at least `0.95`;
- no forbidden path hit;
- reported mean reciprocal rank.

Reported MRR is diagnostic, not a pass/fail threshold. This repository's
`2.6.0-rc.1` frozen fixture is 20/20 cases with Recall@5 `1.0`. Those two
figures are the acceptance result. On baseline commit `6bb9c72` the reported
MRR was `0.8333`; that value is not a retrieval miss and is not a scorer
regression. Five gold paths are found inside the limit but not ranked first
because other relevant files in the same corpus outrank a narrower label.
Documenting this overlap in indexed files can move reported MRR slightly
without changing recall. BM25 determines those five orderings; removing the
small cosine, overlap, and symbol additions would not change their winners.
Fixed 80-line chunks with 16-line overlap favor concise summaries and schemas
over longer chapters that use the same terminology. Ranks below are from
`6bb9c72`; later indexed documentation of this overlap can change them.

| Case | Rank-1 path | Gold rank | Classification |
|---|---|---:|---|
| `authorized-erasure` | `docs/V26.md` | 3 | Overlap; denser V26 summary |
| `redis-owner-socket` | `palimnex/core.py` | 3 | Mixed: ownership spans client and launcher; query `zero` vs script `0` |
| `document-extractor` | `palimnex/README.md` | 2 | Overlap; README contains the query terms |
| `pack-encryption` | pack-manifest schema | 4 | Gold-label; schema is the cipher/manifest contract |
| `audit-tombstone` | deletion-contract schema | 4 | Gold-label; schema is the tombstone contract |

`expected_paths` requires every listed path for recall/pass and uses the
best-ranked listed path for MRR. Adding current winners as extra gold paths
would raise MRR without adjudicating relevance. The `2.6.0-rc.1` scorer and
frozen fixture are unchanged. Numeric token normalization (`zero` vs `0`) and
intent-specific gold labels remain later evaluation-design work. Historical
exception `PM-ACCEPT-001` named a noncritical miss on the prior atomic-swap
corpus; it does not describe this repository's 20/20 frozen result. The
development challenge paraphrase case remains a separate non-regression
observation, not an RC ranking blocker.

Cache migration has two additional hard gates on the same equal corpus. All
three retained v3 generations together must use at most `0.60x` the Redis
bytes of the active v2 baseline, and v3 p95 must be at most `10.0x` v2 on the
shipped `search()` path. The retired in-process hot scorer used a `1.20x`
cap; its accepted full-repository measurement was `0.47885x` size,
`0.85161x` p95, 66 samples per backend, and Recall@5 `1.0`.

The portable bundle defines a semantic-provider interface but registers no
provider, model, network call or HNSW index. Semantic influence remains off.
Promotion requires no critical regression, no recall regression, at least
`+0.05` Recall@5 or `+0.05` MRR, and candidate p95 no more than twice the
baseline measured in the same environment.

## 11. Compatibility and rollback

The root entrypoint and these v2 commands remain accepted:

```text
status index validate search symbols impact path evaluate clear
```

Exit codes remain `0` for success/fresh, `2` for stale or a failed quality
gate, and `1` for operational or validation error. `status` is compact by
default but retains `manifest.chunk_count`; `--verbose` exposes the complete
v3 manifest. Search still returns source text, reopened from verified files.

v2-compatible repositories without `cache_mode` continue on v2. The new
commands are `migration-shadow`, durable session/workflow commands,
`project-hot`, `hot-events`, `memory-keygen`, encrypted pack import/export, and
semantic status/gating. Pack v2 requires `python3-cryptography`; the remaining
source/cache/ledger paths retain Python 3.11 standard-library operation.

`clear` removes only this project's v3 disposable cache. It never opens or
alters the SQLite ledger or legacy v2 namespace.

The separate `scripts/palimnex_redis.sh reset` command operates below
the storage boundary rather than at namespace level. It first stops only the
launcher-owned Redis process, then removes only that instance's Redis log,
RDB dump and temporary RDB projection files. It does not remove the directory
or touch the SQLite database, WAL, lock, import intent, backups or packs. Any
cache namespace that existed only in the removed RDB must be rebuilt; use the
CLI `clear` command when legacy-v2 namespace preservation is required.

Code rollback is repository-specific and remains outside the runtime CLI. A
maintainer must rehearse the selected Git operation on a copy and preserve or
quarantine the durable ledger. Never downgrade across a retention migration
unless the older reader is proven to preserve deletion suppression and audit
tombstones. Cache projections may be rebuilt from source after a compatible
rollback.

## 12. Sources behind the design

- SQLite WAL, transactions and FTS5: https://sqlite.org/docs.html
- Redis streams and TLS: https://redis.io/docs/latest/
- Deterministic CBOR rules considered, not adopted: https://www.rfc-editor.org/rfc/rfc8949
- LongMemEval: https://openreview.net/pdf?id=pZiyCaVuti
- Agent Workflow Memory: https://arxiv.org/abs/2409.07429
- AgentPoison: https://arxiv.org/abs/2407.12784
