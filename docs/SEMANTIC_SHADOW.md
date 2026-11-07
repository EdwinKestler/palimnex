# Local semantic shadow experiment

Palimnex Phase 4 evaluates a deterministic local semantic channel beside the
unchanged production retrieval result. It is an evidence-only experiment: it
does not configure a provider, alter `retrieve_sources`, persist vectors, or
authorize semantic promotion.

## Components

`palimnex.semantic_local.HashedEmbeddingProvider` exposes the existing hashed
embedding through a bounded in-process provider contract. Its identity binds
the provider ID, revision, 384 dimensions, and a behavioral implementation
digest. Provider failures, timeouts, malformed vectors, and identity failures
are typed, non-echoing errors. There is no network access, model download, or
persistent vector store.

`palimnex.semantic_shadow` implements the fixed R14 channel policy. It scans a
query before any provider call, embeds only already-admitted source chunks,
keeps content-digest-keyed vectors in a bounded process-local memo, selects at
most 64 positive-cosine candidates, and adds the visible `semantic` channel to
an isolated RRF comparison. When baseline retrieval abstains, the semantic
channel is suppressed without calling the provider. The comparison is pointer
only and sets `retrieval_influence`, `promotion_authorized`, and
`authorizes_actions` to false.

`palimnex.semantic_eval.evaluate_semantic_shadow` evaluates that channel over
the protected v27, v26 challenge, and Phase 3 ontology suites; the frozen
semantic cohort; source-drift projects; and privacy canaries. The result uses
the additive `palimnex:semantic-shadow-evaluation:v1` contract. The cohort
digest, provider identity, R14 policy digest, promotion policy, and benchmark
protocol are bound into every report.

## Fixed promotion thresholds

A report is `promotable` only when every gate is true:

1. The comparison baseline is canonically identical to a direct
   `retrieve_sources(..., influence="off")` call.
2. No critical case and no individual case regresses.
3. Recall@5 does not decrease in any protected suite.
4. The frozen scored cohort gains at least 0.02 MRR or 0.02 Recall@5, allowing
   only a `1e-12` comparison tolerance.
5. At least one additional scored cohort case passes.
6. The semantic result introduces no forbidden hit that was absent from the
   baseline.
7. Per-case abstention and per-suite negative abstention do not regress.
8. Ambiguity does not lose an expected interpretation.
9. Drift changes the corpus fingerprint, invalidates content-keyed memo
   entries, returns only current content digests, avoids the old path, and does
   not turn a baseline pass into a semantic failure.
10. Query canaries are refused before provider input, corpus canaries are
    refused during source admission, and no canary appears in the report.
11. A fresh-memo rerun produces identical semantic comparison digests.
12. Provider identity remains stable and every comparison binds the same
    identity digest.
13. Paired semantic p95 latency is at most 1.5 times baseline p95 under R15.
14. Channel disclosure is visible and every result, count, rank, and byte
    budget remains bounded and schema-valid.

The report exposes `channels_visible` and `bounded` as separate machine gates.
Running with `benchmark=False` always holds the report and includes
`benchmark_not_run` in `held_reasons`.

## R15 benchmark protocol

R15 uses the local backend and the frozen semantic repository queries in file
order. One shared in-memory memo is warmed by one discarded pass over both
variants. Three measured repetitions then run the variants back to back:
baseline first in even repetitions and semantic first in odd repetitions. The
nearest-rank 95th percentile is the `ceil(0.95 * n)`-th sorted sample. Timing
values are excluded from the determinism comparison.

## Reading a held report

`held_reasons` is the sorted list of false gate names, plus
`benchmark_not_run` when timing was intentionally skipped. Inspect the matching
suite case rows and their baseline/shadow metric summaries; the report never
silently substitutes a fallback provider result. A provider error or privacy
refusal is a typed evaluation failure where the contract requires fail-closed
behavior.

`promotable` means only that the frozen evidence met the owner's fixed Phase 4
thresholds. It is not approval and cannot change production retrieval. Provider
promotion, configuration changes, Git operations, deployment, and any external
action require separate explicit authority.
