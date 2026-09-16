# Palimnex v2.5 runbook

Status: local repository-memory operations only. No command here starts a
chain, creates a wallet, installs WDK/MCP, or contacts a public network.

Run every command from the repository root. Do not paste secrets into event
payloads, task names, workflow files, evidence locators, Redis URLs, or shell
history. Pack operations additionally require the reviewed
distribution-provided `python3-cryptography` package; install and
probes ChaCha20-Poly1305 support.

## 1. Start and verify

```bash
./scripts/palimnex_redis.sh start
# Only with a preserved, fresh equal-corpus v2.4 baseline:
python3 palimnex.py migration-shadow --limit 5
# For a new cache, or after the shadow gate has passed:
python3 palimnex.py index --incremental
python3 palimnex.py validate --deep
python3 palimnex.py evaluate --limit 5
python3 palimnex.py ledger-init
python3 palimnex.py ledger-status
```

`migration-shadow` requires a fresh v2.4 index over the same current corpus.
It proves the v2 key set and bytes remain unchanged, fills all three retained
v3 generations, evaluates v3, and applies the hard total-size (`<=0.60x`) and
shipped `search()` p95 (`<=10.0x`) gates. The retired in-process hot scorer
used `<=1.20x`; that is not the current executable gate. This is migration
evidence, not the way to
initialize an empty new cache. A new checkout with committed `cache_mode: on`
uses `index --incremental`, then `validate --deep` and `evaluate`.

The cutover modes are explicit:

| `cache_mode` | Index behavior | Reads |
|---|---|---|
| `off` | v2 only | v2 |
| `shadow` | build v2 and v3 | v2; v3 is observation only |
| `on` | v3 | v3 |

An old configuration without this field defaults to `off`. Move
`off -> shadow -> on` only after the shadow command passes on a byte-stable,
equal-corpus v2 baseline. This repository's reviewed configuration is `on`.

The evaluation fixture is excluded from indexing and pinned by
`evaluation_fixture_sha256`. Do not update the fixture or its pin merely to
make a regression pass; review the intended case change separately.
Reported MRR is diagnostic. Do not treat a sub-1.0 MRR with complete recall as
a miss, and do not add overlapping winners to `expected_paths` solely to raise
MRR. See `docs/DESIGN.md` section 10 for this repository's `2.6.0-rc.1`
ranking interpretation.

Expected command exit meanings:

| Exit | Meaning |
|---:|---|
| `0` | command succeeded; cache is fresh; quality gate passed |
| `2` | cache is missing/stale, or a quality/promotion gate did not pass |
| `1` | operational, privacy, schema, integrity or input error |

Use `status --verbose` only for diagnosis. Normal `status` is intentionally
compact.

## 2. Start a session

```bash
python3 palimnex.py session-start --task "review local Palimnex gate"
```

Save the returned 32-character `session_id`. The durable SQLite commit occurs
before Redis projection. If `cache_consulted` is false and `projection.status`
is `pending`, the session is still durable.

## 3. Record important work

Use small, typed JSON payloads. A source evidence locator must point to current
repository lines.

```bash
python3 palimnex.py remember \
  --session SESSION_ID \
  --kind decision \
  --subject "project-memory:cache-policy" \
  --payload '{"decision":"Redis remains disposable"}' \
  --retention durable \
  --evidence docs/DESIGN.md:1-20
```

To record unresolved disagreement without hiding either account, keep the same
subject and use `--contradicts EVENT_ID`. Both records remain recallable;
`contradicts` does not make either one current or stale. Use `--supersedes` only
when the new record replaces the predecessor for current selection.

Allowed explicit kinds are `task`, `decision`, `failure`, `outcome`, `fact`,
`evidence`, `correction`, and `revocation`.

`remember` defaults to `retention=session`. All retention classes are written
to crash-safe local SQLite staging/audit, but only explicit `durable` events
can be promoted or exported. Local physical pruning of `volatile` and
`session` rows is not implemented in v2.5.

For a correction, keep the same subject and name the predecessor:

```bash
python3 palimnex.py remember \
  --session SESSION_ID \
  --kind correction \
  --subject "project-memory:cache-policy" \
  --payload '{"decision":"Redis is a derived projection"}' \
  --supersedes OLD_EVENT_ID \
  --retention durable \
  --evidence docs/DESIGN.md:1-20
```

Do not use `--trust observed` as a substitute for evidence. Verification is
derived separately from matching repository bytes.

Local writes always receive `observed_at` from the ledger clock. There is no
`remember --observed-at` option, and the local ledger API refuses a supplied
recorded time; callers control only `--valid-from`. Import alone may preserve a
foreign historical `observed_at`, but imported events remain quarantined and
untrusted. Verification attempts likewise use the actual check time, and the
ledger validates event, evidence, verification and attempt chronology.

## 4. Recall current or historical memory

