# Lane brief: release-2.10.0-prep (version and documentation for the 2.10.0 candidate)

You are a bounded implementer preparing the Palimnex **2.10.0 release
candidate**. The owner approved 2.10.0 on 2026-11-08: the release is additive
and off by default (API v1, ledger schema v1, existing event kinds and
production retrieval unchanged); 3.0.0 stays reserved for removing copied-bundle
support. Another lane is drafting a concept registry in parallel under
`artifacts/ontology/closure/`; do not touch it.

## You own exactly these files (write nothing else)

`palimnex/core.py` (the `BUNDLE_VERSION` line only), `palimnex/CHANGELOG.md`,
`README.md`, `palimnex/README.md`, `docs/INSTALL.md`, `docs/UPGRADING.md`,
`docs/RUNBOOK.md`, `docs/DESIGN.md`, `docs/COMPATIBILITY.md`, `docs/SDK.md`,
`docs/AGENT_INIT_PROMPT.md`, `docs/BUNDLE_MODE.md`, `docs/MIGRATIONS.md`,
`docs/RETENTION.md`, `docs/V26.md`, `docs/index.html`, and
`artifacts/release/2.10.0/evidence/release-prep-summary.md`.

Never edit `docs/ONTOLOGY_ADOPTION.md`, `docs/CONCEPT_REGISTRY.md`, any other
`palimnex/*.py`, tests, schemas, workflows, `pyproject.toml` or `scripts/`.
If one of those needs a change, describe it in your summary instead.

## Tasks

1. `BUNDLE_VERSION = "2.10.0"` in `palimnex/core.py` (pyproject reads it).
2. `palimnex/CHANGELOG.md`: rename `## Unreleased` to `## 2.10.0 - 2026-11-08`
   and open the section with a short summary paragraph: ontology adoption
   (concept registry, coverage receipts and `explain-search`, ontology shadow
   evaluation, opt-in ontology influence that stays off by default, the held
   local semantic shadow experiment, reviewed retrieval feedback records), all
   additive and off by default; ledger schema and event kinds unchanged; cache
   reindex required. Keep every existing bullet. Leave a placeholder bullet
   `- (coordinator) approved concept registry entry` at the end of the section;
   the coordinator replaces it.
3. Replace references that denote the **current or latest** version or an
   install pin (`2.9.0` → `2.10.0`) across the owned docs and site metadata.
   Keep historical mentions (for example "deprecated in 2.9.0", the 2.8.1 →
   2.9.0 table row, "In 2.9.0 and later").
4. `docs/UPGRADING.md`: add a `2.9.0 → 2.10.0` row and section. Verify each
   statement in code before writing it:
   - the cache must be reindexed (`palimnex/cache_v3.py` rejects a manifest
     whose `bundle_version` differs);
   - ledger schema and event kinds unchanged, no migration needed;
   - new opt-in surfaces are off by default (`.palimnex.json`
     `ontology_influence` missing means off; semantic shadow is evidence only;
     feedback records are written only by the owner's commands);
   - **downgrade warning**: a 2.9.x `context` or `capsule` may surface feedback
     facts recorded by 2.10.0, because 2.9 lacks the R16 filter
     (`palimnex/experience.py` `current_eligible`); 2.9.x has no feedback
     commands; withdrawn feedback stays in history either way.
5. `docs/COMPATIBILITY.md`: the version line or matrix for 2.10.0.
6. `artifacts/release/2.10.0/evidence/release-prep-summary.md`: every file
   changed and every `2.9.0` occurrence you kept, with the reason.

## Checks

Run `./.venv/bin/python -m unittest palimnex.tests.test_sdk palimnex.tests.test_onboarding`
(skip tests that need sockets) and `grep -rn "2\.9\.0"` over the owned files to
justify every remaining occurrence. No Git writes, network, installs, Redis or
ledger writes; do not run the full suite or `scripts/palimnex_check.sh`. Print a
short summary when done.
