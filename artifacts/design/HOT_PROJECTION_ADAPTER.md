# Retention-aware Redis hot-projection adapter

Status: proposal awaiting owner decision; not indexed (see AGENTS.md).

No behavior in this document is implemented or authorized. In particular,
this proposal does not authorize a live retention migration, Redis mutation,
projection retirement, erasure, policy activation, or control-chain write.

## Decision requested

Add a bundled, explicitly registered `RedisHotProjectionAdapter` that restores
the metadata-only hot view for a retention ledger while keeping erasure fail
closed. Projection and reads reuse the existing durable implementation and its
exact 4,096-entry stream cap. Retirement is a separate, digest-bound,
explicitly authorized adapter operation. It may remove only the reviewed keys
for this project's derived hot namespace, verifies absence, and then appends a
sanitized `hot_projection_receipt` to the retention control chain.

This is deliberately not a general Redis deletion API. The implementing PR
must obtain the owner's explicit sign-off for the namespaced removal operation.
`FLUSHDB`, `FLUSHALL`, key-pattern scans, wildcard deletion, caller-supplied raw
keys, and mutation of the discovery-cache namespace remain forbidden.

## Current state

### Durable hot projection before migration

The base namespace is derived from the configured project slug and UUID as
`<slug>:<uuid>:project-memory:hot:v1` (`palimnex/cache_v3.py:100-107`). The
ledger adds its persisted `hot_projection_epoch`, producing an effective
namespace ending in `:epoch:<32 hex>` (`palimnex/durable.py:2577-2601`). This
prevents two ledger instances from silently sharing the same projection.

Every event transaction also inserts a unique `projection_outbox` row. Its
`attempted_at` and `delivered_at` fields distinguish an untried event, a
possibly partial/crashed delivery, and an acknowledged delivery
(`palimnex/durable.py:285-292`). Projection:

- requires a trusted Redis write endpoint;
- holds the exclusive ledger lock across attempt recording, Redis mutation,
  and the SQLite acknowledgement;
- writes metadata only, never the event payload;
- uses `XADD MAXLEN = 4096`, so the stream cap is exact;
- maintains an event receipt plus `latest-projected`, `superseded-by`, and
  `contradicted-by` pointers, all with a 30-day expiry; and
- is idempotent across retry by checking the event receipt and bounded stream
  before appending (`palimnex/durable.py:2618-2795`).

`hot_events` reads at most 4,096 stream records, validates every field and
event identity against authoritative SQLite, and only then filters by session
or result limit. It returns no payload and labels SQLite as payload authority
(`palimnex/durable.py:2797-2953`).

### Retention behavior and the unresolved cycle

After migration, `RetentionLedger.project_outbox` raises `adapter required`
and `RetentionLedger.hot_events` refuses the legacy projection
(`palimnex/retention.py:606-610`). Consequently every new durable write commits
but reports its projection pending.

An attempted pre-migration projection is detected solely by
`projection_outbox.attempted_at IS NOT NULL`. Such an event is excluded from
cleanup as `store_not_adapted` (`palimnex/retention.py:420-435`). There is no
current control state that resolves that exclusion.

The public derivative protocol already supplies `enumerate_derivatives`,
`delete`, `invalidate_projection`, `verify_absent`, and `produce_receipt`.
Plans bind project, adapter, event IDs, versions, digests, expiry, and a
confirmation digest; apply rechecks current inventory and application
authorization before each deletion (`palimnex/adapters.py:20-147`). It is the
right protocol to reuse.

The existing retention `adapter_receipt` is not the right control record for
this particular ordering problem. Its semantic validation requires a local
cleanup plan that has already been applied (`palimnex/retention.py:166-187`),
but `store_not_adapted` prevents that local apply. A separate pre-erasure
retirement receipt is needed.

## Goals and non-goals

The adapter must:

1. restore the same metadata-only `project-hot` and `hot-events` behavior for
   `project-memory:retention-ledger:v2`;
2. retain the exact 4,096-entry stream cap and current SQLite verification;
3. cover projections attempted before migration, including partial attempts;
4. make retirement explicit, project-scoped, digest-bound, verified, and
   idempotent;
5. resolve `store_not_adapted` only after a valid control-chain receipt covers
   that event and namespace epoch; and
6. ensure a retired event can never be reprojected by normal retry or rebuild.

It must not:

- weaken holds, session pins, durable/imported authorization, dependency
  closure, pack blockers, or any other cleanup exclusion;