```bash
python3 palimnex.py recall "Redis disposable projection" --limit 10
python3 palimnex.py recall "Redis disposable projection" --include-history
python3 palimnex.py recall "imported history" --include-untrusted
python3 palimnex.py recall "cache policy" --known-at UNIX_MILLISECONDS --valid-at UNIX_MILLISECONDS
python3 palimnex.py recall "cache policy" --promoted-only
```

Normal recall hides a superseded predecessor at the requested knowledge and
validity times. Contradicted records remain visible. Every result is historical
context, never live authority. It also abstains from claimed-untrusted and
imported events. Use `--include-untrusted` only for explicit historical
inspection. A successful `reverify EVENT_ID` against current local source can
restore that event to normal recall without granting action authority.

Current verification is recalculated from source. Changed, unavailable or
older-policy evidence makes `ledger-status` stale and removes the event from
normal recall/consolidation. `--include-history` retains stale observed events;
stale imported/untrusted events also require `--include-untrusted`.

## 5. Close and consolidate

```bash
python3 palimnex.py session-close SESSION_ID \
  --outcome "gate passed" \
  --evidence docs/PROVENANCE.md:1-20

python3 palimnex.py consolidate SESSION_ID
```

Only a closed session can be consolidated. Only active, locally verified,
evidence-backed decisions, failures, outcomes, workflows and facts with
`retention=durable` are promoted. A zero promotion count is valid when nothing
meets that policy.

If cited source lines changed, re-check one event explicitly:

```bash
python3 palimnex.py reverify EVENT_ID
```

Reverification never rewrites the old evidence digest. Success refreshes the
current verification. Drift returns `verified: false`, records an append-only
stale verification attempt, and invalidates the current verification and any
promotion while preserving the event and its history.

## 6. Retry the hot projection

```bash
python3 palimnex.py project-hot --limit 100
python3 palimnex.py ledger-status
```

Repeat until `projection_pending` is zero. This operation writes only derived
metadata to this project's bounded Redis hot namespace.

Read recent notification metadata through the SQLite-verified consumer:

```bash
python3 palimnex.py hot-events --limit 100
python3 palimnex.py hot-events --session SESSION_ID --limit 100
```

`hot-events` validates the complete bounded Redis batch and every field against
SQLite before filtering or limiting. It returns no payload. The
`latest-projected` pointer records delivery order only; it is not a fact-state
or authorization pointer, and there is no Redis `active` pointer.

If the complete disposable hot namespace was lost after events were marked
delivered, rebuild it deliberately:

```bash
python3 palimnex.py project-hot --rebuild --limit 1000
```

`--rebuild` mutates the SQLite outbox by resetting this project's delivered
flags, then force-replays every ledger-committed event's metadata in bounded
batches. That includes local `volatile` and `session` audit events; replay does
not promote or export them. It never projects payload bodies. Do not use it as
a routine retry when the normal response already says
`projection_pending: 0`.

## 7. Store and inspect a workflow

Create a JSON file matching
`palimnex/schemas/workflow-spec.v1.schema.json`. Example:

```json
{
  "version": 1,
  "description": "Recheck the local memory cache",
  "steps": [
    {
      "id": "status",
      "action": "python3 palimnex.py status",
      "preconditions": "Repository root is open",
      "expected": "Exit 0 and status fresh",
      "rollback": "No rollback; read-only command",
      "side_effect": "read"
    }
  ]
}
```

Keep the specification inside the repository. The CLI accepts only a bounded
regular non-symlink path opened with no-follow semantics.

Store it only with current source evidence:

```bash
python3 palimnex.py workflow-put SESSION_ID local-memory-check WORKFLOW.json \
  --evidence docs/RUNBOOK.md:1-20
python3 palimnex.py workflow-dry-run WORKFLOW_ID
```

The dry run lists steps and always reports `will_execute: false`. There is no
execute command. Obtain current authorization independently before performing
any remembered action.

## 8. Generate a key and export a cross-machine pack

Generate one new raw key in an ignored, private directory. The command creates
the file exclusively at mode `0600` and prints only its path, format and key
identifier, never its 32 bytes:

```bash
python3 palimnex.py memory-keygen \
  .palimnex/project-memory/transfer-2026-09.key
python3 palimnex.py ledger-status
python3 palimnex.py memory-export \
  /secure/new/location/project-memory.pmem \
  --key-file .palimnex/project-memory/transfer-2026-09.key
```

`PALIMNEX_PACK_KEY_FILE` may supply only the key-file path. Never put key
bytes in `.env`, command output, configuration, Git, a memory event or a pack.
The key and pack are both private owner-controlled, one-link regular files;
every path component is opened without following symlinks.

The pack selection is `retention-durable-closed-sessions:v1`. It contains only
closed sessions with an explicit durable non-anchor event, their durable
start/close anchors, and selected workflows. Per-session sequences are
compacted. Volatile/session events never enter a pack; orphaned relations and
an empty selection are refused.

Every selected event includes its authenticated, sorted, unique, bounded term
digests. Import validates them and restores those exact derived terms so a
subject-only query has the same explicit historical result after transfer.

