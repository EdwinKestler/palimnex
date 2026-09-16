# Extraction and provenance

Palimnex `2.6.0-rc.1` was extracted locally on 2026-09-15 from the portable
Project Memory bundle in `btc-usdt-atomic-swap` after its retention and
authorized-erasure functionality was promoted from `Unreleased`.

Included scope:

- cache, graph, retrieval, ledger, portability, security, semantic-interface,
  experience, longitudinal, and retention modules;
- schemas, standalone retrieval/challenge fixtures, unit and adversarial tests;
- general design, runbook, retention, v2.6, and longitudinal documentation;
- the supplied authorized-erasure flow diagram as a documentation asset;
- the guarded owner-only Redis launcher.

Deliberately excluded scope:

- all live Redis and SQLite state, packs, keys, credentials, and runtime files;
- atomic-swap crates, contracts, protocol documents, chain configuration, and
  wallet or network material;
- source-repository rollback baselines and operational closure history;
- xAI task-card and replacement-runner experiments coupled to the atomic-swap
  corpus;
- unrelated untracked Mem0 benchmark drafts.

The original `project-memory:*` serialized identifiers are retained as format
compatibility identifiers. See `docs/COMPATIBILITY.md`.
