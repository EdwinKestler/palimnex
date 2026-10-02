"""Ordered durable-ledger migrations: registry, read-only planning and apply.

`plan`, `listing` and `doctor_findings` read the live ledger under the shared
lock and inspect its sidecars without creating, repairing or removing any
file. `apply` is the only writer. Under the exclusive lock it publishes the
replacement guard, records a transient intent, writes a verified snapshot,
applies one adjacent step in one SQLite transaction, verifies the committed
target and then removes the intent. Rerunning the same `apply` is the
recovery operation for every interruption; it never reapplies a committed
step and never restores a snapshot.

The registry is executable policy shipped with this Palimnex version; it is
never loaded from configuration, a pack, a plan file, Redis or the ledger.
Plans, guards, intents, snapshots and results are evidence only and
authorize nothing.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from . import durable as d
from . import retention
from .vcs import git_ignore_state

PLAN_SCHEMA = "project-memory:ledger-migration-plan:v1"
LIST_SCHEMA = "project-memory:ledger-migration-list:v1"
INTENT_SCHEMA = "project-memory:ledger-migration-intent:v1"
RESULT_SCHEMA = "project-memory:ledger-migration-result:v1"
INTENT_SUFFIX = ".migration-intent"
IMPORT_INTENT_SUFFIX = ".import-intent"
TEMPORARY_MARK = ".tmp-"
INTENT_MAX_BYTES = 4096
PHASES = ("prepared", "snapshot_verified", "target_verified")
INTENT_FIELDS = frozenset({
    "schema", "ledger", "source", "target", "expected_digest", "registry", "snapshot",
    "phase", "authority", "authorizes_actions",
})
DIGEST = re.compile(r"[0-9a-f]{64}")
VERSIONED_SCHEMA = re.compile(r"project-memory:[a-z0-9]+(?:-[a-z0-9]+)*:v[1-9][0-9]*")
MARKER_SUFFIX = re.compile(r"\.[a-z0-9]+(?:-[a-z0-9]+)*")
SNAPSHOT_LABEL = re.compile(r"-[a-z0-9]+(?:-[a-z0-9]+)*")
RESERVED_SUFFIXES = frozenset({
    ".lock", "-wal", "-shm", "-journal", IMPORT_INTENT_SUFFIX, INTENT_SUFFIX,
})
OVERRIDE_HINT = "`--allow-unignored-ledger`"

GuardState = Literal["absent", "exact", "empty", "invalid", "unsafe"]
Reader = Callable[[d.MemoryLedger], d.MemoryLedger]
StepApply = Callable[[sqlite3.Connection, d.MemoryLedger, str], None]
StepAudit = Callable[[d.MemoryLedger, sqlite3.Connection], tuple[str, str]]


@dataclass(frozen=True)
class Migration:
    """One adjacent schema step and its user-visible contract.

    `apply` runs inside the engine's transaction and must not commit,
    checkpoint, vacuum, publish files or call external systems. `audit`
    reads the target's record of this step as (from_schema, before_digest).
    """

    source_schema: str
    target_schema: str
    marker_suffix: str
    snapshot_label: str
    effects: tuple[str, ...]
    apply: StepApply
    audit: StepAudit

    @property
    def marker_bytes(self) -> bytes:
        """The replacement guard holds exactly the target schema identifier."""
        return self.target_schema.encode("ascii")


def _plain_reader(ledger: d.MemoryLedger) -> d.MemoryLedger:
    return ledger


READERS: dict[str, Reader] = {
    d.LEDGER_SCHEMA: _plain_reader,
    retention.SCHEMA: retention.as_retention,
}


def validate_registry(
    entries: Sequence[Migration], readers: dict[str, Reader]
) -> tuple[Migration, ...]:
    """Require one contiguous, acyclic chain of versioned, readable schemas."""
    if not entries:
        raise ValueError("migration registry is empty")
    sources = [step.source_schema for step in entries]
    for source in sources:
        if sources.count(source) > 1:
            raise ValueError(f"migration registry has an ambiguous successor for {source}")
    chain = [entries[0].source_schema]
    suffixes: set[str] = set()
    for index, step in enumerate(entries):
        for name in (step.source_schema, step.target_schema):
            if not VERSIONED_SCHEMA.fullmatch(name):
                raise ValueError(f"migration schema is not a versioned identifier: {name!r}")
            if name not in readers:
                raise ValueError(f"migration schema has no exact reader: {name}")
        if step.source_schema == step.target_schema:
            raise ValueError(f"migration target must differ from its source: {step.source_schema}")
        if index and step.source_schema != entries[index - 1].target_schema:
            raise ValueError(f"migration registry has a gap before {step.source_schema}")
        if step.target_schema in chain:
            raise ValueError(f"migration registry has a cycle at {step.target_schema}")
        chain.append(step.target_schema)
        if (
            not MARKER_SUFFIX.fullmatch(step.marker_suffix)
            or step.marker_suffix in RESERVED_SUFFIXES
            or step.marker_suffix in suffixes
        ):
            raise ValueError(f"migration marker suffix is unsafe or reused: {step.marker_suffix!r}")
        suffixes.add(step.marker_suffix)
        if not SNAPSHOT_LABEL.fullmatch(step.snapshot_label):
            raise ValueError(f"migration snapshot label is unsafe: {step.snapshot_label!r}")
        if not step.effects or any(not isinstance(e, str) or not e for e in step.effects):
            raise ValueError(f"migration to {step.target_schema} must declare its effects")
        if not callable(step.apply) or not callable(step.audit):
            raise ValueError(f"migration to {step.target_schema} needs apply and audit callbacks")
    return tuple(entries)


REGISTRY = validate_registry((
    Migration(
        source_schema=d.LEDGER_SCHEMA,
        target_schema=retention.SCHEMA,
        marker_suffix=".retention-v2",
        snapshot_label="-pre-retention-v2",
        effects=retention.MIGRATION_EFFECTS,
        apply=retention.apply_migration,
        audit=retention.migration_audit,
    ),
), READERS)


def registry_identity(registry: Sequence[Migration] = REGISTRY) -> str:
    """A digest of the shipped steps; an intent from another registry is not resumable."""
    return hashlib.sha256(d.canonical_json([
        [step.source_schema, step.target_schema, step.marker_suffix, step.snapshot_label]
        for step in registry
    ])).hexdigest()


def schema_chain(registry: Sequence[Migration] = REGISTRY) -> list[str]:
    return [registry[0].source_schema, *(step.target_schema for step in registry)]


def successor(schema: str, registry: Sequence[Migration] = REGISTRY) -> Migration | None:
    return next((step for step in registry if step.source_schema == schema), None)


def step_into(schema: str, registry: Sequence[Migration] = REGISTRY) -> Migration | None:
    return next((step for step in registry if step.target_schema == schema), None)


def resolve_step(
    observed: str, target: str, registry: Sequence[Migration] = REGISTRY
) -> Migration | None:
    """The one adjacent step from `observed` to `target`; None when already there."""
    chain = schema_chain(registry)
    if observed not in chain:
        raise ValueError(f"unknown ledger schema {observed!r}: no registered migration applies")
    if target not in chain:
        raise ValueError(
            f"unknown migration target {target!r}; `palimnex ledger-migrate --list` "
            "shows the registered targets"
        )
    if target == observed:
        return None
    if chain.index(target) < chain.index(observed):
        raise ValueError(
            f"backward migration from {observed} to {target} is not supported; "
            "migrations never roll a ledger back (docs/UPGRADING.md, \"Rolling back\")"
        )
    step = successor(observed, registry)
    assert step is not None  # observed precedes target in the chain
    if step.target_schema != target:
        raise ValueError(
            f"{target} is not the immediate successor of {observed}; migrate one step at a "
            f"time, next with `--to {step.target_schema}`"
        )
    return step


def _base(ledger: d.MemoryLedger) -> d.MemoryLedger:
    """An ordinary-schema handle on the same paths, whatever reader was selected."""
    return d.MemoryLedger(
        ledger.path, project_id=ledger.project_id_text, project_slug=ledger.project_slug,
        root=ledger.root, source_resolvers=ledger.source_resolvers,
    )


def sidecar(ledger: d.MemoryLedger, suffix: str) -> Path:
    return Path(str(ledger.path) + suffix)


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _relative(ledger: d.MemoryLedger, path: Path) -> str:
    try:
        return path.relative_to(ledger.root).as_posix()
    except ValueError:
        return str(path)


def _resolve(ledger: d.MemoryLedger, recorded: str) -> Path:
    path = Path(recorded)
    return path if path.is_absolute() else ledger.root / path


def _flags(*extra: int) -> int:
    value = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    for flag in extra:
        value |= flag
    return value


def _temporary_aliases(path: Path) -> list[Path]:
    """Engine-owned publication temporaries beside `path` (`<name>.tmp-*`)."""
    prefix = path.name + TEMPORARY_MARK
    try:
        return sorted(entry for entry in path.parent.iterdir() if entry.name.startswith(prefix))
    except FileNotFoundError:
        return []


def _linked_to_temporary(path: Path, metadata: os.stat_result) -> bool:
    """True when the only extra hard link is an interrupted publication temporary."""
    for candidate in _temporary_aliases(path):
        with contextlib.suppress(OSError):
            other = candidate.lstat()
            if (other.st_dev, other.st_ino) == (metadata.st_dev, metadata.st_ino):
                return True
    return False


def guard_state(path: Path, expected: bytes) -> GuardState:
    """Classify a replacement guard without following, creating or repairing it."""
    try:
        descriptor = os.open(path, _flags(os.O_RDONLY, getattr(os, "O_NONBLOCK", 0)))
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unsafe"
    try:
        metadata = os.fstat(descriptor)
        linked = metadata.st_nlink == 1 or (
            metadata.st_nlink == 2 and _linked_to_temporary(path, metadata))
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or not linked:
            return "unsafe"
        if metadata.st_size == 0:
            return "empty"
        content = os.read(descriptor, len(expected) + 1)
    finally:
        os.close(descriptor)
    return "exact" if content == expected else "invalid"


@dataclass
class Inspection:
    """What one locked read of the live ledger established."""

    exists: bool
    observed: str | None = None
    structure: str = "not_checked"
    semantics: str = "not_checked"
    integrity: str = "not_checked"
    foreign_keys: str = "not_checked"
    logical_digest: str | None = None
    audit: tuple[str, str] | None = None

    @property
    def exact(self) -> bool:
        return (self.structure, self.semantics, self.integrity, self.foreign_keys) == (
            "ok", "ok", "ok", "ok")

    def failures(self) -> str:
        checks = {"structure": self.structure, "semantics": self.semantics,
                  "integrity": self.integrity, "foreign_keys": self.foreign_keys}
        return "; ".join(f"{name}: {value}" for name, value in checks.items() if value != "ok")


def _inspect_connection(base: d.MemoryLedger, connection: sqlite3.Connection) -> Inspection:
    """Run the observed schema's exact reader checks on an open, locked connection."""
    result = Inspection(exists=True)
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key='ledger_schema'").fetchone()
    except sqlite3.Error as exc:
        result.structure = f"ledger metadata is unreadable: {exc}"
        return result
    if row is None or not isinstance(row[0], bytes):
        result.structure = "ledger metadata has no ledger_schema"
        return result
    result.observed = row[0].decode("utf-8", "replace")
    reader_factory = READERS.get(result.observed)
    if reader_factory is None:
        result.structure = f"durable ledger schema is unsupported: {result.observed}"
        return result
    reader = reader_factory(base)
    try:
        reader._require_schema(connection)
    except (ValueError, sqlite3.Error) as exc:
        result.structure = str(exc)
        return result
    result.structure = "ok"
    try:
        errors = reader._semantic_errors(connection)
        result.semantics = "ok" if not errors else "; ".join(errors[:3])
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        result.integrity = "ok" if integrity == "ok" else str(integrity)
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        result.foreign_keys = "ok" if not violations else f"{len(violations)} violation(s)"
        if not result.exact:
            return result
        result.logical_digest = reader._logical_digest(connection)
        arrived = step_into(result.observed)
        if arrived is not None:
            result.audit = arrived.audit(reader, connection)
    except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        result.semantics = f"ledger could not be validated: {exc}"
    return result