- expose payloads or make Redis authoritative;
- erase source-discovery cache data, another project's data, backups,
  snapshots, packs, replicas, or exported copies;
- treat Redis unavailability as verified absence;
- claim physical or forensic erasure; or
- make retirement automatic during migration or cleanup.

## Adapter shape

### Registration and capabilities

Implement `RedisHotProjectionAdapter` as a `DerivativeAdapter` v1 with:

```text
api_version = 1
adapter_id = "redis-hot-v1"
project_id = <configured project UUID>
```

Registration uses `AdapterRegistry`; duplicate adapters, API mismatches, and
foreign projects keep the current refusals. The class also exposes an additive
hot-projection capability used internally by the CLI:

```text
project_pending(limit, force=False) -> projection report
read_hot(session_id=None, limit=100) -> verified metadata report
```

This does not change `DerivativeAdapter` v1. The extra capability can be a
separate runtime-checkable `HotProjectionAdapter` protocol or private methods
on the bundled adapter. External derivative adapters remain source-compatible.

`RetentionLedger.project_outbox` and `hot_events` should require this explicit
adapter and delegate to the existing `MemoryLedger` algorithms rather than
forking their Lua, validation, or response formats. The CLI constructs the
bundled adapter only after the normal configuration and trusted-endpoint
checks. With no adapter or unavailable Redis, the current fail-closed error and
pending status remain.

### Projection invariants

Projection keeps the existing effective namespace, key grammar, 30-day TTL,
metadata fields, exact `XADD MAXLEN = 4096`, exclusive ledger lock, durable
attempt-before-Redis ordering, and SQLite acknowledgement-after-Redis ordering.
`hot_events` keeps its whole-stream validation against SQLite before filtering.

The adapter must consult retirement controls before projecting. An event
covered by a valid `hot_projection_receipt` for the current effective namespace
is permanently suppressed, including during `project-hot --rebuild`. Rebuild
may reset delivery state only for non-retired events. Status should report
pending projectable rows separately from retired/suppressed rows so a valid
retirement does not create a permanent false `projection_pending` count.

This requires defining whether the outbox row gains a derived retired state or
whether status joins against the control-chain view. The latter avoids changing
the SQLite table but may cost more; either implementation must keep the logical
digest deterministic and semantic validation exact.

## Inventory and plan

For each requested event, inventory is anchored in the SQLite event and outbox
row, not in Redis alone. A planned `Derivative` uses:

- `object_id`: the 32-hex event ID;
- `version`: the persisted hot-projection epoch;
- `digest`: SHA-256 of a canonical, domain-separated description containing
  the project UUID, effective-namespace digest, event ID, durable record
  digest, subject digest, relation IDs, and the projection key grammar.

The raw namespace is operational input but the persisted plan/receipt contains
only its SHA-256 digest. Inventory includes any outbox row with non-null
`attempted_at`, whether or not `delivered_at` is set. This is essential for a
crash after SQLite records the attempt but before Redis acknowledges it.

The operator flow is separate from cleanup:

```text
hot-projection-retire --plan --event EVENT_ID...
hot-projection-retire --apply PRIVATE_PLAN_JSON \
  --confirm-digest PLAN_DIGEST --actor ACTOR --reason REASON
cleanup-plan --event EVENT_ID...
cleanup-apply ...
```

Names are illustrative. The implementing change should expose the equivalent
SDK operation and may choose a different CLI spelling. Planning is read-only;
apply requires the displayed digest and an authorization callback that checks
the current ledger digest, policy, holds, dependencies, event authorization,
adapter identity, project, namespace epoch, and plan expiry. A generic `True`
callback is insufficient.

## Reviewed, namespaced retirement operation

### Permitted Redis scope

The recommended immediate-retirement design uses one bounded Lua operation per
event. Code derives every key internally from the configured project identity,
the ledger's persisted epoch, and authoritative SQLite metadata. It accepts no
raw key and performs no `SCAN`, `KEYS`, wildcard, database-wide, or
cross-namespace operation.

Only these keys may be touched:

```text
<effective>:events
<effective>:event:<event-id>
<effective>:latest-projected:<subject-digest>
<effective>:superseded-by:<predecessor-id-or-none>
<effective>:contradicted-by:<opposed-id-or-none>
```

For the stream, the script first validates the event receipt and exact record,
or performs the same bounded 4,096-entry recovery scan used by projection. It
then `XDEL`s only the matching stream ID. It removes the event receipt only if
its stored stream ID and record digest match. Each pointer is removed only if
its current value equals the target event ID. A pointer that has advanced to a
different event is preserved. Missing keys are an idempotent success candidate,
not proof by themselves.

