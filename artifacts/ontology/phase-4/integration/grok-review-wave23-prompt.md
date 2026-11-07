You are the INDEPENDENT, READ-ONLY reviewer for Palimnex ontology PHASE 4 (local semantic shadow experiment), waves 2-3,
under `.agents/skills/palimnex-ontology-review/SKILL.md` (read it first). You implemented none of it. Do not modify,
create or delete any repository file; scratch work under /tmp only (temporary checkouts are fine). No network, no Git
writes, no palimnex commands that write. Never read .env*, .palimnex/, secrets/, benchmark/. The coordinator may be
editing palimnex/core.py and integration docs in parallel; those are out of scope for this review.

Authority and contract:
- Approved design: docs/ONTOLOGY_ADOPTION.md ("Phase 4 — Optional local semantic experiment"; accepted-decision rows
  "Phase 4 provider" and "Phase 4 thresholds"). The owner's thresholds: no critical or per-case regression; Recall@5 not
  reduced on any protected suite; at least +0.02 MRR or Recall@5 on the frozen semantic cohort with at least one more
  passing cohort case; p95 <= 1.5x the paired baseline under a fixed benchmark protocol; no new forbidden hits;
  negative abstention, ambiguity, source-drift and privacy-canary gates; deterministic; provider identity bound;
  promotable is not promotion; held is valid and thresholds must never be weakened.
- Coordinator spec: artifacts/ontology/phase-4/briefs/SEMANTIC_SPEC.md v1.1 (sections 2 and 4, R14 and R15), COMMON.md
  and lane briefs. Cohort freeze: artifacts/ontology/phase-4/integration/cohort-freeze.json.
- Approval, manifest, tasks, digests: artifacts/ontology/phase-4/{approval-evidence.json,manifest.json,tasks/,
  integration/bundle-validation.json}; receipts in artifacts/ontology/phase-4/receipts/.

Under review (two workstreams):
1. ontology-phase-4-channel: palimnex/semantic_shadow.py, palimnex/tests/test_semantic_shadow.py,
   palimnex/schemas/semantic-shadow-comparison.v1.schema.json
2. ontology-phase-4-evaluation: palimnex/semantic_eval.py, palimnex/tests/test_semantic_eval.py,
   palimnex/schemas/semantic-shadow-evaluation.v1.schema.json, docs/SEMANTIC_SHADOW.md

For each: run its focused tests and the receipt validator:
  ./.venv/bin/python .agents/skills/palimnex-ontology-coordinator/scripts/validate_contract.py artifacts/ontology/phase-4/tasks/<ws>.json --implementation-receipt artifacts/ontology/phase-4/receipts/<ws>.implementation-receipt.json
Probe adversarially under /tmp (at least 3 per workstream). Priorities:
- PRODUCTION IDENTITY (any difference is a BLOCKER): palimnex/retrieval.py and palimnex/semantic.py unchanged (`git diff
  --stat`); semantic_shadow_retrieve's baseline equals retrieve_sources(influence="off") byte for byte on your own queries.
- R14 exactly as specified: cosine with ascending summation, strict > 0.0 floor, top 64 with (-similarity, pointer)
  ties, truncated flag, suppression when the baseline has no candidates (provider not called), query privacy scan before
  any provider call, fusion identical to _fuse_rankings with the semantic ranking appended, memo keyed by provider
  identity digest and content digest, bounded, in-process only, cleared when full. No fallback on provider errors.
- Comparison contract: field set, no chunk text, no query text, constant authority fields, validator rejects tampering.
- THRESHOLD FIDELITY (any weakening is a BLOCKER): PROMOTION_POLICY values and the gate definitions in section 4 are
  implemented exactly (tolerance 1e-12 only on the gain comparison; scored categories; protected suites; per-case
  forbidden subset; abstention per case and per suite; ambiguity found count; drift with the same memo; privacy with a
  recording provider and no canary in the serialized report; determinism with a fresh memo; identity before/after;
  latency 1.5x; benchmark_not_run when benchmark=False). status is promotable only if every gate is true.
  promotion_authorized, retrieval_influence and authorizes_actions are always false.
- COHORT PIN: COHORT_SHA256 equals cohort-freeze.json; a modified cohort is refused; the evaluator never edits labels.
- R15 benchmark protocol as specified (warm-up discarded, 3 repetitions, alternating order, nearest-rank p95,
  injected clock).
- Canaries built at runtime only; no secret-shaped literal in any owned file (security.scan_bytes).
- Optionally run the real evaluation read-only in a /tmp copy of the working tree (it is slow, several minutes) and
  report the status and held reasons; do not tune anything.

Output: concise summary, then ONE fenced ```json block containing a JSON ARRAY with exactly TWO review receipts matching
.agents/skills/palimnex-ontology-review/assets/review-receipt.v1.schema.json. Copy design_identity from the task card and
task_digest/approval_evidence_digest from bundle-validation.json. Prefix evidence with BLOCKER, MAJOR, MINOR or NOTE.
Status: rejected for any BLOCKER; accepted only if no MAJOR remains.