def inspect(ledger: d.MemoryLedger) -> Inspection:
    """Read the observed schema and run its exact reader's checks under the shared lock."""
    base = _base(ledger)
    if not base.path.is_file() or base.path.is_symlink():
        return Inspection(exists=False)
    with base.file_lock(exclusive=False):
        connection = base._open(create=False)
        try:
            return _inspect_connection(base, connection)
        finally:
            connection.close()


def read_intent(ledger: d.MemoryLedger) -> dict[str, Any] | None:
    """The validated transient intent, None when absent; malformed intents raise."""
    path = sidecar(ledger, INTENT_SUFFIX)
    try:
        descriptor = os.open(path, _flags(os.O_RDONLY, getattr(os, "O_NONBLOCK", 0)))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("migration intent must not be a symlink") from exc
    try:
        metadata = os.fstat(descriptor)
        linked = metadata.st_nlink == 1 or (
            metadata.st_nlink == 2 and _linked_to_temporary(path, metadata))
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or not linked:
            raise ValueError("migration intent must be one owner-controlled regular file")
        raw = os.read(descriptor, INTENT_MAX_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > INTENT_MAX_BYTES:
        raise ValueError("migration intent is too large")
    try:
        document = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("migration intent is not canonical JSON") from exc
    if not isinstance(document, dict) or d.canonical_json(document) != raw:
        raise ValueError("migration intent is not canonical JSON")
    snapshot = document.get("snapshot")
    if (
        set(document) != INTENT_FIELDS
        or document["schema"] != INTENT_SCHEMA
        or document["phase"] not in PHASES
        or document["authority"] != "historical_only"
        or document["authorizes_actions"] is not False
        or not isinstance(document["expected_digest"], str)
        or not DIGEST.fullmatch(document["expected_digest"])
        or not isinstance(document["registry"], str)
        or any(not isinstance(document[field], str) or not document[field]
               for field in ("ledger", "source", "target"))
        or not (snapshot is None or (
            isinstance(snapshot, dict) and set(snapshot) == {"path", "verified"}
            and isinstance(snapshot["path"], str) and snapshot["path"]
            and isinstance(snapshot["verified"], bool)))
    ):
        raise ValueError("migration intent has an invalid field set")
    return document


def _resumable(
    intent: dict[str, Any], ledger: d.MemoryLedger, step: Migration, expected_digest: str
) -> str | None:
    """Why `intent` cannot be resumed by this invocation, or None when it can."""
    if intent["ledger"] != _relative(ledger, ledger.path):
        return "it names another ledger"
    if intent["registry"] != registry_identity():
        return "it was written by a different migration registry"
    if (intent["source"], intent["target"]) != (step.source_schema, step.target_schema):
        return f"it records {intent['source']} -> {intent['target']}"
    if intent["expected_digest"] != expected_digest:
        return "it was started with a different --expected-digest"
    return None


def _ignore_states(ledger: d.MemoryLedger, step: Migration) -> dict[str, str]:
    snapshot = (
        ledger.path.parent / d.SNAPSHOT_DIRECTORY
        / f"{ledger.path.stem}{step.snapshot_label}.sqlite3"
    )
    return {
        "intent": git_ignore_state(ledger.root, _relative(ledger, sidecar(ledger, INTENT_SUFFIX))),
        "snapshot": git_ignore_state(ledger.root, _relative(ledger, snapshot)),
    }


def _ignore_refusal(states: dict[str, str]) -> str | None:
    if any(state in {"not_ignored", "unknown"} for state in states.values()):
        return (
            "Git does not confirm that the migration intent and snapshot paths are ignored; "
            f"add `.palimnex/` to .gitignore or override explicitly with {OVERRIDE_HINT}"
        )
    return None


def _apply_command(step: Migration) -> str:
    return (f"`palimnex ledger-migrate --apply --to {step.target_schema} "
            "--expected-digest DIGEST`")


def _plan_command(step: Migration) -> str:
    return (f"`palimnex ledger-migrate --plan --to {step.target_schema} "
            "--expected-digest DIGEST`")


def _document(ledger: d.MemoryLedger, **fields: Any) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "mode": "plan",
        "will_write": False,
        "authority": "historical_only",
        "authorizes_actions": False,
        "ledger": _relative(ledger, ledger.path),
        **fields,
    }


