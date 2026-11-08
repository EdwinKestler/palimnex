## Palimnex 2.10.0 release candidate

Closes the ontology adoption (`docs/ONTOLOGY_ADOPTION.md`) and prepares 2.10.0.
**Do not merge on its own:** merge only together with tagging `v2.10.0` and the
PyPI publication, which need the owner's separate approval (R17,
`artifacts/release/2.10.0/evidence/R17-release-docs-sequencing.md`). The
install text already names 2.10.0, as the 2.9.0 release commit did.

### What changes

- **Approved concept registry** `ontology/concept-registry.v1.json`: 16
  source-bound concepts, drafted blind to the evaluation sets, independently
  reviewed and frozen (`artifacts/ontology/closure/`). Merging this pull
  request is the owner's approval of the registry. `explain-search` uses it by
  default. Promotion evidence is `promotable` on the local and cache backends
  with no regression. **Ontology influence stays off**; `.palimnex.json` is
  unchanged.
- **Version 2.10.0**: `BUNDLE_VERSION`, the 2.10.0 changelog section,
  current-version references, the 2.9.0 → 2.10.0 upgrade notes (cache
  reindex; ledger unchanged; downgrade warning about the R16 context filter).
- **Removal announced in 2.9.0**: `retention-migrate --no-snapshot` (argparse
  now exits 2). SDK API v1 `migrate_retention(snapshot=False)` remains.
- **Tests**: three frozen registry fixtures re-pinned to the edited
  `README.md` and `docs/DESIGN.md` (R18, versions only); the real-checkout
  missing-registry promotion test now uses an explicit absent path; CI-only
  portability fixes: golden digests normalize `checkout_id` (macOS
  `/private/tmp`), and the Redis wrapper test probes for a binary that runs
  under a copied name (multicall coreutils on Ubuntu, `/bin/sh` on macOS).

API v1, ledger schema v1, event kinds, cache-v3 identifiers and production
retrieval defaults are unchanged.

### Evidence

- Local gate (unsandboxed): 550 tests OK (1 expected skip), strict mypy clean
  on 22 files, standard gate, deep validation, `palimnex evaluate` every
  critical case passing.
- Clean build from a `git archive` of `ce4fde2`
  (`artifacts/release/2.10.0/tools/build_clean.sh`): wheel byte-reproducible
  and free of tests, wheel and sdist pass `twine check --strict`,
  installed-wheel smoke passes; checksums in
  `artifacts/release/2.10.0/evidence/dist-sha256.txt`. Full candidate report:
  `artifacts/release/2.10.0/evidence/RC_REPORT.md`.
- Upgrade rehearsal v2.9.0 → 2.10.0 passed
  (`artifacts/release/2.10.0/evidence/upgrade-rehearsal.json`).
- Adoption smoke tests on isolated snapshots of waveshares3, ereditas and
  edgelinkd (`artifacts/release/2.10.0/evidence/adoption-summary.md`).
- Independent reviews (Grok): registry accepted_with_limits, closure
  integration accepted_with_limits, release preparation accepted_with_limits,
  with every limit recorded in the review receipts and handoffs.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01ASdxP91bu2vuHUcdjk7LEp
