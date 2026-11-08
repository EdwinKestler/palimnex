# Lane brief: ontology-phase-5-feedback-core

Read `COMMON.md` and `FEEDBACK_SPEC.md` (sections 1 and 2). You own
`palimnex/feedback.py`, `palimnex/tests/test_feedback.py` and
`docs/RETRIEVAL_FEEDBACK.md`. The schema lane writes the JSON Schemas in
parallel; validate payloads in code (do not import the schema files at runtime).

## Implement

Everything in section 2, exactly. Build every payload with `build_feedback` or
the withdrawal builder, validate it before writing, and never write through any
path other than `MemoryLedger.append_event`.

## Tests: `palimnex/tests/test_feedback.py` (temporary repository and ledger)

- record → report shows `current`; the ledger marks the source evidence
  verified; payload digest equals `sha256(canonical_json(payload))`.
- query normalization (whitespace, R9) and every refusal reason: empty, too
  long, too many terms, control characters, privacy canary in query, note or
  reason (not echoed), bad locator, non-admitted path (excluded or missing
  file), out-of-range lines, bad judgement, origin or reviewer.
- source drift: edit the bound lines → `stale` with `source_current: false`;
  restore → `current`.
- correction supersedes (same subject, new judgement) → old `superseded`, new
  `current`; correcting with a different locator is impossible by construction.
- withdrawal → `withdrawn`, still present with `include_history`, never deleted;
  withdrawing twice or withdrawing a non-feedback event is refused.
- an event of another kind or schema is ignored; a tampered feedback payload
  appended directly through `append_event` is reported `invalid`.
- determinism of the report; authority fields always `historical_only`/false.
- logical export (`ledger.logical_document()`) preserves feedback events, and a
  ledger restored from it reports the same records.
- `retrieve_sources` results for a query are byte-identical with and without
  feedback in the ledger (no influence).

## Docs: `docs/RETRIEVAL_FEEDBACK.md`

What a feedback record is and is not (not authority, not ranking), the payloads,
states, the owner-run commands (section 3), drift, correction, withdrawal, and
privacy.
