# Draft concept-registry v1 semantics

Status: **Phase 0 draft awaiting the owner exit gate.** This document and its
examples do not approve a registry, grant retrieval influence, or authorize an
external action.

## Contract and identity

`concept-registry.v1.schema.json` drafts
`palimnex:concept-registry:v1` as a separate, additive document. It does not
change `project-memory:context:v1`, cache v3, ledger v1, pack v2, or any other
existing wire format. The registry has `authority: historical_only` and
`authorizes_actions: false` in every mode.

`project.project_slug` and `project.project_id` must exactly equal the effective
values from the checkout's committed `.palimnex.json`. The schema checks the
shape; the loader performs the equality check. Current UUID parsing is grounded
in `palimnex/cache_v3.py::project_id`, and current slug normalization is grounded
in `palimnex/core.py::project_slug`. A mismatch is cross-project input and fails
before any concept is used.

The registry schema is the single Phase 0 source of truth for the shared
definitions `$defs.conceptId`, `$defs.alias`, and `$defs.projectIdentity`.
Other contracts reference those definitions through the registry schema's
absolute `$id`; they do not copy or broaden the patterns or bounds. In
particular, `$defs.alias` is the only stored-alias definition and
`$defs.projectIdentity` is the only project-identity definition.

`registry_version` is the contract version and is exactly `1`. A reader-breaking
change requires a new schema identifier and version. `registry_kind` is an
explicit separation control:

- `candidate_set` accepts only `candidate` and `withdrawn` entries, lives
  outside the approved registry read path, and has no matching or retrieval
  influence.
- `approved_registry` accepts only `approved`, `superseded`, and `withdrawn`
  entries. Only its `approved` entries are eligible for exact matching.

The committed location of the approved read path remains an owner decision.
Until that path is approved, every file here is an unapproved example.

## Bounds

The loader checks the encoded UTF-8 file before JSON decoding and rejects a
registry larger than 1,000,000 bytes. The schema additionally bounds each
collection and scalar:

| Item | Bound |
| --- | --- |
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

Source-locator string and integer bounds are inherited without modification
from `palimnex/schemas/source-locator.v1.schema.json`.

## Stable identities and lifecycle

A `concept_id` is a stable lowercase identifier, not a display name. It is
3-128 code points, starts with a lowercase ASCII letter, and uses `.`, `_`, or
`-` only as single separators between nonempty lowercase alphanumeric
segments. No prefix is required. Renaming a canonical name or alias does not
change it. IDs are unique in a registry.

Allowed reviewed transitions are:

```text
candidate --> approved --> superseded
    |            |
    +------------+--> withdrawn
```

`candidate` to `approved` is not a field toggle performed by a tool. It requires
a reviewed repository change that moves or rewrites the entry into the approved
read path. The review preserves `provenance.origin`; therefore a
`model_candidate` can become approved only through that repository change, not
because a model, generator, persistence layer, or agent marked it so. In this
contract, "approved" means only that the committed registry entry passed that
review. It never means an operation, provider call, Git write, deployment, or
other action is authorized.

`withdrawn` and `superseded` are terminal for matching. Their definitions,
relations, and source bindings remain historical evidence in the reviewed
file, but loaders exclude them from match indexes and coverage. A later concept
uses `predecessor_concept_id` to identify the concept it replaces. A valid
supersession update atomically marks the predecessor `superseded` and adds an
`approved` successor. A successor may later become superseded, so intermediate
members can have both `status: superseded` and a predecessor.

The loader requires each predecessor to exist in the same registry, forbids
self-links and forks, requires the predecessor to be `superseded`, permits the
successor to be `approved` or `superseded`, and rejects cycles. Relations use a
small closed vocabulary: `broader_than`, `narrower_than`, `related_to`, and
`depends_on`. Every relation target must be an ID in the same registry. These
relations support retrieval explanation only; they do not inherit authority
from the target.

## Deterministic alias normalization and ambiguity

Canonical names are display strings. Matching keys are derived from each
canonical name and from the stored aliases by this exact procedure:

1. Apply Unicode NFKC normalization.
2. Apply Unicode default `casefold`.
3. Reject any resulting code point whose Unicode general category begins with
   `C` (control, format, surrogate, private-use, or unassigned).
4. Replace every Unicode punctuation (`P*`), Unicode separator (`Z*`), and
   whitespace code point with U+0020 SPACE.
