"""Durable typed events, temporal recall, and dry-run workflows."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import heapq
import json
import os
import re
import secrets
import sqlite3
import stat
import time
import uuid
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import quote

from .security import policy_digest, read_bounded_file, scan_text


LEDGER_SCHEMA = "project-memory:ledger:v1"
PAYLOAD_CODEC = "canonical-json+zlib"
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_IMPORT_SESSIONS = 100_000
MAX_IMPORT_EVENTS = 1_000_000
# One event is 23 RESP aggregate items (record/id/field array plus 20 fields).
# 4096 therefore keeps a complete exact-capped stream below core's 100,000
# item parser ceiling with room for the outer response array.
HOT_STREAM_MAXLEN = 4_096
MAX_QUERY_BYTES = 8 * 1024
MAX_QUERY_TERMS = 128
MAX_SUBJECT_BYTES = 8 * 1024
MAX_RECALL_CANDIDATES = 10_000
MAX_EVENT_TERMS = 32_768

EVENT_KINDS = {
    "session_started": 1,
    "task": 2,
    "decision": 3,
    "failure": 4,
    "outcome": 5,
    "workflow": 6,
    "fact": 7,
    "evidence": 8,
    "correction": 9,
    "revocation": 10,
    "session_closed": 11,
}
EVENT_KIND_NAMES = {value: key for key, value in EVENT_KINDS.items()}
CLAIMED_TRUST = {"untrusted": 0, "observed": 1}
CLAIMED_TRUST_NAMES = {value: key for key, value in CLAIMED_TRUST.items()}
SENSITIVITY_CODES = {"public": 0, "internal": 1, "restricted": 2, "secret": 3}
SENSITIVITY_NAMES = {value: key for key, value in SENSITIVITY_CODES.items()}
RETENTION_CODES = {"volatile": 0, "session": 1, "durable": 2}
RETENTION_NAMES = {value: key for key, value in RETENTION_CODES.items()}
PROMOTABLE_KINDS = {
    EVENT_KINDS[name] for name in ("decision", "failure", "outcome", "workflow", "fact")
}
SIDE_EFFECT_CODES = {
    "none": 0,
    "read": 1,
    "local_write": 2,
    "external_write": 3,
    "destructive": 4,
}
EVIDENCE_KINDS = {"source": 1, "git": 2, "test": 3, "artifact": 4, "external": 5}
VERIFICATION_OUTCOMES = {"verified": 1, "stale": 2}
VERIFICATION_FAILURES = {
    "none": 0,
    "changed": 1,
    "unavailable": 2,
    "unsupported": 3,
    "policy_changed": 4,
}


def _eligible_supersessor_exists_sql(
    predecessor_expression: str,
    *,
    include_untrusted: bool,
    promoted_only: bool,
    as_of: bool | str = False,
) -> str:
    """One trust predicate for recall, consolidation, and promotion validation."""
    joins = [
        "JOIN events assertion ON assertion.event_id=s.assertion_event_id",
        "LEFT JOIN verifications assertion_verification "
        "ON assertion_verification.event_id=assertion.event_id",
    ]
    conditions = [
        f"s.predecessor_event_id={predecessor_expression}",
        f"assertion.project_id={predecessor_expression.rsplit('.', 1)[0]}.project_id",
    ]
    if promoted_only:
        joins.append(
            "LEFT JOIN promotions assertion_promotion "
            "ON assertion_promotion.event_id=assertion.event_id"
        )
        conditions.extend(
            (
                "assertion_verification.event_id IS NOT NULL",
                "assertion_promotion.event_id IS NOT NULL",
            )
        )
    elif not include_untrusted:
        conditions.append(
            "(assertion.claimed_trust=1 OR assertion_verification.event_id IS NOT NULL)"
        )
    if as_of is True:
        conditions.extend(("s.recorded_at<=?", "s.effective_at<=?"))
        if promoted_only:
            conditions.append("assertion_promotion.promoted_at<=?")
    elif isinstance(as_of, str):
        conditions.extend((f"s.recorded_at<={as_of}", f"s.effective_at<={as_of}"))
        if promoted_only:
            conditions.append(f"assertion_promotion.promoted_at<={as_of}")
    return (
        "EXISTS(SELECT 1 FROM supersessions s "
        + " ".join(joins)
        + " WHERE "
        + " AND ".join(conditions)
        + ")"
    )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS import_batches (
    import_batch_id BLOB PRIMARY KEY CHECK(length(import_batch_id)=16),
    imported_at INTEGER NOT NULL,
    source_logical_digest BLOB NOT NULL CHECK(length(source_logical_digest)=32),
    authenticated INTEGER NOT NULL CHECK(authenticated IN (0,1))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sessions (
    session_id BLOB PRIMARY KEY CHECK(length(session_id)=16),
    project_id BLOB NOT NULL CHECK(length(project_id)=16),
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    status INTEGER NOT NULL CHECK(status IN (1,2)),
    task_payload BLOB NOT NULL,
    task_digest BLOB NOT NULL CHECK(length(task_digest)=32),
    import_batch_id BLOB REFERENCES import_batches(import_batch_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS events (
    event_id BLOB PRIMARY KEY CHECK(length(event_id)=16),
    project_id BLOB NOT NULL CHECK(length(project_id)=16),
    session_id BLOB NOT NULL REFERENCES sessions(session_id),
    sequence INTEGER NOT NULL CHECK(sequence>0),
    kind INTEGER NOT NULL CHECK(kind BETWEEN 1 AND 11),
    subject_digest BLOB NOT NULL CHECK(length(subject_digest)=32),
    terms_digest BLOB NOT NULL CHECK(length(terms_digest)=32),
    observed_at INTEGER NOT NULL,
    valid_from INTEGER NOT NULL,
    supersedes_event_id BLOB REFERENCES events(event_id),
    contradicts_event_id BLOB REFERENCES events(event_id),
    claimed_trust INTEGER NOT NULL CHECK(claimed_trust IN (0,1)),
    sensitivity INTEGER NOT NULL CHECK(sensitivity BETWEEN 0 AND 3),
    retention INTEGER NOT NULL CHECK(retention BETWEEN 0 AND 2),
    payload_codec TEXT NOT NULL,
    payload BLOB NOT NULL,
    payload_digest BLOB NOT NULL CHECK(length(payload_digest)=32),
    record_digest BLOB NOT NULL UNIQUE CHECK(length(record_digest)=32),
    import_batch_id BLOB REFERENCES import_batches(import_batch_id),
    UNIQUE(session_id, sequence)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS events_session_sequence ON events(session_id,sequence);
CREATE INDEX IF NOT EXISTS events_subject_time ON events(subject_digest,observed_at,valid_from);
CREATE INDEX IF NOT EXISTS events_project_time ON events(project_id,observed_at);

CREATE TABLE IF NOT EXISTS supersessions (
    assertion_event_id BLOB PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    predecessor_event_id BLOB NOT NULL REFERENCES events(event_id),
    recorded_at INTEGER NOT NULL,
    effective_at INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS supersessions_predecessor
    ON supersessions(predecessor_event_id,recorded_at,effective_at);

CREATE TABLE IF NOT EXISTS contradictions (
    assertion_event_id BLOB PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    opposed_event_id BLOB NOT NULL REFERENCES events(event_id),
    recorded_at INTEGER NOT NULL,
    effective_at INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS contradictions_opposed
    ON contradictions(opposed_event_id,recorded_at,effective_at);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id BLOB PRIMARY KEY CHECK(length(evidence_id)=16),
    event_id BLOB NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    kind INTEGER NOT NULL CHECK(kind BETWEEN 1 AND 5),
    locator BLOB NOT NULL,
    locator_digest BLOB NOT NULL CHECK(length(locator_digest)=32),
    content_digest BLOB CHECK(content_digest IS NULL OR length(content_digest)=32),
    locally_verified INTEGER NOT NULL CHECK(locally_verified IN (0,1)),
    verified_at INTEGER
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS evidence_event ON evidence(event_id);

CREATE TABLE IF NOT EXISTS verifications (
    event_id BLOB PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    verified_at INTEGER NOT NULL,
    verifier_policy_digest BLOB NOT NULL CHECK(length(verifier_policy_digest)=32),
    evidence_set_digest BLOB NOT NULL CHECK(length(evidence_set_digest)=32)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS verification_attempts (
    attempt_id BLOB PRIMARY KEY CHECK(length(attempt_id)=16),
    event_id BLOB NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    attempt_sequence INTEGER NOT NULL CHECK(attempt_sequence>0),
    checked_at INTEGER NOT NULL,
    outcome INTEGER NOT NULL CHECK(outcome BETWEEN 1 AND 2),
    failure_code INTEGER NOT NULL CHECK(failure_code BETWEEN 0 AND 4),
    verifier_policy_digest BLOB NOT NULL CHECK(length(verifier_policy_digest)=32),
    stored_evidence_set_digest BLOB NOT NULL CHECK(length(stored_evidence_set_digest)=32),
    observed_evidence_set_digest BLOB CHECK(
        observed_evidence_set_digest IS NULL OR length(observed_evidence_set_digest)=32
    ),
    UNIQUE(event_id,attempt_sequence)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS verification_attempts_event
    ON verification_attempts(event_id,attempt_sequence,checked_at);

CREATE TABLE IF NOT EXISTS event_terms (
    event_id BLOB NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    term_digest BLOB NOT NULL CHECK(length(term_digest)=16),
    PRIMARY KEY(event_id,term_digest)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS event_terms_term ON event_terms(term_digest,event_id);

CREATE TABLE IF NOT EXISTS nodes (
    node_id BLOB PRIMARY KEY CHECK(length(node_id)=16),
    kind INTEGER NOT NULL,
    identity_digest BLOB NOT NULL UNIQUE CHECK(length(identity_digest)=32),
    created_event_id BLOB NOT NULL REFERENCES events(event_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS edges (
    edge_id BLOB PRIMARY KEY CHECK(length(edge_id)=16),
    source_node_id BLOB NOT NULL REFERENCES nodes(node_id),
    target_node_id BLOB NOT NULL REFERENCES nodes(node_id),
    kind INTEGER NOT NULL,
    created_event_id BLOB NOT NULL REFERENCES events(event_id),
    recorded_at INTEGER NOT NULL,
    effective_at INTEGER NOT NULL,
    UNIQUE(source_node_id,target_node_id,kind,created_event_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS promotions (
    event_id BLOB PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    promoted_at INTEGER NOT NULL,
    policy_digest BLOB NOT NULL CHECK(length(policy_digest)=32)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS workflows (
    workflow_id BLOB PRIMARY KEY CHECK(length(workflow_id)=16),
    event_id BLOB NOT NULL UNIQUE REFERENCES events(event_id),
    name_digest BLOB NOT NULL CHECK(length(name_digest)=32),
    version INTEGER NOT NULL CHECK(version>0),
    specification BLOB NOT NULL,
    specification_digest BLOB NOT NULL CHECK(length(specification_digest)=32)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS workflow_steps (
    workflow_id BLOB NOT NULL REFERENCES workflows(workflow_id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK(position>=0),
    step_id_digest BLOB NOT NULL CHECK(length(step_id_digest)=32),
    side_effect INTEGER NOT NULL CHECK(side_effect BETWEEN 0 AND 4),
    step_payload BLOB NOT NULL,
    PRIMARY KEY(workflow_id,position)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS projection_outbox (
    outbox_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id BLOB NOT NULL UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    attempted_at INTEGER,
    delivered_at INTEGER
);
CREATE INDEX IF NOT EXISTS projection_pending ON projection_outbox(delivered_at,outbox_id);
"""

TABLE_COLUMNS = {
    "metadata": ("key", "value"),
    "import_batches": ("import_batch_id", "imported_at", "source_logical_digest", "authenticated"),
    "sessions": (
        "session_id", "project_id", "started_at", "ended_at", "status", "task_payload",
        "task_digest", "import_batch_id",
    ),
    "events": (
        "event_id", "project_id", "session_id", "sequence", "kind", "subject_digest",
        "terms_digest", "observed_at", "valid_from", "supersedes_event_id", "contradicts_event_id",
        "claimed_trust", "sensitivity", "retention", "payload_codec", "payload",
        "payload_digest", "record_digest", "import_batch_id",
    ),
    "supersessions": ("assertion_event_id", "predecessor_event_id", "recorded_at", "effective_at"),
    "contradictions": ("assertion_event_id", "opposed_event_id", "recorded_at", "effective_at"),
    "evidence": (
        "evidence_id", "event_id", "kind", "locator", "locator_digest", "content_digest",
        "locally_verified", "verified_at",
    ),
    "verifications": ("event_id", "verified_at", "verifier_policy_digest", "evidence_set_digest"),
    "verification_attempts": (
        "attempt_id", "event_id", "attempt_sequence", "checked_at", "outcome", "failure_code",
        "verifier_policy_digest", "stored_evidence_set_digest", "observed_evidence_set_digest",
    ),
    "event_terms": ("event_id", "term_digest"),
    "nodes": ("node_id", "kind", "identity_digest", "created_event_id"),
    "edges": (
        "edge_id", "source_node_id", "target_node_id", "kind", "created_event_id",
        "recorded_at", "effective_at",
    ),
    "promotions": ("event_id", "promoted_at", "policy_digest"),
    "workflows": (
        "workflow_id", "event_id", "name_digest", "version", "specification",
        "specification_digest",
    ),
    "workflow_steps": (
        "workflow_id", "position", "step_id_digest", "side_effect", "step_payload",
    ),
    "projection_outbox": (
        "outbox_id", "event_id", "created_at", "attempted_at", "delivered_at",
    ),
}
EXPECTED_INDEXES = {
    "events_session_sequence",
    "events_subject_time",
    "events_project_time",
    "supersessions_predecessor",
    "contradictions_opposed",
    "evidence_event",
    "verification_attempts_event",
    "event_terms_term",
    "projection_pending",
}
EXPECTED_METADATA_KEYS = {
    "ledger_schema",
    "project_id",
    "project_slug",
    "payload_codec",
    "scanner_policy_digest",
    "hot_projection_epoch",
}


def now_ms() -> int:
    return int(time.time() * 1_000)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _parse_json(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("memory payload is not valid UTF-8 JSON") from exc
    try:
        canonical = canonical_json(value)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("memory payload exceeds canonical JSON structure limits") from exc
    if canonical != raw:
        raise ValueError("memory payload is not canonical JSON")
    return value


def pack_payload(value: Any) -> tuple[bytes, bytes]:
    raw = canonical_json(value)
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"memory payload exceeds {MAX_PAYLOAD_BYTES} bytes")
    findings = scan_text(raw.decode("utf-8"))
    if findings:
        details = ", ".join(f"{item.rule}@{item.line}" for item in findings[:5])
        raise ValueError(f"memory payload rejected by content privacy policy: {details}")
    return zlib.compress(raw, level=9), hashlib.sha256(raw).digest()


