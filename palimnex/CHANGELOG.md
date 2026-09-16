# Palimnex changelog

All notable portable-bundle changes are recorded here. Bundle versions describe executable and
operator-facing behavior; cache and graph schemas are versioned independently.

## Unreleased

No changes yet.

## 2.7.0 - 2026-09-16

- Installable Python distribution, console scripts, PEP 561 types and public
  SDK v1 with explicit repository roots and write guards.
- Versioned derivative adapter protocol and namespaced SQLite reference
  backend with generation checks, projection invalidation and verified receipts.
- Structured source locators and explicitly registered version-aware resolvers.
- Signed predecessor-linked Merkle checkpoints with keyed commitments and
  external-tip verification, without a live ledger migration.
- Ed25519 identities, injectable signer protocol, and optional detached pack
  signatures verified against operator-configured public keys.
- Optional MCP stdio tools over the SDK, read-only by default with session-bound
  evidence recording when explicitly enabled.

Existing `project-memory:*` storage formats and frozen fixtures remain intact.
External derivative coordination does not clear legacy retention blockers.
See `docs/SDK.md` for protocol semantics and deployment limitations.

## 2.6.0-rc.1 - 2026-09-15

Release candidate for the portable Palimnex bundle only. SQLite schema
v1, Redis cache v3 and encrypted pack v2 remain the compatibility baseline.
Retention migration, policy activation and cleanup stay explicit operator
writes; this release does not claim distributed or forensic erasure.

### Added

- Explicit, expiring per-event authorization for durable and imported erasure,
  with record-class-specific reason codes and permanently protected session
  audit anchors.
- Derived-fact support sets with deterministic maximum-confidence
  recomputation; unsupported derivatives and temporal assertion components are
  withdrawn with their forgotten source.
- Cleanup-plan and deletion-contract v2 plus a non-reconstructive erasure
  tombstone schema. Receipts retain pseudonymous identifiers, keyed record
  commitments, policy/authorization metadata, verification state, counts and
  retention-control hash-chain continuity, never deleted payloads.
- MIT license for the independent Palimnex repository.
- GitHub Actions workflow that installs the test-only `jsonschema` dependency
  and runs `scripts/palimnex_check.sh` on isolated temporary Redis with no
  live-ledger write or model call.
- Dependency-free GitHub Pages architecture site with retrieval, durable-memory,
  erasure, storage, prerequisite, and third-party dependency diagrams.

### Changed

- Local erasure now removes evidence, verification attempts, promotions,
  workflows, lexical indexes and graph/relationship derivatives, and scrubs
  session prompt/outcome payloads before secure-delete compaction.
- Managed packs and previously attempted hot projections fail closed until a
  verified retirement/invalidation adapter is available. No distributed or
  forensic-erasure claim is made.
- Standalone Palimnex extraction keeps the promoted retention implementation,
  schemas, tests and operator documentation while excluding source-project
  runtime state and domain-specific rollback history.

### Documentation

- Recorded that this repository's frozen evaluation is 20/20 with Recall@5
  `1.0`. Baseline commit `6bb9c72` reported MRR `0.8333` from overlapping
  relevant gold labels, not a miss or scorer regression. Historical exception
  `PM-ACCEPT-001` is bound to the prior corpus only. The frozen fixture and
  scorer are unchanged. Reported MRR remains diagnostic.

## 2.5.0 - 2026-09-04

### Added

- Project-UUID-scoped compact Redis v3 generations with hashed postings,
  quantized vectors, no source bodies/plaintext lexical-token lists, bounded
  candidate retrieval, renewable reader leases, three-generation retention
  and fenced garbage collection. Graph records retain sensitive plaintext
  structural names.
- Full content privacy admission before indexing or persistence, with
  rule-and-line-only diagnostics and digest-pinned exceptions.
- Deterministic Markdown and generic-document graph extraction.
- A SHA-256-pinned frozen evaluation fixture outside its indexed corpus.
- A typed SQLite ledger for sessions, events, evidence, bitemporal
  supersession, additive contradiction, promotion, workflow records and an
  idempotent Redis hot outbox.
- Explicit bounded hot-projection rebuild from durable metadata after loss of
  disposable Redis state.
- Session retention by default, durable-only promotion, and
  `retention-durable-closed-sessions:v1` pack selection; local non-durable audit
  rows are not yet physically pruned.
- Bounded ChaCha20-Poly1305 authenticated and encrypted cross-machine packs
  with validate-first quarantine, explicit atomic activation, backup and crash
  recovery. Raw 32-byte keys are owner-only, path-hardened files supplied
  separately from packs.
