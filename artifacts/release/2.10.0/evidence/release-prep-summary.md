# Release 2.10.0 preparation evidence

Lane: `release-2.10.0-prep`

## Files changed

| File | Release-preparation change |
|---|---|
| `palimnex/core.py` | Changed only `BUNDLE_VERSION` to the candidate version. |
| `palimnex/CHANGELOG.md` | Opened the dated release section, added the additive/off-by-default summary, preserved every existing bullet, and added the coordinator placeholder. |
| `README.md` | Updated the current distribution, install pin and tag; retained the prior release's migration-framework history. |
| `palimnex/README.md` | Updated the portable bundle heading and current package status. |
| `docs/INSTALL.md` | Updated the published-release statement and every exact install pin/tag. |
| `docs/UPGRADING.md` | Added the new transition row and code-verified upgrade/downgrade notes. |
| `docs/RUNBOOK.md` | Updated the runbook release heading. |
| `docs/DESIGN.md` | Updated the current release-line status. |
| `docs/COMPATIBILITY.md` | Identified the ontology-adoption surfaces with their release version. |
| `docs/AGENT_INIT_PROMPT.md` | Updated the release baseline and added the current additive surfaces. |
| `docs/V26.md` | Updated the current release-line cross-reference. |
| `docs/index.html` | Updated the package/API site metadata. |
| `artifacts/release/2.10.0/evidence/release-prep-summary.md` | Recorded this bounded lane's changes and retained-version audit. |

## Kept prior-release occurrences

Every remaining occurrence reported by the required prior-version grep is
listed here. These are historical statements or transition endpoints, not
current-version claims or install pins.

| File and line | Reason retained |
|---|---|
| `palimnex/CHANGELOG.md:103` | Dated heading for the prior release. |
| `palimnex/CHANGELOG.md:162` | Historical upgrade note naming its source and target release. |
| `palimnex/CHANGELOG.md:163` | Historical cache-rebuild result for that release. |
| `palimnex/CHANGELOG.md:166` | Historical compatibility statement for that writer. |
| `palimnex/CHANGELOG.md:167` | Historical older-reader compatibility statement. |
| `README.md:18` | Attributes the migration framework to the release that introduced it. |
| `docs/UPGRADING.md:107` | Records when copied-bundle deprecation began. |
| `docs/UPGRADING.md:143` | Existing historical transition row from the preceding release. |
| `docs/UPGRADING.md:144` | Source endpoint of the new transition row. |
| `docs/UPGRADING.md:146` | Source endpoint of the new detailed transition section. |
| `docs/UPGRADING.md:278` | States when the generic migration framework became available. |
| `docs/UPGRADING.md:325` | Dates the safe replacement behavior for legacy empty markers. |
| `docs/COMPATIBILITY.md:31` | Attributes the migration framework and its contracts to their introducing release. |
| `docs/SDK.md:84` | Marks when SDK retention migration began using the generic engine. |
| `docs/BUNDLE_MODE.md:4` | Records the implemented design version. |
| `docs/BUNDLE_MODE.md:105` | Historical deprecation timeline entry. |
| `docs/BUNDLE_MODE.md:217` | Historical approved timeline decision. |
| `docs/MIGRATIONS.md:4` | Records the framework's implementation version. |
| `docs/RETENTION.md:272` | Marks when retention migration began using the generic engine. |

## Code verification

- `palimnex/cache_v3.py` rejects an active manifest whose `bundle_version`
  differs from `BUNDLE_VERSION`.
- `palimnex/ontology_influence.py` maps a missing `ontology_influence` key to
  `off`, and neither `off` nor `shadow` activates influence.
- `palimnex/semantic_shadow.py` emits `retrieval_influence: false` and
  `promotion_authorized: false`; execution requires the explicit evaluation
  command.
- `palimnex/feedback.py`, `palimnex/core.py` and `palimnex/durable.py` show that
  the explicit feedback commands reuse `fact`, `correction` and `revocation`;
  ledger schema v1 and the event-kind table match the prior release tag.
- The prior release tag lacks the feedback-schema exclusion now present in
  `palimnex.experience.current_eligible`, and it has no feedback commands.

## Checks

- The requested two-module unittest command ran 55 tests: 53 passed; the two
  socket-dependent onboarding tests could not run in the restricted sandbox
  (`AF_UNIX` bind returned `EPERM`, and Redis could not start on its socket).
- Rerunning those modules with exactly those two socket tests excluded passed
  all 53 selected tests.
- `grep -rn` over every owned file found only the retained occurrences listed
  above.
- `git diff --check` passed for the scoped release-preparation diff.

## Out-of-scope follow-up

The CLI still exposes deprecated `retention-migrate --no-snapshot` in
`palimnex/core.py`, while existing release documentation says it is removed in
the candidate version. Removing or rescheduling it requires changes beyond the
brief's `BUNDLE_VERSION`-line-only permission, plus corresponding test updates.

## Addendum (coordinator, 2026-11-08, after review round 2)

The statement above that the CLI still exposes `retention-migrate --no-snapshot`
describes the tree before lane `release-2.10.0-no-snapshot`. That lane removed
the option (argparse now exits 2), kept SDK API v1 `migrate_retention(snapshot=False)`
with its warning, and updated `docs/MIGRATIONS.md`, `docs/RETENTION.md`,
`docs/SDK.md`, the 2.10.0 CHANGELOG section and the 2.9.0 → 2.10.0 UPGRADING
section. The coordinator then rewrote the two remaining live-sounding UPGRADING
passages in the past tense, disclosed the removal in `docs/COMPATIBILITY.md`, and
deleted the unused `NO_SNAPSHOT_DEPRECATION` constant from `palimnex/retention.py`.
Reviews: `artifacts/release/2.10.0/reviews/release-prep.round-1.json` (rejected)
and `release-prep.round-2.json` (accepted_with_limits); install-text decision R17.
