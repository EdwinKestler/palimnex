# Frozen evaluation margin

Status: options B and C are approved and implemented by
`phase3/eval-fixture-v27`. The v27 cases remain draft review data until the
owner approves them in this PR. Option A remains a measured experiment only;
no scorer change is included.

## Status and constraints

This note began as analysis on `fc1d67b110dbcaa7f6de007f64b49dfce94071aa`,
the 2.8.0 `main` baseline. The approved v27 fixture and diagnostic margin
warning now move the note into the indexed design corpus with their
implementation. `palimnex/evaluation/v25.json` remains byte-identical frozen
historical evidence.

The critical `redis-owner-socket` case searches for `private owner only Redis
Unix socket port zero` and expects `scripts/palimnex_redis.sh` within the first
five results. Its best expected-path chunk is now fifth. This leaves no
positional margin: one new non-expected chunk above it would move the expected
path to rank 6 and fail the critical case.

The constraints in [DESIGN.md](../DESIGN.md#10-frozen-evaluation-baseline-and-ranking-interpretation)
apply. Documentation must not be reworded to avoid relevant vocabulary, and
current winners must not be added to `expected_paths` merely to make the case
pass.

## Reproduced ranking

Palimnex combines the recorded components as:

```text
score = BM25 + 0.3 * cosine + 0.2 * overlap + symbol_boost
```

The CLI calls the overlap component `lexical`. Scores below were reproduced
from a fresh, deep-validated cache at the baseline commit.

| Rank | Chunk | Total | BM25 | Symbol | Cosine | Overlap |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `palimnex/core.py:1153-1232` | 25.061800 | 24.803241 | 0 | 0.278530 | 0.875000 |
| 2 | `docs/INSTALL.md:193-272` | 19.775426 | 19.533938 | 0 | 0.304959 | 0.750000 |
| 3 | `palimnex/core.py:1089-1168` | 18.607849 | 18.451743 | 0 | 0.103686 | 0.625000 |
| 4 | `scripts/upgrade_rehearsal.py:193-272` | 18.093444 | 17.896480 | 0 | 0.156546 | 0.750000 |
| 5 | `scripts/palimnex_redis.sh:257-336` | 18.012105 | 17.807822 | 0 | 0.180943 | 0.750000 |
| 6 | `scripts/palimnex_redis.sh:1-80` | 14.514601 | 14.322510 | 0 | 0.223637 | 0.625000 |
| 7 | `palimnex/README.md:65-144` | 14.208307 | 14.006464 | 0 | 0.172810 | 0.750000 |
| 8 | `palimnex/core.py:1217-1296` | 13.910065 | 13.764931 | 0 | 0.150447 | 0.500000 |
| 9 | `docs/DESIGN.md:129-208` | 12.252268 | 12.043716 | 0 | 0.195174 | 0.750000 |
| 10 | `palimnex/tests/test_redis_client.py:65-144` | 12.147680 | 12.015361 | 0 | 0.024397 | 0.625000 |

BM25 dominates this ordering; none of the ten results receives a symbol boost.
Every result misses the word `zero`. The four chunks above the expected script
are dense matches for the remaining terms:

- `core.py:1153-1232` matches seven of eight query tokens while implementing
  trusted Redis endpoints, Unix-socket path limits, ownership, and errors.
- `INSTALL.md:193-272` matches six tokens and repeatedly explains the same
  owner-only socket operations.
- `core.py:1089-1168` matches five tokens, but its Redis client parsing and port
  validation repeat those terms often enough to produce a higher BM25 score.
- `upgrade_rehearsal.py:193-272` matches six tokens while starting and checking
  a socket-only Redis server with the literal `--port 0`.

The expected script also matches six tokens. It contains the literal
`--port 0`, but the query token `zero` does not match `0`. The nearest
outranker is only `0.081339` score above the expected chunk. Rank 6 is
`3.497504` below it, but that result is another chunk from the same expected
path. The nearest lower result from a different path is rank 7, `3.803798`
below. Those score gaps do not provide pass/fail safety: the expected path is
already at the rank-5 limit, so its positional margin to failure is zero.

At this baseline the frozen v25 evaluation passes all 20 cases, all critical
cases, and all forbidden-path checks, with Recall@5 of `1.0` and MRR of
`0.8533333333333333`. The Redis case contributes reciprocal rank `0.2`.

### Effect of adding this note

Because Markdown documentation is part of the indexed corpus, this note is
itself a new, highly relevant result. After indexing it unchanged, its first
chunk ranks first at `25.649968`, the expected script moves from rank 5 to rank
6, and the frozen run reports 19/20 cases, failed critical status, Recall@5
`0.9545454545454546`, and MRR `0.8433333333333334`. This is the predicted
failure, not a scorer or fixture regression hidden by this PR. Avoiding the
case's vocabulary in this note would make the documentation less accurate and
would violate the stated constraint; therefore the failure remains visible
pending an owner-approved option.

## Option A: normalize numeric tokens in the scorer

Define a finite, reviewed canonical mapping for number words and numerals, such
as `zero` and `0`, and apply it consistently during query and corpus
tokenization. Because tokenization contributes to postings, overlap, and
embeddings, this is a retrieval-policy change. Its policy identity must change
and the corpus must be reindexed; silently reading an old index under the new
tokenization is not valid.

Acceptance must be fixed before measuring the candidate:

1. Use the same source commit and corpus for both runs. Keep v25 and its digest
   unchanged.
2. On v25, require every critical case to pass, Recall@5 not to fall below
   `1.0`, and every forbidden-path check to remain clear. Report baseline MRR
   `0.8533333333333333` and candidate MRR rather than optimizing only this one
   case.
3. Require the Redis expected path to gain positive positional margin,
   preferably rank 4 or better. A candidate that leaves it fifth has not solved
   the stated problem.
4. Run the pinned v26 challenge fixture unchanged and require no backend recall,
   passed-case, or abstention regression from the current baselines:
   `files_lexical` 4/6 and recall `0.6666667`, `v25_cache` 4/6 and recall
   `0.6666667`, and `v26_context` 5/6 and recall `0.8333333`; all three have
   abstention accuracy `1.0`.
5. v26 currently has neither critical flags nor an MRR field. Before comparing
   the scorer, define and compute the same rank-aware MRR diagnostic for its
   positive cases before and after, without changing its pass/fail semantics.
6. Record the corpus fingerprint, policy identity, per-case rank deltas, and
   search latency for both runs.

Cost is moderate: tokenizer design, index-policy migration, unit tests, a full
reindex, and evaluation across both fixtures. The principal risk is broad rank
movement: many competitors also contain numeric literals, so normalization may
help them as much as the expected script or regress unrelated queries.

## Option B: owner-reviewed versioned fixture

The implementation creates v27 while preserving v25 byte-for-byte as
historical evidence. Its changed cases are draft review data. DESIGN section
10 records the intended retrieval task and the reason for each changed query
or label. The labels are based on ownership and contract authority, not on
whichever path currently ranks first.

This PR switches the gate by changing `.palimnex.json` to the new fixture path
and its independently calculated digest. Adoption evidence includes:

- the new fixture digest and an owner-reviewed rationale for every changed
  case;
- a structured case diff between v25 and the proposed fixture;
- v25 and proposed-fixture results on the same commit and corpus, including
  critical status, Recall@5, forbidden paths, MRR, and per-case ranks;
- tests for fixture parsing, digest enforcement, and real-checkout evaluation;
- a fresh deep validation, full gate, and unchanged v25 file and digest.

Cost is high because gold-label review is a product and intent decision, not a
mechanical edit. The main risk is masking a real retrieval regression through
relabeling or making historical comparisons misleading. Versioning and the
side-by-side evidence reduce that risk but do not remove it.

## Option C: warning-only critical margin check

Evaluation now reports `critical_margin_warnings` whenever any required path
for a critical case is exactly at that case's rank limit. The standalone gate
prints the named cases as a warning. The list does not contribute to status or
exit code. Tests cover an expected path below the limit, exactly at the limit,
and absent from the result window.

Cost is low: a diagnostic calculation, output schema/documentation, and tests.
The risks are warning fatigue and a false sense of protection. This case would
warn immediately, but the option creates no retrieval margin and the next
ranking shift can still break the gate.

## Decision

The owner selected options B and C. Option A is measured below against the
same corpus but is not merged. The v27 draft is not accepted merely because it
passes mechanically: owner review of every changed intent and label remains
the approval boundary.

## Option A experiment results

The isolated experiment canonicalized English number words from `zero` through
`ten` to numerals during both corpus and query tokenization. It rebuilt fresh
in-memory indexes over the same final branch corpus. It did not change shipped
tokenization, ranking code, or the cache policy identity.

| Fixture/backend | Before recall | Before MRR | After recall | After MRR | Critical ranks before -> after |
|---|---:|---:|---:|---:|---|
| v25 | 0.9545454545 | 0.8183333333 | 1.0 | 0.8283333333 | `redis-owner-socket` absent -> 5; `audit-tombstone` 5 -> 5; `experience-capsule` 4 -> 4; `pack-encryption` 3 -> 3; `cache-reader-lease` 2 -> 2; all other critical cases 1 -> 1 |
| v26 `files_lexical` | 0.6666666667 | 0.8 | 0.6666666667 | 0.8 | none defined by the challenge fixture |
| v26 `v25_cache` | 0.6666666667 | 0.8 | 0.6666666667 | 0.8 | none defined by the challenge fixture |
| v26 `v26_context` | 0.8333333333 | 0.8 | 0.8333333333 | 0.8 | none defined by the challenge fixture |
| v27 draft | 1.0 | 0.9 | 1.0 | 0.9 | `cache-reader-lease`, `authorized-erasure`, `experience-capsule`, and `redis-owner-socket` 2 -> 2; all other critical cases 1 -> 1 |

The v26 MRR is the preregistered positive-case diagnostic; v26 has no critical
flags. Its cases-passed counts were unchanged at 4/6, 4/6, and 5/6 for the
three backends respectively.

Normalization recovered the v25 Redis case only at rank 5. It created no
positive positional margin, left other limiting v25 cases unchanged, and did
not improve v26 or v27. It therefore fails the experiment's acceptance rule
and is not a merge candidate.
