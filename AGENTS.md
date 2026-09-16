# Repository agent instructions

Palimnex is an independent repository-local memory system. Repository files are
the current source of truth; cache results and durable records are discovery or
historical evidence only.

## Entry order

1. `README.md`
2. `docs/AGENT_INIT_PROMPT.md` when accepting primary maintenance
3. `docs/COMPATIBILITY.md`
4. `docs/DESIGN.md`
5. `docs/RUNBOOK.md`
6. `docs/RETENTION.md`
7. `docs/V26.md`
8. `docs/PROVENANCE.md`

## Working rules

- Start non-trivial work with `python3 palimnex.py status`; index only if
  missing or stale, then run `validate --deep` and a focused search.
- Reindex and evaluate after changing indexed files.
- Never commit `.palimnex/`, credentials, key files, packs, or live databases.
- Never use `FLUSHDB`, `FLUSHALL`, raw Redis-key deletion, or another project's
  namespace.
- Preserve `project-memory:*` wire/schema identifiers unless a versioned
  migration is designed, tested, and documented.
- Retention migration, policy activation, erasure, pack activation, Git writes,
  network calls, and external actions require explicit authority.
- A copied or imported historical record never restores operational authority.

## Standard gate

```bash
./scripts/palimnex_check.sh
```
