# Lane brief: ontology-phase-0-coverage-contract

Read `COMMON.md` in this folder first. You own
`artifacts/design/ontology-phase-0/coverage/` and your receipt file.

## Deliverables

1. `coverage/retrieval-coverage.v1.schema.json`, the draft schema for
   `palimnex:retrieval-coverage:v1`. Cover every field in the design's
   "`palimnex:retrieval-coverage:v1`" section:
   - `query_digest` (define the exact normalization before hashing); no raw
     query text by default;
   - identities: project, checkout (ground in `palimnex/vcs.py` and
     `palimnex/identity.py`), corpus (ground in how the cache and evaluation
     identify a corpus, for example in `palimnex/cache_v3.py`), and registry
     digest;
   - recognized concepts with the exact matched aliases; covered concepts with
     verified bindings expressed as `palimnex:source-locator:v1` objects;
     uncovered, ambiguous (with candidate concept IDs) and stale concepts;
   - coverage as integer numerator and denominator (no floats in the
     canonical form), bounded counts and an explicit truncation flag for each
     list;
   - retrieval truncation and byte-budget omission state, kept separate from
     answerability;
   - status `answerable | partial | ambiguous | unanswerable`;
   - semantic or provider influence disclosure (today: provider disabled,
     influence none; mirror `palimnex/semantic.py` vocabulary);
   - `receipt_digest`, `authority: evidence_only`, `authorizes_actions: false`.
2. `coverage/SEMANTICS.md`, covering:
   - a complete, deterministic status decision table, including the
     zero-recognized-concepts case, ambiguity precedence, and stale bindings.
     State why truncation or byte-budget omission never by itself yields
     `unanswerable`.
   - coverage arithmetic and ordering rules (sort keys, tie-breaking);
   - "coverage is not correctness" stated as a reader obligation;
   - the relationship to `project-memory:context:v1`: a separate result, never
     embedded (ground in where the context envelope is built in source);
   - what is never persisted (raw query, source excerpts, secret findings);
   - open questions for the owner, including the `explain-search` CLI output
     shape.
3. `coverage/examples/valid/*.json`: one example per status, plus a truncated
   but `answerable` example and a byte-budget-omission example.
   `coverage/examples/invalid/*.json`: at least 6, each named after its
   single failure reason (float ratio, raw query field, `authorizes_actions:
   true`, ambiguous concept counted as covered, unknown status, oversize list).
4. `coverage/check_coverage_contract.py`, offline: checks the schema, runs
   all examples with the expected pass or fail result, recomputes
   `receipt_digest`, and enforces the decision table as a cross-field check.
   JSON Schema alone cannot prove that "ambiguous is never covered" or that
   the status matches the counts, so implement those as Python checks. Exit 0
   only when all checks hold.

Registry schema work belongs to another lane; reference the registry by digest
only.
