You are the INDEPENDENT, READ-ONLY reviewer for the Palimnex 2.10.0 release-candidate preparation. You wrote none of it.
Do not modify, create or delete any repository file; scratch work under /tmp only. No network, no Git writes, no
palimnex commands that write. Never read .env*, .palimnex/, secrets/, benchmark/. A concept-registry lane is working in
parallel under artifacts/ontology/closure/; it is out of scope.

Owner decision (docs/ONTOLOGY_ADOPTION.md row "Release candidate"): Palimnex 2.10.0 is additive and off by default (API
v1, ledger schema v1, existing event kinds and production retrieval unchanged); 3.0.0 stays reserved for removing
copied-bundle support.

Review the uncommitted changes (`git diff` against HEAD 79f5a54) made by two lanes:
1. release-2.10.0-prep (brief artifacts/release/2.10.0/briefs/RELEASE_PREP_BRIEF.md; summary
   artifacts/release/2.10.0/evidence/release-prep-summary.md): BUNDLE_VERSION, CHANGELOG 2.10.0 section, README files,
   docs (INSTALL, UPGRADING, RUNBOOK, DESIGN, COMPATIBILITY, SDK, AGENT_INIT_PROMPT, BUNDLE_MODE, MIGRATIONS,
   RETENTION, V26, index.html).
2. release-2.10.0-no-snapshot (brief artifacts/release/2.10.0/briefs/NO_SNAPSHOT_REMOVAL_BRIEF.md): removal of the CLI
   option `retention-migrate --no-snapshot` announced in 2.9.0 for 2.10.0; SDK API v1 `snapshot=False` kept with a
   warning.

Check:
- Every changed "current version" reference is right and every kept 2.9.0 mention is historical; nothing claims a
  publication, tag or PyPI release that has not happened.
- UPGRADING 2.9.0 -> 2.10.0: each claim verified in code (cache reindex because cache_v3 rejects a manifest with another
  bundle_version; ledger schema and event kinds unchanged; opt-in surfaces off by default; the downgrade warning that a
  2.9.x context or capsule may surface feedback facts because 2.9 lacks palimnex/experience.py's R16 filter).
- The CHANGELOG 2.10.0 section is accurate and complete for the commits since v2.9.0 (`git log v2.9.0..HEAD --oneline`
  if the tag exists locally, else since 604861b) plus the uncommitted changes; a placeholder bullet for the registry is
  expected.
- The --no-snapshot removal: argparse rejects the option; the CLI always snapshots; SDK snapshot=False still works and
  warns with accurate text; tests updated and meaningful; no other retention behaviour changed; docs consistent; it is
  disclosed as a CLI removal announced in 2.9.0. Is this compatible with the owner's "additive" framing and with
  docs/COMPATIBILITY.md's stability promises? Report any conflict as MAJOR.
- Run: ./.venv/bin/python -m unittest palimnex.tests.test_migrations palimnex.tests.test_sdk palimnex.tests.test_retention
  (skip socket-only failures and say which), ./.venv/bin/python -m mypy, and `python3 palimnex.py --help` checks for the
  version string if available read-only.

Output: a concise summary, then ONE fenced ```json block with
{"review": "palimnex-2.10.0-release-prep", "status": "accepted" | "accepted_with_limits" | "rejected",
 "findings": [{"severity": "BLOCKER|MAJOR|MINOR|NOTE", "file": "...", "finding": "..."}], "commands": [...],
 "limitations": [...], "reviewer_modified_repository": false}. Status rejected for any BLOCKER; accepted only if no
MAJOR remains.