Although these commands remove entries, this is not "raw Redis-key deletion":
it is a proposed reviewed adapter operation over a closed, project-derived key
set with compare-before-remove and post-operation verification. It still needs
the owner's explicit approval in the implementing session. No implementation
should land under the present authority.

### Verification

After mutation and while still holding the exclusive ledger lock, verification
must establish all of the following from a fresh Redis read:

- no record in the complete bounded stream has the target event ID;
- the event receipt key is absent;
- none of the three derivable pointers has the target event ID as its value;
- no unexpected or malformed matching record was observed; and
- the effective namespace and durable record digest still equal the plan.

Redis errors, an untrusted endpoint, a changed namespace/record, malformed
state, multiple matching stream records, or incomplete verification all fail.
No receipt is written and `store_not_adapted` remains.

### Remove-nothing alternative

An alternative is to create a new hot namespace epoch and rebuild only
non-retired events there. It avoids deleting Redis entries, and is appropriate
for restoring service after namespace corruption. It does **not** immediately
prove erasure of the old epoch: old metadata can remain until its TTL expires.
Therefore it cannot resolve `store_not_adapted` until the adapter later verifies
that every old-epoch key and stream record for the event is absent. If Redis
state was copied or persistence retains another instance, that copy stays out
of scope and must be reported.

Recommendation: implement the reviewed namespaced operation for immediate
retirement and retain epoch rollover as a recovery/rebuild tool, not as a
substitute for verified absence.

## Sanitized control-chain receipt

Add the versioned control kind `hot_projection_receipt` with payload schema
`project-memory:hot-projection-receipt:v1`. The payload contains only:

```json
{
  "schema": "project-memory:hot-projection-receipt:v1",
  "adapter_id": "redis-hot-v1",
  "project_id": "<uuid>",
  "plan_digest": "<sha256>",
  "ledger_digest_before": "<sha256>",
  "namespace_digest": "<sha256>",
  "epoch": "<32 hex>",
  "events": [
    {
      "event_id": "<32 hex>",
      "derivative_digest": "<sha256>",
      "receipt_digest": "<sha256>",
      "status": "verified_absent"
    }
  ],
  "verified_at": 0,
  "actor": "<pseudonymous machine identifier>",
  "reason": "<privacy-scanned bounded text>",
  "forensic_erasure": false,
  "authority": "historical_only",
  "authorizes_actions": false
}
```

`receipt_digest` commits to the adapter result, plan, event, namespace digest,
and verification time; it contains no Redis values, payload, URL, socket path,
credentials, raw namespace, or backend response blob. Event IDs and the epoch
are already local pseudonymous operational metadata, but remain privacy
sensitive.

Receipt recording happens in one SQLite transaction after Redis verification.
Semantic validation checks the exact field set, schema, project, adapter,
digests, timestamps, sorted unique events, matching attempted outbox rows, and
control-chain integrity. An identical receipt is idempotent. Conflicting
receipts for the same event and epoch fail closed.

The retention state builds a set of `(event_id, epoch, derivative_digest)`
covered by valid receipts. The `store_not_adapted` exclusion becomes:

```text
attempted_at is not null
and no valid hot_projection_receipt covers this event's current projection derivative
```

All other exclusions preserve their current ordering and meaning. A receipt
resolves only this Redis hot-projection blocker; it does not satisfy a pack
blocker, authorize cleanup, waive a hold, or prove external-copy erasure.

The control-chain write changes the ledger logical digest. Any cleanup plan
made before retirement becomes stale and must be regenerated. That is desired:
the newly reviewed cleanup plan incorporates the retirement evidence.

## Projections attempted before migration

The migration retains `projection_outbox`, its timestamps, the persisted epoch,
and event metadata. The adapter can therefore reconcile all historical cases:

| Durable state | Redis state | Required result |
|---|---|---|
| `attempted_at` null | none expected | no legacy blocker; normal retention projection may publish later |
| attempted, delivered | matching record/keys | remove in project namespace, verify, receipt |
| attempted, not delivered | matching partial state | remove every matching component, verify, receipt |
| attempted, not delivered | no matching Redis state | verify full absence, receipt |
| attempted | malformed, duplicated, or digest-mismatched state | fail closed; no receipt |
| attempted | Redis unavailable/untrusted | fail closed; no receipt |
| attempted | stream entry already capped/expired but pointer or receipt remains | remove remaining matching keys, verify, receipt |
| attempted | all components expired | verify complete absence, receipt |

