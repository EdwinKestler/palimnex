# Concept registry v1

Palimnex concept registries are bounded, source-backed JSON documents described
by `palimnex/schemas/concept-registry.v1.schema.json`. They add reviewed concept
identity and matching metadata without changing existing `project-memory:*`
formats, cache v3, ledger v1, pack v2, or retrieval results. The broader phased
design and its authority boundaries are in
[`ONTOLOGY_ADOPTION.md`](ONTOLOGY_ADOPTION.md).

## Identity and registry kinds

A registry uses the wire identifier `palimnex:concept-registry:v1`, version `1`,
and the effective `project_slug` and `project_id` of the checkout that reads it.
The schema validates their shape; a reader must also require exact equality with
the checkout identity. Cross-project input is refused before any concept is
used.

`registry_kind` keeps candidates separate from reviewed content:

- `candidate_set` contains only `candidate` and `withdrawn` records. It is not
  an approved read path and has no matching or retrieval influence.
- `approved_registry` contains only `approved`, `superseded`, and `withdrawn`
  records. Only `approved` records are eligible for matching.

Here, `approved` means that a committed registry entry passed repository review.
It is not a runtime badge and does not authorize Git changes, network or model
calls, deployment, migration, policy activation, erasure, pack activation, or
any other operation. Generated, imported, persisted, or model-produced entries
remain candidates until a separate reviewed repository change approves them.

The approved registry lives at `ontology/concept-registry.v1.json`. It is
committed, reviewed source, loaded directly by `palimnex explain-search`, and
never admitted to the ordinary source index, so the ontology's own labels never
count as independent source evidence. `--registry PATH` (repository-relative)
overrides the default. A missing default file means coverage is disabled; a
missing explicit path is an error. Generated or imported candidate sets belong
under `artifacts/ontology/candidates/`, outside both the approved read path and
the index; only a reviewed change can copy entries into the approved registry.
No configuration key loads a registry, and concepts have no retrieval influence.
See `docs/COVERAGE_RECEIPT.md`.

## Stable concepts and lifecycle

`concept_id` is a stable lowercase identifier of 3-128 code points. It begins
with an ASCII letter and may use `.`, `_`, or `-` only as single separators
between nonempty lowercase alphanumeric segments. It is not a display name and
has no required prefix. IDs are unique within one registry.

Canonical names are display strings. Renaming a canonical name or alias does
not rename the concept. The reviewed lifecycle is:

```text
candidate --> approved --> superseded
    |            |
    +------------+--> withdrawn
```

Superseded and withdrawn concepts remain historical evidence but do not match.
A successor names its `predecessor_concept_id`. The predecessor must be a
superseded concept in the same registry; self-links, forks, missing
predecessors, and cycles are invalid. Relation targets must also exist in the
same registry. Relations are explanatory only and do not transfer authority.

## Alias normalization and ambiguity

The following six-step procedure governs registry keys derived from canonical
names and stored aliases:

1. Unicode NFKC normalization.
2. Unicode default case folding.
3. Refusal of any code point in a Unicode `C*` category, including TAB, LF,
   and CR.
4. Replacement of Unicode punctuation (`P*`), separators (`Z*`), and
   whitespace with U+0020 SPACE.
5. Collapse repeated whitespace and trim both ends.
6. Refusal if the result is empty or exceeds 128 code points.

A stored alias must equal its normalized result byte-for-byte. A concept cannot
repeat a matching key through its canonical name and aliases. A matching key
may intentionally occur on more than one approved concept; readers retain all
matching concept IDs in deterministic order and report ambiguity. They do not
silently choose one concept or count an ambiguous concept as covered.

Query text is bounded at 8,192 UTF-8 bytes and privacy-scanned. Every
whitespace character (including TAB, LF, and CR) is then treated as U+0020
SPACE, and steps 1-5 apply, so any other control character in a query is
refused. The 128 code-point bound in step 6 applies only to stored keys; a
query that normalizes to nothing is refused. See coordinator clarifications
[R9](../artifacts/ontology/phase-1/integration/clarification-R9.md) and
[R11](../artifacts/ontology/phase-2/integration/clarification-R11.md).

## Source bindings, drift, and refusals

Each source binding is an existing `palimnex:source-locator:v1` object. A
malformed locator is refused while the registry is parsed with reason
`invalid_source_binding`. Before a valid binding supports a result, a reader
reopens the bound source (a repository-relative regular file for the `repo`
scheme), performs privacy admission, applies the bounded range, and verifies
both the current source version and selected-byte SHA-256 digest.

Ordinary source drift returns a verification result: the binding has reason
`source_drift`, and a concept with any such binding is stale. This category
includes a missing or unreadable source, an unavailable or incompatible
resolver, a resolver failure, a version mismatch, a malformed resolved result,
an invalid range, a selected-byte digest mismatch, or a change detected by the
second read. A stale concept is never silently treated as covered or replaced
with historical content.

Unsafe inputs are instead typed operation errors and produce no verification
result:

- malformed, absolute, or traversal repository paths are refused with
  `source_path_refused`;
- a repository root that cannot be resolved is refused with
  `source_root_refused`;
- a symlink in the repository source path is refused with
  `source_symlink_refused`;
- an external resolver that claims a different project is refused with
  `source_project_mismatch`; a registry bound to a different checkout is
  separately refused with `project_mismatch`; and
- admitted source bytes containing privacy findings are refused with
  `source_privacy_refused`.

Source bytes must pass privacy scanning before alias generation, extraction,
embedding, prompting, or any other derivation. Refusals and logs identify only
the field or rule and never echo matched values, source excerpts, credentials,
or provider responses.

## Canonical digest

`registry_digest` binds every other semantic field. To calculate it:

1. Decode one UTF-8 JSON object while rejecting duplicate keys and non-finite
   numbers.
2. Remove the top-level `registry_digest` member.
3. Serialize the remaining object with `palimnex.durable.canonical_json`:
   sorted keys, compact separators, Unicode preserved, and non-finite numbers
   refused.
4. Store the lowercase SHA-256 hexadecimal digest of those bytes.

Indentation does not affect the digest. A mismatch is corruption and must fail
visibly; it is not repaired in memory.

## Bounds

Readers reject encoded registry files larger than 1,000,000 bytes before JSON
decoding. The schema additionally limits:

| Item | Bound |
| --- | ---: |
| Concepts | 1-512 |
| Concept ID | 3-128 code points |
| Canonical name | 1-256 code points |
| Aliases per concept | 0-32 |
| Normalized alias | 1-128 code points |
| Definition | 1-4096 code points |
| Relations per concept | 0-32 |
| Source bindings per concept | 0-32; at least 1 when approved |
| Project slug | 1-128 code points |
| Project UUID | exactly 36 lowercase canonical characters |

Source-locator bounds are inherited unchanged from
`source-locator.v1.schema.json`.

## Compatibility and non-authority

The registry is additive and has `authority: historical_only` and
`authorizes_actions: false` in every mode. Its concepts, provenance, relations,
and source links support deterministic explanation only. Coverage does not
prove correctness, and historical or copied registry content never restores
operational authority.

Phase 1 does not persist ontology state in Redis or the durable ledger and does
not alter retrieval. Before a separately approved integration, rollback is
simply omitting the optional registry input. Any future reader-breaking change
requires a new schema identifier and version.
