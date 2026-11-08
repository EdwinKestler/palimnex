# Phase 5 shared interface: reviewed retrieval feedback records (v1.1)

v1.1 (after the round-1 review): R16 — `context` and `capsule` exclude events
whose payload schema is a feedback schema from historical recall
(`palimnex/experience.py current_eligible`, coordinator-owned); `palimnex
recall` still lists them as ledger history. Report records carry
`invalid_reason` (`null` unless `state` is `invalid`), which both lanes adopted
to resolve the reason-code wording in section 2.

Owner decisions (2026-11-07), recorded in `docs/ONTOLOGY_ADOPTION.md`:
this round builds **feedback records only**. They are reviewed, source-verified
"query → locator" judgements, stored as **existing ledger event kinds** with a
**new versioned payload**, review-attributed, provenance-bound and
non-authorizing. **The owner writes the real ledger**, through commands; agents
implement and test against temporary ledgers only. Feedback has **no retrieval
influence**: a feedback shadow channel and its frozen evaluation are a later
round, and any opt-in influence after that needs its own approval and a new
versioned behaviour contract. The semantic cache is skipped; static graph
exploration (offline HTML + JSON) is deferred.

Nothing in this phase changes `retrieve_sources`, `context`, `explain-search`,
`search`, `symbols`, `impact`, `palimnex evaluate`, the ledger schema, event
kinds, `memory-event.v1`, packs, exports, retention or erasure rules.
`palimnex/durable.py` is read-only.

## 1. Payloads

### `palimnex:retrieval-feedback:v1` (recorded with kind `fact`, or `correction`)

```json
{
  "schema": "palimnex:retrieval-feedback:v1",
  "query": "normalized query text",
  "query_digest": "<sha256 hex of the UTF-8 normalized query>",
  "judgement": "answers | does_not_answer",
  "source": {"path": "palimnex/retrieval.py", "start_line": 174, "end_line": 188,
             "content_digest": "<sha256 hex of the selected lines joined by \\n>",
             "file_digest": "<sha256 hex of the whole file bytes>"},
  "review": {"reviewer": "EdwinKestler", "method": "manual"},
  "provenance": {"origin": "manual | explain_search | context"},
  "note": "optional reviewer note or null",
  "authority": "historical_only",
  "authorizes_actions": false,
  "retrieval_influence": false
}
```

- **Query normalization:** strip, then replace every run of Unicode whitespace
  with one space (as R9). Non-empty, at most 8 KiB UTF-8 (R11 bound), at most
  128 lexical terms, no control characters after normalization, and no
  `security.scan_text` finding (refusal `query_privacy_refused`, never echoed).
- **Source:** a repository-relative `path:start-end` (or `path:line`) locator.
  The path must be a file of the current admitted corpus
  (`cache_v3.source_snapshot(root)`), so privacy admission already ran; the line
  range must exist. `content_digest` is computed exactly as
  `MemoryLedger._source_evidence_digest` computes it for `path:start-end`, so the
  ledger marks the source evidence verified. Refusals: `locator_invalid`,
  `source_not_admitted`, `range_invalid`.
- **Reviewer:** 1–128 printable characters, no `scan_text` finding.
  `method` is always `manual` in v1.
- **Note:** `null` or 1–1024 UTF-8 bytes, printable plus `\n`, no `scan_text`
  finding (refusal `note_privacy_refused`).
- **Subject** (the ledger subject; the ledger requires the same subject for
  supersession): `"retrieval-feedback:" + sha256_hex(query_digest + "\0" +
  path + ":" + start + "-" + end)`. No query text in the subject.

### `palimnex:retrieval-feedback-withdrawal:v1` (recorded with kind `revocation`)

`{schema, withdraws_event_id, review: {reviewer, method: "manual"}, reason
(1–1024 bytes, privacy-scanned), authority: "historical_only",
authorizes_actions: false, retrieval_influence: false}`.

All payloads have exactly these keys (`additionalProperties: false`), with
JSON Schemas in `palimnex/schemas/retrieval-feedback.v1.schema.json`,
`retrieval-feedback-withdrawal.v1.schema.json` and
`retrieval-feedback-report.v1.schema.json` (draft 2020-12).

