# Phase 5 — reviewed retrieval feedback records: handoff (v1.0 · 2026-11-07 16:20)

Status: **implemented, tested and independently reviewed. Not committed, not
pushed. The repository's real ledger was not written.** Approval:
`artifacts/ontology/phase-5/approval-evidence.json`. Scope per the owner's
decisions (design rows "Phase 5 scope", "Feedback storage", "Feedback
influence", "Graph exploration format"): feedback records only.

## Delivered

| Path | What |
| --- | --- |
| `palimnex/feedback.py` | Builders and validators for `palimnex:retrieval-feedback:v1` and `palimnex:retrieval-feedback-withdrawal:v1`; `record_feedback` (event kind `fact`), `correct_feedback` (`correction`, same query and source), `withdraw_feedback` (`revocation`, never deletes), all through `MemoryLedger.append_event`; read-only `feedback_report` (`palimnex:retrieval-feedback-report:v1`, states `current`, `stale`, `superseded`, `withdrawn`, `invalid`) |
| `palimnex/schemas/retrieval-feedback*.v1.schema.json` | The three public schemas, with valid and invalid fixtures |
| `palimnex feedback-record`, `feedback-correct`, `feedback-withdraw` | Owner-run ledger writes |
| `palimnex feedback-report [--include-history]` | Read-only report |
| `palimnex/experience.py` (R16, 4 lines) | `context` and `capsule` skip feedback payloads in historical recall |
| `docs/RETRIEVAL_FEEDBACK.md` | What a record is and is not, payloads, states, commands, drift, privacy |

Each record binds the query (normalized, privacy-scanned), the source range
(content digest checked against current admitted bytes; the ledger marks the
evidence verified), the judgement (`answers` or `does_not_answer`), the reviewer
and the origin, and is `historical_only` with `authorizes_actions` and
`retrieval_influence` false.

## How you record feedback (your real ledger)

```bash
palimnex session-start --task "review retrieval feedback"
palimnex feedback-record --session <id> --query "..." --locator palimnex/retrieval.py:174-188 \
  --judgement answers --reviewer EdwinKestler [--note "..."]
palimnex feedback-report
palimnex session-close <id> --outcome "feedback reviewed"
```

Change a judgement with `feedback-correct --event <id>`; withdraw with
`feedback-withdraw --event <id> --reason "..."`. Nothing is deleted.

## Evidence

- Gate (`integration/gate.log`, unsandboxed): 550 tests OK; strict mypy clean on
  22 files; fresh index and deep validation; `palimnex evaluate` 20/20, every
  critical case passing, Recall@5 1.0, MRR 0.8917 (unchanged); Phase 3 shadow
  gates and influence status unchanged; standard gate passed; `ledger-status`
  read only. `retrieval.py`, `durable.py`, `semantic.py`, `cache_v3.py`,
  `ontology_influence.py` and `memory-event.v1` unchanged; `experience.py` has
  only the 4 R16 lines. Redis was running when the gate started and was left as
  found.
- R16 negative control (`integration/r16-negative-control.log`): the context and
  capsule isolation test fails with the R16 filter disabled and passes with it.

## Independent review (Grok 4.6 xhigh)

- Feedback schemas: **accepted**. Two MINORs, both covered by runtime checks in
  `palimnex.feedback`: JSON Schema cannot require `end_line ≥ start_line`, and
  the schema path pattern admits colons and backslashes that the code refuses.
- Feedback core: **rejected** in round 1 with one BLOCKER (recorded feedback
  changed `context` and `capsule` output through ledger recall) and one MINOR.
  After R16 the re-review is **accepted_with_limits**: BLOCKER RESOLVED; the
  MINOR (its test reads the schema lane's files without a declared dependency
  edge) is ACCEPTED-RESIDUAL, the schemas having been accepted first.
- Integration: **accepted_with_limits**, no BLOCKER, MAJOR or MINOR.

The review limits, and how each is closed:

1. Full suite and standard gate not re-run by the reviewer (both receipts):
   run unsandboxed by the coordinator and passed (`integration/gate.log`).
2. The reviewer did not read `.palimnex/` or run ledger, feedback, `context` or
   `capsule` commands against this checkout (both receipts): required by the
   review rules; every behaviour was probed in temporary ledgers instead.
3. R16 is a coordinator decision (integration receipt): **awaiting your
   confirmation** below.
4. `ledger.recall` scans up to 10,000 matching candidates before the R16 filter
   (integration receipt): in a ledger holding more than 10,000 events matching
   one query, feedback rows could take scan slots and push other history out of
   `context`. Accepted as a disclosed residual; `context` already reports
   `candidate_scan_truncated` in that case. A permanent fix (excluding feedback
   before the candidate cap) would change `durable.py`, which this phase kept
   read-only.
5. The core lane's undeclared schema dependency: accepted residual (above).

Also disclosed: the core lane notes that two concurrent feedback commands
against the same event could each append a successor; sequential repeats are
refused. During the integration review I regenerated the integration receipt
once to cite the negative-control log (a coordinator record; the audits show
no reviewer write).

## For the owner

1. Confirm **R16** (`integration/clarification-R16.md`): feedback is excluded
   from `context` and `capsule`; `palimnex recall` still lists it as ledger
   history.
2. Accept Phase 5 (feedback records) and commit. Modified tracked files:
   `docs/COMPATIBILITY.md`, `docs/ONTOLOGY_ADOPTION.md`, `palimnex/CHANGELOG.md`,
   `palimnex/core.py`, `palimnex/experience.py`, `pyproject.toml`; the rest is
   untracked. `.env.example`, `benchmark/` and transient logs are untouched.
3. Later rounds, each needing its own approval: the feedback shadow channel
   and frozen evaluation (once enough reviewed records exist), then the
   offline graph explorer.