5. Collapse consecutive whitespace to one U+0020 and trim both ends.
6. Reject an empty result or one longer than 128 code points.

Aliases are stored in that normalized form and must equal the procedure's
output byte-for-byte. A canonical name need not be stored normalized; its
derived matching key follows the same steps. Within one concept, duplicate
matching keys are rejected, including an alias that merely repeats the
canonical-name key.

Across concepts, a normalized key may intentionally identify more than one
approved concept. The loader reports that collision as a validation diagnostic
but does **not** reject the registry. Its index retains every matching concept
ID in sorted order. A query with that exact key is `ambiguous`, lists all
candidate IDs, and counts none as covered. This choice preserves intentional
polysemy while failing closed; silently choosing one ID would create false
confidence. Candidate, superseded, and withdrawn concepts never participate in
the ambiguity set.

This contract defines concept recognition only. The separate coverage-receipt
lane defines how ambiguity appears in `palimnex:retrieval-coverage:v1`.

## Source bindings and drift

Every binding is the existing `palimnex:source-locator:v1` shape, referenced by
its `$id`; this draft does not define a second locator. The loader constructs
`palimnex/locators.py::SourceLocator` and calls
`palimnex/locators.py::resolve_locator` on every binding before it can support a
match or coverage result.

A frozen coverage case embeds a complete
`palimnex:concept-registry:v1` document and validates it against this schema;
it does not use a reduced or renamed registry shape. A frozen case that models
source drift may use the fixture suite's declared placeholder locator digest
only when the case itself sets `binding_digests_are_placeholders: true`. The
placeholder replaces only the locator's `digest` value; the source locator is
never wrapped or reshaped. Placeholder binding digests are fixture metadata,
are never valid in a committed registry, and must not be accepted by the
registry loader.

For a repository locator, `RepositoryResolver` reopens a normalized
repository-relative regular file without following symlinks. `select_range`
applies the bounded range only after privacy admission. `resolve_locator`
checks resolver version, current source version, and the SHA-256 digest of the
selected bytes; failures are collapsed to a non-echoing unavailable or
version/digest-mismatch error. A missing, excluded, unreadable, changed, or
digest-mismatched binding is drifted. If any binding needed for a concept is
drifted, that concept is stale and is never reported as covered. It is not
silently treated as an uncovered query or replaced with historical content.

## Canonical registry digest

To calculate `registry_digest`:

1. Parse one UTF-8 JSON object while rejecting duplicate keys and non-finite
   numbers.
2. Remove the top-level `registry_digest` member.
3. Serialize the remaining object with
   `palimnex/durable.py::canonical_json`: keys sorted, `,` and `:` separators,
   Unicode preserved, and NaN/Infinity refused.
4. Store the lowercase SHA-256 hex digest of those bytes.

The digest is independent of source-file indentation but binds every semantic
field. A mismatch is corruption and fails visibly. It is not repaired in
memory.

## Privacy and non-authority

Raw source bytes must pass `palimnex/security.py::scan_bytes` before alias,
definition, relation, embedding, prompt, or other derivative generation. This
ordering is already enforced for locator ranges by
`palimnex/locators.py::select_range`; future candidate generators must preserve
it before deriving anything. Findings expose only rule identifiers and line
numbers. Refusals and logs never contain matched values, source excerpts,
provider responses, or credentials.

No registry mode authorizes network access, model calls, Git changes, cache or
ledger mutation, migration, retention, erasure, pack activation, policy
activation, publication, or deployment. Generated or imported entries remain
candidates until a separate reviewed repository change.

## Rollback and compatibility

Before any separately approved retrieval integration, rollback is deletion or
disabling of the optional registry input; existing retrieval behavior is
unchanged. No persistent Redis projection or durable-ledger state is proposed
in v1. If a later phase introduces a disposable projection, the committed
registry remains its rebuildable source and the projection is never its only
copy.

## Open questions for the owner exit gate

1. Confirm `registry_kind` and the candidate/approved path separation mechanism.
2. Choose the committed approved-registry location and whether it is indexed.
3. Confirm the 1,000,000-byte, 512-concept, and per-field bounds.
4. Confirm NFKC plus casefold and punctuation-to-space normalization.
5. Confirm that cross-concept alias collisions are reported and retained as
   ambiguity instead of making the whole registry invalid.
6. Confirm the four relation types and the no-fork supersession rule.
7. Choose the future implementation module name (`concepts.py` is the Phase 0
   working default; `ontology.py` remains an alternative).