## 2. Module `palimnex/feedback.py` (feedback-core lane)

```python
FEEDBACK_SCHEMA = "palimnex:retrieval-feedback:v1"
WITHDRAWAL_SCHEMA = "palimnex:retrieval-feedback-withdrawal:v1"
REPORT_SCHEMA = "palimnex:retrieval-feedback-report:v1"
JUDGEMENTS = ("answers", "does_not_answer"); ORIGINS = ("manual", "explain_search", "context")
class FeedbackError(ValueError): reason, field     # "retrieval feedback refused: {reason} at {field}"

def normalize_query(query: str) -> str
def build_feedback(query, locator, judgement, reviewer, *, root, note=None, origin="manual") -> dict
def feedback_subject(payload: Mapping) -> str
def validate_feedback_payload(value: object) -> dict          # structure, bounds, digests self-consistent
def validate_withdrawal_payload(value: object) -> dict
def record_feedback(ledger, session_id, *, query, locator, judgement, reviewer,
                    note=None, origin="manual", sensitivity="internal") -> dict
def correct_feedback(ledger, session_id, event_id, *, judgement, reviewer, note=None) -> dict
def withdraw_feedback(ledger, session_id, event_id, *, reviewer, reason) -> dict
def feedback_report(ledger, *, include_history=False) -> dict
```

- `record_feedback` calls `ledger.append_event(session_id, "fact", subject=...,
  payload=..., evidence=[{"kind": "source", "locator": "path:start-end",
  "content_digest": ...}], trust="observed", sensitivity=sensitivity,
  retention="durable")` and returns `{event_id, subject, payload_digest
  (sha256 of canonical_json(payload)), verified, authority: "historical_only",
  authorizes_actions: false, retrieval_influence: false}`.
- `correct_feedback` reads the referenced event (it must be a current
  feedback event of this project), rebuilds the payload for the **same query
  and locator** against current source with the new judgement, reviewer and
  note, and appends kind `correction` with `supersedes=event_id`.
- `withdraw_feedback` appends kind `revocation` with `supersedes=event_id` and a
  withdrawal payload. Withdrawn feedback is never deleted.
- Reading uses a **read-only** `ledger.connection(create=False)` (as
  `palimnex/experience.py` does) and `durable.unpack_payload`; events whose
  payload schema is not one of the two feedback schemas are ignored. A payload
  claiming a feedback schema that fails validation is reported as
  `state: "invalid"` with a reason code, never silently dropped.
- `feedback_report` returns `palimnex:retrieval-feedback-report:v1`:
  `{schema, project_id, records: [{event_id, kind, state, judgement,
  query_digest, query, source, reviewer, origin, observed_at, superseded_by,
  withdrawn_by, source_current}], counts: {current, stale, superseded,
  withdrawn, invalid}, include_history, authority: "historical_only",
  authorizes_actions: false, retrieval_influence: false}`. `state` is
  `withdrawn` (a revocation supersedes it), `superseded` (a correction
  supersedes it), `stale` (latest, but the source file or range no longer
  hashes to `content_digest`: source drift), `invalid`, or `current`. Without
  `include_history`, only latest non-withdrawn records are listed (current,
  stale, invalid); counts always cover everything. Records are ordered by
  `(observed_at, event_id)`. Deterministic for a given ledger and checkout.
- Feedback never reaches `retrieve_sources`, `context`, `explain-search` or
  `search`: no import of `feedback` from those modules.

## 3. CLI (integration, coordinator)

`palimnex feedback-record --session S --query Q --locator path:a-b --judgement
answers|does_not_answer --reviewer NAME [--note TEXT] [--origin ...]
[--sensitivity ...]`, `palimnex feedback-correct --session S --event E
--judgement ... --reviewer NAME [--note TEXT]`, `palimnex feedback-withdraw
--session S --event E --reviewer NAME --reason TEXT` (ledger writes, run by the
owner) and the read-only `palimnex feedback-report [--include-history]`.