def _intent_status(
    ledger: d.MemoryLedger, step: Migration | None, expected_digest: str,
    refusals: list[str], preconditions: dict[str, Any], *, committed: bool,
) -> str | None:
    """Plan view of a pending intent: a recovery note, or a refusal appended."""
    if preconditions["migration_intent"] == "absent":
        return None
    name = _relative(ledger, sidecar(ledger, INTENT_SUFFIX))
    try:
        intent = read_intent(ledger)
    except ValueError as exc:
        refusals.append(f"migration intent {name} is unreadable ({exc}); preserve it for review")
        return None
    assert intent is not None
    preconditions["migration_intent"] = intent["phase"]
    reason = "no registered step applies" if step is None else _resumable(
        intent, ledger, step, expected_digest)
    if reason is None and not committed and intent["phase"] == "target_verified":
        reason = "it records a verified target but the ledger is still the source"
    if reason is not None:
        refusals.append(f"migration intent {name} is not resumable: {reason}")
        return None
    return (f"an interrupted migration recorded phase {intent['phase']}; rerun the same "
            "apply to finish it")


def plan(
    ledger: d.MemoryLedger, *, target: str, expected_digest: str,
    allow_unignored: bool = False,
) -> dict[str, Any]:
    """Describe the one adjacent migration to `target` without writing anything."""
    base = _base(ledger)
    found = inspect(base)
    refusals: list[str] = []
    preconditions: dict[str, Any] = {
        "structure": found.structure, "semantics": found.semantics,
        "integrity": found.integrity, "foreign_keys": found.foreign_keys,
        "import_intent": "present" if _present(sidecar(base, IMPORT_INTENT_SUFFIX)) else "absent",
        "migration_intent": "present" if _present(sidecar(base, INTENT_SUFFIX)) else "absent",
    }
    fields: dict[str, Any] = {
        "observed_schema": found.observed, "requested_target": target,
        "logical_digest": found.logical_digest, "preconditions": preconditions,
        "step": None, "next_step": None, "replacement_guard": None, "snapshot": None,
        "effects": [], "expected_digest_matches": False,
    }
    if not found.exists:
        refusals.append("durable ledger is missing")
        return _document(base, status="refused", refusals=refusals, **fields)
    if found.observed is None or not found.exact:
        refusals.append("the observed ledger does not pass its exact reader's checks")
        return _document(base, status="refused", refusals=refusals, **fields)
    if preconditions["import_intent"] == "present":
        refusals.append("pending import blocks ledger migration")
    try:
        step = resolve_step(found.observed, target)
    except ValueError as exc:
        refusals.append(str(exc))
        after = successor(found.observed)
        fields["next_step"] = after.target_schema if after else None
        return _document(base, status="refused", refusals=refusals, **fields)
    if step is None:
        return _document(base, **_completed(base, found, expected_digest, refusals, fields))
    recovery = _intent_status(base, step, expected_digest, refusals, preconditions,
                              committed=False)
    guard_path = sidecar(base, step.marker_suffix)
    guard = guard_state(guard_path, step.marker_bytes)
    fields["step"] = {"source": step.source_schema, "target": step.target_schema}
    fields["effects"] = list(step.effects)
    fields["expected_digest_matches"] = found.logical_digest == expected_digest
    fields["replacement_guard"] = {"path": _relative(base, guard_path), "state": guard}
    fields["snapshot"] = {
        "policy": "required",
        "directory": f"{_relative(base, base.path.parent / d.SNAPSHOT_DIRECTORY)}/",
        "name_suffix": f"{step.snapshot_label}.sqlite3",
        "note": d.SNAPSHOT_ERASURE_NOTE,
    }
    ignore = _ignore_states(base, step)
    preconditions["git_ignore"] = ignore
    preconditions["replacement_guard"] = guard
    if not fields["expected_digest_matches"]:
        refusals.append("DIGEST_MISMATCH")
    if guard in {"invalid", "unsafe"}:
        refusals.append(
            f"replacement guard {fields['replacement_guard']['path']} is {guard}; preserve it "
            "and obtain manual review rather than overwriting it"
        )
    refusal = None if allow_unignored else _ignore_refusal(ignore)
    if refusal:
        refusals.append(refusal)
    guard_notes = {
        "exact": "resumable: the replacement guard is already published",
        "empty": "legacy interrupted guard publication: apply replaces the empty guard "
                 "atomically after confirming the exact source and digest",
    }
    recovery = recovery or guard_notes.get(guard)
    if refusals:
        status = "refused"
    elif recovery:
        status = "resumable"
        fields["recovery"] = recovery
    else:
        status = "ready"
    return _document(base, status=status, refusals=refusals, **fields)


