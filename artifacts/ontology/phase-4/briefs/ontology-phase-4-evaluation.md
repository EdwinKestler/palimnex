# Lane brief: ontology-phase-4-evaluation (wave 3, after channel and cohort)

Read `COMMON.md` and `SEMANTIC_SPEC.md` section 4 first. You own
`palimnex/semantic_eval.py`, `palimnex/tests/test_semantic_eval.py`,
`palimnex/schemas/semantic-shadow-evaluation.v1.schema.json` and
`docs/SEMANTIC_SHADOW.md`. Everything else is finished and read-only, including
the frozen cohort `palimnex/evaluation/semantic-shadow.v1.json`, whose SHA-256
is recorded in `artifacts/ontology/phase-4/integration/cohort-freeze.json`. Pin
that digest as `COHORT_SHA256`. You must not change the cohort, its labels or
any threshold.

## Implement

`evaluate_semantic_shadow`, `SemanticEvaluationError`, `PROMOTION_POLICY`, the
R15 benchmark protocol and the report exactly as section 4 specifies. Reuse
`palimnex/ontology_eval.py` helpers read-only where section 4 names them rather
than duplicating them. Build canaries at runtime from fragments and check each
against `security.scan_text`.

## Tests: `palimnex/tests/test_semantic_eval.py`

Keep tests fast: use small synthetic cohorts written into temporary checkouts
(monkeypatch the cohort path and pinned digest for those tests), and
`benchmark=False` except in a benchmark test driven by a fake `clock_ns`.
- the report validates against its schema and is deterministic apart from the
  benchmark block;
- `promotable` when every gate holds (a synthetic cohort plus a scripted
  provider double that ranks the expected file first);
- each gate can fail: construct a regression, a forbidden hit, an abstention
  regression, a collapsed ambiguity, a non-deterministic provider, an identity
  that changes mid-run, a latency over 1.5x (fake clock), and `benchmark=False`
  (`benchmark_not_run`);
- the source-drift gate catches a memo keyed by something other than content
  (a deliberately broken memo double) and passes with the real memo;
- the privacy gate: query canaries refused before the provider sees them;
  corpus canary refused by admission; no canary in the serialized report;
- a modified cohort file fails with `fixture_digest_mismatch`;
- `promotion_authorized`, `retrieval_influence` and `authorizes_actions` are
  always false.
Do not run the real-repository evaluation; the coordinator runs it.

## Docs: `docs/SEMANTIC_SHADOW.md`

What the provider, channel and evaluation are; R14 and R15; every gate and the
owner's thresholds; that `promotable` is not promotion; that nothing changes
production retrieval; how to read a `held` report.
