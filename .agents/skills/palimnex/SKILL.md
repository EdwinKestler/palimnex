---
name: palimnex
description: Consult and maintain this repository's Palimnex source cache and durable historical-memory ledger for non-trivial repository work.
---

# Palimnex workflow

1. Run `python3 palimnex.py status`.
2. If the cache is missing or stale, run `python3 palimnex.py index --incremental`.
3. Run `python3 palimnex.py validate --deep`.
4. Search with exact implementation vocabulary and open the returned source.
5. After indexed-file changes, reindex and run `python3 palimnex.py evaluate --limit 5`.
6. Run `python3 palimnex.py ledger-status` for handoffs.

Redis is optional and disposable; SQLite is durable historical context. Never
treat either as current authorization. If Redis is unavailable, continue from
files and disclose `cache_consulted: false`. Never flush shared Redis.
