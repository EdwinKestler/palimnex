# Phase 4 — local semantic shadow experiment: handoff (v1.1 · 2026-11-07 00:10)

Result: **HELD** under the owner's thresholds. Implemented, tested and
independently reviewed. Evidence only: nothing promotes the provider or changes
production retrieval. Not committed, not pushed. Approval:
`artifacts/ontology/phase-4/approval-evidence.json`.

## Delivered

| Path | What |
| --- | --- |
| `palimnex/semantic_local.py` | `HashedEmbeddingProvider` (`palimnex-hashed-embedding`, revision 1, 384 dimensions) over `core.embedding`; behavioural implementation digest; `palimnex:semantic-provider-identity:v1`; `checked_embed` with typed refusals (invalid input, provider failure, timeout, count, vector, dimension, NaN/Inf). Test doubles in `palimnex/tests/semantic_doubles.py` |
| `palimnex/semantic_shadow.py` | R14 semantic channel beside the unchanged baseline; `palimnex:semantic-shadow-comparison:v1`; in-process memo keyed by provider identity and content digest; query privacy scan before any provider call; suppression when the baseline has no candidates |
| `palimnex/evaluation/semantic-shadow.v1.json` | Frozen cohort (`palimnex:semantic-shadow-cohort:v1`): 26 repository cases, 2 drift and 3 privacy-canary project cases; written blind; SHA-256 `bfaa3998…` (`integration/cohort-freeze.json`) |
| `palimnex/semantic_eval.py`, `palimnex evaluate-semantic-shadow` | `palimnex:semantic-shadow-evaluation:v1` with the owner's 16 gates, the R15 benchmark protocol and `palimnex:semantic-promotion-policy:v2` (+0.02, 1 extra pass, 1.5×); exit 0 promotable, 2 held, 1 refused |
| `docs/SEMANTIC_SHADOW.md` | What each part does, R14, R15, every gate, how to read a held report |

Unchanged (verified by `git diff` in the gate): `retrieval.py`, `semantic.py`
(`project-memory:semantic-provider:v1`, +0.05/2×, `semantic-status`,
`semantic-gate`), `cache_v3.py`, `experience.py`, `ontology_influence.py`.
Only `core.py` gained the new subcommand.

## Official evaluation (`integration/semantic-evaluation.json`)

| Gate | Result | Detail |
| --- | --- | --- |
| `cohort_gain` (+0.02 MRR or Recall@5) | **fail** | MRR 0.0952 → 0.0952; Recall@5 0.0833 → 0.0833 |
| `cohort_additional_pass` (≥ 1) | **fail** | none |
| `no_critical_regression`, `no_case_regression` | **fail** | Phase 3 cohort: `alias-retention-ledger` and `alias-rrf-fusion` (both critical) pass in baseline, fail with the semantic channel |
| `protected_recall_not_reduced` | **fail** | Phase 3 cohort Recall@5 0.083 → 0.042 |
| `latency_within_bound` (≤ 1.5×) | pass | p95 745.6 ms vs 712.0 ms (1.05×), 78 samples each |
| `baseline_identical`, `no_new_forbidden`, `abstention_not_regressed`, `ambiguity_not_collapsed`, `source_drift`, `privacy_canary`, `deterministic`, `provider_identity_bound`, `channels_visible`, `bounded` | pass | |

Also measured, without promotion weight: on local retrieval the v27 suite
improved from 5 to 9 passing cases (Recall@5 0.385 → 0.692). Its queries are
keyword-dense, which suits a feature-hashing embedding; the paraphrase cohort,
which is what Phase 4 is meant to test, gained nothing.

## Gate (`integration/gate.log`, unsandboxed)

523 tests OK; strict mypy clean on 21 files; fresh index and deep validation;
`palimnex evaluate` every critical case passing, Recall@5 1.0, MRR 0.8917
(unchanged); `evaluate-ontology-shadow` all eight gates true; ontology influence
off; semantic v1 disabled; standard gate passed; ledger integrity ok with 0
events; cohort still pinned. Redis was already running and was left as found.

## Independent review (Grok 4.6 xhigh)

- Provider: **accepted**.
- Cohort: **rejected** in round 1 (four MAJORs: two paraphrase queries,
  `paraphrase-active-reader` and `paraphrase-portable-rescan`, and two synonym
  queries, `synonym-tamper-evident-record` and `synonym-secret-detector`, copied
  source phrasing; a MINOR for the missing isolation test; a NOTE on the canary
  rule name). After fix round
  1 and spec v1.1 (A1, A2), re-review **accepted** with every finding RESOLVED.
  Frozen only then.
- Channel: **accepted**; one MINOR (its tests do not assert `retrieval.py` is
  unchanged), closed by the gate's `git diff` step.
- Evaluation: **accepted** with three MINORs. Fix round 1 resolved two (the
  1e-12 tolerance now applies only to the gain check; the whole report is
  scanned for canaries) and the re-review **accepted** it. The third (most
  gate-failure unit tests mock the suite runner) remains a recorded limit,
  covered by the reviewer's live probes and two real-repository runs.
- Integration (the coordinator's own work): **rejected** in round 3
  (`round-3/`: the receipt reported audit exit codes as 0 when three saved
  audits exited 1 because of coordinator records, and cited an undocumented
  reviewer write block; a MINOR for an omitted provider limit) and **rejected**
  in round 4 (`round-4/`: all round-3 findings RESOLVED; two MAJORs and two
  MINORs in this handoff, corrected in this version). The second focused
  re-review of this version is **accepted_with_limits**
  (`reviews/ontology-phase-4-integration.review-receipt.json`): every round-4
  finding RESOLVED, no BLOCKER, MAJOR or MINOR. Its limits, and how each is
  closed:
  1. Full suite and `palimnex_check.sh` not run by the reviewer: run
     unsandboxed by the coordinator and passed (`integration/gate.log`).
  2. `evaluate-semantic-shadow` not re-run by the reviewer: the official report
     (`integration/semantic-evaluation.json`) was compared to this handoff and
     the receipt; the wave 2-3 reviewer also ran the evaluation independently on
     a copy of the tree and got the same held reasons.
  3. Ledger not read by the reviewer: `gate.log` records integrity ok with 0
     events.
  4. The recovered wave-1 review audit printout has no `changed_by_lane`:
     accepted as a disclosed residual. The lane window before it is saved in
     full (`ownership-audit.wave1.json`), and the recovered printout shows only
     coordinator records as unowned paths.
  5. `reviewer-launch.md` listed only the first five launches: regenerated
     after that review from the tool history with all seven Phase 4 launches.
  This section was the only change after that review; the closing audit is
  `integration/ownership-audit.integration-rereview2.json`.

## For the owner

1. Confirm **R14** (channel policy) and **R15** (benchmark protocol), recorded in
   `briefs/SEMANTIC_SPEC.md` before measurement, and spec amendments **A1/A2**.
2. Decide the outcome: Phase 4 stays **held**. The in-process hashed provider
   does not meet the gain threshold. A possible next step is a real local-model
   experiment, which the owner's decision says needs its own separate approval;
   it is designed to plug a new provider (with its own identity) into this
   provider seam and run the same frozen cohort, evaluation and gates.
3. Commit, if you want the experiment kept. New Phase 4 files are untracked,
   and four tracked files are modified: `docs/COMPATIBILITY.md`,
   `palimnex/CHANGELOG.md`, `palimnex/core.py` and `pyproject.toml`.
   `.env.example`, `benchmark/` and transient logs remain untouched.
