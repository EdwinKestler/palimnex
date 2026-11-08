You are a bounded implementer for the Palimnex 2.10.0 release candidate, lane `release-2.10.0-no-snapshot` (approved).
Read AGENTS.md, then artifacts/release/2.10.0/briefs/NO_SNAPSHOT_REMOVAL_BRIEF.md, and follow it exactly. Write ONLY the files it lists
(the CLI test module is palimnex/tests/test_migrations.py). A read-only reviewer works in parallel; another lane's
files under artifacts/ontology/closure/ are off limits. Never read .env*, .palimnex/, secrets/, benchmark/.
When done, print a short summary: files changed, tests run, remaining --no-snapshot mentions and why.
