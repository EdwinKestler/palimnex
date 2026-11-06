# Draft retrieval coverage v1 semantics

Status: Phase 0 draft awaiting the owner exit gate. This document does not
approve implementation, retrieval influence, provider use, persistence, or an
external action.

## Reader obligation

`palimnex:retrieval-coverage:v1` reports whether approved concepts have current,
verified source support. **Coverage is not correctness.** A reader must reopen
the cited current source, reason about the question, and independently verify
any answer. The receipt has `authority: evidence_only` and
`authorizes_actions: false`; it cannot authorize an operation.

## Query digest

The producer validates the admitted query as a non-empty string within the
existing 8 KiB UTF-8 query bound, then computes `query_digest` exactly as
follows:

1. replace every CRLF pair with LF;
2. replace each remaining CR with LF;
3. normalize the result to Unicode NFC;
4. preserve case, leading and trailing whitespace, and every other code point;
5. encode as strict UTF-8; and
6. take lowercase hexadecimal SHA-256.

The policy identifier is
`sha256-utf8-nfc-lf-preserve-whitespace-case:v1`. Raw query text is not part of
this receipt and is not persisted by this contract. The current query byte and
token bounds are grounded in `palimnex/cache_v3.py:179-187`.

## Identity bindings

- `identities.project` uses the registry contract's single
  `$defs.projectIdentity` definition. `project_id` is the canonical committed
  UUID accepted by `palimnex/cache_v3.py:80-87`; `project_slug` follows
  `palimnex/core.py:305-313`.
- `checkout.checkout_id` is SHA-256 over strict UTF-8 encoding of
  `str(root.resolve())`, matching `palimnex/retrieval.py:144-146`. It identifies
  the resolved checkout location, not a Git revision, signer, or source state.
- `corpus.fingerprint` is the admitted source snapshot fingerprint over framed
  repository-relative paths and bytes (`palimnex/cache_v3.py:190-218`).
  `index_policy_digest` binds the source-admission/index policy. Together these
  identify source state more precisely than the checkout location alone.
- `registry.digest` binds canonical content of a separately reviewed
  `palimnex:concept-registry:v1`. This lane does not define that registry.

`palimnex/vcs.py:1-39` exposes ignore-state checks but no commit identity, and
`palimnex/identity.py:1-40` defines signer identity rather than checkout
identity. The receipt therefore does not claim that `checkout_id` is a commit,
signature, or trust assertion.

## Recognition and source state

Exact alias matching produces the recognized concept set `R`. The registry's
single alias definition and SEMANTICS algorithm apply: stored aliases are
already NFKC-normalized, casefolded, mapped from punctuation to spaces, and
whitespace-collapsed. Each visible recognized record lists those exact stored
normalized aliases. Display forms belong only in the registry's
`canonical_name`. An alias that maps to more than one incompatible concept
produces one ambiguity record; its candidate IDs remain recognized but are not
covered.

For each concept, exactly one classification applies:

- **covered**: at least one binding was reopened, privacy-admitted, range
  selected, and digest-verified;
- **uncovered**: the approved concept has no applicable source binding;
- **stale**: applicable binding material exists but every applicable binding
  fails current verification; or
- **ambiguous candidate**: the exact alias cannot select one compatible
  concept.

Bindings reuse `palimnex:source-locator:v1` without a second locator shape.
The resolver rejects traversal, scans bytes before selecting a range, and
collapses provider details into a non-echoing failure
(`palimnex/locators.py:95-139`). A stale record carries the locator commitment,
never refused source bytes or a provider exception.

Malformed or traversal paths, symlinks, cross-project bindings, and privacy
refusals are typed operation errors and produce no coverage receipt. They must
not be converted into `uncovered`, `stale`, or another receipt state. Stale
source is different: a structurally admitted, project-local binding whose
current source is missing, unavailable, version-changed, or digest-changed
produces a receipt with a bounded stale reason. This provisional distinction is
R7 and remains flagged for the owner's Phase 0 exit gate.

Let `C`, `U`, and `S` be the total counts of covered, uncovered, and stale
concepts, and let `A` be the total number of distinct ambiguity candidate IDs.
The contract requires:

```text
R = C + U + S + A
coverage.numerator   = C
coverage.denominator = R
```

The canonical receipt contains no floating-point ratio. A UI may display
`C / R`, but `0 / 0` stays the integer pair and must not be converted to NaN,
infinity, or a claim of full coverage.

## Deterministic status decision table

Rows are evaluated from top to bottom. Ambiguity has precedence over every
other state.

