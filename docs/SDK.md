# Python SDK and extension contracts

The 2.7.0 distribution introduces public Python API v1. `palimnex.api`,
`palimnex.locators`, `palimnex.adapters`, `palimnex.identity`, and
`palimnex.integrity` are supported extension surfaces. Other modules remain
implementation details. Breaking changes to these interfaces require a new
API major version; additive methods do not. Check `API_VERSION` and adapter
`api_version` before connecting an integration. Plugins are supplied explicitly;
Palimnex does not auto-import installed entry points or fetch plugins.

## Install and open

Build or install the checkout with Python 3.11 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[crypto,mcp,test]'
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

The base package has no third-party Python dependencies. `crypto` provides
encrypted transfer and Ed25519 identity; `mcp` provides the optional protocol
transport. `test` provides schema validation, type checking and build tools.
Redis server/CLI remain external prerequisites for source-cache integration.
SQLite uses Python's standard library. The distribution carries `py.typed`,
versioned JSON schemas, frozen evaluation resources and offline test helpers.

For the installed CLI, change into the target repository or set `PALIMNEX_ROOT`
before starting the process. `python -m palimnex` and `palimnex` are equivalent.
The copied `palimnex.py` wrapper preserves script-location rooting unless
`PALIMNEX_ROOT` explicitly overrides it.
The SDK always receives an explicit repository root; it never derives a target
from the installed package directory. A committed `.palimnex.json` containing
the project's UUID, slug and private ledger path is required.

```python
from pathlib import Path
from palimnex import Palimnex, Event, Evidence, RecallOptions
from palimnex.locators import repository_locator

root = Path('/path/to/repository')
client = Palimnex(root, writable=True)
client.initialize()  # explicit; opening a client creates no ledger
session = client.start_session('review storage behavior')
source = repository_locator(root, 'docs/DESIGN.md:1-20')
result = client.record(Event(
    session_id=session['session_id'], kind='fact',
    subject='storage behavior', payload={'observation': 'reviewed source'},
    evidence=(Evidence(source),), retention='durable',
))
client.close_session(session['session_id'], 'review complete')
reader = Palimnex(root)  # read-only SDK methods by default
history = reader.recall('storage behavior', RecallOptions(limit=5))
```

The stable request objects are typed dataclasses; results retain the existing
versioned dictionary envelopes. Defaults exclude restricted/secret results and
untrusted or stale history. SDK recall uses audit visibility, including session
records; `visibility='current'` selects durable current memory. Reading never
promotes trust or grants permission. Writes are synchronous and preserve the
ledger's transaction semantics. Exceptions remain `ValueError` for invalid
inputs/state and `PermissionError` for a read-only client. Cryptographic keys
are never included in result envelopes.

## Versioned source references

`SourceLocator` contains `scheme`, `source_id`, `version`, `range`, and `digest`.
The serialized prefix is `palimnex:source-locator:v1:` followed by canonical
JSON inside the existing evidence locator string column. No SQLite migration
is required. Existing path-and-line evidence continues to work. Older readers
cannot resolve the new prefix and treat those references as unavailable.

Ranges are inclusive one-based `lines` or half-open zero-based `bytes`.
`digest` is SHA-256 of the selected bytes. Repository versions are the SHA-256
of the complete file; line selections retain legacy newline normalization.
Readers verify both version and selected content every time. The resolver
returns at most one megabyte of UTF-8 source for privacy admission before
range selection. Resolvers must also bound their own I/O and timeouts.

Only `repo` is built in. Applications register a `SourceResolver` instance for
schemes such as `sqlite`, `document`, `https`, or `semantica`. A resolver returns
`ResolvedSource(content, version)` for the exact requested identity/version.
Registration is a trusted-code boundary: callers configure credentials, tenant
scope, network allowlists, redirects, query binding and timeouts. A URL in a
locator never triggers a network request by itself. Missing, incompatible,
changed or unavailable resolvers fail verification. Adapter errors are redacted.
Semantica is an extension target, not a bundled or live-validated integration.

Byte integrity is not factual truth or claim entailment. Existing extractive
capsule/claim quotation remains limited to admitted repository path locators;
external evidence is governed and recallable but is not automatically quoted
into capsules. Imported evidence stays untrusted until locally reverified.

## Derivative backends

`DerivativeAdapter` v1 defines `enumerate_derivatives`, `delete`,
`verify_absent`, `invalidate_projection`, and `produce_receipt`.
`AdapterRegistry` rejects duplicate identities, protocol mismatch and foreign
projects. Plans bind event IDs, object versions/digests, adapter/project scope,
and a five-minute expiry. Apply requires the displayed plan digest and an
application authorization callback, reevaluated before each deletion. That
callback must consult the application's current permissions, preservation
holds, dependencies, and retention rules. Supplying `True` without those checks
does not implement an authorization policy.

The SQLite reference adapter manages its own two namespaced tables using an
application-supplied connection. Use a separate private database and serialize
access. `initialize()` and `put()` are explicit writes. Deletes compare object
generation and content digest, invalidate its projection, and verify both
stores before a non-content receipt is returned. Changing objects or new
derivatives requires replanning. Failures propagate; earlier store deletions
remain effective. Idempotent retries handle already-absent objects and pending
projection invalidation. Persist operational plans privately for recovery.
Projection-only survivors remain discoverable when replanning after failure;
inconsistent generations or payload digests fail closed.

