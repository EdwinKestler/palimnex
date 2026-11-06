# Retrieval coverage receipts

`palimnex:retrieval-coverage:v1` is deterministic evidence about whether
approved concepts have current source support. Coverage is not correctness: a
reader must still inspect current source and independently verify any answer.
Every receipt has `authority: evidence_only` and `authorizes_actions: false`.
The broader compatibility and authority boundaries are documented in
[`ONTOLOGY_ADOPTION.md`](ONTOLOGY_ADOPTION.md); registry rules are in
[`CONCEPT_REGISTRY.md`](CONCEPT_REGISTRY.md).

## Query and identity bindings

The receipt contains no raw query. `query_digest` is SHA-256 of strict UTF-8
after CRLF and CR are mapped to LF and the text is normalized to NFC. Case and
all other whitespace are preserved. The policy identifier is
`sha256-utf8-nfc-lf-preserve-whitespace-case:v1`.

The receipt binds the effective project identity, the resolved-checkout digest,
the admitted corpus fingerprint and index-policy digest, and the canonical
approved-registry digest. Checkout identity names a resolved location, not a
Git revision, signature, or trust assertion. Source bindings reuse
`palimnex:source-locator:v1` and must be reopened, privacy-admitted, and
digest-verified before they support coverage.

## Classification and status

Each recognized concept is classified exactly once:

- **covered**: at least one applicable source binding verifies;
- **uncovered**: no applicable source binding exists;
- **stale**: binding material exists but current verification fails; or
- **ambiguous candidate**: an exact alias maps to multiple concepts and no
  concept is silently selected.

If `R`, `C`, `U`, `S`, and `A` are the recognized, covered, uncovered, stale,
and distinct ambiguous-candidate counts, then `R = C + U + S + A`. Coverage is
the integer pair `C / R`; the receipt never stores a floating-point ratio.

| First matching condition | `status` |
| --- | --- |
| At least one ambiguity | `ambiguous` |
| No recognized concepts | `unanswerable` |
| Every recognized concept is covered | `answerable` |
| Some but not all recognized concepts are covered | `partial` |
| Concepts are recognized but none is covered | `unanswerable` |

Ambiguity takes precedence even when another concept is covered. An ambiguous
candidate is never counted as covered.

## Completeness, ordering, and digest

Retrieval truncation, coverage-output truncation, and byte-budget omission are
separate disclosures. None alone makes a result `unanswerable`. Status uses the
full bounded totals, while visible collections may be truncated. Byte-budget
state separately reports the budget, used bytes, omitted item count, and
whether omission occurred.

Collections use deterministic Unicode code-point ordering: concept IDs and
aliases first; ambiguity records by alias then candidates; locators by scheme,
source identity, version, range, and digest. Duplicates and overlapping
classifications are invalid. `receipt_digest` is lowercase SHA-256 of Palimnex
canonical JSON after removing only `receipt_digest`.

`semantic_disclosure` explicitly records the v1 semantic-provider interface as
disabled, with no external network, provider, HNSW, or retrieval influence. A
future semantic mode requires a separate versioned contract and approval.

## `explain-search`

The command is:

```text
palimnex explain-search QUERY [--limit N] [--byte-budget N] [--backend local|cache] [--no-graph] [--registry PATH]
```

It defaults to `--limit 5`, `--byte-budget 8192`, and `--backend local`.
`palimnex explain-search` prints one `palimnex:explain-search:v1` document. Its
`search` member is the unchanged result of the bounded, source-backed
`retrieve_sources` retrieval used by `context`; it is not the output of
`palimnex search` and is not re-ranked, filtered, or annotated. The sibling
`coverage` member is a full receipt when `coverage_state` is `enabled`.

The approved registry defaults to `ontology/concept-registry.v1.json`.
`--registry PATH` selects another repository-relative path; absolute paths and
paths containing `..` are refused. A missing default registry produces
`coverage_state: registry_absent` and `coverage: null`, prints the document, and
exits 0. A missing explicit registry is a typed refusal. The wrapper records
whether the path came from `default` or `argument`.

Malformed or traversal-bearing paths, symlinks, cross-project registries or
bindings, privacy refusals, non-approved registry kinds, and malformed queries
are typed refusals under R7. A missing explicit registry and every typed refusal
exit 1 with a non-echoing error and no document. Source drift is different: it
is a bounded stale receipt state.

The document is printed and never persisted. The raw query appears only inside
the unchanged bounded `retrieve_sources` result under its existing behavior;
the coverage receipt contains only `query_digest`. Source excerpts, privacy
findings, refused bytes, credentials, provider errors, model inputs, and model
outputs are not added or persisted by these contracts.
