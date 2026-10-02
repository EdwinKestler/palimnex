"""Ordered durable-ledger migration registry and read-only planning.

Nothing in this module migrates a ledger. `plan`, `listing` and
`doctor_findings` read the live ledger under the shared lock and inspect its
sidecars without creating, repairing or removing any file. The registry is
executable policy shipped with this Palimnex version; it is never loaded from
configuration, a pack, a plan file, Redis or the ledger. Plans, replacement
guards and intents are evidence only and authorize nothing.
"""
from __future__ import annotations

import os
import re
import sqlite3
import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from . import durable as d
from . import retention
from .vcs import git_ignore_state

PLAN_SCHEMA = "project-memory:ledger-migration-plan:v1"
LIST_SCHEMA = "project-memory:ledger-migration-list:v1"
INTENT_SUFFIX = ".migration-intent"
IMPORT_INTENT_SUFFIX = ".import-intent"
VERSIONED_SCHEMA = re.compile(r"project-memory:[a-z0-9]+(?:-[a-z0-9]+)*:v[1-9][0-9]*")
MARKER_SUFFIX = re.compile(r"\.[a-z0-9]+(?:-[a-z0-9]+)*")
SNAPSHOT_LABEL = re.compile(r"-[a-z0-9]+(?:-[a-z0-9]+)*")
RESERVED_SUFFIXES = frozenset({
    ".lock", "-wal", "-shm", "-journal", IMPORT_INTENT_SUFFIX, INTENT_SUFFIX,
})
OVERRIDE_HINT = "`--allow-unignored-ledger`"

GuardState = Literal["absent", "exact", "empty", "invalid", "unsafe"]
Reader = Callable[[d.MemoryLedger], d.MemoryLedger]


@dataclass(frozen=True)
class Migration:
    """One adjacent schema step and its user-visible contract."""

    source_schema: str
    target_schema: str
    marker_suffix: str
    snapshot_label: str
    effects: tuple[str, ...]

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
    return tuple(entries)


REGISTRY = validate_registry((
    Migration(
        source_schema=d.LEDGER_SCHEMA,
        target_schema=retention.SCHEMA,
        marker_suffix=".retention-v2",
        snapshot_label="-pre-retention-v2",
        effects=retention.MIGRATION_EFFECTS,
    ),
), READERS)


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


def guard_state(path: Path, expected: bytes) -> GuardState:
    """Classify a replacement guard without following, creating or repairing it."""
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unsafe"
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            return "unsafe"
        if metadata.st_size == 0:
            return "empty"
        content = os.read(descriptor, len(expected) + 1)
    finally:
        os.close(descriptor)
    return "exact" if content == expected else "invalid"


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _relative(ledger: d.MemoryLedger, path: Path) -> str:
    try:
        return path.relative_to(ledger.root).as_posix()
    except ValueError:
        return str(path)


@dataclass
class Inspection:
    """What a shared-lock read of the live ledger established."""

    exists: bool
    observed: str | None = None
    structure: str = "not_checked"
    semantics: str = "not_checked"
    integrity: str = "not_checked"
    foreign_keys: str = "not_checked"
    logical_digest: str | None = None
    audit_before_digest: str | None = None

    @property
    def exact(self) -> bool:
        return (self.structure, self.semantics, self.integrity, self.foreign_keys) == (
            "ok", "ok", "ok", "ok")


def inspect(ledger: d.MemoryLedger) -> Inspection:
    """Read the observed schema and run its exact reader's checks under the shared lock."""
    base = _base(ledger)
    if not base.path.is_file() or base.path.is_symlink():
        return Inspection(exists=False)
    result = Inspection(exists=True)
    with base.file_lock(exclusive=False):
        connection = base._open(create=False)
        try:
            try:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key='ledger_schema'"
                ).fetchone()
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
            errors = reader._semantic_errors(connection)
            result.semantics = "ok" if not errors else "; ".join(errors[:3])
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            result.integrity = "ok" if integrity == "ok" else str(integrity)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            result.foreign_keys = "ok" if not violations else f"{len(violations)} violation(s)"
            if not result.exact:
                return result
            result.logical_digest = reader._logical_digest(connection)
            if isinstance(reader, retention.RetentionLedger):
                first = reader._controls(connection)[0]["payload"]
                result.audit_before_digest = first.get("before_digest")
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            result.semantics = f"ledger could not be validated: {exc}"
        finally:
            connection.close()
    return result


def _ignore_states(ledger: d.MemoryLedger, step: Migration) -> dict[str, str]:
    snapshot = (
        ledger.path.parent / d.SNAPSHOT_DIRECTORY
        / f"{ledger.path.stem}{step.snapshot_label}.sqlite3"
    )
    return {
        "intent": git_ignore_state(ledger.root, _relative(ledger, sidecar(ledger, INTENT_SUFFIX))),
        "snapshot": git_ignore_state(ledger.root, _relative(ledger, snapshot)),
    }


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


