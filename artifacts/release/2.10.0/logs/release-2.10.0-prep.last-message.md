Completed the bounded 2.10.0 release-prep lane.

- Changed 13 authorized files: `palimnex/core.py`, changelog, READMEs, eight release docs/site files, and the [release evidence summary](/home/kestl/github/palimnex/artifacts/release/2.10.0/evidence/release-prep-summary.md).
- Kept 19 `2.9.0` occurrences, all historical or upgrade-transition references; each is justified in the evidence summary.
- Checks: 53 non-socket tests passed. Two excluded socket tests failed under sandbox restrictions (`EPERM`/Redis socket startup). Version reports `2.10.0`; grep audit and `git diff --check` passed.
- Follow-up outside lane scope: decide whether to remove or reschedule `retention-migrate --no-snapshot`; implementation and tests still expose it although existing docs say removal occurs in 2.10.0.
- `cache_consulted: false` due to the lane’s explicit Redis/`.palimnex/` prohibition.