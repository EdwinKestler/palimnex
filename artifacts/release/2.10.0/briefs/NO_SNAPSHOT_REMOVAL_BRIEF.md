# Lane brief: release-2.10.0-no-snapshot (honour the published 2.10.0 removal)

The 2.9.0 release published a deprecation contract: the CLI option
`palimnex retention-migrate --no-snapshot` is deprecated through 2.9.x and is
**removed in 2.10.0**, while SDK API v1 keeps `migrate_retention(...,
snapshot=False)` (still warning). See `docs/MIGRATIONS.md` (around lines 282,
471, 589), `docs/RETENTION.md` (around line 269), `docs/UPGRADING.md` (2.9.0
notes), `docs/SDK.md` and `palimnex/retention.py` (`NO_SNAPSHOT_DEPRECATION`).
The coordinator decided to honour that contract in 2.10.0.

## You own exactly these files

`palimnex/core.py` (only the `retention-migrate` parser option and its handler
branches), `palimnex/retention.py` (only the deprecation message text and any
CLI-only code path, if one exists), the tests that exercise the CLI option
(find them with `grep -rn "no-snapshot\|no_snapshot" palimnex/tests`),
`docs/MIGRATIONS.md`, `docs/RETENTION.md`, `docs/SDK.md`, and the
`## 2.10.0` section of `palimnex/CHANGELOG.md` plus the `2.9.0 → 2.10.0`
section of `docs/UPGRADING.md` (add to them; another lane already wrote them).
Write nothing else. Do not move or reflow code above line 600 of
`palimnex/retention.py`: an approved concept registry binds line ranges there.

## Do

1. Remove `--no-snapshot` from `retention-migrate`; argparse then rejects it
   (exit 2). The CLI always takes the pre-migration snapshot.
2. Keep SDK API v1 `migrate_retention(snapshot=False)` working with its
   existing deprecation warning; update the warning text so it no longer
   refers to a CLI flag that exists (state that the CLI option was removed in
   2.10.0 and the SDK parameter remains under API v1).
3. Update tests: the CLI option is rejected; the SDK path still works and
   warns; every other retention-migrate behaviour unchanged.
4. Docs: present tense for the removal in the owned docs; a CHANGELOG bullet
   under 2.10.0 ("Removed `retention-migrate --no-snapshot`, as announced in
   2.9.0"); an UPGRADING note in the 2.9.0 → 2.10.0 section.

## Checks

`./.venv/bin/python -m unittest` on the retention, migration and SDK test
modules you touched (skip socket-only tests), `./.venv/bin/python -m mypy`, and
`grep -rn "no-snapshot" palimnex docs README.md` to justify every remaining
mention. No Git writes, network, installs, Redis or ledger writes; do not run
the full suite or `scripts/palimnex_check.sh`. Print a short summary.
