# Lane brief: ontology-phase-0-threat-cases

Read `COMMON.md` in this folder first. You own
`artifacts/design/ontology-phase-0/threat-model/`,
`artifacts/design/ontology-phase-0/frozen-cases/`, and your receipt file.

## Deliverables

1. `threat-model/THREAT_MODEL.md`:
   - assets and trust boundaries: repository source, the approved registry,
     candidate entries, the Redis projection, the SQLite ledger, coverage
     receipts, a future semantic provider, and parallel agents;
   - threats per boundary (spoofed approval, alias poisoning or collision,
     candidate promotion by persistence, stale bindings, path traversal and
     symlinks, cross-project leakage, secret derivation into aliases or
     embeddings, silent downgrade, evaluation overfitting, oversize inputs,
     parallel-agent overwrite, authority inflation from receipts);
   - for each threat: the mitigating invariant from the design (cite its
     number), the existing source control that implements it today where one
     exists (cite file and function, such as `palimnex/locators.py` and
     `palimnex/security.py`), the test case IDs from the matrix below, and the
     residual risk;
   - open questions for the owner.
2. `frozen-cases/cases.v0.json`: the frozen case matrix. Each case has a
   stable `case_id`, `category`, `description`, a minimal inline registry
   fixture (concepts and aliases only; use placeholder locator digests and
   mark them as placeholders), the query, the expected coverage `status`,
   expected recognized, covered, uncovered and ambiguous concept IDs, and the
   phase it gates (1, 2 or 3). Required categories, with at least two cases
   each:
   positive, partial, ambiguous, negative/unrelated, stale-source, secret,
   truncation, byte-budget, supersession, withdrawn, candidate-non-influence,
   path-traversal/symlink, cross-project, normalization (case, Unicode,
   whitespace). Use the status vocabulary in the design
   (`answerable | partial | ambiguous | unanswerable`); where the right
   expected status is debatable, set `"expected_status_disputed": true` with
   a reason instead of guessing.
   Secret cases use `"canary_recipe"` objects (fragments joined at test time),
   never a literal secret.
3. `frozen-cases/README.md`: how cases are frozen (file digest recorded at the
   exit gate), the rule that labels never change to make a candidate pass,
   and how Phase 1-3 tests will consume the file.
4. `frozen-cases/check_cases.py`, offline: validates structure and unique IDs,
   enforces the category minimums and the status vocabulary, and runs
   `palimnex.security.scan_bytes` over every file you own. It must report no
   findings, which proves no literal secret material is stored. It also
   rebuilds each canary recipe and confirms that `scan_text` does detect it,
   so the cases really test secret handling. Exit 0 only when everything
   holds.

Schema drafting belongs to the other two lanes; do not define registry or
receipt schemas here.
