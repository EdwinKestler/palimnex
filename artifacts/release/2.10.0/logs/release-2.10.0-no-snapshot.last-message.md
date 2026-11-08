Implemented the approved `release-2.10.0-no-snapshot` lane.

- Files changed: `palimnex/core.py`, `palimnex/retention.py`, `palimnex/tests/test_migrations.py`, `docs/MIGRATIONS.md`, `docs/RETENTION.md`, `docs/SDK.md`, `palimnex/CHANGELOG.md`, and `docs/UPGRADING.md`.
- CLI now rejects `--no-snapshot` with exit 2 and always takes the verified snapshot. SDK API v1 `snapshot=False` still works and warns.
- Tests: 72 retention/migration/SDK tests passed; mypy passed; `git diff --check` passed.
- Remaining `--no-snapshot` mentions document its removal, test rejection, preserve the compatibility warning, or record historical 2.8/2.9 behavior. Two grep hits were compiled `__pycache__` copies.
- `cache_consulted: false`; prohibited cache, secret, benchmark, and ontology-closure paths were not read. No full suite, standard gate, Git writes, network, Redis, or ledger operations were run.