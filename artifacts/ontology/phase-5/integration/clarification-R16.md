# R16 — feedback stays out of context and capsule recall (coordinator decision, for owner confirmation)

Found by the independent review (BLOCKER on `ontology-phase-5-feedback-core`,
`artifacts/ontology/phase-5/round-1/`): a feedback record is stored as an
ordinary `fact` event, and `assemble_context` (`palimnex context`) and
`build_capsule` (`palimnex capsule`) recall matching ledger facts into their
results as `historical_event` items. So a recorded feedback event changed the
`context` and `capsule` output, which the owner excluded ("excluded from
retrieval influence") and `FEEDBACK_SPEC.md` promised would not happen.

Decision:

1. `palimnex/experience.py` `current_eligible` returns `False` for events whose
   payload `schema` is `palimnex:retrieval-feedback:v1` or
   `palimnex:retrieval-feedback-withdrawal:v1`, so `context` and `capsule`
   never include feedback, whatever its kind. The check uses the schema strings
   only; `experience.py` does not import `palimnex.feedback`.
2. Every other event is filtered exactly as before. With no feedback in the
   ledger, `context` and `capsule` are byte-identical to the committed code.
3. `palimnex recall` (explicit ledger memory search) and the hot-event
   projection still show feedback events as ordinary `historical_only` ledger
   history. They are ledger audit surfaces, not retrieval results.
4. The integration lane (coordinator) gains ownership of
   `palimnex/experience.py` for this one change (task card and manifest amended;
   `integration/bundle-validation.r16.json`). Lane cards are unchanged.
5. `FEEDBACK_SPEC.md` v1.1 records the rule.
