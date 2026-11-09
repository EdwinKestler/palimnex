# Palimnex 2.10.1 release-candidate report

Date: 2026-11-08 (America/Guatemala)

## Candidate

- Source commit: `0d01565` (`Fix large-corpus Redis indexing`)
- Pull request: <https://github.com/EdwinKestler/palimnex/pull/27>
- CI run: <https://github.com/EdwinKestler/palimnex/actions/runs/42560592169>
- Version: `2.10.1`
- Release status at this report: candidate only; no tag, PyPI publication, or
  GitHub release yet

## Outcome

The candidate fixes cache-v3 indexing for large admitted repositories. Chunk,
graph, and posting writes are split by exact RESP request bytes; ordinary
groups target at most 4 MiB, while one indivisible atomic request has a 32 MiB
hard limit. Complete registry entries use their validated manifests for owned
keys, and retries remove abandoned staging generations before creating a new
one.

No public API, ledger schema, encrypted-pack format, cache-v3 identifier,
retrieval scoring, or ontology behavior changes. Ontology influence remains
off and `.palimnex.json` is unchanged.

## Validation

| Check | Result |
| --- | --- |
| Standard gate | 556 tests passed, 1 expected skip; challenge and longitudinal offline gates passed; isolated Redis retrieval 20/20 with Recall@5 1.0 |
| Strict typing | Clean across 22 configured source files |
| Frozen retrieval | Recall@5 1.0, MRR 0.8916666666666666, every critical case passed, forbidden paths clear |
| CI matrix | Python 3.11–3.14 on Ubuntu and Python 3.11 on macOS passed |
| Upgrade rehearsal | 2.10.0 to 2.10.1 passed |
| Package checks | Wheel and sdist passed `twine check --strict`; installed core and crypto smokes passed; removed `--no-snapshot` option exits 2 |
| Wheel contents | 80 members, no tests; two clean builds had identical member names and payload bytes, with archive metadata differences only |
| Approved registry | All source bindings current after maintenance-only re-pin; no concept or alias changed |

## Large-corpus acceptance

The installed candidate wheel, without monkeypatches or setting changes,
rebuilt `/media/kestl/andor/github/rgbhackathon` from its 2.10.0 cache and then
passed deep validation:

- files: 2,828
- chunks: 12,759
- posting terms: 77,311
- graph symbols: 66,398
- graph edges: 217,422
- index time: 37,392 ms

The test wrote only that repository's disposable Palimnex Redis namespace. It
did not write its ledger or tracked files.

## State and boundaries

- Palimnex ledger: integrity OK, zero events; no durable write or migration
- Palimnex cache: consulted and rebuilt during validation
- Optional ontology, semantic, feedback-shadow, and graph-explorer work: not
  activated or implemented by this patch
- Publication remains the controlled merge, annotated tag, `publish.yml`,
  PyPI verification, and GitHub-release transaction described in
  `docs/RELEASING.md`