def _completed(
    ledger: d.MemoryLedger, found: Inspection, expected_digest: str,
    refusals: list[str], fields: dict[str, Any],
) -> dict[str, Any]:
    """Plan fields when the observed schema already is the requested target."""
    assert found.observed is not None
    arrived = step_into(found.observed)
    if arrived is None:
        return {**fields, "status": "refused" if refusals else "already_migrated",
                "refusals": refusals}
    fields["expected_digest_matches"] = found.audit == (arrived.source_schema, expected_digest)
    fields["audit_before_digest"] = found.audit[1] if found.audit else None
    recovery = _intent_status(ledger, arrived, expected_digest, refusals,
                              fields["preconditions"], committed=True)
    guard_path = sidecar(ledger, arrived.marker_suffix)
    guard = guard_state(guard_path, arrived.marker_bytes)
    fields["replacement_guard"] = {"path": _relative(ledger, guard_path), "state": guard}
    fields["preconditions"]["replacement_guard"] = guard
    if guard not in {"exact", "absent"}:
        refusals.append(
            f"replacement guard {fields['replacement_guard']['path']} is {guard} beside a "
            "migrated ledger; preserve it and obtain manual review"
        )
    if (recovery or guard == "absent") and not fields["expected_digest_matches"]:
        refusals.append("DIGEST_MISMATCH")
    if refusals:
        return {**fields, "status": "refused", "refusals": refusals}
    if recovery:
        return {**fields, "status": "resumable", "recovery": recovery, "refusals": refusals}
    if guard == "absent":
        fields["recovery"] = (
            "guard repair required: apply exact-verifies this target and its migration "
            "audit, then atomically publishes the missing replacement guard"
        )
        return {**fields, "status": "guard_repair_required", "refusals": refusals}
    return {**fields, "status": "already_migrated", "refusals": refusals}


