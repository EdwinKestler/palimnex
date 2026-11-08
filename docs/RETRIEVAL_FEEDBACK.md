# Reviewed retrieval feedback

Reviewed retrieval feedback records a manual, source-verified judgement that a
specific repository source range either answers or does not answer a normalized
query. It is durable historical evidence for later review.

Feedback is **not** approval, operational authority, a ranking signal, automatic
query-history learning, or a statement that an answer is true. Every payload
states `authority: historical_only`, `authorizes_actions: false`, and
`retrieval_influence: false`. Recording feedback does not change
`retrieve_sources`, context assembly, `explain-search`, cache search, symbols,
impact, or evaluation. A later feedback shadow or influence channel requires a
separate design, evaluation, and approval.

## Public payloads

`palimnex:retrieval-feedback:v1` is stored as an existing `fact` event. It
contains:

- the whitespace-normalized query and its SHA-256 digest;
- `answers` or `does_not_answer`;
- an admitted repository path, inclusive line range, selected-content digest,
  and whole-file digest;
- a named manual reviewer and `manual`, `explain_search`, or `context` origin;
- an optional reviewed note; and
- the fixed non-authorizing fields above.

The ledger subject is an opaque digest of the query digest and source locator.
It does not contain query text. The event carries matching source evidence, so
the ledger verifies the selected lines at append time.

A correction uses the same payload schema in an existing `correction` event.
It keeps the original query, locator, origin, subject, and sensitivity while
recording a new judgement, reviewer, and optional note. The original event is
preserved as superseded history.

`palimnex:retrieval-feedback-withdrawal:v1` is stored as an existing
`revocation` event. It identifies the withdrawn event, manual reviewer, and
reviewed reason. Withdrawal preserves both the feedback and revocation; it
never deletes history.

The JSON contracts are
`palimnex/schemas/retrieval-feedback.v1.schema.json`,
`retrieval-feedback-withdrawal.v1.schema.json`, and
`retrieval-feedback-report.v1.schema.json`.

## Report states

The read-only `palimnex:retrieval-feedback-report:v1` report orders records by
observation time and event ID and assigns one state:

- `current`: the latest record and both its selected range and file still match;
- `stale`: the latest record, but its admitted source or digest has drifted;
- `superseded`: replaced by a correction;
- `withdrawn`: revoked by a withdrawal event; or
- `invalid`: an event claims a feedback schema but its payload or event
  envelope fails validation. The report exposes only a stable reason code for
  invalid data, never rejected query, note, reason, or reviewer text.

By default, the report lists only current, stale, and invalid records. With
history included it also lists superseded and withdrawn records. Counts always
cover every state. Restored logical exports retain the records as
historical-only data; importing them does not restore operational authority.

## Owner-run commands

Ledger writes are explicit owner actions. Use an open ledger session and a
currently admitted source locator:

```bash
python3 palimnex.py feedback-record \
  --session SESSION_ID \
  --query 'normalized or unnormalized reviewed query' \
  --locator 'palimnex/retrieval.py:174-188' \
  --judgement answers \
  --reviewer 'Reviewer Name' \
  --origin manual \
  --note 'Optional reviewed note'

python3 palimnex.py feedback-correct \
  --session SESSION_ID \
  --event EVENT_ID \
  --judgement does_not_answer \
  --reviewer 'Reviewer Name' \
  --note 'Why the reviewed judgement changed'

python3 palimnex.py feedback-withdraw \
  --session SESSION_ID \
  --event EVENT_ID \
  --reviewer 'Reviewer Name' \
  --reason 'Why this feedback is withdrawn'

python3 palimnex.py feedback-report
python3 palimnex.py feedback-report --include-history
```

Correction and withdrawal accept only a current feedback event in the same
project. Repeating either action against an already superseded or withdrawn
event is refused.

## Privacy and bounds

Queries are stripped and every Unicode-whitespace run becomes one space. The
normalized query is non-empty, at most 8 KiB and 128 lexical terms, free of
remaining control characters, and privacy-scanned. Reviewer names are 1–128
printable characters. Notes and withdrawal reasons are 1–1024 UTF-8 bytes,
allow printable text plus newlines, and are privacy-scanned.

The locator must be a repository-relative admitted file and an existing
inclusive line range. Source admission runs before the payload is built. A
privacy refusal returns only a stable reason and field; it does not echo or
persist rejected text. Feedback APIs never write through a path other than
`MemoryLedger.append_event`, and report access opens the ledger read-only.