Inventory must not assume `delivered_at` proves presence, or that its absence
proves no Redis mutation. `attempted_at` remains the conservative boundary.

## Crash and retry behavior

There is no distributed transaction between Redis and SQLite. Hold the ledger
owner lock across inventory revalidation, Redis retirement, Redis verification,
and control receipt commit, but document these crash points:

| Crash point | Observable state | Recovery |
|---|---|---|
| before Redis mutation | original projection, no receipt | retry unchanged plan after revalidation |
| during bounded Lua operation | Redis script is atomic: either pre- or post-operation state | re-enumerate and retry idempotently |
| after Redis removal, before verification | some/all state absent, no receipt | retry original private plan; absence must be freshly verified |
| after verification, before SQLite receipt | Redis absent, blocker remains | retry; verify again, then append receipt |
| during SQLite receipt transaction | transaction either absent or committed | reopen, validate chain, retry identical receipt if absent |
| after receipt commit | receipt resolves blocker | retries return the existing receipt; projection paths suppress the event |
| after receipt, before cleanup plan | no payload deletion yet | create a fresh cleanup plan using the changed ledger digest |
| after cleanup apply | ordinary retention compaction semantics | use existing `cleanup-finalize`; never restore deleted payload merely to repair projection state |

The operational plan must be stored privately until the control receipt is
confirmed. A lost plan is recoverable by replanning only if the new inventory
can prove the same derivative identity or verified absence; ambiguity fails.

Concurrent `project-hot`, `--rebuild`, retirement, and hot reads serialize on
the ledger owner lock. The Redis Lua operation prevents interleaving inside the
target namespace. A receipt is committed before the lock is released, so a
normal local projector cannot reintroduce the retired event.

## Downgrade and compatibility impact

`hot_projection_receipt` is a new retention control kind. It has the same class
of downgrade hazard as `adapter_receipt`: 2.7.0 does not know the kind and will
refuse semantic validation of the whole ledger. Existing 2.8.0/2.8.1 readers
also do not know it and should be expected to refuse rather than silently
ignore erasure state. This is the safe outcome.

The implementation must add the new versioned identifier and downgrade matrix
to `docs/COMPATIBILITY.md` and `docs/UPGRADING.md`, and update the minimum-reader
story selected for the general migration design. It cannot improve the error
message emitted by already released readers. Operators must not record the new
kind until they no longer need those versions against the ledger.

All existing `project-memory:*` identifiers remain unchanged. The hot base
namespace stays `project-memory:hot:v1`, retention ledger stays
`project-memory:retention-ledger:v2`, and existing adapter receipts keep their
exact meaning. Only `project-memory:hot-projection-receipt:v1` is additive.

## Authority and operational boundaries

- Migration does not activate this adapter and does not retire old entries.
- Planning reads state only and grants no authority.
- Projection publishing is a derived-cache write and still requires a trusted
  configured endpoint.
- Retirement is a consequential Redis write and control-chain write. It needs
  an explicit invocation, current authorization, confirmation digest, actor,
  reason, and the owner's approval of the adapter operation.
- Cleanup remains a later, separately confirmed SQLite erasure transaction.
- A receipt is historical evidence, never permission to erase or act.
- Redis persistence files, replicas, filesystem snapshots, monitoring logs,
  backups, and exported copies remain outside the receipt and must be listed as
  unresolved where applicable.

## Test plan

### Unit and protocol tests

- Protocol registration accepts the bundled v1 adapter and rejects foreign
  projects, duplicate identity, wrong API version, raw namespaces, raw keys,
  and untrusted endpoints.
- Plans are canonical, sorted, bounded, expire, bind the ledger digest and
  epoch, and refuse changed event metadata or namespace state.
- Projection after retention migration uses metadata only and preserves the
  exact 4,096-entry cap under append, retry, and rebuild.
- `hot_events` keeps full-stream validation, SQLite comparison, poisoning
  refusal, payload omission, session filtering after verification, and the
  current response contract.
- Pre-migration attempted/delivered, attempted/undelivered, capped, expired,
  partial, malformed, duplicate, and unavailable-Redis cases match the table
  above.
- Retirement touches only the five derived keys for the selected project,
  epoch, and event. Canary keys in this project's discovery namespace, a
  sibling epoch, another project namespace, and unrelated Redis data remain
  byte-identical.
- Conditional pointer removal preserves pointers that have advanced to another
  event.
- Verification rejects any surviving matching stream record, receipt, or
  pointer and never records a control receipt on uncertainty.