def listing(ledger: d.MemoryLedger) -> dict[str, Any]:
    """Registered steps and where the current ledger stands; reads only."""
    base = _base(ledger)
    found = inspect(base)
    chain = schema_chain()
    position = chain.index(found.observed) if found.observed in chain else None
    migrations = []
    for step in REGISTRY:
        source_index = chain.index(step.source_schema)
        if position is None:
            standing = "unknown"
        elif position > source_index:
            standing = "applied"
        elif position == source_index:
            standing = "next"
        else:
            standing = "later"
        migrations.append({
            "source": step.source_schema,
            "target": step.target_schema,
            "effects": list(step.effects),
            "snapshot": "required",
            "replacement_guard": f"<ledger>{step.marker_suffix}",
            "standing": standing,
        })
    return {
        "schema": LIST_SCHEMA,
        "will_write": False,
        "authority": "historical_only",
        "authorizes_actions": False,
        "ledger": _relative(base, base.path),
        "ledger_present": found.exists,
        "observed_schema": found.observed,
        "chain": chain,
        "migrations": migrations,
    }


FindingStatus = Literal["warn", "fail"]
Finding = tuple[str, FindingStatus, str, str | None]


def doctor_findings(ledger: d.MemoryLedger) -> list[Finding]:
    """(id, status, detail, action) rows for unfinished or unsafe migration state."""
    base = _base(ledger)
    findings: list[Finding] = []
    intent_path = sidecar(base, INTENT_SUFFIX)
    if _present(intent_path):
        try:
            intent = read_intent(base)
            phase = f" recording phase {intent['phase']}" if intent else ""
        except ValueError as exc:
            phase = f" that cannot be read ({exc})"
        findings.append((
            "migration_intent", "warn",
            f"an interrupted ledger migration intent exists at "
            f"{_relative(base, intent_path)}{phase}",
            "review it, then rerun the same `palimnex ledger-migrate --apply` with the same "
            "--to and --expected-digest; never delete the intent to skip recovery",
        ))
    try:
        found = inspect(base)
    except (ValueError, OSError):
        found = Inspection(exists=base.path.is_file())
    chain = schema_chain()
    position = chain.index(found.observed) if found.observed in chain else None
    for step in REGISTRY:
        path = sidecar(base, step.marker_suffix)
        name = _relative(base, path)
        state = guard_state(path, step.marker_bytes)
        reached = position is not None and position >= chain.index(step.target_schema)
        at_source = found.observed == step.source_schema
        if state == "absent":
            if reached:
                findings.append((
                    "replacement_guard", "warn",
                    f"the ledger is {found.observed} but its replacement guard {name} is "
                    "missing, so legacy pack replacement is guarded only by the ledger itself",
                    f"run {_apply_command(step)} with the source digest recorded in the "
                    "migration audit (`ledger-migrate --plan` shows it); it exact-verifies the "
                    "target and republishes the guard. Never create the guard by hand",
                ))
        elif state == "exact":
            if at_source:
                findings.append((
                    "replacement_guard", "warn",
                    f"{name} guards an unfinished migration to {step.target_schema}: the ledger "
                    f"is still {step.source_schema}; this state is resumable and refuses legacy "
                    "pack replacement",
                    f"run {_plan_command(step)} with the current logical digest, then complete "
                    f"it with {_apply_command(step)}",
                ))
            elif not found.exists:
                findings.append((
                    "replacement_guard", "fail",
                    f"{name} exists but the ledger is missing; legacy pack activation stays "
                    "refused",
                    "point durable_ledger_path at the existing ledger; do not create a new "
                    "ledger or delete the guard",
                ))
            elif not reached:
                findings.append((
                    "replacement_guard", "fail",
                    f"{name} does not match the observed ledger schema {found.observed}",
                    "preserve every file and obtain manual review",
                ))
        elif state == "empty" and at_source:
            findings.append((
                "replacement_guard", "warn",
                f"{name} is empty: an interrupted legacy guard publication beside a "
                f"{step.source_schema} ledger",
                f"preserve it; {_plan_command(step)} confirms the exact source and digest, and "
                f"{_apply_command(step)} then replaces the empty guard atomically",
            ))
        else:
            findings.append((
                "replacement_guard", "fail",
                f"{name} is {state}; it cannot be trusted as a replacement guard",
                "preserve every file and obtain manual review rather than overwriting it",
            ))
    return findings


