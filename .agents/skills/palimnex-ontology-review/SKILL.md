---
name: palimnex-ontology-review
description: >-
  Independently review Palimnex ontology-adoption changes for source grounding,
  retrieval quality, privacy, compatibility, provenance, rollback, and authority
  boundaries. Use for adversarial workstream or integration validation; default
  to read-only and do not repair unless separately requested.
---

# Palimnex ontology review

Load the base `palimnex` skill first. Prefer a fresh reviewer agent that did not
implement the work. Review current source and the actual diff rather than relying
on an implementation summary, cache result, or child-agent receipt.

Require the approved design identity, approval evidence, implementation task
card, repository state, actual diff, and acceptance criteria. Missing or
inconsistent authority evidence is a review blocker.

## Review

Verify the assigned acceptance criteria and at least:

- stable concept identity and current source bindings;
- explicit covered, uncovered, ambiguous, truncated, and omitted behavior;
- candidate/approved separation and no automatic trust or promotion;
- secret admission before derivation and refusal without value echo;
- deterministic, network-free, provider-disabled default behavior;
- provider model, revision, dimensions, artifact digest, and local/remote
  disclosure for experiments;
- no critical frozen-evaluation or negative-abstention regression;
- exact schema/reader compatibility and a credible rollback path;
- no change to current-source, historical-only, or action-authority boundaries;
- disjoint workstream ownership and reviewed shared-file integration; and
- reproducible tests rather than self-reported success.

Coverage is not correctness. A nonempty result, passing model judgment, or
promotable metric is insufficient when source grounding, ambiguity, privacy,
compatibility, or rollback is unresolved.

## Behavior

- Remain read-only unless the user separately requests a repair and assigns a
  new non-review workstream.
- Run focused tests and, for material integration, the isolated standard gate.
- Do not edit frozen labels merely to make the candidate pass.
- Do not authorize integration, commit, push, provider calls, publication,
  migration, retention, erasure, or deployment.
- Return `accepted`, `accepted_with_limits`, `rejected`, or `blocked` using
  [the runtime contract](assets/runtime-contract.yaml) and
  [the review-receipt schema](assets/review-receipt.v1.schema.json).

## Handoff

Identify exact evidence, commands, failures, severity, affected paths,
compatibility/rollback implications, cache/ledger state, and Git state. Separate
confirmed defects from open questions and environment limitations.