def unpack_payload(value: bytes, expected_digest: bytes | None = None) -> Any:
    decompressor = zlib.decompressobj()
    try:
        raw = decompressor.decompress(value, MAX_PAYLOAD_BYTES + 1)
    except zlib.error as exc:
        raise ValueError("memory payload is not valid compressed data") from exc
    if (
        len(raw) > MAX_PAYLOAD_BYTES
        or decompressor.unconsumed_tail
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise ValueError("memory payload exceeds limits or has trailing compressed data")
    raw += decompressor.flush()
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("memory payload expands beyond its limit")
    if expected_digest is not None and hashlib.sha256(raw).digest() != expected_digest:
        raise ValueError("memory payload digest mismatch")
    return _parse_json(raw)


def _id_bytes(value: str, label: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError(f"{label} must be 32 lowercase hexadecimal characters")
    return bytes.fromhex(value)


def _new_id() -> bytes:
    return secrets.token_bytes(16)


def _digest_text(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _event_record_digest(
    project_id: bytes,
    session_id: bytes,
    event_id: bytes,
    sequence: int,
    kind: int,
    subject_digest: bytes,
    terms_digest: bytes,
    observed_at: int,
    valid_from: int,
    supersedes: bytes | None,
    contradicts: bytes | None,
    claimed_trust: int,
    sensitivity: int,
    retention: int,
    payload_digest: bytes,
    import_batch_id: bytes | None,
) -> bytes:
    material = b"\0".join(
        (
            project_id,
            session_id,
            event_id,
            str(sequence).encode(),
            str(kind).encode(),
            subject_digest,
            terms_digest,
            str(observed_at).encode(),
            str(valid_from).encode(),
            supersedes or b"",
            contradicts or b"",
            str(claimed_trust).encode(),
            str(sensitivity).encode(),
            str(retention).encode(),
            payload_digest,
            import_batch_id or b"",
        )
    )
    return hashlib.sha256(material).digest()


def _term_digests(value: Any) -> list[bytes]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
    terms = set(part.lower() for part in re.findall(r"[A-Za-z0-9_]+", text))
    result = sorted(hashlib.sha256(term.encode("utf-8")).digest()[:16] for term in terms)
    if not result or len(result) > MAX_EVENT_TERMS:
        raise ValueError(
            f"memory event must contain between 1 and {MAX_EVENT_TERMS} retrieval terms"
        )
    return result


def _term_set_digest(terms: Iterable[bytes], *, allow_empty: bool = False) -> bytes:
    """Bind the exact canonical searchable term set into the event record."""
    values = list(terms)
    if (
        (not values and not allow_empty)
        or len(values) > MAX_EVENT_TERMS
        or any(type(value) is not bytes or len(value) != 16 for value in values)
        or values != sorted(values)
        or len(values) != len(set(values))
    ):
        raise ValueError("event term digests must be a non-empty sorted unique digest list")
    return hashlib.sha256(
        b"project-memory:event-terms:v1\0" + b"".join(values)
    ).digest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_private_directory(root: Path, directory: Path) -> None:
    """Create a private in-repository directory without traversing symlinks."""
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("durable ledger directory escaped the repository") from exc
    if not relative.parts:
        raise ValueError("durable ledger must use a private subdirectory")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptors: list[int] = []
    try:
        current = os.open(root, flags)
        descriptors.append(current)
        for component in relative.parts:
            try:
                os.mkdir(component, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
            metadata = os.fstat(current)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ValueError("durable ledger directories must be owned by this user")
        os.fchmod(current, 0o700)
    except OSError as exc:
        raise ValueError("durable ledger directory must contain no symlink") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _guard_private_file(path: Path, label: str) -> None:
    """Reject non-private aliases before SQLite or a lock may open them."""
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ValueError(f"{label} must not be a symlink") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise ValueError(f"{label} must be one owner-controlled regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def validate_project_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("project_id must be a UUID") from exc


class MemoryLedger:
    """SQLite authority for durable memory; all returned authority is historical-only."""

    schema = LEDGER_SCHEMA
    table_columns = TABLE_COLUMNS

    def __init__(self, path: Path, *, project_id: str, project_slug: str, root: Path,
                 source_resolvers=None):
        self.source_resolvers = dict(source_resolvers or {})
        self.root = root.resolve()
        candidate = path if path.is_absolute() else root / path
        self.path = candidate.absolute()
        if not self.path.is_relative_to(self.root):
            raise ValueError("durable ledger path must stay inside the repository")
        self.project_id_text = validate_project_id(project_id)
        self.project_id = uuid.UUID(self.project_id_text).bytes
        self.project_slug = project_slug
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _guard_paths(self) -> None:
        _ensure_private_directory(self.root, self.path.parent)
        guarded = (
            (self.path, "durable ledger"),
            (self.lock_path, "durable ledger lock"),
            (Path(str(self.path) + "-wal"), "durable ledger WAL"),
            (Path(str(self.path) + "-shm"), "durable ledger shared memory"),
            (Path(str(self.path) + "-journal"), "durable ledger journal"),
        )
        for candidate, label in guarded:
            _guard_private_file(candidate, label)

    @contextmanager
    def file_lock(self, *, exclusive: bool) -> Iterator[None]:
        self._guard_paths()
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
            ):
                raise ValueError("durable ledger lock must be one owner-controlled regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _open(self, *, create: bool) -> sqlite3.Connection:
        self._guard_paths()
        if not create and not self.path.is_file():
            raise ValueError(f"durable ledger is missing: {self.path}")
        if create and not self.path.exists():
            try:
                descriptor = os.open(
                    self.path,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                self._guard_paths()
            else:
                try:
                    os.fchmod(descriptor, 0o600)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                _fsync_directory(self.path.parent)
        mode = "rwc" if create else "rw"
        uri = f"file:{quote(str(self.path))}?mode={mode}&nofollow=1"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA trusted_schema=OFF")
        if self.path.exists():
            os.chmod(self.path, 0o600)
        return connection

    @contextmanager
    def connection(
        self,
        *,
        create: bool = True,
        write: bool = False,
        require_semantic: bool = True,
    ) -> Iterator[sqlite3.Connection]:
        with self.file_lock(exclusive=write):
            connection = self._open(create=create)
            try:
                self._require_schema(connection)
                if require_semantic:
                    semantic_errors = self._semantic_errors(connection)
                    if semantic_errors:
                        raise ValueError(
                            "durable ledger failed semantic validation: "
                            + "; ".join(semantic_errors[:5])
                        )
                if write:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
                if write:
                    connection.commit()
            except BaseException:
                if write:
                    connection.rollback()
                raise
            finally:
                connection.close()

    def initialize(self) -> dict[str, Any]:
        self._guard_paths()
        with self.file_lock(exclusive=True):
            connection = self._open(create=True)
            try:
                # executescript commits an already-open transaction in Python's
                # sqlite3 wrapper. Put the transaction in the script itself so
                # a crash cannot leave a partially created schema.
                connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA_SQL + "\nCOMMIT;")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._initialize_metadata(connection)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
            finally:
                connection.close()
        _fsync_directory(self.path.parent)
        return self.status()

    def _initialize_metadata(self, connection: sqlite3.Connection) -> None:
        expected = {
            "ledger_schema": self.schema,
            "project_id": self.project_id_text,
            "project_slug": self.project_slug,
            "payload_codec": PAYLOAD_CODEC,
            "scanner_policy_digest": policy_digest(),
        }
        for key, value in expected.items():
            row = connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
            if (
                row is not None
                and key != "scanner_policy_digest"
                and row["value"].decode("utf-8") != value
            ):
                raise ValueError(f"durable ledger metadata mismatch for {key}")
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key,value) VALUES(?,?)",
                (key, value.encode("utf-8")),
            )
        connection.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES(?,?)",
            ("hot_projection_epoch", secrets.token_hex(16).encode("ascii")),
        )

    def _require_schema(self, connection: sqlite3.Connection) -> dict[str, str]:
        rows = connection.execute("SELECT key,value FROM metadata").fetchall()
        metadata = {row["key"]: row["value"].decode("utf-8") for row in rows}
        if set(metadata) != EXPECTED_METADATA_KEYS:
            raise ValueError("durable ledger metadata has an unexpected field set")
        if metadata.get("ledger_schema") != self.schema:
            raise ValueError("durable ledger schema is unsupported")
        if metadata.get("project_id") != self.project_id_text:
            raise ValueError("durable ledger belongs to a different project")
        if metadata.get("project_slug") != self.project_slug:
            raise ValueError("durable ledger project slug does not match this repository")
        if metadata.get("payload_codec") != PAYLOAD_CODEC:
            raise ValueError("durable ledger payload codec is unsupported")
        creation_policy = metadata.get("scanner_policy_digest", "")
        if not re.fullmatch(r"[0-9a-f]{64}", creation_policy):
            raise ValueError("durable ledger scanner policy metadata is invalid")
        if not re.fullmatch(r"[0-9a-f]{32}", metadata.get("hot_projection_epoch", "")):
            raise ValueError("durable ledger hot projection epoch is invalid")
        objects = connection.execute(
            "SELECT type,name FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_autoindex_%' AND name!='sqlite_sequence'"
        ).fetchall()
        tables = {row["name"] for row in objects if row["type"] == "table"}
        indexes = {row["name"] for row in objects if row["type"] == "index"}
        other = {row["name"] for row in objects if row["type"] not in {"table", "index"}}
        if tables != set(self.table_columns) or indexes != EXPECTED_INDEXES or other:
            raise ValueError("durable ledger schema object set is not exact")
        for table, expected_columns in self.table_columns.items():
            observed_columns = tuple(
                row["name"] for row in connection.execute(f"PRAGMA table_xinfo({table})")
            )
            if observed_columns != expected_columns:
                raise ValueError(f"durable ledger column set differs for {table}")
        return metadata

    def _semantic_errors(self, connection: sqlite3.Connection) -> list[str]:
        errors: list[str] = []

        def report(message: str) -> None:
            if len(errors) < 100:
                errors.append(message)

        session_batches: dict[bytes, bytes | None] = {}
        session_times: dict[bytes, tuple[int, int | None]] = {}
        for row in connection.execute("SELECT * FROM sessions ORDER BY session_id"):
            session_batches[row["session_id"]] = row["import_batch_id"]
            session_times[row["session_id"]] = (row["started_at"], row["ended_at"])
            if row["project_id"] != self.project_id:
                report("session belongs to another project")
            if (
                row["started_at"] < 0
                or
                (row["status"] == 1 and row["ended_at"] is not None)
                or (
                    row["status"] == 2
                    and (row["ended_at"] is None or row["ended_at"] < row["started_at"])
                )
            ):
                report("session status and end time disagree")
            try:
                task = unpack_payload(row["task_payload"], row["task_digest"])
                if (
                    not isinstance(task, dict)
                    or set(task) != {"task"}
                    or not isinstance(task["task"], str)
                    or not task["task"].strip()
                ):
                    raise ValueError
            except (TypeError, ValueError):
                report("session task payload failed validation")

        event_rows = connection.execute(
            "SELECT * FROM events ORDER BY session_id,sequence,event_id"
        ).fetchall()
        event_by_id = {row["event_id"]: row for row in event_rows}
        sequences: dict[bytes, list[int]] = {}
        for row in event_rows:
            sequences.setdefault(row["session_id"], []).append(row["sequence"])
            if row["project_id"] != self.project_id:
                report("event belongs to another project")
            if row["import_batch_id"] != session_batches.get(row["session_id"]):
                report("event import batch differs from its session")
            started_at, ended_at = session_times.get(row["session_id"], (-1, None))
            if (
                row["observed_at"] < started_at
                or row["valid_from"] < 0
                or (ended_at is not None and row["observed_at"] > ended_at)
            ):
                report("event time is outside its session record")
            if row["import_batch_id"] is not None and row["claimed_trust"] != CLAIMED_TRUST["untrusted"]:
                report("imported event is not quarantined as untrusted")
            if row["payload_codec"] != PAYLOAD_CODEC:
                report("event payload codec is unsupported")
            try:
                unpack_payload(row["payload"], row["payload_digest"])
            except ValueError:
                report("event payload failed validation")
            term_rows = [
                item["term_digest"]
                for item in connection.execute(
                    "SELECT term_digest FROM event_terms WHERE event_id=? ORDER BY term_digest",
                    (row["event_id"],),
                )
            ]
            try:
                expected_terms_digest = _term_set_digest(term_rows, allow_empty=self.schema != LEDGER_SCHEMA)
            except ValueError:
                expected_terms_digest = b""
            if expected_terms_digest != row["terms_digest"]:
                report("event retrieval term set failed validation")
            expected_record = _event_record_digest(
                row["project_id"], row["session_id"], row["event_id"], row["sequence"],
                row["kind"], row["subject_digest"], row["terms_digest"],
                row["observed_at"], row["valid_from"],
                row["supersedes_event_id"], row["contradicts_event_id"], row["claimed_trust"],
                row["sensitivity"], row["retention"], row["payload_digest"],
                row["import_batch_id"],
            )
            if expected_record != row["record_digest"]:
                report("event record digest failed validation")
        for values in sequences.values():
            if sorted(values) != list(range(1, len(values) + 1)):
                report("event sequence is not contiguous")

        events_by_session: dict[bytes, list[sqlite3.Row]] = {}
        for row in event_rows:
            events_by_session.setdefault(row["session_id"], []).append(row)
        for session_id, (started_at, ended_at) in session_times.items():
            rows = events_by_session.get(session_id, [])
            if any(
                current["observed_at"] < previous["observed_at"]
                for previous, current in zip(rows, rows[1:])
            ):
                report("event observation time moves backwards within a session")
            start_rows = [row for row in rows if row["kind"] == EVENT_KINDS["session_started"]]
            close_rows = [row for row in rows if row["kind"] == EVENT_KINDS["session_closed"]]
            try:
                task = unpack_payload(
                    connection.execute(
                        "SELECT task_payload FROM sessions WHERE session_id=?", (session_id,)
                    ).fetchone()[0]
                )
                start_payload = unpack_payload(start_rows[0]["payload"], start_rows[0]["payload_digest"])
            except (IndexError, TypeError, ValueError):
                task = start_payload = None
            if (
                len(start_rows) != 1
                or start_rows[0]["sequence"] != 1
                or start_rows[0]["observed_at"] != started_at
                or start_rows[0]["retention"] != RETENTION_CODES["durable"]
                or start_payload != task
            ):
                report("session start event differs from its session")
            if ended_at is None:
                if close_rows:
                    report("open session contains a close event")
            else:
                try:
                    close_payload = unpack_payload(
                        close_rows[0]["payload"], close_rows[0]["payload_digest"]
                    )
                except (IndexError, ValueError):
                    close_payload = None
                if (
                    len(close_rows) != 1
                    or close_rows[0]["sequence"] != len(rows)
                    or close_rows[0]["observed_at"] != ended_at
                    or close_rows[0]["retention"] != RETENTION_CODES["durable"]
                    or not isinstance(close_payload, dict)
                    or set(close_payload) != {"outcome"}
                    or not isinstance(close_payload["outcome"], str)
                    or not close_payload["outcome"].strip()
                ):
                    report("session close event differs from its session")

        for relation, column, table, target in (
            ("supersession", "supersedes_event_id", "supersessions", "predecessor_event_id"),
            ("contradiction", "contradicts_event_id", "contradictions", "opposed_event_id"),
        ):
            mismatches = connection.execute(
                f"SELECT count(*) FROM events e LEFT JOIN {table} r "
                f"ON r.assertion_event_id=e.event_id WHERE "
                f"(e.{column} IS NULL) != (r.assertion_event_id IS NULL) OR "
                f"(e.{column} IS NOT NULL AND (e.{column}!=r.{target} "
                "OR e.observed_at!=r.recorded_at OR e.valid_from!=r.effective_at))"
            ).fetchone()[0]
            if mismatches:
                report(f"{relation} column and assertion table disagree")
            invalid_targets = connection.execute(
                f"SELECT count(*) FROM {table} r JOIN events assertion "
                f"ON assertion.event_id=r.assertion_event_id JOIN events target "
                f"ON target.event_id=r.{target} WHERE assertion.event_id=target.event_id "
                "OR assertion.project_id!=target.project_id "
                "OR assertion.subject_digest!=target.subject_digest "
                "OR (assertion.retention=2 AND target.retention!=2)"
            ).fetchone()[0]
            if invalid_targets:
                report(f"{relation} target identity failed validation")
            relation_map = {
                row["assertion_event_id"]: row[target]
                for row in connection.execute(
                    f"SELECT assertion_event_id,{target} FROM {table}"
                )
            }
            resolved_relations = set()
            for start in relation_map:
                seen = set()
                cursor = start
                while cursor in relation_map and cursor not in resolved_relations:
                    if cursor in seen:
                        report(f"{relation} graph contains a cycle")
                        break
                    seen.add(cursor)
                    cursor = relation_map[cursor]
                resolved_relations.update(seen)

        evidence_by_event: dict[bytes, list[dict[str, Any]]] = {}
        for row in connection.execute("SELECT * FROM evidence ORDER BY event_id,evidence_id"):
            event = event_by_id.get(row["event_id"])
            try:
                locator = unpack_payload(row["locator"])["locator"]
                if _digest_text(locator) != row["locator_digest"]:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                report("evidence locator failed validation")
            if bool(row["locally_verified"]) != (row["verified_at"] is not None):
                report("evidence verification flag and timestamp disagree")
            if (
                event is None
                or (
                    row["verified_at"] is not None
                    and event["import_batch_id"] is None
                    and row["verified_at"] < event["observed_at"]
                )
            ):
                report("evidence verification chronology failed validation")
            evidence_by_event.setdefault(row["event_id"], []).append(dict(row))
        verification_by_event: dict[bytes, dict[str, Any]] = {}
        for row in connection.execute("SELECT * FROM verifications ORDER BY event_id"):
            verification_by_event[row["event_id"]] = dict(row)
            evidence = evidence_by_event.get(row["event_id"], [])
            event = event_by_id.get(row["event_id"])
            expected = self._evidence_set_digest(evidence)
            if (
                not evidence
                or event is None
                or (
                    event["import_batch_id"] is None
                    and row["verified_at"] < event["observed_at"]
                )
                or any(
                    item["verified_at"] is not None
                    and item["verified_at"] > row["verified_at"]
                    for item in evidence
                )
                or any(
                    item["kind"] != EVIDENCE_KINDS["source"]
                    or not item["locally_verified"]
                    or item["content_digest"] is None
                    for item in evidence
                )
                or expected != row["evidence_set_digest"]
            ):
                report("verification is not backed by its exact evidence set")

        attempts_by_event: dict[bytes, list[dict[str, Any]]] = {}
        for row in connection.execute(
            "SELECT a.*,e.observed_at,e.project_id,e.import_batch_id FROM verification_attempts a "
            "LEFT JOIN events e ON e.event_id=a.event_id "
            "ORDER BY a.event_id,a.attempt_sequence"
        ):
            attempts_by_event.setdefault(row["event_id"], []).append(dict(row))
            evidence = evidence_by_event.get(row["event_id"], [])
            expected = self._evidence_set_digest(evidence)
            successful = row["outcome"] == VERIFICATION_OUTCOMES["verified"]
            if (
                row["project_id"] != self.project_id
                or row["observed_at"] is None
                or (
                    row["import_batch_id"] is None
                    and row["checked_at"] < row["observed_at"]
                )
                or row["stored_evidence_set_digest"] != expected
                or (successful and (
                    row["failure_code"] != VERIFICATION_FAILURES["none"]
                    or row["observed_evidence_set_digest"] != expected
                ))
                or (not successful and row["failure_code"] == VERIFICATION_FAILURES["none"])
                or (
                    row["failure_code"] == VERIFICATION_FAILURES["changed"]
                    and (
                        row["observed_evidence_set_digest"] is None
                        or row["observed_evidence_set_digest"] == expected
                    )
                )
            ):
                report("verification attempt history failed validation")

        for event_id, attempts in attempts_by_event.items():
            if [item["attempt_sequence"] for item in attempts] != list(
                range(1, len(attempts) + 1)
            ) or any(
                current["checked_at"] < previous["checked_at"]
                for previous, current in zip(attempts, attempts[1:])
            ):
                report("verification attempt order failed validation")
            latest = attempts[-1]
            current_verification = verification_by_event.get(event_id)
            latest_succeeded = (
                latest["outcome"] == VERIFICATION_OUTCOMES["verified"]
            )
            if latest_succeeded:
                if (
                    current_verification is None
                    or current_verification["verified_at"] != latest["checked_at"]
                    or current_verification["verifier_policy_digest"]
                    != latest["verifier_policy_digest"]
                    or current_verification["evidence_set_digest"]
                    != latest["stored_evidence_set_digest"]
                ):
                    report("current verification differs from latest successful attempt")
            elif current_verification is not None:
                report("stale verification attempt still has current verification state")
        if set(verification_by_event) - set(attempts_by_event):
            report("current verification has no append-only attempt history")

        for row in connection.execute("SELECT * FROM workflows ORDER BY workflow_id"):
            try:
                specification = unpack_payload(row["specification"], row["specification_digest"])
                normalized = self._validate_workflow(specification.get("name", ""), {
                    "version": specification.get("version"),
                    "description": specification.get("description", ""),
                    "steps": specification.get("steps"),
                })
                if normalized != specification or row["version"] != normalized["version"]:
                    raise ValueError
                if row["name_digest"] != _digest_text(normalized["name"]):
                    raise ValueError
                event = event_by_id.get(row["event_id"])
                if (
                    event is None
                    or event["project_id"] != self.project_id
                    or event["kind"] != EVENT_KINDS["workflow"]
                    or unpack_payload(event["payload"], event["payload_digest"])
                    != normalized
                ):
                    raise ValueError
                steps = connection.execute(
                    "SELECT * FROM workflow_steps WHERE workflow_id=? ORDER BY position",
                    (row["workflow_id"],),
                ).fetchall()
                if len(steps) != len(normalized["steps"]):
                    raise ValueError
                for position, (stored, expected_step) in enumerate(
                    zip(steps, normalized["steps"], strict=True)
                ):
                    if (
                        stored["position"] != position
                        or stored["step_id_digest"] != _digest_text(expected_step["id"])
                        or stored["side_effect"] != SIDE_EFFECT_CODES[expected_step["side_effect"]]
                        or unpack_payload(stored["step_payload"]) != expected_step
                    ):
                        raise ValueError
            except (AttributeError, TypeError, ValueError):
                report("workflow specification failed validation")

        workflow_events = sum(row["kind"] == EVENT_KINDS["workflow"] for row in event_rows)
        workflow_rows = connection.execute("SELECT count(*) FROM workflows").fetchone()[0]
        if workflow_events != workflow_rows:
            report("workflow events and workflow records are not one-to-one")

        promotion_policy = hashlib.sha256(
            b"local-verification+evidence+active+promotable+historical-only:v1"
        ).digest()
        invalid_promotions = connection.execute(
            "SELECT count(*) FROM promotions p JOIN events e ON e.event_id=p.event_id "
            "LEFT JOIN verifications v ON v.event_id=e.event_id "
            "WHERE e.project_id!=? OR e.kind NOT IN (3,4,5,6,7) OR e.retention!=2 "
            "OR v.event_id IS NULL "
            "OR p.policy_digest!=? OR "
            + _eligible_supersessor_exists_sql(
                "e.event_id",
                include_untrusted=False,
                promoted_only=False,
                as_of="p.promoted_at",
            ),
            (self.project_id, promotion_policy),
        ).fetchone()[0]
        if invalid_promotions:
            report("promotion is not evidence-verified, active, and policy-bound")

        expected_event_nodes = {
            hashlib.sha256(b"event\0" + row["event_id"]).digest(): row["event_id"]
            for row in event_rows
        }
        expected_subject_nodes = {
            hashlib.sha256(b"subject\0" + row["subject_digest"]).digest()
            for row in event_rows
        }
        node_by_identity = {
            row["identity_digest"]: row
            for row in connection.execute("SELECT * FROM nodes ORDER BY node_id")
        }
        if set(node_by_identity) != set(expected_event_nodes) | expected_subject_nodes:
            report("graph node identity set differs from events")
        else:
            for identity, row in node_by_identity.items():
                if identity in expected_event_nodes:
                    if row["kind"] != 1 or row["created_event_id"] != expected_event_nodes[identity]:
                        report("event graph node kind or creator failed validation")
                else:
                    creator = event_by_id.get(row["created_event_id"])
                    if (
                        row["kind"] != 2
                        or creator is None
                        or identity
                        != hashlib.sha256(b"subject\0" + creator["subject_digest"]).digest()
                    ):
                        report("subject graph node kind or creator failed validation")

        expected_edges = set()
        for row in event_rows:
            source = hashlib.sha256(b"event\0" + row["event_id"]).digest()
            subject = hashlib.sha256(b"subject\0" + row["subject_digest"]).digest()
            expected_edges.add(
                (source, subject, 1, row["event_id"], row["observed_at"], row["valid_from"])
            )
            for target_id, kind in (
                (row["supersedes_event_id"], 2),
                (row["contradicts_event_id"], 3),
            ):
                if target_id is not None:
                    expected_edges.add(
                        (
                            source,
                            hashlib.sha256(b"event\0" + target_id).digest(),
                            kind,
                            row["event_id"],
                            row["observed_at"],
                            row["valid_from"],
                        )
                    )
        observed_edges = {
            (
                row["source_identity"], row["target_identity"], row["kind"],
                row["created_event_id"], row["recorded_at"], row["effective_at"],
            )
            for row in connection.execute(
                "SELECT source.identity_digest AS source_identity,"
                "target.identity_digest AS target_identity,e.kind,e.created_event_id,"
                "e.recorded_at,e.effective_at FROM edges e "
                "JOIN nodes source ON source.node_id=e.source_node_id "
                "JOIN nodes target ON target.node_id=e.target_node_id"
            )
        }
        if observed_edges != expected_edges:
            report("graph edge set differs from events")

        outbox_rows = connection.execute(
            "SELECT o.*,e.observed_at FROM projection_outbox o "
            "JOIN events e ON e.event_id=o.event_id ORDER BY o.outbox_id"
        ).fetchall()
        if len(outbox_rows) != len(event_rows) or any(
            row["created_at"] != row["observed_at"]
            or (
                row["attempted_at"] is not None
                and row["attempted_at"] < row["created_at"]
            )
            or (
                row["delivered_at"] is not None
                and (
                    row["attempted_at"] is None
                    or row["delivered_at"] < row["attempted_at"]
                )
            )
            for row in outbox_rows
        ):
            report("projection outbox does not exactly cover event history")
        return errors

    def status(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {
                "status": "missing",
                "schema": self.schema,
                "path": str(self.path),
                "project_id": self.project_id_text,
            }
        with self.connection(create=False, require_semantic=False) as connection:
            metadata = self._require_schema(connection)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            semantic_errors = self._semantic_errors(connection)
            counts = {
                table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in (
                    "sessions", "events", "evidence", "verifications",
                    "verification_attempts", "promotions", "nodes", "edges", "workflows",
                )
            }
            pending = connection.execute(
                "SELECT count(*) FROM projection_outbox WHERE delivered_at IS NULL"
            ).fetchone()[0]
            logical_digest = self._logical_digest(connection)
            stale_verifications = []
            for row in connection.execute(
                "SELECT event_id,verifier_policy_digest FROM verifications ORDER BY event_id"
            ):
                check = self._current_source_evidence(
                    connection,
                    row["event_id"],
                    verifier_policy_digest=row["verifier_policy_digest"],
                )
                if not check["current"]:
                    stale_verifications.append(
                        {"event_id": row["event_id"].hex(), "reason": check["reason"]}
                    )
        structurally_ready = integrity == "ok" and not foreign_keys and not semantic_errors
        ready = structurally_ready and not stale_verifications
        return {
            "status": "ready" if ready else ("stale" if structurally_ready else "corrupt"),
            "schema": self.schema,
            "path": str(self.path),
            "project_id": self.project_id_text,
            "integrity": integrity,
            "foreign_key_errors": len(foreign_keys),
            "semantic_errors": semantic_errors,
            "counts": counts,
            "projection_pending": pending,
            "stale_verification_count": len(stale_verifications),
            "stale_verifications": stale_verifications[:100],
            "logical_digest": logical_digest,
            "scanner_policy_digest_at_creation": metadata["scanner_policy_digest"],
            "current_scanner_policy_digest": policy_digest(),
            "scanner_policy_matches_creation": (
                metadata["scanner_policy_digest"] == policy_digest()
            ),
        }

    def start_session(self, task: str, *, session_id: str | None = None) -> dict[str, Any]:
        self.initialize()
        if not isinstance(task, str) or not task.strip():
            raise ValueError("session task must not be empty")
        task_value = {"task": task.strip()}
        task_payload, task_digest = pack_payload(task_value)
        sid = _id_bytes(session_id, "session_id") if session_id else _new_id()
        timestamp = now_ms()
        with self.connection(write=True) as connection:
            if connection.execute("SELECT 1 FROM sessions WHERE session_id=?", (sid,)).fetchone():
                raise ValueError("session_id already exists")
            connection.execute(
                "INSERT INTO sessions(session_id,project_id,started_at,status,task_payload,task_digest) "
                "VALUES(?,?,?,?,?,?)",
                (sid, self.project_id, timestamp, 1, task_payload, task_digest),
            )
            event = self._append_event_tx(
                connection,
                sid,
                "session_started",
                subject=f"session:{sid.hex()}",
                payload=task_value,
                evidence_rows=[],
                claimed_trust="observed",
                sensitivity="internal",
                retention="durable",
                observed_at=timestamp,
                valid_from=timestamp,
            )
        return {"session_id": sid.hex(), "started_at": timestamp, "event": event}

    def append_event(
        self,
        session_id: str,
        kind: str,
        *,
        subject: str,
        payload: Any,
        evidence: Iterable[dict[str, Any]] = (),
        supersedes: str | None = None,
        contradicts: str | None = None,
        trust: str = "observed",
        sensitivity: str = "internal",
        retention: str = "session",
        valid_from: int | None = None,
    ) -> dict[str, Any]:
        if kind in {"correction", "revocation"} and not supersedes:
            raise ValueError("correction/revocation requires a superseded event")
        sid = _id_bytes(session_id, "session_id")
        requested_observed = now_ms()
        evidence_rows = [self._prepare_evidence(item) for item in evidence]
        with self.connection(create=False, write=True) as connection:
            observed = self._next_session_observed_at(
                connection, sid, requested_observed
            )
            self._align_verified_evidence(evidence_rows, observed)
            effective = observed if valid_from is None else valid_from
            return self._append_event_tx(
                connection,
                sid,
                kind,
                subject=subject,
                payload=payload,
                evidence_rows=evidence_rows,
                supersedes=supersedes,
                contradicts=contradicts,
                claimed_trust=trust,
                sensitivity=sensitivity,
                retention=retention,
                observed_at=observed,
                valid_from=effective,
            )

    @staticmethod
    def _next_session_observed_at(
        connection: sqlite3.Connection, session_id: bytes, requested: int
    ) -> int:
        row = connection.execute(
            "SELECT s.started_at,max(e.observed_at) AS last_observed "
            "FROM sessions s LEFT JOIN events e ON e.session_id=s.session_id "
            "WHERE s.session_id=? GROUP BY s.session_id",
            (session_id,),
        ).fetchone()
        if row is None:
            raise ValueError("session does not exist in this project")
        return max(requested, row["started_at"], row["last_observed"] or 0)

    @staticmethod
    def _align_verified_evidence(
        evidence_rows: list[dict[str, Any]], observed_at: int
    ) -> None:
        for item in evidence_rows:
            if item["locally_verified"]:
                item["verified_at"] = max(item["verified_at"] or 0, observed_at)

    def _append_event_tx(
        self,
        connection: sqlite3.Connection,
        session_id: bytes,
        kind: str,
        *,
        subject: str,
        payload: Any,
        evidence_rows: list[dict[str, Any]],
        supersedes: str | None = None,
        contradicts: str | None = None,
        claimed_trust: str = "observed",
        sensitivity: str = "internal",
        retention: str = "durable",
        observed_at: int,
        valid_from: int,
        allow_closed: bool = False,
        event_id: bytes | None = None,
        import_batch_id: bytes | None = None,
        forced_sequence: int | None = None,
        subject_digest_override: bytes | None = None,
        term_digests_override: tuple[bytes, ...] | None = None,
    ) -> dict[str, Any]:
        if kind not in EVENT_KINDS:
            raise ValueError("unsupported memory event kind")
        if claimed_trust not in CLAIMED_TRUST:
            raise ValueError("trust may be only untrusted or observed; verification is evidence-derived")
        if sensitivity not in SENSITIVITY_CODES or retention not in RETENTION_CODES:
            raise ValueError("unsupported sensitivity or retention value")
        if (
            not isinstance(subject, str)
            or not subject.strip()
            or len(subject.encode("utf-8")) > MAX_SUBJECT_BYTES
        ):
            raise ValueError(
                f"memory event subject must be non-empty and at most {MAX_SUBJECT_BYTES} UTF-8 bytes"
            )
        subject_findings = scan_text(subject)
        if subject_findings:
            summary = ", ".join(
                f"{item.rule}@{item.line}" for item in subject_findings[:5]
            )
            raise ValueError(f"memory event subject rejected by privacy policy: {summary}")
        if type(observed_at) is not int or type(valid_from) is not int or observed_at < 0 or valid_from < 0:
            raise ValueError("event timestamps must be non-negative integer milliseconds")
        session = connection.execute(
            "SELECT status,started_at,ended_at FROM sessions WHERE session_id=? AND project_id=?",
            (session_id, self.project_id),
        ).fetchone()
        if session is None:
            raise ValueError("session does not exist in this project")
        if session["status"] != 1 and not allow_closed:
            raise ValueError("session is closed")
        if (
            observed_at < session["started_at"]
            or (session["ended_at"] is not None and observed_at > session["ended_at"])
        ):
            raise ValueError("event observed_at must fall inside its session record")
        previous = connection.execute(
            "SELECT observed_at FROM events WHERE session_id=? "
            "ORDER BY sequence DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if (
            import_batch_id is None
            and previous is not None
            and observed_at < previous["observed_at"]
        ):
            raise ValueError("event observed_at must not precede prior session history")
        predecessor = _id_bytes(supersedes, "supersedes") if supersedes else None
        opposed = _id_bytes(contradicts, "contradicts") if contradicts else None
        subject_digest = subject_digest_override or _digest_text(subject.strip())
        if len(subject_digest) != 32:
            raise ValueError("memory event subject digest must be SHA-256")
        if predecessor is not None:
            previous = connection.execute(
                "SELECT subject_digest,retention FROM events WHERE event_id=? AND project_id=?",
                (predecessor, self.project_id),
            ).fetchone()
            if previous is None or previous["subject_digest"] != subject_digest:
                raise ValueError("supersession must reference the same subject in this project")
            if retention == "durable" and previous["retention"] != RETENTION_CODES["durable"]:
                raise ValueError("durable supersession cannot depend on non-durable history")
        if opposed is not None:
            previous = connection.execute(
                "SELECT subject_digest,retention FROM events WHERE event_id=? AND project_id=?",
                (opposed, self.project_id),
            ).fetchone()
            if previous is None or previous["subject_digest"] != subject_digest:
                raise ValueError("contradiction must reference the same subject in this project")
            if retention == "durable" and previous["retention"] != RETENTION_CODES["durable"]:
                raise ValueError("durable contradiction cannot depend on non-durable history")
        packed, payload_digest = pack_payload(payload)
        term_digests = (
            list(term_digests_override)
            if term_digests_override is not None
            else _term_digests({"subject": subject, "payload": payload, "kind": kind})
        )
        terms_digest = _term_set_digest(term_digests)
        sequence = forced_sequence or connection.execute(
            "SELECT coalesce(max(sequence),0)+1 FROM events WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        eid = event_id or _new_id()
        record_digest = _event_record_digest(
            self.project_id,
            session_id,
            eid,
            sequence,
            EVENT_KINDS[kind],
            subject_digest,
            terms_digest,
            observed_at,
            valid_from,
            predecessor,
            opposed,
            CLAIMED_TRUST[claimed_trust],
            SENSITIVITY_CODES[sensitivity],
            RETENTION_CODES[retention],
            payload_digest,
            import_batch_id,
        )
        connection.execute(
            "INSERT INTO events(event_id,project_id,session_id,sequence,kind,subject_digest,terms_digest,"
            "observed_at,valid_from,supersedes_event_id,contradicts_event_id,claimed_trust,"
            "sensitivity,retention,payload_codec,payload,payload_digest,record_digest,import_batch_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid, self.project_id, session_id, sequence, EVENT_KINDS[kind], subject_digest,
                terms_digest,
                observed_at, valid_from, predecessor, opposed, CLAIMED_TRUST[claimed_trust],
                SENSITIVITY_CODES[sensitivity], RETENTION_CODES[retention], PAYLOAD_CODEC,
                packed, payload_digest, record_digest, import_batch_id,
            ),
        )
        if predecessor is not None:
            connection.execute(
                "INSERT INTO supersessions(assertion_event_id,predecessor_event_id,recorded_at,effective_at) "
                "VALUES(?,?,?,?)",
                (eid, predecessor, observed_at, valid_from),
            )
        if opposed is not None:
            connection.execute(
                "INSERT INTO contradictions(assertion_event_id,opposed_event_id,recorded_at,effective_at) "
                "VALUES(?,?,?,?)",
                (eid, opposed, observed_at, valid_from),
            )
        for term in term_digests:
            connection.execute("INSERT INTO event_terms(event_id,term_digest) VALUES(?,?)", (eid, term))
        for item in evidence_rows:
            connection.execute(
                "INSERT INTO evidence(evidence_id,event_id,kind,locator,locator_digest,content_digest,"
                "locally_verified,verified_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    item["evidence_id"], eid, item["kind"], item["locator"], item["locator_digest"],
                    item["content_digest"], item["locally_verified"], item["verified_at"],
                ),
            )
        if evidence_rows and all(item["locally_verified"] for item in evidence_rows):
            verification_timestamp = max(
                now_ms(),
                observed_at,
                *(item["verified_at"] for item in evidence_rows if item["verified_at"] is not None),
            )
            self._insert_verification(
                connection, eid, evidence_rows, verification_timestamp
            )
        self._write_event_graph(
            connection, eid, subject_digest, predecessor, opposed, observed_at, valid_from
        )
        connection.execute(
            "INSERT INTO projection_outbox(event_id,created_at) VALUES(?,?)", (eid, observed_at)
        )
        return {
            "event_id": eid.hex(),
            "session_id": session_id.hex(),
            "sequence": sequence,
            "kind": kind,
            "observed_at": observed_at,
            "valid_from": valid_from,
            "supersedes": supersedes,
            "contradicts": contradicts,
            "record_digest": record_digest.hex(),
            "verified": bool(evidence_rows and all(item["locally_verified"] for item in evidence_rows)),
            "authority": "historical_only",
            "authorizes_actions": False,
            "projection_pending": True,
        }

    def _prepare_evidence(self, item: dict[str, Any]) -> dict[str, Any]:
        from .locators import SourceLocator
        if isinstance(item, dict) and isinstance(item.get("locator"), dict):
            item = {**item, "locator": SourceLocator.from_dict(item["locator"]).encode()}
        if not isinstance(item, dict) or not isinstance(item.get("locator"), str):
            raise ValueError("evidence requires a string locator")
        kind_name = item.get("kind", "source")
        if kind_name not in EVIDENCE_KINDS:
            raise ValueError("unsupported evidence kind")
        locator = item["locator"].strip()
        if not locator:
            raise ValueError("evidence locator must not be empty")
        locator_payload, _ = pack_payload({"locator": locator})
        provided_digest = item.get("content_digest")
        digest = None
        verified = False
        if kind_name == "source":
            digest = self._source_evidence_digest(locator)
            verified = provided_digest is None or provided_digest == digest.hex()
            if provided_digest is not None and not verified:
                raise ValueError("source evidence digest does not match current repository bytes")
        elif provided_digest is not None:
            if not isinstance(provided_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", provided_digest):
                raise ValueError("evidence content_digest must be lowercase hexadecimal SHA-256")
            digest = bytes.fromhex(provided_digest)
        return {
            "evidence_id": _new_id(),
            "kind": EVIDENCE_KINDS[kind_name],
            "locator": locator_payload,
            "locator_digest": _digest_text(locator),
            "content_digest": digest,
            "locally_verified": int(verified),
            "verified_at": now_ms() if verified else None,
        }

    def _source_evidence_digest(self, locator: str) -> bytes:
        from .locators import LOCATOR_PREFIX, SourceLocator, resolve_locator
        if locator.startswith(LOCATOR_PREFIX):
            raw = resolve_locator(SourceLocator.decode(locator), self.root, self.source_resolvers)
            return hashlib.sha256(raw).digest()
        match = re.fullmatch(r"([^:]+):(\d+)(?:-(\d+))?", locator)
        if match is None:
            raise ValueError("source evidence must be path:start or path:start-end")
        relative, first_raw, last_raw = match.groups()
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("source evidence path must be repository-relative")
        try:
            raw = read_bounded_file(self.root, relative_path, max_bytes=1_000_000)
        except ValueError as exc:
            raise ValueError("source evidence must be a readable non-symlink file") from exc
        try:
            lines = raw.decode("utf-8", errors="strict").splitlines()
        except UnicodeError as exc:
            raise ValueError("source evidence must be UTF-8") from exc
        first = int(first_raw)
        last = int(last_raw or first_raw)
        if first < 1 or last < first or last > len(lines):
            raise ValueError("source evidence line range is outside the file")
        return hashlib.sha256("\n".join(lines[first - 1 : last]).encode("utf-8")).digest()

    @staticmethod
    def _evidence_set_digest(evidence_rows: Iterable[Any]) -> bytes:
        return hashlib.sha256(
            b"".join(
                sorted(
                    item["locator_digest"] + (item["content_digest"] or b"")
                    for item in evidence_rows
                )
            )
        ).digest()

    @staticmethod
    def _record_verification_attempt(
        connection: sqlite3.Connection,
        event_id: bytes,
        timestamp: int,
        *,
        outcome: str,
        failure: str,
        stored_digest: bytes,
        observed_digest: bytes | None,
    ) -> int:
        previous = connection.execute(
            "SELECT attempt_sequence,checked_at FROM verification_attempts "
            "WHERE event_id=? ORDER BY attempt_sequence DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        sequence = 1 if previous is None else previous["attempt_sequence"] + 1
        # Preserve real serialized order even when the wall clock has coarse
        # millisecond resolution or moves backwards. Equal timestamps remain
        # valid; attempt_sequence is the authoritative tie breaker.
        checked_at = (
            timestamp
            if previous is None
            else max(timestamp, previous["checked_at"])
        )
        connection.execute(
            "INSERT INTO verification_attempts("
            "attempt_id,event_id,attempt_sequence,checked_at,outcome,failure_code,"
            "verifier_policy_digest,stored_evidence_set_digest,observed_evidence_set_digest) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                _new_id(), event_id, sequence, checked_at, VERIFICATION_OUTCOMES[outcome],
                VERIFICATION_FAILURES[failure], bytes.fromhex(policy_digest()), stored_digest,
                observed_digest,
            ),
        )
        return checked_at

    def _insert_verification(
        self,
        connection: sqlite3.Connection,
        event_id: bytes,
        evidence_rows: list[dict[str, Any]],
        timestamp: int,
    ) -> int:
        evidence_digest = self._evidence_set_digest(evidence_rows)
        verified_at = self._record_verification_attempt(
            connection,
            event_id,
            timestamp,
            outcome="verified",
            failure="none",
            stored_digest=evidence_digest,
            observed_digest=evidence_digest,
        )
        connection.execute(
            "INSERT OR REPLACE INTO verifications("
            "event_id,verified_at,verifier_policy_digest,evidence_set_digest) VALUES(?,?,?,?)",
            (event_id, verified_at, bytes.fromhex(policy_digest()), evidence_digest),
        )
        return verified_at

    def _current_source_evidence(
        self,
        connection: sqlite3.Connection,
        event_id: bytes,
        *,
        verifier_policy_digest: bytes | None = None,
    ) -> dict[str, Any]:
        """Reopen source evidence once and report current derived trust without mutating history."""
        rows = connection.execute(
            "SELECT * FROM evidence WHERE event_id=? ORDER BY evidence_id", (event_id,)
        ).fetchall()
        stored_digest = self._evidence_set_digest(rows)
        if not rows or any(
            row["kind"] != EVIDENCE_KINDS["source"] or row["content_digest"] is None
            for row in rows
        ):
            return {
                "current": False,
                "reason": "unsupported",
                "stored_digest": stored_digest,
                "observed_digest": None,
                "rows": rows,
            }
        if (
            verifier_policy_digest is not None
            and verifier_policy_digest != bytes.fromhex(policy_digest())
        ):
            return {
                "current": False,
                "reason": "policy_changed",
                "stored_digest": stored_digest,
                "observed_digest": None,
                "rows": rows,
            }
        observed_rows = []
        try:
            for row in rows:
                locator = unpack_payload(row["locator"])["locator"]
                observed_rows.append(
                    {
                        "locator_digest": row["locator_digest"],
                        "content_digest": self._source_evidence_digest(locator),
                    }
                )
        except (KeyError, TypeError, ValueError):
            return {
                "current": False,
                "reason": "unavailable",
                "stored_digest": stored_digest,
                "observed_digest": None,
                "rows": rows,
            }
        observed_digest = self._evidence_set_digest(observed_rows)
        return {
            "current": observed_digest == stored_digest,
            "reason": "none" if observed_digest == stored_digest else "changed",
            "stored_digest": stored_digest,
            "observed_digest": observed_digest,
            "rows": rows,
        }

    def _verification_state(
        self,
        connection: sqlite3.Connection,
        event_id: bytes,
        cache: dict[tuple[bytes, int], str] | None = None,
        *,
        known_at: int | None = None,
    ) -> str:
        boundary = now_ms() if known_at is None else known_at
        cache_key = (event_id, boundary)
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        # Trust is bitemporal too.  A successful verification performed after
        # the requested knowledge boundary must not retrospectively admit an
        # imported/untrusted event or let it suppress an earlier fact.
        attempt = connection.execute(
            "SELECT outcome,verifier_policy_digest,stored_evidence_set_digest "
            "FROM verification_attempts WHERE event_id=? AND checked_at<=? "
            "ORDER BY attempt_sequence DESC LIMIT 1",
            (event_id, boundary),
        ).fetchone()
        if attempt is None:
            state = "unverified"
        elif attempt["outcome"] == VERIFICATION_OUTCOMES["stale"]:
            state = "stale"
        else:
            check = self._current_source_evidence(
                connection,
                event_id,
                verifier_policy_digest=attempt["verifier_policy_digest"],
            )
            state = (
                "current"
                if check["current"]
                and check["stored_digest"] == attempt["stored_evidence_set_digest"]
                else "stale"
            )
        if cache is not None:
            cache[cache_key] = state
        return state

    def _verification_is_current(
        self,
        connection: sqlite3.Connection,
        event_id: bytes,
        cache: dict[tuple[bytes, int], str] | None = None,
        *,
        known_at: int | None = None,
    ) -> bool:
        return (
            self._verification_state(
                connection, event_id, cache, known_at=known_at
            )
            == "current"
        )

    def _has_eligible_current_supersessor(
        self,
        connection: sqlite3.Connection,
        predecessor: bytes,
        *,
        known_at: int,
        valid_at: int,
        include_untrusted: bool,
        promoted_only: bool,
        verification_cache: dict[tuple[bytes, int], str],
    ) -> bool:
        rows = connection.execute(
            "SELECT assertion.event_id,assertion.claimed_trust,"
            "p.event_id AS promoted_event_id,p.promoted_at "
            "FROM supersessions s JOIN events assertion "
            "ON assertion.event_id=s.assertion_event_id "
            "LEFT JOIN promotions p ON p.event_id=assertion.event_id "
            "WHERE s.predecessor_event_id=? AND assertion.project_id=? "
            "AND s.recorded_at<=? AND s.effective_at<=?",
            (predecessor, self.project_id, known_at, valid_at),
        ).fetchall()
        for row in rows:
            state = self._verification_state(
                connection,
                row["event_id"],
                verification_cache,
                known_at=known_at,
            )
            if state == "stale":
                continue
            if promoted_only:
                if (
                    row["promoted_event_id"] is not None
                    and row["promoted_at"] <= known_at
                    and state == "current"
                ):
                    return True
            elif include_untrusted or row["claimed_trust"] == CLAIMED_TRUST["observed"]:
                return True
            elif state == "current":
                return True
        return False

    def _write_event_graph(
        self,
        connection: sqlite3.Connection,
        event_id: bytes,
        subject_digest: bytes,
        predecessor: bytes | None,
        opposed: bytes | None,
        recorded_at: int,
        effective_at: int,
    ) -> None:
        event_node = self._ensure_node(
            connection, 1, hashlib.sha256(b"event\0" + event_id).digest(), event_id
        )
        subject_node = self._ensure_node(
            connection, 2, hashlib.sha256(b"subject\0" + subject_digest).digest(), event_id
        )
        self._ensure_edge(connection, event_node, subject_node, 1, event_id, recorded_at, effective_at)
        if predecessor is not None:
            previous_node = self._ensure_node(
                connection, 1, hashlib.sha256(b"event\0" + predecessor).digest(), predecessor
            )
            self._ensure_edge(connection, event_node, previous_node, 2, event_id, recorded_at, effective_at)
        if opposed is not None:
            opposed_node = self._ensure_node(
                connection, 1, hashlib.sha256(b"event\0" + opposed).digest(), opposed
            )
            self._ensure_edge(
                connection, event_node, opposed_node, 3, event_id, recorded_at, effective_at
            )

    @staticmethod
    def _ensure_node(
        connection: sqlite3.Connection, kind: int, identity: bytes, event_id: bytes
    ) -> bytes:
        row = connection.execute("SELECT node_id FROM nodes WHERE identity_digest=?", (identity,)).fetchone()
        if row:
            return row["node_id"]
        node_id = _new_id()
        connection.execute(
            "INSERT INTO nodes(node_id,kind,identity_digest,created_event_id) VALUES(?,?,?,?)",
            (node_id, kind, identity, event_id),
        )
        return node_id

    @staticmethod
    def _ensure_edge(
        connection: sqlite3.Connection,
        source: bytes,
        target: bytes,
        kind: int,
        event_id: bytes,
        recorded_at: int,
        effective_at: int,
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO edges(edge_id,source_node_id,target_node_id,kind,created_event_id,"
            "recorded_at,effective_at) VALUES(?,?,?,?,?,?,?)",
            (_new_id(), source, target, kind, event_id, recorded_at, effective_at),
        )

    def close_session(
        self,
        session_id: str,
        *,
        outcome: str,
        evidence: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        if not isinstance(outcome, str) or not outcome.strip():
            raise ValueError("session outcome must not be empty")
        sid = _id_bytes(session_id, "session_id")
        requested_timestamp = now_ms()
        evidence_list = list(evidence)
        evidence_rows = [self._prepare_evidence(item) for item in evidence_list]
        with self.connection(create=False, write=True) as connection:
            row = connection.execute(
                "SELECT status FROM sessions WHERE session_id=? AND project_id=?", (sid, self.project_id)
            ).fetchone()
            if row is None or row["status"] != 1:
                raise ValueError("session is missing or already closed")
            timestamp = self._next_session_observed_at(
                connection, sid, requested_timestamp
            )
            self._align_verified_evidence(evidence_rows, timestamp)
            event = self._append_event_tx(
                connection,
                sid,
                "session_closed",
                subject=f"session:{session_id}",
                payload={"outcome": outcome.strip()},
                evidence_rows=evidence_rows,
                claimed_trust="observed",
                sensitivity="internal",
                retention="durable",
                observed_at=timestamp,
                valid_from=timestamp,
            )
            connection.execute(
                "UPDATE sessions SET status=2,ended_at=? WHERE session_id=?", (timestamp, sid)
            )
        return {"session_id": session_id, "status": "closed", "event": event}

    def recall(
        self,
        query: str,
        *,
        limit: int = 10,
        known_at: int | None = None,
        valid_at: int | None = None,
        include_history: bool = False,
        include_untrusted: bool = False,
        promoted_only: bool = False,
        max_sensitivity: str = "secret",
        session_id: str | None = None,
        retention: str | None = None,
        visibility: str = "audit",
        result_filter: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("recall query must not be empty")
        if len(query.encode("utf-8")) > MAX_QUERY_BYTES:
            raise ValueError(f"recall query exceeds {MAX_QUERY_BYTES} UTF-8 bytes")
        lexical_terms = re.findall(r"[A-Za-z0-9_]+", query)
        if len(lexical_terms) > MAX_QUERY_TERMS:
            raise ValueError(f"recall query exceeds {MAX_QUERY_TERMS} lexical terms")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("recall limit must be between 1 and 100")
        for label, timestamp in (("known_at", known_at), ("valid_at", valid_at)):
            if timestamp is not None and (type(timestamp) is not int or timestamp < 0):
                raise ValueError(f"{label} must be a non-negative integer millisecond timestamp")
        if max_sensitivity not in SENSITIVITY_CODES or visibility not in {"audit", "current"}:
            raise ValueError("unsupported recall sensitivity or visibility")
        if retention is not None and retention not in RETENTION_CODES:
            raise ValueError("unsupported recall retention")
        selected_session = _id_bytes(session_id, "session_id") if session_id else None
        terms = _term_digests(query)
        known = now_ms() if known_at is None else known_at
        valid = known if valid_at is None else valid_at
        if not terms:
            return {"query": query, "known_at": known, "valid_at": valid, "results": []}
        placeholders = ",".join("?" for _ in terms)
        promotion_clause = (
            "AND p.event_id IS NOT NULL AND p.promoted_at<=? AND v.event_id IS NOT NULL"
            if promoted_only
            else ""
        )
        scope_clauses = ["e.sensitivity<=?"]
        scope_arguments: list[Any] = [SENSITIVITY_CODES[max_sensitivity]]
        if retention is not None:
            scope_clauses.append("e.retention=?")
            scope_arguments.append(RETENTION_CODES[retention])
        if visibility == "current":
            scope_clauses.append("(e.retention=2 OR (e.session_id=? AND EXISTS(SELECT 1 FROM sessions active WHERE active.session_id=e.session_id AND active.status=1)))")
            scope_arguments.append(selected_session)
        elif selected_session is not None:
            scope_clauses.append("e.session_id=?")
            scope_arguments.append(selected_session)
        scope_sql = " AND ".join(scope_clauses)
        sql = f"""
            SELECT e.*,count(DISTINCT t.term_digest) AS matches,p.promoted_at,v.verified_at
            FROM event_terms t
            JOIN events e ON e.event_id=t.event_id
            LEFT JOIN promotions p ON p.event_id=e.event_id
            LEFT JOIN verifications v ON v.event_id=e.event_id
            WHERE t.term_digest IN ({placeholders})
              AND e.project_id=? AND e.observed_at<=? AND e.valid_from<=?
              {promotion_clause}
              AND {scope_sql}
            GROUP BY e.event_id
            ORDER BY matches DESC,e.observed_at DESC,e.sequence DESC
            LIMIT ?
        """
        arguments: list[Any] = [*terms, self.project_id, known, valid]
        if promoted_only:
            arguments.append(known)
        arguments.extend(scope_arguments)
        arguments.append(MAX_RECALL_CANDIDATES + 1)
        with self.connection(create=False, write=bool(getattr(self, "pin_reads", False) and session_id)) as connection:
            self._require_schema(connection)
            candidate_rows = connection.execute(sql, arguments).fetchall()
            candidate_scan_truncated = len(candidate_rows) > MAX_RECALL_CANDIDATES
            verification_cache: dict[tuple[bytes, int], str] = {}
            results = []
            for row in candidate_rows[:MAX_RECALL_CANDIDATES]:
                if visibility == "current" and row["kind"] in (EVENT_KINDS["revocation"], EVENT_KINDS["session_started"], EVENT_KINDS["session_closed"]):
                    continue
                state = self._verification_state(
                    connection,
                    row["event_id"],
                    verification_cache,
                    known_at=known,
                )
                if not include_history and state == "stale":
                    continue
                if promoted_only and state != "current":
                    continue
                if (
                    not include_untrusted
                    and row["claimed_trust"] == CLAIMED_TRUST["untrusted"]
                    and state != "current"
                ):
                    continue
                if (
                    not include_history
                    and self._has_eligible_current_supersessor(
                        connection,
                        row["event_id"],
                        known_at=known,
                        valid_at=valid,
                        include_untrusted=include_untrusted,
                        promoted_only=promoted_only and visibility != "current",
                        verification_cache=verification_cache,
                    )
                ):
                    continue
                result = self._event_result(connection, row, verified_override=(state == "current"), known_at=known)
                if result_filter is not None and not result_filter(result):
                    continue
                results.append(result)
                if len(results) == limit:
                    break
            if getattr(self, "pin_reads", False) and session_id:
                self._pin_read_tx(connection, session_id, [r["event_id"] for r in results])
        return {
            "query": query,
            "known_at": known,
            "valid_at": valid,
            "include_history": include_history,
            "include_untrusted": include_untrusted,
            "promoted_only": promoted_only,
            "max_sensitivity": max_sensitivity,
            "visibility": visibility,
            "candidate_scan_limit": MAX_RECALL_CANDIDATES,
            "candidate_scan_truncated": candidate_scan_truncated,
            "results": results,
        }

    def _event_result(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        verified_override: bool | None = None,
        known_at: int | None = None,
    ) -> dict[str, Any]:
        evidence = []
        for item in connection.execute(
            "SELECT kind,locator,content_digest,locally_verified FROM evidence "
            "WHERE event_id=? ORDER BY evidence_id",
            (row["event_id"],),
        ):
            evidence.append(
                {
                    "kind": item["kind"],
                    "locator": unpack_payload(item["locator"])["locator"],
                    "content_digest": item["content_digest"].hex() if item["content_digest"] else None,
                    "locally_verified": bool(item["locally_verified"]),
                }
            )
        verified = (
            verified_override
            if verified_override is not None
            else (row["verified_at"] is not None if "verified_at" in row.keys() else False)
        )
        result = {
            "event_id": row["event_id"].hex(),
            "session_id": row["session_id"].hex(),
            "sequence": row["sequence"],
            "kind": EVENT_KIND_NAMES[row["kind"]],
            "observed_at": row["observed_at"],
            "valid_from": row["valid_from"],
            "supersedes": row["supersedes_event_id"].hex() if row["supersedes_event_id"] else None,
            "contradicts": row["contradicts_event_id"].hex()
            if row["contradicts_event_id"] else None,
            "claimed_trust": CLAIMED_TRUST_NAMES[row["claimed_trust"]],
            "trust": "verified" if verified else CLAIMED_TRUST_NAMES[row["claimed_trust"]],
            "source_integrity": "current" if verified else "unverified_or_stale",
            "verification_kind": "source_bytes_only",
            "sensitivity": SENSITIVITY_NAMES[row["sensitivity"]],
            "retention": RETENTION_NAMES[row["retention"]],
            "payload": unpack_payload(row["payload"], row["payload_digest"]),
            "record_digest": row["record_digest"].hex(),
            "evidence": evidence,
            "promoted": (
                row["promoted_at"] is not None
                and (known_at is None or row["promoted_at"] <= known_at)
                if "promoted_at" in row.keys()
                else False
            ),
            "imported": row["import_batch_id"] is not None,
            "authority": "historical_only",
            "authorizes_actions": False,
            "score": row["matches"] if "matches" in row.keys() else None,
        }

        from .experience import claim_support
        result["claim_support"] = claim_support(result, self.root)
        return result

    def reverify(self, event_id: str) -> dict[str, Any]:
        eid = _id_bytes(event_id, "event_id")
        with self.connection(create=False, write=True) as connection:
            event = connection.execute(
                "SELECT event_id,observed_at FROM events WHERE event_id=? AND project_id=?",
                (eid, self.project_id),
            ).fetchone()
            if event is None:
                raise ValueError("event does not exist in this project")
            existing = connection.execute(
                "SELECT verified_at FROM verifications WHERE event_id=?", (eid,)
            ).fetchone()
            check = self._current_source_evidence(connection, eid)
            if not check["rows"]:
                raise ValueError("event has no evidence to verify")
            if check["reason"] == "unsupported":
                raise ValueError("only source evidence can be locally reverified")
            timestamp = now_ms()
            if not check["current"]:
                connection.execute(
                    "UPDATE evidence SET locally_verified=0,verified_at=NULL WHERE event_id=?",
                    (eid,),
                )
                invalidated_promotion = connection.execute(
                    "DELETE FROM promotions WHERE event_id=?", (eid,)
                ).rowcount
                invalidated_verification = connection.execute(
                    "DELETE FROM verifications WHERE event_id=?", (eid,)
                ).rowcount
                timestamp = self._record_verification_attempt(
                    connection,
                    eid,
                    timestamp,
                    outcome="stale",
                    failure=check["reason"],
                    stored_digest=check["stored_digest"],
                    observed_digest=check["observed_digest"],
                )
                return {
                    "event_id": event_id,
                    "verified": False,
                    "stale": True,
                    "reason": check["reason"],
                    "invalidated_previous_verification": bool(invalidated_verification),
                    "invalidated_promotion": bool(invalidated_promotion),
                    "checked_at": timestamp,
                    "authority": "historical_only",
                    "authorizes_actions": False,
                }
            prepared = [
                {
                    "locator_digest": row["locator_digest"],
                    "content_digest": row["content_digest"],
                }
                for row in check["rows"]
            ]
            timestamp = self._insert_verification(
                connection, eid, prepared, timestamp
            )
            connection.execute(
                "UPDATE evidence SET locally_verified=1,verified_at=? WHERE event_id=?",
                (timestamp, eid),
            )
        return {
            "event_id": event_id,
            "verified": True,
            "verified_at": timestamp,
            "already_verified": existing is not None,
            "authority": "historical_only",
            "authorizes_actions": False,
        }

    def consolidate(self, session_id: str, *, require_claim_support: bool = False) -> dict[str, Any]:
        sid = _id_bytes(session_id, "session_id")
        requested_timestamp = now_ms()
        promotion_policy = hashlib.sha256(
            b"local-verification+evidence+active+promotable+historical-only:v1"
        ).digest()
        promoted = []
        with self.connection(create=False, write=True) as connection:
            session = connection.execute(
                "SELECT status,ended_at FROM sessions WHERE session_id=? AND project_id=?",
                (sid, self.project_id),
            ).fetchone()
            if session is None or session["status"] != 2:
                raise ValueError("only a closed session in this project can be consolidated")
            timestamp = max(requested_timestamp, session["ended_at"])
            rows = connection.execute(
                f"""
                SELECT e.event_id FROM events e
                JOIN verifications v ON v.event_id=e.event_id
                WHERE e.session_id=? AND e.project_id=? AND e.kind IN (3,4,5,6,7)
                  AND e.retention=2 AND e.observed_at<=? AND e.valid_from<=?
                  AND EXISTS(SELECT 1 FROM evidence x WHERE x.event_id=e.event_id)
                ORDER BY e.sequence
                """,
                (sid, self.project_id, timestamp, timestamp),
            ).fetchall()
            verification_cache: dict[tuple[bytes, int], str] = {}
            for row in rows:
                if not self._verification_is_current(
                    connection,
                    row["event_id"],
                    verification_cache,
                    known_at=timestamp,
                ):
                    continue
                if self._has_eligible_current_supersessor(
                    connection,
                    row["event_id"],
                    known_at=timestamp,
                    valid_at=timestamp,
                    include_untrusted=False,
                    promoted_only=False,
                    verification_cache=verification_cache,
                ):
                    continue
                if require_claim_support:
                    supported_row = connection.execute("SELECT * FROM events WHERE event_id=?", (row["event_id"],)).fetchone()
                    result = self._event_result(connection, supported_row, verified_override=True)
                    if result["claim_support"] != "exact_source_quote":
                        continue
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO promotions(event_id,promoted_at,policy_digest) VALUES(?,?,?)",
                    (row["event_id"], timestamp, promotion_policy),
                ).rowcount
                if inserted:
                    promoted.append(row["event_id"].hex())
        return {
            "session_id": session_id,
            "promoted": promoted,
            "promoted_count": len(promoted),
            "policy_digest": promotion_policy.hex(),
            "authority": "historical_only",
            "authorizes_actions": False,
        }

    def put_workflow(
        self,
        session_id: str,
        name: str,
        specification: dict[str, Any],
        *,
        evidence: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = self._validate_workflow(name, specification)
        requested_timestamp = now_ms()
        evidence_rows = [self._prepare_evidence(item) for item in evidence]
        if not evidence_rows or not all(item["locally_verified"] for item in evidence_rows):
            raise ValueError("workflow storage requires locally verified source evidence")
        sid = _id_bytes(session_id, "session_id")
        workflow_id = _new_id()
        packed, digest = pack_payload(normalized)
        with self.connection(create=False, write=True) as connection:
            timestamp = self._next_session_observed_at(
                connection, sid, requested_timestamp
            )
            self._align_verified_evidence(evidence_rows, timestamp)
            event = self._append_event_tx(
                connection,
                sid,
                "workflow",
                subject=f"workflow:{name.strip()}",
                payload=normalized,
                evidence_rows=evidence_rows,
                claimed_trust="observed",
                sensitivity="internal",
                retention="durable",
                observed_at=timestamp,
                valid_from=timestamp,
            )
            connection.execute(
                "INSERT INTO workflows(workflow_id,event_id,name_digest,version,specification,"
                "specification_digest) VALUES(?,?,?,?,?,?)",
                (
                    workflow_id, bytes.fromhex(event["event_id"]), _digest_text(name.strip()),
                    normalized["version"], packed, digest,
                ),
            )
            for position, step in enumerate(normalized["steps"]):
                step_payload, _ = pack_payload(step)
                connection.execute(
                    "INSERT INTO workflow_steps(workflow_id,position,step_id_digest,side_effect,"
                    "step_payload) VALUES(?,?,?,?,?)",
                    (
                        workflow_id, position, _digest_text(step["id"]),
                        SIDE_EFFECT_CODES[step["side_effect"]], step_payload,
                    ),
                )
        return {
            "workflow_id": workflow_id.hex(),
            "event": event,
            "steps": len(normalized["steps"]),
        }

    @staticmethod
    def _validate_workflow(name: str, specification: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or not isinstance(specification, dict):
            raise ValueError("workflow requires a name and object specification")
        version = specification.get("version")
        steps = specification.get("steps")
        description = specification.get("description", "")
        if (
            type(version) is not int
            or version < 1
            or not isinstance(description, str)
            or not isinstance(steps, list)
            or not steps
        ):
            raise ValueError("workflow requires a positive version and non-empty steps")
        required = {"id", "action", "preconditions", "expected", "rollback", "side_effect"}
        normalized_steps = []
        for position, step in enumerate(steps):
            if not isinstance(step, dict) or set(step) != required:
                raise ValueError(f"workflow step {position} must contain exactly {sorted(required)}")
            if not all(isinstance(step[key], str) and step[key].strip() for key in required):
                raise ValueError(f"workflow step {position} fields must be non-empty strings")
            if step["side_effect"] not in SIDE_EFFECT_CODES:
                raise ValueError(f"workflow step {position} has an invalid side_effect")
            normalized_steps.append({key: step[key].strip() for key in sorted(required)})
        allowed_top = {"version", "steps", "description"}
        if set(specification) - allowed_top:
            raise ValueError("workflow specification contains unsupported fields")
        return {
            "name": name.strip(),
            "version": version,
            "description": description.strip(),
            "steps": normalized_steps,
            "execution_policy": "dry-run-only",
            "past_authorization_replayed": False,
        }

    def workflow_dry_run(self, workflow_id: str) -> dict[str, Any]:
        wid = _id_bytes(workflow_id, "workflow_id")
        with self.connection(create=False) as connection:
            row = connection.execute(
                "SELECT w.*,v.verified_at FROM workflows w "
                "LEFT JOIN verifications v ON v.event_id=w.event_id WHERE w.workflow_id=?",
                (wid,),
            ).fetchone()
            if row is None:
                raise ValueError("workflow does not exist")
            specification = unpack_payload(row["specification"], row["specification_digest"])
            evidence_count = connection.execute(
                "SELECT count(*) FROM evidence WHERE event_id=?", (row["event_id"],)
            ).fetchone()[0]
            verification_current = self._verification_is_current(
                connection, row["event_id"]
            )
        return {
            "workflow_id": workflow_id,
            "mode": "dry-run",
            "will_execute": False,
            "verified": verification_current,
            "evidence_count": evidence_count,
            "authority": "historical_only",
            "authorizes_actions": False,
            "past_authorization_replayed": False,
            "steps": [
                {
                    "position": position,
                    **step,
                    "will_execute": False,
                }
                for position, step in enumerate(specification["steps"])
            ],
        }

    @staticmethod
    def _epoch_hot_namespace(
        connection: sqlite3.Connection, base_namespace: str
    ) -> str:
        if (
            not isinstance(base_namespace, str)
            or not base_namespace
            or len(base_namespace.encode("utf-8")) > 1_024
        ):
            raise ValueError("hot projection namespace is invalid")
        row = connection.execute(
            "SELECT value FROM metadata WHERE key='hot_projection_epoch'"
        ).fetchone()
        try:
            epoch = row["value"].decode("ascii")
        except (AttributeError, KeyError, TypeError, UnicodeError) as exc:
            raise ValueError("durable ledger hot projection epoch is invalid") from exc
        if re.fullmatch(r"[0-9a-f]{32}", epoch) is None:
            raise ValueError("durable ledger hot projection epoch is invalid")
        return f"{base_namespace}:epoch:{epoch}"

    def hot_projection_namespace(self, base_namespace: str) -> str:
        """Return this ledger instance's disposable Redis projection namespace."""
        with self.connection(create=False) as connection:
            return self._epoch_hot_namespace(connection, base_namespace)

    def reset_hot_projection(self) -> dict[str, Any]:
        """Make every ledger-committed event eligible for hot-cache reconciliation."""
        with self.connection(create=False, write=True) as connection:
            changed = connection.execute(
                "UPDATE projection_outbox SET delivered_at=NULL WHERE event_id IN "
                "(SELECT event_id FROM events WHERE project_id=?) AND delivered_at IS NOT NULL",
                (self.project_id,),
            ).rowcount
            total = connection.execute(
                "SELECT count(*) FROM projection_outbox o JOIN events e ON e.event_id=o.event_id "
                "WHERE e.project_id=?",
                (self.project_id,),
            ).fetchone()[0]
        return {"reset": changed, "eligible": total}

    def project_outbox(
        self,
        client: Any,
        hot_namespace: str,
        *,
        limit: int = 100,
        force: bool = False,
    ) -> dict[str, Any]:
        client.require_trusted_write_endpoint()
        if not 1 <= limit <= 1_000:
            raise ValueError("projection limit must be between 1 and 1000")
        script = """
            local expected={
              'event',ARGV[2],'session',ARGV[3],'kind',ARGV[4],
              'subject',ARGV[5],'observed',ARGV[6],'supersedes',ARGV[7],
              'contradicts',ARGV[8],'trust',ARGV[9],
              'sensitivity',ARGV[10],'digest',ARGV[11]
            }
            local function exact(entry)
              if #entry ~= 2 then return false end
              local fields=entry[2]
              if #fields ~= #expected then return false end
              for i=1,#expected do
                if fields[i] ~= expected[i] then return false end
              end
              return true
            end
            local retry=ARGV[13] == '1'
            local receipt=redis.call('get',KEYS[2])
            if receipt then
              local separator=receipt and string.find(receipt,'|',1,true)
              if not separator then return -1 end
              local stream_id=string.sub(receipt,1,separator-1)
              local digest=string.sub(receipt,separator+1)
              if not string.match(stream_id,'^%d+%-%d+$') or digest ~= ARGV[11] then
                return -1
              end
              local entries=redis.call('xrange',KEYS[1],stream_id,stream_id,'COUNT',1)
              if #entries == 1 then
                if entries[1][1] ~= stream_id or not exact(entries[1]) then return -1 end
                redis.call('expire',KEYS[1],ARGV[12])
                return 0
              end
              retry=true
            end
            if retry then
              local entries=redis.call('xrange',KEYS[1],'-','+','COUNT',ARGV[1])
              local found=nil
              for _,entry in ipairs(entries) do
                local fields=entry[2]
                local candidate=nil
                for i=1,#fields,2 do
                  if fields[i] == 'event' then candidate=fields[i+1] end
                end
                if candidate == ARGV[2] then
                  if found or not exact(entry) then return -1 end
                  found=entry[1]
                end
              end
              if found then
                redis.call('set',KEYS[2],found .. '|' .. ARGV[11],'EX',ARGV[12])
                redis.call('expire',KEYS[1],ARGV[12])
                return 0
              end
            end
            local stream_id=redis.call('xadd',KEYS[1],'MAXLEN','=',ARGV[1],'*',
              'event',ARGV[2],'session',ARGV[3],'kind',ARGV[4],'subject',ARGV[5],
              'observed',ARGV[6],'supersedes',ARGV[7],'contradicts',ARGV[8],
              'trust',ARGV[9],'sensitivity',ARGV[10],'digest',ARGV[11])
            redis.call('set',KEYS[2],stream_id .. '|' .. ARGV[11],'EX',ARGV[12])
            redis.call('expire',KEYS[1],ARGV[12])
            redis.call('set',KEYS[3],ARGV[2],'EX',ARGV[12])
            if ARGV[7] ~= '' then redis.call('set',KEYS[4],ARGV[2],'EX',ARGV[12]) end
            if ARGV[8] ~= '' then redis.call('set',KEYS[5],ARGV[2],'EX',ARGV[12]) end
            return 1
        """
        delivered = []
        appended = []
        deduplicated = []
        # Hold the owner-only ledger lock across durable attempt recording,
        # Redis projection, and SQLite acknowledgement. The committed attempt
        # distinguishes a first delivery from crash recovery without allowing
        # two local projectors to race the same outbox row.
        with self.file_lock(exclusive=True):
            connection = self._open(create=False)
            try:
                self._require_schema(connection)
                semantic_errors = self._semantic_errors(connection)
                if semantic_errors:
                    raise ValueError(
                        "durable ledger failed semantic validation: "
                        + "; ".join(semantic_errors[:5])
                    )
                effective_namespace = self._epoch_hot_namespace(
                    connection, hot_namespace
                )
                rows = connection.execute(
                    """
                    SELECT o.outbox_id,o.attempted_at,e.event_id,e.kind,e.subject_digest,
                           e.observed_at,e.session_id,e.supersedes_event_id,
                           e.contradicts_event_id,e.claimed_trust,e.sensitivity,e.record_digest
                    FROM projection_outbox o JOIN events e ON e.event_id=o.event_id
                    WHERE o.delivered_at IS NULL AND e.project_id=?
                    ORDER BY o.outbox_id LIMIT ?
                    """,
                    (self.project_id, limit),
                ).fetchall()
                for row in rows:
                    retry = row["attempted_at"] is not None
                    attempted_at = row["attempted_at"] or max(now_ms(), row["observed_at"])
                    if not retry:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.execute(
                            "UPDATE projection_outbox SET attempted_at=? "
                            "WHERE outbox_id=? AND attempted_at IS NULL AND delivered_at IS NULL",
                            (attempted_at, row["outbox_id"]),
                        )
                        connection.commit()

                    event_hex = row["event_id"].hex()
                    subject_hex = row["subject_digest"].hex()
                    supersedes = (
                        row["supersedes_event_id"].hex()
                        if row["supersedes_event_id"] else ""
                    )
                    contradicts = (
                        row["contradicts_event_id"].hex()
                        if row["contradicts_event_id"] else ""
                    )
                    projection_result = client.execute(
                        "EVAL", script, "5", f"{effective_namespace}:events",
                        f"{effective_namespace}:event:{event_hex}",
                        f"{effective_namespace}:latest-projected:{subject_hex}",
                        f"{effective_namespace}:superseded-by:{supersedes or 'none'}",
                        f"{effective_namespace}:contradicted-by:{contradicts or 'none'}",
                        str(HOT_STREAM_MAXLEN), event_hex, row["session_id"].hex(),
                        str(row["kind"]), subject_hex, str(row["observed_at"]),
                        supersedes, contradicts, str(row["claimed_trust"]),
                        str(row["sensitivity"]), row["record_digest"].hex(),
                        str(30 * 24 * 60 * 60), "1" if retry else "0",
                    )
                    if projection_result == -1:
                        raise ValueError(
                            "hot projection receipt is stale or differs from its stream record"
                        )
                    if projection_result not in {0, 1}:
                        raise ValueError("hot projection returned an invalid acknowledgement")
                    delivered_at = max(now_ms(), row["observed_at"], attempted_at)
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        "UPDATE projection_outbox SET delivered_at=? "
                        "WHERE outbox_id=? AND delivered_at IS NULL",
                        (delivered_at, row["outbox_id"]),
                    )
                    connection.commit()
                    delivered.append(event_hex)
                    (appended if projection_result == 1 else deduplicated).append(event_hex)
                remaining = connection.execute(
                    "SELECT count(*) FROM projection_outbox o "
                    "JOIN events e ON e.event_id=o.event_id "
                    "WHERE e.project_id=? AND o.delivered_at IS NULL",
                    (self.project_id,),
                ).fetchone()[0]
            except BaseException:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
        return {
            "delivered": delivered,
            "delivered_count": len(delivered),
            "appended_count": len(appended),
            "deduplicated_count": len(deduplicated),
            "remaining": remaining,
            "forced": force,
            "hot_namespace": effective_namespace,
        }

    def hot_events(
        self,
        client: Any,
        hot_namespace: str,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Consume bounded projection metadata; payload recall remains SQLite-backed."""
        if type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("hot event limit must be between 1 and 1000")
        session_filter = _id_bytes(session_id, "session_id").hex() if session_id is not None else None
        effective_namespace = self.hot_projection_namespace(hot_namespace)
        response = client.execute(
            "XREVRANGE",
            f"{effective_namespace}:events",
            "+",
            "-",
            "COUNT",
            str(HOT_STREAM_MAXLEN),
        )
        if not isinstance(response, list) or len(response) > HOT_STREAM_MAXLEN:
            raise ValueError("hot event stream returned a malformed or oversized response")
        expected_fields = {
            "event", "session", "kind", "subject", "observed", "supersedes",
            "contradicts", "trust", "sensitivity", "digest",
        }
        parsed: list[dict[str, str]] = []
        stream_ids: set[str] = set()
        event_ids: set[str] = set()
        for record in response:
            if not isinstance(record, list) or len(record) != 2 or not isinstance(record[1], list):
                raise ValueError("hot event stream contains a malformed record")
            try:
                stream_id = (
                    record[0].decode("ascii") if isinstance(record[0], bytes) else str(record[0])
                )
            except UnicodeError as exc:
                raise ValueError("hot event stream contains a non-ASCII stream id") from exc
            if not re.fullmatch(r"[0-9]+-[0-9]+", stream_id) or stream_id in stream_ids:
                raise ValueError("hot event stream contains an invalid or duplicate stream id")
            stream_ids.add(stream_id)
            flat = record[1]
            if len(flat) != 2 * len(expected_fields):
                raise ValueError("hot event stream contains an invalid field count")
            try:
                fields = {
                    (key.decode("ascii") if isinstance(key, bytes) else str(key)):
                    (value.decode("ascii") if isinstance(value, bytes) else str(value))
                    for key, value in zip(flat[::2], flat[1::2], strict=True)
                }
            except UnicodeError as exc:
                raise ValueError("hot event stream contains non-ASCII metadata") from exc
            if set(fields) != expected_fields:
                raise ValueError("hot event stream contains an unexpected field set")
            try:
                kind = int(fields["kind"])
                observed_at = int(fields["observed"])
                trust = int(fields["trust"])
                sensitivity = int(fields["sensitivity"])
            except ValueError as exc:
                raise ValueError("hot event stream contains an invalid integer") from exc
            if (
                not re.fullmatch(r"[0-9a-f]{32}", fields["event"])
                or not re.fullmatch(r"[0-9a-f]{32}", fields["session"])
                or not re.fullmatch(r"[0-9a-f]{64}", fields["subject"])
                or not re.fullmatch(r"[0-9a-f]{64}", fields["digest"])
                or fields["supersedes"] not in {""} and not re.fullmatch(r"[0-9a-f]{32}", fields["supersedes"])
                or fields["contradicts"] not in {""} and not re.fullmatch(r"[0-9a-f]{32}", fields["contradicts"])
                or kind not in EVENT_KIND_NAMES
                or trust not in CLAIMED_TRUST_NAMES
                or sensitivity not in SENSITIVITY_NAMES
                or observed_at < 0
            ):
                raise ValueError("hot event stream contains invalid typed metadata")
            if fields["event"] in event_ids:
                raise ValueError("hot event stream contains a duplicate event id")
            event_ids.add(fields["event"])
            parsed.append(fields)

        authoritative: dict[str, sqlite3.Row] = {}
        identifiers = [bytes.fromhex(fields["event"]) for fields in parsed]
        with self.connection(create=False) as connection:
            if self._epoch_hot_namespace(connection, hot_namespace) != effective_namespace:
                raise ValueError("durable ledger changed during hot projection read")
            for offset in range(0, len(identifiers), 500):
                batch = identifiers[offset : offset + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = connection.execute(
                    "SELECT event_id,session_id,kind,subject_digest,observed_at,"
                    "supersedes_event_id,contradicts_event_id,claimed_trust,sensitivity,record_digest "
                    f"FROM events WHERE project_id=? AND event_id IN ({placeholders})",
                    (self.project_id, *batch),
                ).fetchall()
                for row in rows:
                    authoritative[row["event_id"].hex()] = row
        if len(authoritative) != len(parsed):
            raise ValueError(
                "hot event stream contains an unknown event absent from the authoritative durable ledger"
            )

        verified: list[tuple[dict[str, str], sqlite3.Row]] = []
        for fields in parsed:
            row = authoritative[fields["event"]]
            expected = {
                "event": row["event_id"].hex(),
                "session": row["session_id"].hex(),
                "kind": str(row["kind"]),
                "subject": row["subject_digest"].hex(),
                "observed": str(row["observed_at"]),
                "supersedes": (
                    row["supersedes_event_id"].hex() if row["supersedes_event_id"] else ""
                ),
                "contradicts": (
                    row["contradicts_event_id"].hex() if row["contradicts_event_id"] else ""
                ),
                "trust": str(row["claimed_trust"]),
                "sensitivity": str(row["sensitivity"]),
                "digest": row["record_digest"].hex(),
            }
            if fields != expected:
                raise ValueError("hot event stream metadata differs from the durable ledger")
            verified.append((fields, row))

        results = []
        for fields, row in verified:
            if session_filter is not None and fields["session"] != session_filter:
                continue
            results.append(
                {
                    "event_id": fields["event"],
                    "session_id": fields["session"],
                    "kind": EVENT_KIND_NAMES[row["kind"]],
                    "subject_digest": fields["subject"],
                    "observed_at": row["observed_at"],
                    "supersedes": fields["supersedes"] or None,
                    "contradicts": fields["contradicts"] or None,
                    "trust": CLAIMED_TRUST_NAMES[row["claimed_trust"]],
                    "sensitivity": SENSITIVITY_NAMES[row["sensitivity"]],
                    "record_digest": fields["digest"],
                    "authority": "historical_only",
                    "authorizes_actions": False,
                }
            )
            if len(results) == limit:
                break
        return {
            "session_id": session_filter,
            "limit": limit,
            "hot_namespace": effective_namespace,
            "bounded_stream_maxlen": HOT_STREAM_MAXLEN,
            "stream_records_verified": len(verified),
            "verified_against_sqlite": True,
            "payloads_included": False,
            "payload_authority": "sqlite",
            "results": results,
        }

    def logical_document(self) -> dict[str, Any]:
        """Return the portable logical subset; derived trust/promotions are deliberately omitted."""
        with self.connection(create=False) as connection:
            return self._logical_document(connection)

    def portable_document(self) -> dict[str, Any]:
        """Select explicit durable memory from closed sessions for transfer."""
        with self.connection(create=False) as connection:
            document = self._logical_document(connection)
        closed_sessions = {
            item["session_id"] for item in document["sessions"] if item["status"] == 2
        }
        selected_sessions = {
            item["session_id"]
            for item in document["events"]
            if item["session_id"] in closed_sessions
            and item["retention"] == "durable"
            and item["kind"] not in {"session_started", "session_closed"}
        }
        selected_events = [
            item
            for item in document["events"]
            if item["session_id"] in selected_sessions
            and item["retention"] == "durable"
        ]
        selected_ids = {item["event_id"] for item in selected_events}
        for item in selected_events:
            for relation in ("supersedes", "contradicts"):
                target = item[relation]
                if target is not None and target not in selected_ids:
                    raise ValueError(
                        "durable pack selection would orphan a non-durable or open-session relation"
                    )
        next_sequence: dict[str, int] = {}
        for item in selected_events:
            session_id = item["session_id"]
            next_sequence[session_id] = next_sequence.get(session_id, 0) + 1
            item["sequence"] = next_sequence[session_id]
        selected_workflows = [
            item for item in document["workflows"] if item["event_id"] in selected_ids
        ]
        return {
            **document,
            "sessions": [
                item for item in document["sessions"] if item["session_id"] in selected_sessions
            ],
            "events": selected_events,
            "workflows": selected_workflows,
        }

    def _logical_document(self, connection: sqlite3.Connection) -> dict[str, Any]:
        sessions = [
            {
                "session_id": row["session_id"].hex(),
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "status": row["status"],
                "task": unpack_payload(row["task_payload"], row["task_digest"]),
            }
            for row in connection.execute(
                "SELECT * FROM sessions WHERE project_id=? ORDER BY session_id", (self.project_id,)
            )
        ]
        events = []
        for row in connection.execute(
            "SELECT * FROM events WHERE project_id=? ORDER BY session_id,sequence,event_id",
            (self.project_id,),
        ):
            evidence = [
                {
                    "evidence_id": item["evidence_id"].hex(),
                    "kind": item["kind"],
                    "locator": unpack_payload(item["locator"])["locator"],
                    "content_digest": item["content_digest"].hex()
                    if item["content_digest"] else None,
                }
                for item in connection.execute(
                    "SELECT * FROM evidence WHERE event_id=? ORDER BY evidence_id", (row["event_id"],)
                )
            ]
            events.append(
                {
                    "event_id": row["event_id"].hex(),
                    "session_id": row["session_id"].hex(),
                    "sequence": row["sequence"],
                    "kind": EVENT_KIND_NAMES[row["kind"]],
                    "subject_digest": row["subject_digest"].hex(),
                    "term_digests": [
                        item["term_digest"].hex()
                        for item in connection.execute(
                            "SELECT term_digest FROM event_terms "
                            "WHERE event_id=? ORDER BY term_digest",
                            (row["event_id"],),
                        )
                    ],
                    "observed_at": row["observed_at"],
                    "valid_from": row["valid_from"],
                    "supersedes": row["supersedes_event_id"].hex()
                    if row["supersedes_event_id"] else None,
                    "contradicts": row["contradicts_event_id"].hex()
                    if row["contradicts_event_id"] else None,
                    "sensitivity": SENSITIVITY_NAMES[row["sensitivity"]],
                    "retention": RETENTION_NAMES[row["retention"]],
                    "payload": unpack_payload(row["payload"], row["payload_digest"]),
                    "evidence": evidence,
                }
            )
        workflows = [
            {
                "workflow_id": row["workflow_id"].hex(),
                "event_id": row["event_id"].hex(),
                "name_digest": row["name_digest"].hex(),
                "version": row["version"],
                "specification": unpack_payload(row["specification"], row["specification_digest"]),
            }
            for row in connection.execute("SELECT * FROM workflows ORDER BY workflow_id")
        ]
        return {
            "schema": "project-memory:logical-export:v1",
            "project_id": self.project_id_text,
            "project_slug": self.project_slug,
            "sessions": sessions,
            "events": events,
            "workflows": workflows,
        }

    def logical_digest(self) -> str:
        return hashlib.sha256(canonical_json(self.logical_document())).hexdigest()

    def _logical_digest(self, connection: sqlite3.Connection) -> str:
        """Typed and row-framed digest used for local status integrity evidence."""
        digest = hashlib.sha256()
        ordering = {
            "metadata": "key",
            "import_batches": "import_batch_id",
            "sessions": "session_id",
            "events": "event_id",
            "supersessions": "assertion_event_id",
            "contradictions": "assertion_event_id",
            "evidence": "evidence_id",
            "verifications": "event_id",
            "verification_attempts": "event_id,attempt_sequence",
            "event_terms": "event_id,term_digest",
            "nodes": "node_id",
            "edges": "edge_id",
            "promotions": "event_id",
            "workflows": "workflow_id",
            "workflow_steps": "workflow_id,position",
        }
        for table, order in ordering.items():
            table_bytes = table.encode("utf-8")
            digest.update(b"T" + len(table_bytes).to_bytes(4, "big") + table_bytes)
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                digest.update(b"R" + len(row).to_bytes(4, "big"))
                for value in tuple(row):
                    if value is None:
                        tag, raw = b"N", b""
                    elif isinstance(value, bytes):
                        tag, raw = b"B", value
                    elif isinstance(value, int):
                        tag, raw = b"I", str(value).encode("ascii")
                    elif isinstance(value, float):
                        tag, raw = b"F", value.hex().encode("ascii")
                    else:
                        tag, raw = b"S", str(value).encode("utf-8")
                    digest.update(tag + len(raw).to_bytes(8, "big") + raw)
        return digest.hexdigest()

    def restore_untrusted_document(
        self,
        document: dict[str, Any],
        *,
        source_logical_digest: str,
        authenticated: bool,
    ) -> dict[str, Any]:
        """Load a validated logical document into an empty ledger as quarantined history."""
        self.initialize()
        if self.status()["counts"]["events"]:
            raise ValueError("untrusted logical restore requires an empty ledger")
        if not isinstance(document, dict):
            raise ValueError("logical memory document must be an object")
        sessions = document.get("sessions")
        events = document.get("events")
        workflows = document.get("workflows")
        if (
            set(document) != {
                "schema", "project_id", "project_slug", "sessions", "events", "workflows"
            }
            or document.get("schema") != "project-memory:logical-export:v1"
            or document.get("project_id") != self.project_id_text
            or document.get("project_slug") != self.project_slug
            or not isinstance(sessions, list)
            or not isinstance(events, list)
            or not isinstance(workflows, list)
            or len(sessions) > MAX_IMPORT_SESSIONS
            or len(events) > MAX_IMPORT_EVENTS
        ):
            raise ValueError("logical memory document identity, shape, or limits are invalid")
        if type(authenticated) is not bool:
            raise ValueError("import authentication state must be a boolean")
        batch_id = _new_id()
        imported_at = now_ms()
        try:
            source_digest = bytes.fromhex(source_logical_digest)
        except ValueError as exc:
            raise ValueError("source logical digest is invalid") from exc
        if len(source_digest) != 32:
            raise ValueError("source logical digest is invalid")
        if hashlib.sha256(canonical_json(document)).digest() != source_digest:
            raise ValueError("source logical digest does not match the logical document")
        with self.connection(create=False, write=True) as connection:
            connection.execute(
                "INSERT INTO import_batches(import_batch_id,imported_at,source_logical_digest,authenticated) "
                "VALUES(?,?,?,?)",
                (batch_id, imported_at, source_digest, int(authenticated)),
            )
            for session in sessions:
                if not isinstance(session, dict) or set(session) != {
                    "session_id", "started_at", "ended_at", "status", "task"
                }:
                    raise ValueError("imported session has an invalid field set")
                sid = _id_bytes(session["session_id"], "session_id")
                task_payload, task_digest = pack_payload(session["task"])
                if (
                    type(session["started_at"]) is not int
                    or session["started_at"] < 0
                    or session["status"] not in (1, 2)
                    or (
                        session["status"] == 1
                        and session["ended_at"] is not None
                    )
                    or (
                        session["status"] == 2
                        and (
                            type(session["ended_at"]) is not int
                            or session["ended_at"] < session["started_at"]
                        )
                    )
                ):
                    raise ValueError("imported session status is invalid")
                connection.execute(
                    "INSERT INTO sessions(session_id,project_id,started_at,ended_at,status,task_payload,"
                    "task_digest,import_batch_id) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        sid, self.project_id, session["started_at"], session["ended_at"],
                        session["status"], task_payload, task_digest, batch_id,
                    ),
                )
            pending_events: dict[str, dict[str, Any]] = {}
            for event in events:
                required = {
                    "event_id", "session_id", "sequence", "kind", "subject_digest", "observed_at",
                    "valid_from", "supersedes", "contradicts", "sensitivity", "retention",
                    "term_digests", "payload", "evidence",
                }
                if not isinstance(event, dict) or set(event) != required:
                    raise ValueError("imported event has an invalid field set")
                event_key = event["event_id"]
                _id_bytes(event_key, "event_id")
                _id_bytes(event["session_id"], "session_id")
                if event_key in pending_events:
                    raise ValueError("imported event_id is duplicated")
                if (
                    event["kind"] not in EVENT_KINDS
                    or event["sensitivity"] not in SENSITIVITY_CODES
                    or event["retention"] not in RETENTION_CODES
                    or type(event["sequence"]) is not int
                    or event["sequence"] < 1
                    or type(event["observed_at"]) is not int
                    or event["observed_at"] < 0
                    or type(event["valid_from"]) is not int
                    or event["valid_from"] < 0
                    or (
                        event["supersedes"] is not None
                        and not isinstance(event["supersedes"], str)
                    )
                    or (
                        event["contradicts"] is not None
                        and not isinstance(event["contradicts"], str)
                    )
                ):
                    raise ValueError("imported event contains an invalid enum, sequence, or timestamp")
                try:
                    subject_digest = bytes.fromhex(event["subject_digest"])
                except (TypeError, ValueError) as exc:
                    raise ValueError("imported event subject digest is invalid") from exc
                if len(subject_digest) != 32 or event["subject_digest"] != subject_digest.hex():
                    raise ValueError("imported event subject digest is invalid")
                encoded_terms = event["term_digests"]
                if (
                    not isinstance(encoded_terms, list)
                    or not encoded_terms
                    or len(encoded_terms) > MAX_EVENT_TERMS
                    or any(
                        not isinstance(item, str)
                        or re.fullmatch(r"[0-9a-f]{32}", item) is None
                        for item in encoded_terms
                    )
                    or encoded_terms != sorted(encoded_terms)
                    or len(encoded_terms) != len(set(encoded_terms))
                ):
                    raise ValueError("imported event term digests are invalid")
                term_digests = tuple(bytes.fromhex(item) for item in encoded_terms)
                _term_set_digest(term_digests)
                if event["supersedes"] is not None:
                    _id_bytes(event["supersedes"], "supersedes")
                if event["contradicts"] is not None:
                    _id_bytes(event["contradicts"], "contradicts")
                evidence_rows = []
                if not isinstance(event["evidence"], list):
                    raise ValueError("imported evidence must be a list")
                for evidence in event["evidence"]:
                    if not isinstance(evidence, dict) or set(evidence) != {
                        "evidence_id", "kind", "locator", "content_digest"
                    }:
                        raise ValueError("imported evidence has an invalid field set")
                    if (
                        type(evidence["kind"]) is not int
                        or evidence["kind"] not in EVIDENCE_KINDS.values()
                        or not isinstance(evidence["locator"], str)
                        or not evidence["locator"].strip()
                    ):
                        raise ValueError("imported evidence kind or locator is invalid")
                    locator_payload, _ = pack_payload({"locator": evidence["locator"]})
                    try:
                        digest = (
                            bytes.fromhex(evidence["content_digest"])
                            if evidence["content_digest"] is not None
                            else None
                        )
                    except (TypeError, ValueError) as exc:
                        raise ValueError("imported evidence digest is invalid") from exc
                    if digest is not None and len(digest) != 32:
                        raise ValueError("imported evidence digest is invalid")
                    evidence_rows.append(
                        {
                            "evidence_id": _id_bytes(evidence["evidence_id"], "evidence_id"),
                            "kind": evidence["kind"],
                            "locator": locator_payload,
                            "locator_digest": _digest_text(evidence["locator"]),
                            "content_digest": digest,
                            "locally_verified": 0,
                            "verified_at": None,
                        }
                    )
                pending_events[event_key] = {
                    **event,
                    "_subject_digest": subject_digest,
                    "_term_digests": term_digests,
                    "_evidence_rows": evidence_rows,
                }

            sequences: dict[str, list[int]] = {}
            for event in pending_events.values():
                sequences.setdefault(event["session_id"], []).append(event["sequence"])
            for values in sequences.values():
                if sorted(values) != list(range(1, len(values) + 1)):
                    raise ValueError("imported event sequences must be contiguous per session")

            # Portable ordering is independent of session ordering. Compute a
            # deterministic Kahn order once so deep histories do not recurse
            # and large packs do not repeatedly scan/sort all remaining rows.
            dependencies: dict[str, set[str]] = {}
            dependents: dict[str, list[str]] = {
                event_id: [] for event_id in pending_events
            }
            for event_id, event in pending_events.items():
                targets = {
                    target
                    for target in (event["supersedes"], event["contradicts"])
                    if target is not None
                }
                if not targets.issubset(pending_events):
                    raise ValueError(
                        "imported supersession graph is cyclic or references a missing event"
                    )
                dependencies[event_id] = targets
                for target in targets:
                    dependents[target].append(event_id)
            ready: list[tuple[tuple[str, int, str], str]] = [
                ((event["session_id"], event["sequence"], event_id), event_id)
                for event_id, event in pending_events.items()
                if not dependencies[event_id]
            ]
            heapq.heapify(ready)
            ordered_event_ids: list[str] = []
            while ready:
                _, event_id = heapq.heappop(ready)
                ordered_event_ids.append(event_id)
                for dependent in dependents[event_id]:
                    dependencies[dependent].remove(event_id)
                    if not dependencies[dependent]:
                        event = pending_events[dependent]
                        key = (event["session_id"], event["sequence"], dependent)
                        heapq.heappush(ready, (key, dependent))
            if len(ordered_event_ids) != len(pending_events):
                raise ValueError(
                    "imported supersession graph is cyclic or references a missing event"
                )

            for event_id in ordered_event_ids:
                event = pending_events[event_id]
                eid = _id_bytes(event["event_id"], "event_id")
                sid = _id_bytes(event["session_id"], "session_id")
                self._append_event_tx(
                    connection,
                    sid,
                    event["kind"],
                    subject="imported-subject:" + event["subject_digest"],
                    payload=event["payload"],
                    evidence_rows=event["_evidence_rows"],
                    supersedes=event["supersedes"],
                    contradicts=event["contradicts"],
                    claimed_trust="untrusted",
                    sensitivity=event["sensitivity"],
                    retention=event["retention"],
                    observed_at=event["observed_at"],
                    valid_from=event["valid_from"],
                    allow_closed=True,
                    event_id=eid,
                    import_batch_id=batch_id,
                    forced_sequence=event["sequence"],
                    subject_digest_override=event["_subject_digest"],
                    term_digests_override=event["_term_digests"],
                )
            for workflow in workflows:
                required = {"workflow_id", "event_id", "name_digest", "version", "specification"}
                if not isinstance(workflow, dict) or set(workflow) != required:
                    raise ValueError("imported workflow has an invalid field set")
                specification = workflow["specification"]
                normalized = self._validate_workflow(specification.get("name", ""), {
                    "version": specification.get("version"),
                    "description": specification.get("description", ""),
                    "steps": specification.get("steps"),
                })
                packed, digest = pack_payload(normalized)
                wid = _id_bytes(workflow["workflow_id"], "workflow_id")
                eid = _id_bytes(workflow["event_id"], "event_id")
                try:
                    name_digest = bytes.fromhex(workflow["name_digest"])
                except (TypeError, ValueError) as exc:
                    raise ValueError("imported workflow name digest is invalid") from exc
                event_row = connection.execute(
                    "SELECT kind,payload,payload_digest FROM events "
                    "WHERE event_id=? AND project_id=? AND import_batch_id=?",
                    (eid, self.project_id, batch_id),
                ).fetchone()
                if (
                    len(name_digest) != 32
                    or workflow["name_digest"] != name_digest.hex()
                    or workflow["version"] != normalized["version"]
                    or event_row is None
                    or event_row["kind"] != EVENT_KINDS["workflow"]
                    or unpack_payload(event_row["payload"], event_row["payload_digest"]) != normalized
                ):
                    raise ValueError("imported workflow identity or event binding is invalid")
                connection.execute(
                    "INSERT INTO workflows(workflow_id,event_id,name_digest,version,specification,"
                    "specification_digest) VALUES(?,?,?,?,?,?)",
                    (wid, eid, name_digest, workflow["version"], packed, digest),
                )
                for position, step in enumerate(normalized["steps"]):
                    step_payload, _ = pack_payload(step)
                    connection.execute(
                        "INSERT INTO workflow_steps(workflow_id,position,step_id_digest,side_effect,"
                        "step_payload) VALUES(?,?,?,?,?)",
                        (wid, position, _digest_text(step["id"]), SIDE_EFFECT_CODES[step["side_effect"]], step_payload),
                    )
            semantic_errors = self._semantic_errors(connection)
            if semantic_errors:
                raise ValueError(
                    "restored durable ledger failed semantic validation: "
                    + "; ".join(semantic_errors[:5])
                )
        return {
            "status": "restored_quarantined",
            "import_batch_id": batch_id.hex(),
            "events": len(events),
            "authenticated": authenticated,
            "promotions_imported": 0,
            "verifications_imported": 0,
            "authority": "historical_only",
            "authorizes_actions": False,
        }
