# Phase 0 frozen ontology cases

Status: **draft pending the Phase 0 exit gate**

`cases.v0.json` is the proposed common case matrix for ontology Phases 1-3. It
does not approve an implementation or retrieval influence.

## Freeze rule

At the Phase 0 exit gate, the owner records the exact SHA-256 digest of the
accepted bytes. After that point, case IDs, fixtures, queries, labels, disputed
markers, and expected concept sets in v0 do not change to make an implementation
candidate pass. A substantive correction requires a separately reviewed new
matrix version and preserves the old digest as historical evaluation evidence.

Every `registry_fixture` is a complete `palimnex:concept-registry:v1` document
that validates against the Phase 0 registry schema. Concept lifecycle uses
`status`; `source_bindings` contains direct, complete
`palimnex:source-locator:v1` objects; aliases are stored after the registry's
NFKC, casefold, punctuation-to-space, and whitespace-collapse normalization;
and `registry_digest` binds the canonical fixture content. Cases that need both
approved and candidate content use a separate complete
`candidate_registry_fixture`, preserving the registry's read-path separation.

The placeholder locator digest is deliberately not current source evidence.
Each consuming test replaces it with the digest produced by that test's local
fixture. A case with one or more placeholder values sets the single case-level
`binding_digests_are_placeholders: true` flag; locators are never wrapped or
reshaped to carry fixture metadata.

Expected classifications follow `R = C + U + S + A`: every case separately
lists covered, uncovered, stale, and ambiguous concept IDs. Ambiguity wins the
status decision while allowing other, disjoint concepts to remain covered.
`expected_outcome` distinguishes a typed operation `error` with no receipt from
a `receipt`; the provisional R7 split stays disputed pending the exit gate.

## Consumption by phase

- Phase 1 consumes cases with `gates_phase: 1` for registry validation, alias
  normalization, collisions, lifecycle non-influence, source admission, path
  safety, and project isolation.
- Phase 2 consumes all Phase 1 cases plus `gates_phase: 2` for deterministic
  coverage status, source verification, partial/negative results, truncation,
  byte-budget state, ordering, and bounded receipts.
- Phase 3 consumes all earlier cases plus `gates_phase: 3` to prove candidate
  and secret material have no ontology retrieval influence and that shadow
  output cannot alter the returned baseline ranking.

Tests may materialize repository files, digests, symlinks, resolver responses,
and canaries only in isolated temporary fixtures. They must not rewrite the
matrix or use live Redis, SQLite, provider, network, or repository state.
Disputed statuses remain explicit review gates; a test suite must not silently
choose one side.

## Offline check

From the repository root, run:

```bash
./.venv/bin/python artifacts/design/ontology-phase-0/frozen-cases/check_cases.py
```

The checker validates every registry fixture against the registry and
source-locator schemas through a local `referencing.Registry`, verifies each
canonical registry digest, rejects non-normalized stored aliases, enforces the
four disjoint expected collections and R7 outcome split, checks phase gates and
category minimums, and proves a digest-only locator fails schema validation. It
also checks the case/Unicode/whitespace normalization dimensions and scans every
file owned by this lane with `palimnex.security.scan_bytes`.

Secret cases store only fragment recipes. The checker verifies that no stored
fragment is credential-shaped, reconstructs each canary in memory, and proves
`palimnex.security.scan_text` detects it. It never prints the reconstructed
value. Exit status is zero only when structure, category coverage, canary
detection, and the owned-file privacy scan all pass.