# --- apply -----------------------------------------------------------------

def _no_fault(boundary: str) -> None:
    """Crash-injection hook; tests replace it to interrupt at a named boundary."""


_boundary: Callable[[str], None] = _no_fault


def _write_temporary(final: Path, data: bytes) -> Path:
    temporary = final.with_name(f"{final.name}{TEMPORARY_MARK}{os.getpid()}-{time.time_ns()}")
    descriptor = os.open(temporary, _flags(os.O_WRONLY, os.O_CREAT, os.O_EXCL), 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return temporary


def _install_new(final: Path, data: bytes, stage: str) -> None:
    """Publish a new file atomically; `os.link` never overwrites an existing one."""
    temporary = _write_temporary(final, data)
    _boundary(f"{stage}-temporary-written")
    try:
        try:
            os.link(temporary, final)
        except FileExistsError as exc:
            raise ValueError(f"{final.name} appeared concurrently; refusing to overwrite it") from exc
        _boundary(f"{stage}-linked")
    finally:
        os.unlink(temporary)
    d._fsync_directory(final.parent)


def _install_replacement(final: Path, data: bytes, stage: str) -> None:
    temporary = _write_temporary(final, data)
    _boundary(f"{stage}-temporary-written")
    try:
        os.replace(temporary, final)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
    d._fsync_directory(final.parent)


def _remove_temporaries(ledger: d.MemoryLedger) -> list[str]:
    """Remove safely identified temporaries left by an interrupted publication."""
    removed: list[str] = []
    finals = [sidecar(ledger, step.marker_suffix) for step in REGISTRY]
    for final in [*finals, sidecar(ledger, INTENT_SUFFIX)]:
        for candidate in _temporary_aliases(final):
            metadata = candidate.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_size > INTENT_MAX_BYTES
            ):
                raise ValueError(
                    f"unexpected file {candidate.name} beside the ledger; preserve it and "
                    "obtain manual review"
                )
            candidate.unlink()
            removed.append(candidate.name)
    if removed:
        d._fsync_directory(ledger.path.parent)
    return removed


def _write_intent(ledger: d.MemoryLedger, document: dict[str, Any], *, new: bool) -> None:
    raw = d.canonical_json(document)
    if len(raw) > INTENT_MAX_BYTES:
        raise ValueError("migration intent would exceed its size bound")
    path = sidecar(ledger, INTENT_SUFFIX)
    if new:
        _install_new(path, raw, "intent")
    else:
        _install_replacement(path, raw, "intent")


def _publish_guard(ledger: d.MemoryLedger, step: Migration) -> str:
    """Make the exact replacement guard durable; returns what was done."""
    path = sidecar(ledger, step.marker_suffix)
    state = guard_state(path, step.marker_bytes)
    if state == "exact":
        d._guard_private_file(path, "replacement guard")
        return "existing"
    if state == "absent":
        _install_new(path, step.marker_bytes, "guard")
        _boundary("guard-published")
        return "published"
    if state == "empty":
        # Legacy O_EXCL-then-write gap. The caller already exact-checked the
        # source and matched the digest under this exclusive lock.
        before = path.lstat()
        temporary = _write_temporary(path, step.marker_bytes)
        try:
            now = path.lstat()
            if (now.st_dev, now.st_ino, now.st_size) != (before.st_dev, before.st_ino, 0):
                raise ValueError(f"{path.name} changed during recovery; obtain manual review")
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
        d._fsync_directory(path.parent)
        _boundary("guard-published")
        return "replaced_empty"
    raise ValueError(
        f"replacement guard {path.name} is {state}; preserve it and obtain manual review "
        "rather than overwriting it"
    )