These receipts describe logical row/projection absence only. They do not claim
compaction, backup destruction, replica acknowledgement, or forensic erasure.
Adapters are trusted implementations whose receipt assertions require backend
specific acceptance tests. No distributed transaction is implied.

The independent coordinator does not bypass the existing retention ledger.
Registered packs and legacy attempted hot projections continue to block local
cleanup until a deletion-registry-aware integration is supplied. A generic
adapter receipt cannot be submitted to clear those blockers. The SDK's
`plan_erasure`, `authorize_erasure`, and `apply_erasure` retain the existing
local policy, hold, protected-anchor and digest-bound requirements.

## Signer identity and custody

`Ed25519Signer` supports raw private key files created exclusively with mode
0600 by `generate_signing_key`. Reuse the existing no-follow owner/file checks.
Use separate keys for signing, encryption and checkpoint commitments.
`Signer` v1 also allows an application-provided KMS/HSM implementation whose
`sign(message)` returns Ed25519 signatures and whose `public_key` is pinned.
No particular KMS provider is bundled or contacted.

`TrustedIdentity(name, public_key)` maps public-key fingerprints to identities
chosen by the receiver. Sender-supplied names/public keys never establish trust.
Removing a fingerprint from this map revokes its acceptance; key rotation
requires an operator-reviewed map change. There is no PKI, discovery or implied
organizational identity proof beyond that configured binding.

Pack v2 ciphertext bytes remain unchanged. An optional detached
`palimnex:signature:v1` attestation binds SHA-256 of the exact encrypted envelope,
the `encrypted-pack` domain and signer fingerprint. `export_pack(..., signer=)`
returns it as `signature`; retain it privately beside the pack. SDK import
requires a trusted signature by default; `require_signature=False` explicitly
permits legacy unsigned transfers. The legacy CLI keeps its v2 behavior.
Verification covers the same bytes passed to decryption. A valid signature
does not restore event verification, promotion or operating authority.

## Signed event-history checkpoints

`checkpoint(commitment_key=..., signer=..., previous=..., trusted=...)` takes a
consistent SQLite snapshot and builds a domain-separated Merkle tree over
ordered canonical events, including evidence. A second commitment covers the
complete typed ledger state (including trust/import and retention controls).
Leaves and ledger commitments use HMAC-SHA-256 so retained checkpoints do not
publish direct content digests usable for simple plaintext guessing.

Each signed checkpoint carries project/schema, sequence, predecessor hash,
event count/root, commitment-key identity and local timestamp. `verify_history`
checks signatures, ordering and continuity against a caller-supplied expected
tip. `verify_checkpoint` additionally compares the current ledger snapshot.
Keep the expected tip in an independently controlled location. Without that
external anchor, an attacker can replace the entire history with an older
valid prefix. A compromised signer can attest to false states. This is explicit
checkpointing, not automatic per-write authentication or an independent clock.
The first checkpoint is a baseline attestation, not retroactive provenance.

Checkpointing never changes the ledger schema or writes live state. Store
returned attestations in a private custody system; they retain counts, timing,
identifiers and keyed commitments. Authorized cleanup produces a new snapshot
root; a subsequent checkpoint links to the prior one without retaining erased
plaintext. Checkpoints, keys and receipts still need their own retention policy.
Retention-controlled ledgers remain incompatible with replacement imports.

## MCP

Install the `mcp` extra, then launch:

```bash
palimnex-mcp --root /path/to/repository
```

The official Python MCP SDK handles the stdio handshake and transport. No HTTP
listener is exposed. Tools are `recall` (current durable public/internal
memory), `plan_erasure` (inspection), and `verify_erasure` (local receipt check).
`--write-session SESSION_ID` adds `record_evidence` for that existing session
only. It accepts locators from the configured admitted repository corpus;
private/excluded files are refused. Clients cannot select another session or
install a resolver. Unknown/oversized arguments are rejected. There is no
erasure, migration, policy activation, signing-key or shell execution tool.

Hosts choose which repository/session to expose and manage process access.
Tool annotations help hosts present operations; enforcement comes from the SDK
write guard and narrow tool definitions. Protocol results remain untrusted
historical content. Integration tests exercise an actual stdio client handshake,
tool listing and invocation, plus read-only and session restrictions.

## Publication and release boundary

This checkout prepares version 2.7.0; building it does not publish it to PyPI.
The manual `publish.yml` workflow accepts an existing reviewed `v2.7.0` tag,
checks that the package and runtime versions match, reruns the gate, checks
types, builds wheel/sdist and tests the installed wheel outside the checkout.
Only the publish job receives an OIDC token. It does not create tags or releases.

Before first publication, the project owner must configure a PyPI pending
Trusted Publisher for project `palimnex`, GitHub owner `EdwinKestler`, repository
`palimnex`, workflow `publish.yml`, environment `pypi`. Configure that GitHub
environment with required reviewers before dispatching. No long-lived upload
token is needed. Review the release, authorize its tag, then manually dispatch
the selected version and approve the environment. Package-name availability is
not reserved by a local build. Until PyPI confirms publication, install from the
checkout or the locally built wheel; do not assume `pip install palimnex` works.

References: [Python packaging metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/)
and the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