The target must not already exist. Pack v2 encrypts and authenticates with
ChaCha20-Poly1305, permits selected `restricted` events, and still refuses any
selected `secret` event. It rescans all selected variable content against the
current privacy policy before encryption. The outer manifest exposes no
plaintext-content size or digest.

Shared-key authentication proves integrity and key possession, not which
person or machine sent the pack. Transfer the pack and key through separate
protected channels, back up the key separately, and apply a deletion policy at
both ends. Losing the key makes the pack unrecoverable. Rotate by generating a
new key and exporting a new pack; there is no in-place rekey operation.

## 9. Validate or activate an imported pack

Validation is the safe default:

```bash
python3 palimnex.py memory-import /secure/location/project-memory.pmem \
  --key-file /secure/separate/location/transfer-2026-09.key
```

Expected status is `validated_quarantined`, with `activated: false`,
`authenticated: true`, `authority: historical_only`, and
`authorizes_actions: false`. Authentication does not establish source truth or
sender identity.

Activation replaces local memory and therefore requires both flags:

```bash
python3 palimnex.py memory-import /secure/location/project-memory.pmem \
  --key-file /secure/separate/location/transfer-2026-09.key \
  --activate --replace
```

The old SQLite database is retained beside the live ledger as a uniquely named
pre-import backup. Imported promotions and verifications are discarded. Review
imported history with `recall --include-untrusted`, then locally reverify
matching source evidence before normal recall or consolidation.

If a process stopped during activation:

```bash
python3 palimnex.py memory-recover-import
python3 palimnex.py ledger-status
```

Recovery follows the fsynced import intent and selects the live, candidate, or
backup database without guessing paths outside the ledger directory.

## 10. Redis outage

Do not retry the durable write blindly. Read the command response first. If it
contains a session or event ID and only the projection is pending, the write
committed.

```bash
./scripts/palimnex_redis.sh start
python3 palimnex.py project-hot --limit 1000
python3 palimnex.py ledger-status
```

Source discovery requires Redis. Durable `recall`, ledger status and session
history do not.

## 11. Clear only the disposable v3 cache

```bash
python3 palimnex.py clear
python3 palimnex.py ledger-status
```

The response must say both `durable_ledger_touched: false` and
`legacy_namespace_touched: false`. Rebuild v3 with:

```bash
python3 palimnex.py index --incremental
python3 palimnex.py validate --deep
```

Never use `FLUSHDB`, `FLUSHALL`, wildcard key deletion, or another project's
namespace.

The preserved legacy v2 namespace still contains full source chunks and
plaintext lexical-token lists. `clear` is intentionally v3-only and cannot be
represented as deleting that legacy sensitive data. Retire v2 only through a
separately reviewed operation, or accept that the lower-level local Redis reset
removes every namespace in its RDB and then rebuild the needed v3 projections.

To discard the complete persisted projection of the repository-managed local
Redis instance, use the lower-level launcher only after accepting that every
cache namespace in its RDB must be rebuilt:

```bash
./scripts/palimnex_redis.sh reset
./scripts/palimnex_redis.sh start
python3 palimnex.py index --incremental
python3 palimnex.py project-hot --rebuild --limit 1000
python3 palimnex.py validate --deep
```

`reset` stops only a Redis process verified as owned by this launcher. It
removes the Redis log, RDB dump and temporary RDB projection files, not the
state directory. It preserves the SQLite ledger, WAL, lock, import intent,
backups and `.pmem` packs. Unlike `palimnex.py clear`, it is not a
namespace-selective operation, so do not use it when a legacy-v2 cache that
exists only in the local RDB must be retained.

## 12. Semantic provider status

```bash
python3 palimnex.py semantic-status
```

The bundled result must remain disabled: no provider, external network, HNSW,
or retrieval influence. `semantic-gate BASELINE.json CANDIDATE.json` evaluates
metrics only. Both files must be bounded regular non-symlink paths inside the
repository and are opened with no-follow semantics. A passing metrics file does
not install or enable a provider.

## 13. Gate

```bash
./scripts/palimnex_check.sh
```

The memory gate uses temporary files and an isolated local Redis process or
test double. It must not alter the live ledger or configured cache namespaces.

## 14. Code rollback without memory loss

1. Stop creating session events.
2. Run `ledger-status`.
3. Generate/back up a separate key and export an encrypted pack when its
   `restricted` sensitivity ceiling permits it; a selected `secret` event
   still blocks export.
4. Keep the SQLite database, WAL, lock, import intent and backups in place.
5. Create a separate filesystem copy and rehearse the selected Git revert or
   source replacement there before touching the working repository.
6. Never downgrade code across an irreversible retention migration unless the
   older reader is proven to preserve deletion suppression and tombstones.

Code rollback is a Git operation and is intentionally not bundled into the
runtime CLI. It must not delete or rewrite Redis, SQLite, packs, keys, or the
ignored state directory. Keep the ledger quarantined if the selected code
version cannot safely read its schema.