- Authenticated, bounded event term digests preserve subject-only recall across
  export/import and are validated against deletion, addition, ordering,
  duplication and malformed-value corruption.
- Machine-readable event, workflow, logical-export and pack-manifest schemas.
- A disabled-by-default semantic-provider interface and evidence-only promotion
  gate; no provider, model, HNSW index or network runtime is bundled.

### Fixed

- Indexer C18: a later edit that keeps some chunk text no longer leaves those
  content-addressed records with a stale `file_hash`. Reuse now requires the
  stored digest to match the current file, the writer replaces a record when
  the payload differs, and `index --repair-deep` regenerates the refreshed
  digest. Deep validation no longer needs `clear` after an ordinary edit.
- Frozen `evaluate` search cases and the migration p95 samples call the
  shipped `search()` scorer. The duplicate in-process v3 hot scorer is gone.
- Shadow migration `legacy_comparison` is an asserted v2-versus-v3 check, not
  a literal `"passed"`: v3 must return every expected path, and v2 must either
  do the same or overlap v3.

### Security and authority

- Local writes default to an owner-only Unix socket. Plain Redis TCP is
  loopback-only; remote Redis requires authenticated TLS with CA and hostname
  verification.
- The repository Redis launcher's guarded reset removes only its projection
  log/RDB files and preserves the durable SQLite ledger and adjacent state.
- Portable-pack authentication proves symmetric-key possession and integrity,
  not sender identity. The privacy-minimal outer manifest exposes no plaintext
  content size or digest. Encrypted export permits `restricted` records,
  refuses `secret` records and rescans the selected logical content; imports
  remain quarantined/untrusted and discard current verification and promotion
  state.
- Normal recall abstains from imported or claimed-untrusted events;
  `--include-untrusted` is explicit historical inspection.
- Current verification is derived from source evidence, not latched forever.
  Changed, unavailable or policy-old evidence becomes stale, removes current
  verification/promotion and remains available only as append-only attempt and
  observed history.
- Every durable or imported result is historical context and cannot authorize
  Git, network, wallet, deployment, spending, destructive or external writes.

### Compatibility and migration

- The v2 CLI command names, common flags, search text result and exit-code
  meanings remain available. `status` is compact by default and adds
  `--verbose` for the complete manifest.
- `cache_mode=off` keeps v2 authoritative, `shadow` dual-builds while v2 stays
  authoritative, and `on` makes v3 authoritative. Missing means `off`; this
  repository's evidenced configuration is `on`.
- Redis cache schema: `project-memory:cache:v3`, in a new UUID-scoped namespace.
- Durable ledger schema: `project-memory:ledger:v1`.
- Portable pack schema: `project-memory:pack:v2`; pack operations require the
  reviewed distribution `python3-cryptography` package.
- The legacy `project-memory:v2` namespace is read-only during shadow
  comparison and is never changed by v3 migration or `clear`.
  It still contains full source chunks and plaintext lexical-token lists and
  remains sensitive until a separate retirement or lower-level local reset.
- Migration acceptance requires an equal-corpus, byte-stable v2 baseline, all
  three retained v3 generations, total v3 size at most `0.60x` v2 and v3 p95
  at most `10.0x` v2 on the shipped `search()` path.
- Filesystem rollback to `88354eb` preserves/quarantines SQLite and leaves both
  Redis namespaces untouched.

## 2.4.0 - 2026-08-17

### Added

- Read-only `path SOURCE TARGET` queries using deterministic breadth-first search over the resolved
  dependency graph.
- Forward and reverse traversal, repeatable edge-kind filters, bounded depth, and explicit opt-in
  for probable unique-short-name resolutions.
- Ordered symbol paths, hop counts, resolution metadata, and source pointers in path results.
- `palimnex.py --version` and a package-level `palimnex.__version__` value.
- Exact repository-relative `exclude_paths` configuration and boundary-safe strict UTF-8 probing.

### Compatibility

- Cache schema: `project-memory:v2` (unchanged).
- Code-graph schema: `project-memory:code-graph:v3` (unchanged).
- Graph-record schema: `project-memory:graph-record:v1` (unchanged).
- Redis namespace and mandatory privacy boundaries are unchanged.
- Upgrades require an incremental index to activate a 2.4.0 manifest; unchanged chunks and graph
  records remain reusable.

## 2.3.0

- Moved per-file extraction graphs into path-owned, content-addressed Redis records.
- Kept compact graph references and aggregate counts in the active manifest.
- Added on-demand graph loading, cross-file resolution, deep graph validation, incremental record
  reuse and repair, and migration from embedded 2.2 graphs.
