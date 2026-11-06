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

The placeholder locator digest is deliberately not current source evidence.
Each consuming test replaces it with the digest produced by that test's local
fixture and keeps `digest_is_placeholder: true` only in this design artifact.

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

The checker validates required fields, unique IDs, status vocabulary, expected
set consistency, phase gates, category minimums, placeholder digests, and the
case/Unicode/whitespace normalization dimensions. It also scans every file
owned by this lane with `palimnex.security.scan_bytes`.

Secret cases store only fragment recipes. The checker verifies that no stored
fragment is credential-shaped, reconstructs each canary in memory, and proves
`palimnex.security.scan_text` detects it. It never prints the reconstructed
value. Exit status is zero only when structure, category coverage, canary
detection, and the owned-file privacy scan all pass.