- Receipt payload contains no payload, source text, raw namespace, Redis URL,
  socket path, credentials, key values, or backend blobs.
- New control validation rejects altered fields, duplicate/unsorted events,
  wrong project/epoch/digest, impossible timestamps, conflicting receipts, and
  broken control-chain continuity.

### Erasure and recovery tests

- `store_not_adapted` remains before retirement, disappears only for events
  covered by a valid receipt, and remains for uncovered dependencies.
- Receipt creation changes the logical digest and stales an earlier cleanup
  plan; a newly generated plan can proceed only when all other rules allow it.
- Holds, session pins, durable/imported authorization, protected anchors,
  dependency guards, and managed packs still block exactly as before.
- Retired events cannot be reprojected by retry, normal writes, or
  `project-hot --rebuild`.
- Inject a process crash after Redis removal but before receipt. On restart,
  the event stays blocked; an idempotent retry verifies absence, records one
  receipt, and only then resolves the blocker.
- Inject crashes before removal, during/after the Lua script, during the SQLite
  receipt transaction, and after receipt commit. Verify no duplicate control
  records and no false acknowledgement.
- Redis loss after a valid receipt does not invalidate the historical receipt;
  restoring an older Redis dump containing the event is detected by hot-read or
  adapter verification and must not be described as globally erased.
- Real `redis-server` integration repeats scope canaries, concurrency, TTL,
  exact stream cap, crash/retry, and restart-persistence cases.

### Compatibility and repository gates

- An old-reader fixture proves 2.7.0 refuses a ledger containing the new kind;
  current pre-feature readers are also recorded as refusing it.
- Existing `adapter_receipt` and Semantica tests remain unchanged.
- The full gate, mypy, installed-wheel smoke, upgrade rehearsal, and isolated
  Redis tests pass.
- Once approved and implemented, move this design into `docs/` with the code,
  update compatibility/upgrade/runbook/retention/SDK text, reindex, validate,
  and evaluate. Because the design uses Redis vocabulary from the critical
  `redis-owner-socket` case, adoption requires
  `critical_margin_warnings: []`; this is an explicit acceptance check, not a
  reason to reword documentation around the evaluation.

## Rollback story

Before any retirement receipt exists, code rollback restores the current
fail-closed behavior; the Redis projection remains disposable and the ledger is
unchanged. After a receipt exists, rollback to a reader that does not understand
the new control kind is intentionally refused. Do not delete the receipt,
rewrite the control chain, reset the ledger epoch, or restore an old ledger to
force compatibility.

A source rollback to code that still understands the receipt may stop further
projection and retirement operations without undoing recorded absence. Runtime
data rollback is not supplied: restoring an older ledger or Redis dump can
revive data and requires separate explicit authorization and reconciliation.

## Open questions for the owner

1. Approve the recommended compare-before-remove, project/epoch-scoped Lua
   operation, or require the remove-nothing epoch rollover with up to the full
   TTL delay before `store_not_adapted` can resolve?
2. Should the retirement CLI accept only event IDs already selected by a fresh
   cleanup plan, or permit an independent retirement plan for future cleanup?
3. Should `project-hot` on a retention ledger auto-register the bundled adapter
   after normal endpoint checks, or require an explicit configuration flag such
   as `hot_projection_adapter: redis-hot-v1`?
4. Should `projection_pending` exclude receipt-retired rows, or should status
   expose both `projection_pending` and `projection_retired` counts?
5. Is `hot_projection_receipt` the accepted control kind and
   `project-memory:hot-projection-receipt:v1` the accepted payload schema, or
   should the general migration proposal first establish a minimum-reader field?
6. Should one retirement plan be capped at the existing adapter limit of 1,000
   events, or use a smaller operational batch to reduce lock duration?
7. Must real-Redis crash testing include RDB/AOF restart modes in CI, or is the
   current ephemeral Redis configuration plus deterministic fault injection the
   first acceptance boundary?

## Recommended implementation order after approval

1. Resolve the open questions and record the compatibility/minimum-reader
   decision.
2. Add schemas and pure validation/state resolution with downgrade tests.
3. Add the bundled adapter and bounded real-Redis inventory/retirement tests.
4. Delegate retention projection/read paths to the existing durable logic.
5. Add explicit plan/apply SDK and CLI surfaces, crash recovery, and status.
6. Move this approved design into `docs/`, update operator documentation and
   compatibility tables, then run the complete gates including an empty
   `critical_margin_warnings` result.