| Priority | Condition | Status |
| --- | --- | --- |
| 1 | one or more ambiguous aliases (`ambiguous_concepts.total_count > 0`) | `ambiguous` |
| 2 | no concepts recognized (`R = 0`, therefore `C = U = S = A = 0`) | `unanswerable` |
| 3 | every recognized concept is covered (`C = R > 0`) | `answerable` |
| 4 | at least one, but not every, recognized concept is covered (`0 < C < R`) | `partial` |
| 5 | concepts were recognized but none is covered (`R > 0` and `C = 0`) | `unanswerable` |

Stale-only support is therefore `unanswerable`; a mixture of verified and stale
concepts is `partial`; any ambiguity remains `ambiguous` even if other concepts
are covered.

Retrieval truncation, coverage-output truncation, or byte-budget omission never
by itself produces `unanswerable`. These are independent completeness
disclosures. Status is computed from the full bounded totals, not merely the
visible list prefixes. A truncated `answerable` receipt says all recognized
concepts have verified bindings while some receipt detail is omitted; it does
not promise that a downstream answer includes every relevant excerpt.

## Bounds and truncation

Each top-level collection carries `total_count` and `truncated`. Each nested
alias, candidate, or binding list carries its own count and truncation flag.
When a flag is false, its count equals the visible list length. When true, the
count is at least the visible length and status arithmetic uses the full count.
All counts, visible lists, strings, source ranges, and byte states are bounded
by the schema.

`retrieval_state.retrieval_truncated` describes retrieval candidate/result
limits. `byte_budget_omission` separately records serialized UTF-8 budget use
and omission, matching the separation already exposed by
`palimnex/retrieval.py:136-146`. `coverage_output_truncated` is true exactly
when any coverage collection or nested detail list is truncated.

## Ordering and canonical digest

No locale or insertion order participates. Strings are NFC-normalized and sort
by Unicode code point. Producers apply these ascending keys:

1. recognized, covered, uncovered, and stale concepts: `concept_id`;
2. matched aliases and candidate IDs: string value;
3. ambiguity records: `(matched_alias, candidate_concept_ids)`;
4. source locators: `(scheme, source_id, version, range.unit, range.start,
   range.end, digest)`; and
5. stale records with the same concept: `reason`, then locator keys.

Duplicate concept IDs within a category, duplicate aliases within a recognized
record, and duplicate locators within a binding list are invalid. Covered,
uncovered, stale, and ambiguous-candidate sets are disjoint.

`receipt_digest` is lowercase SHA-256 over Palimnex canonical JSON of the whole
receipt with only `receipt_digest` removed. Canonical JSON is UTF-8, has sorted
object keys and compact separators, preserves Unicode, and refuses NaN and
infinity, matching `palimnex/durable.py:362-369`.

## Semantic disclosure and compatibility

The v1 draft mirrors the only current semantic-provider state from
`palimnex/semantic.py:48-64`: interface
`project-memory:semantic-provider:v1`, mode `disabled`, no external network,
no registered provider, no HNSW, and no retrieval influence. A later semantic
mode needs a separately approved versioned contract; it cannot broaden this v1
meaning silently.

The coverage receipt is a separate result. It is never embedded into or added
to `project-memory:context:v1`, whose exact envelope is constructed in
`palimnex/experience.py:233-240`. This draft changes no cache, context, ledger,
pack, event, Redis namespace, SQLite object, CLI behavior, or existing wire
identifier. Rollback before implementation is deletion of these unapproved
drafts; a future implementation must preserve baseline behavior when coverage
is not requested.

## Persistence and privacy boundary

This contract does not persist raw queries, source excerpts, privacy scanner
findings, refused bytes, secret values, provider errors, credentials, model
inputs, or model outputs. It stores only digests, bounded identities, concept
IDs, exact matched aliases already admitted by the approved registry, locator
commitments, counts, and non-echoing state. Privacy admission must precede
alias/concept derivation and locator verification; this receipt cannot be used
to justify sending source to a provider.

## Open owner decisions

1. For the provisional `explain-search` CLI, should coverage be a second JSON
   document, a named sibling object in a new command result, or a path to a
   separately written receipt? It must not alter `project-memory:context:v1`.
2. Should checkout identity remain the current resolved-root digest or gain a
   separately versioned, privacy-reviewed VCS identity in a later contract?
3. Should the final registry define one shared alias-normalization identifier
   that this receipt must bind in addition to the registry digest?
4. Should stale reasons remain the four bounded public categories here, with
   all resolver/provider detail suppressed?
5. At the exit gate, confirm the collection limits (256 visible, 4096 total),
   nested-detail limits (16 visible, 64 total), and 64 MiB receipt byte-state
   ceiling.