def plan(
    ledger: d.MemoryLedger, *, target: str, expected_digest: str,
    allow_unignored: bool = False,
) -> dict[str, Any]:
    """Describe the one adjacent migration to `target` without writing anything."""
    base = _base(ledger)
    found = inspect(base)
    refusals: list[str] = []
    import_intent = "present" if _present(sidecar(base, IMPORT_INTENT_SUFFIX)) else "absent"
    migration_intent = "present" if _present(sidecar(base, INTENT_SUFFIX)) else "absent"
    preconditions: dict[str, Any] = {
        "structure": found.structure, "semantics": found.semantics,
        "integrity": found.integrity, "foreign_keys": found.foreign_keys,
        "import_intent": import_intent, "migration_intent": migration_intent,
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
    if import_intent == "present":
        refusals.append("pending import blocks ledger migration")
    if migration_intent == "present":
        refusals.append(
            f"an interrupted migration intent exists at "
            f"{_relative(base, sidecar(base, INTENT_SUFFIX))}; review it before any migration"
        )
    try:
        step = resolve_step(found.observed, target)
    except ValueError as exc:
        refusals.append(str(exc))
        after = successor(found.observed)
        fields["next_step"] = after.target_schema if after else None
        return _document(base, status="refused", refusals=refusals, **fields)
    if step is None:
        return _document(base, **_completed(base, found, expected_digest, refusals, fields))
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
    if not allow_unignored and any(state in {"not_ignored", "unknown"} for state in ignore.values()):
        refusals.append(
            "Git does not confirm that the migration intent and snapshot paths are ignored; "
            f"add `.palimnex/` to .gitignore or override explicitly with {OVERRIDE_HINT}"
        )
    recovery = {"exact": "resumable: the replacement guard is already published",
                "empty": "legacy interrupted guard publication: the apply engine replaces the "
                         "empty guard atomically after confirming the exact source and digest"}
    if refusals:
        status = "refused"
    elif guard in recovery:
        status = "resumable"
        fields["recovery"] = recovery[guard]
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
    fields["expected_digest_matches"] = (
        found.audit_before_digest == expected_digest if arrived else False)
    if arrived is None:
        return {**fields, "status": "already_migrated", "refusals": refusals}
    guard_path = sidecar(ledger, arrived.marker_suffix)
    guard = guard_state(guard_path, arrived.marker_bytes)
    fields["replacement_guard"] = {"path": _relative(ledger, guard_path), "state": guard}
    fields["preconditions"]["replacement_guard"] = guard
    fields["audit_before_digest"] = found.audit_before_digest
    if guard == "exact":
        return {**fields, "status": "refused" if refusals else "already_migrated",
                "refusals": refusals}
    if guard == "absent":
        if not fields["expected_digest_matches"]:
            refusals.append("DIGEST_MISMATCH")
        fields["recovery"] = (
            "guard repair required: the apply engine exact-verifies this target and its "
            "migration audit, then atomically publishes the missing replacement guard"
        )
        return {**fields, "status": "refused" if refusals else "guard_repair_required",
                "refusals": refusals}
    refusals.append(
        f"replacement guard {fields['replacement_guard']['path']} is {guard} beside a migrated "
        "ledger; preserve it and obtain manual review"
    )
    return {**fields, "status": "refused", "refusals": refusals}


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


def _plan_command(step: Migration) -> str:
    return (f"`palimnex ledger-migrate --plan --to {step.target_schema} "
            "--expected-digest DIGEST`")


def doctor_findings(ledger: d.MemoryLedger) -> list[Finding]:
    """(id, status, detail, action) rows for unfinished or unsafe migration state."""
    base = _base(ledger)
    findings: list[Finding] = []
    intent = sidecar(base, INTENT_SUFFIX)
    if _present(intent):
        findings.append((
            "migration_intent", "warn",
            f"an interrupted ledger migration intent exists at {_relative(base, intent)}",
            "review the recorded phase, then rerun the same ledger migration apply with the "
            "same --to and --expected-digest; never delete the intent to skip recovery",
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
                    "preserve the ledger; the migration apply engine exact-verifies the target "
                    "and republishes the guard. Never create the guard by hand",
                ))
        elif state == "exact":
            if at_source:
                findings.append((
                    "replacement_guard", "warn",
                    f"{name} guards an unfinished migration to {step.target_schema}: the ledger "
                    f"is still {step.source_schema}; this state is resumable and refuses legacy "
                    "pack replacement",
                    f"run {_plan_command(step)} with the current logical digest, then complete "
                    "it with the matching apply",
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
                f"preserve it; {_plan_command(step)} reports whether the exact source and digest "
                "can be confirmed so the apply engine may replace it atomically",
            ))
        else:
            findings.append((
                "replacement_guard", "fail",
                f"{name} is {state}; it cannot be trusted as a replacement guard",
                "preserve every file and obtain manual review rather than overwriting it",
            ))
    return findings