def _verify_snapshot_file(
    ledger: d.MemoryLedger, path: Path, step: Migration, expected_digest: str
) -> dict[str, Any]:
    """Re-verify a recorded snapshot: private, intact, the source schema and digest."""
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"recorded snapshot {path} is missing") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise ValueError(f"recorded snapshot {path} is not one owner-controlled regular file")
    try:
        check = sqlite3.connect(f"file:{quote(str(path))}?mode=ro&nofollow=1", uri=True)
        try:
            check.row_factory = sqlite3.Row
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            row = check.execute("SELECT value FROM metadata WHERE key='ledger_schema'").fetchone()
            digest = ledger._logical_digest(check)
        finally:
            check.close()
    except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"recorded snapshot {path} does not verify: {exc}") from exc
    if integrity != "ok" or row is None or row[0] != step.source_schema.encode():
        raise ValueError(f"recorded snapshot {path} does not verify")
    if digest != expected_digest:
        raise ValueError(f"recorded snapshot {path} does not match the expected digest")
    return {
        "path": str(path),
        "bytes": metadata.st_size,
        "integrity": "ok",
        "logical_digest": digest,
        "schema": step.source_schema,
        "note": d.SNAPSHOT_ERASURE_NOTE,
    }


def _snapshot_phase(
    ledger: d.MemoryLedger, connection: sqlite3.Connection, intent: dict[str, Any],
    step: Migration, expected_digest: str, recovery: list[str],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Write, reuse or (after an interruption) quarantine and rewrite the snapshot."""
    recorded = intent["snapshot"]
    if recorded is None:
        return intent, None
    path = _resolve(ledger, recorded["path"])
    if recorded["verified"]:
        return intent, _verify_snapshot_file(ledger, path, step, expected_digest)
    if _present(path):
        try:
            receipt = _verify_snapshot_file(ledger, path, step, expected_digest)
            recovery.append("reused the snapshot an interrupted run had written")
        except ValueError:
            quarantined = path.with_name(f"{path.name}.quarantined-{time.time_ns()}")
            os.rename(path, quarantined)
            d._fsync_directory(path.parent)
            recovery.append(f"quarantined an incomplete snapshot as {quarantined.name}")
            path = ledger.default_snapshot_path(step.snapshot_label)
            intent = {**intent, "snapshot": {"path": _relative(ledger, path), "verified": False}}
            _write_intent(ledger, intent, new=False)
            receipt = d.write_snapshot(ledger, connection, path)
    else:
        receipt = d.write_snapshot(ledger, connection, path)
    _boundary("snapshot-verified")
    intent = {**intent, "phase": "snapshot_verified",
              "snapshot": {"path": _relative(ledger, path), "verified": True}}
    _write_intent(ledger, intent, new=False)
    _boundary("intent-snapshot-recorded")
    return intent, receipt


def _finish(
    ledger: d.MemoryLedger, connection: sqlite3.Connection, intent: dict[str, Any],
    step: Migration, expected_digest: str,
) -> None:
    """Exact-verify the committed target, record it, then remove the intent."""
    found = _inspect_connection(ledger, connection)
    if found.observed != step.target_schema or not found.exact:
        raise ValueError(
            "migration target verification failed; the intent and guard are kept: "
            + (found.failures() or f"observed {found.observed}")
        )
    if found.audit != (step.source_schema, expected_digest):
        raise ValueError(
            "migration target verification failed: its migration audit does not record "
            f"{step.source_schema} with the expected digest"
        )
    if guard_state(sidecar(ledger, step.marker_suffix), step.marker_bytes) != "exact":
        raise ValueError("migration target verification failed: the replacement guard is not exact")
    _boundary("target-verified")
    _write_intent(ledger, {**intent, "phase": "target_verified"}, new=False)
    _boundary("intent-verified-recorded")
    os.unlink(sidecar(ledger, INTENT_SUFFIX))
    _boundary("intent-removed")
    d._fsync_directory(ledger.path.parent)


def _result(
    status: str, step: Migration | None, target: str, *, resumed: bool,
    recovery: list[str], guard: str, snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "status": status,
        "source": step.source_schema if step else target,
        "target": target,
        "resumed": resumed,
        "recovery": recovery,
        "replacement_guard": guard,
        "pre_migration_snapshot": snapshot,
        "authority": "historical_only",
        "authorizes_actions": False,
    }


def apply(
    ledger: d.MemoryLedger, *, target: str, expected_digest: str,
    snapshot: bool = True, snapshot_path: Path | None = None, allow_unignored: bool = False,
) -> dict[str, Any]:
    """Apply, resume or complete the one adjacent migration to `target`.

    Only the explicit caller authorizes this attempt; the expected digest binds
    it to the ledger state the caller reviewed. `snapshot=False` exists only
    for the deprecated legacy paths.
    """
    base = _base(ledger)
    if not base.path.is_file() or base.path.is_symlink():
        raise ValueError(f"durable ledger is missing: {base.path}")
    with base.file_lock(exclusive=True):
        removed = _remove_temporaries(base)
        connection = base._open(create=False)
        try:
            result = _apply_locked(
                base, connection, target=target, expected_digest=expected_digest,
                snapshot=snapshot, snapshot_path=snapshot_path, allow_unignored=allow_unignored,
            )
        finally:
            connection.close()
    if removed:
        result["recovery"] = [f"removed interrupted temporaries: {', '.join(removed)}",
                              *result["recovery"]]
        result["resumed"] = True
    return result


def _apply_locked(
    base: d.MemoryLedger, connection: sqlite3.Connection, *, target: str,
    expected_digest: str, snapshot: bool, snapshot_path: Path | None, allow_unignored: bool,
) -> dict[str, Any]:
    found = _inspect_connection(base, connection)
    if found.observed is None or found.structure != "ok":
        raise ValueError(f"cannot migrate this ledger: {found.structure}")
    if _present(sidecar(base, IMPORT_INTENT_SUFFIX)):
        raise ValueError("pending import blocks ledger migration")
    intent = read_intent(base)
    if found.observed == target:
        return _complete(base, connection, found, intent, target, expected_digest)
    step = resolve_step(found.observed, target)
    assert step is not None
    if not found.exact:
        raise ValueError(f"cannot migrate a corrupt ledger: {found.failures()}")
    if found.logical_digest != expected_digest:
        raise ValueError("DIGEST_MISMATCH")
    recovery: list[str] = []
    if intent is not None:
        reason = _resumable(intent, base, step, expected_digest)
        if reason is not None:
            raise ValueError(f"migration intent is not resumable: {reason}; preserve it for review")
        if intent["phase"] == "target_verified":
            raise ValueError("migration intent records a verified target but the ledger is "
                             "still the source; preserve both and obtain manual review")
        recovery.append(f"resumed an interrupted migration at phase {intent['phase']}")
    creates_files = intent is None or (snapshot and intent["snapshot"] is None)
    if creates_files and not allow_unignored:
        refusal = _ignore_refusal(_ignore_states(base, step))
        if refusal:
            raise ValueError(refusal)
    guard = _publish_guard(base, step)
    if guard == "replaced_empty":
        recovery.append("replaced the empty legacy replacement guard")
    elif guard == "existing" and intent is None:
        recovery.append("continued after an existing replacement guard")
    if intent is None:
        recorded = None
        if snapshot:
            path = snapshot_path or base.default_snapshot_path(step.snapshot_label)
            recorded = {"path": _relative(base, path), "verified": False}
        intent = {
            "schema": INTENT_SCHEMA, "ledger": _relative(base, base.path),
            "source": step.source_schema, "target": step.target_schema,
            "expected_digest": expected_digest, "registry": registry_identity(),
            "snapshot": recorded, "phase": "prepared",
            "authority": "historical_only", "authorizes_actions": False,
        }
        _write_intent(base, intent, new=True)
        _boundary("intent-created")
    elif snapshot and intent["snapshot"] is None:
        path = base.default_snapshot_path(step.snapshot_label)
        intent = {**intent, "snapshot": {"path": _relative(base, path), "verified": False}}
        _write_intent(base, intent, new=False)
    intent, receipt = _snapshot_phase(base, connection, intent, step, expected_digest, recovery)
    connection.execute("BEGIN IMMEDIATE")
    try:
        step.apply(connection, base, expected_digest)
        _boundary("transaction-applied")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    _boundary("committed")
    _finish(base, connection, intent, step, expected_digest)
    return _result("migrated", step, target, resumed=bool(recovery), recovery=recovery,
                   guard=guard, snapshot=receipt)


def _complete(
    base: d.MemoryLedger, connection: sqlite3.Connection, found: Inspection,
    intent: dict[str, Any] | None, target: str, expected_digest: str,
) -> dict[str, Any]:
    """The ledger already is `target`: finish a committed migration or repair its guard."""
    arrived = step_into(target)
    if arrived is None:
        return _result("already_migrated", None, target, resumed=False, recovery=[],
                       guard="unchanged", snapshot=None)
    if not found.exact:
        raise ValueError(f"migration target verification failed: {found.failures()}")
    audit_matches = found.audit == (arrived.source_schema, expected_digest)
    guard_path = sidecar(base, arrived.marker_suffix)
    state = guard_state(guard_path, arrived.marker_bytes)
    if intent is not None:
        reason = _resumable(intent, base, arrived, expected_digest)
        if reason is not None:
            raise ValueError(f"migration intent is not resumable: {reason}; preserve it for review")
        if not audit_matches:
            raise ValueError("DIGEST_MISMATCH")
        guard = "existing" if state == "exact" else _publish_guard(base, arrived)
        receipt = None
        if intent["snapshot"] is not None:
            with contextlib.suppress(ValueError):
                receipt = _verify_snapshot_file(
                    base, _resolve(base, intent["snapshot"]["path"]), arrived, expected_digest)
        _finish(base, connection, intent, arrived, expected_digest)
        return _result("migrated", arrived, target, resumed=True,
                       recovery=[f"completed a committed migration from phase {intent['phase']}"],
                       guard=guard, snapshot=receipt)
    if state == "exact":
        return _result("already_migrated", arrived, target, resumed=False, recovery=[],
                       guard="existing", snapshot=None)
    if state != "absent":
        raise ValueError(
            f"replacement guard {guard_path.name} is {state} beside a migrated ledger; "
            "preserve it and obtain manual review"
        )
    if not audit_matches:
        raise ValueError("DIGEST_MISMATCH")
    _publish_guard(base, arrived)
    return _result("guard_repaired", arrived, target, resumed=True,
                   recovery=["republished the missing replacement guard after exact verification"],
                   guard="published", snapshot=None)
