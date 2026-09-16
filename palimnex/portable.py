"""Bounded, quarantined, machine-native cross-machine memory packs."""

from __future__ import annotations

import contextlib
import heapq
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import struct
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .durable import (
    LEDGER_SCHEMA,
    MAX_EVENT_TERMS,
    MAX_IMPORT_EVENTS,
    MAX_IMPORT_SESSIONS,
    SENSITIVITY_CODES,
    MemoryLedger,
    canonical_json,
)
from .security import policy_digest, scan_bytes


PACK_SCHEMA = "project-memory:pack:v2"
PACK_SELECTION = "retention-durable-closed-sessions:v1"
PACK_CIPHER = "chacha20-poly1305"
PACK_KEY_FORMAT = "raw-32-byte:v1"
PACK_KEY_BYTES = 32
PACK_NONCE_BYTES = 12
MAGIC = b"PMEM25\x00\x02"
MAX_PACK_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_LOGICAL_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 500
INTENT_SCHEMA = "project-memory:import-intent:v1"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_directory_nofollow(path: Path) -> int:
    """Open an existing absolute directory one component at a time."""
    absolute = path.absolute()
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current = os.open(os.sep, flags)
    try:
        for component in absolute.parts[1:]:
            child = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _write_new_private_file(path: Path, raw: bytes, label: str) -> Path:
    target = path.absolute()
    try:
        parent_descriptor = _open_directory_nofollow(target.parent)
    except OSError as exc:
        raise ValueError(f"{label} parent must exist and contain no symlink component") from exc
    try:
        try:
            descriptor = os.open(
                target.name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            raise ValueError(f"{label} target must be a new non-symlink file") from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
            ):
                raise ValueError(f"{label} target must be one owner-controlled regular file")
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.fchmod(descriptor, 0o600)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(target.name, dir_fd=parent_descriptor)
            raise
        finally:
            os.close(descriptor)
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return target


def _open_private_input(
    path: Path,
    label: str,
    *,
    maximum_bytes: int,
    exact_bytes: int | None = None,
) -> tuple[int, os.stat_result]:
    """Open one owner-private regular file without following any path component."""
    target = path.absolute()
    try:
        parent_descriptor = _open_directory_nofollow(target.parent)
    except OSError as exc:
        raise ValueError(f"{label} parent must contain no symlink component") from exc
    try:
        try:
            descriptor = os.open(
                target.name,
                os.O_RDONLY
                | getattr(os, "O_NONBLOCK", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_descriptor,
            )
        except OSError as exc:
            raise ValueError(f"{label} must be a readable non-symlink file") from exc
    finally:
        os.close(parent_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size > maximum_bytes
            or (exact_bytes is not None and metadata.st_size != exact_bytes)
        ):
            raise ValueError(
                f"{label} must be one private owner file within its regular-file size boundary"
            )
        return descriptor, metadata
    except BaseException:
        os.close(descriptor)
        raise


def generate_pack_key(path: Path) -> dict[str, Any]:
    """Create a machine-readable raw AEAD key without ever printing it."""
    key = secrets.token_bytes(PACK_KEY_BYTES)
    target = _write_new_private_file(path, key, "pack key")
    return {
        "status": "generated",
        "path": str(target),
        "key_id": _pack_key_id(key),
        "format": PACK_KEY_FORMAT,
        "bytes": PACK_KEY_BYTES,
    }


def load_pack_key(path: Path) -> bytes:
    """Read exactly one private, owner-controlled raw pack key."""
    descriptor, metadata = _open_private_input(
        path, "pack key", maximum_bytes=PACK_KEY_BYTES, exact_bytes=PACK_KEY_BYTES
    )
    try:
        key = os.read(descriptor, PACK_KEY_BYTES + 1)
        final = os.fstat(descriptor)
        if (
            len(key) != PACK_KEY_BYTES
            or final.st_dev != metadata.st_dev
            or final.st_ino != metadata.st_ino
            or final.st_size != metadata.st_size
        ):
            raise ValueError("pack key changed while it was read")
        return key
    finally:
        os.close(descriptor)


def _pack_key_id(key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) != PACK_KEY_BYTES:
        raise ValueError("pack key must contain exactly 32 raw bytes")
    return hashlib.sha256(b"project-memory-pack-key-id\0" + key).hexdigest()


def _aead(key: bytes):
    _pack_key_id(key)
    try:
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    except ImportError as exc:
        raise ValueError(
            "authenticated packs require the reviewed distribution cryptography package"
        ) from exc
    return ChaCha20Poly1305(key)


def _parse_canonical(raw: bytes, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"{label} contains forbidden non-finite number {value}")

    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    try:
        canonical = canonical_json(value)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} exceeds canonical JSON structure limits") from exc
    if canonical != raw:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _bounded_decompress(compressed: bytes) -> bytes:
    if not compressed:
        raise ValueError("memory pack encrypted payload is empty")
    decompressor = zlib.decompressobj()
    try:
        raw = decompressor.decompress(compressed, MAX_LOGICAL_BYTES + 1)
    except zlib.error as exc:
        raise ValueError("memory pack payload is not valid compressed data") from exc
    if (
        len(raw) > MAX_LOGICAL_BYTES
        or decompressor.unconsumed_tail
        or not decompressor.eof
        or decompressor.unused_data
    ):
        raise ValueError("memory pack payload exceeds limits or has trailing data")
    raw += decompressor.flush()
    if len(raw) > MAX_LOGICAL_BYTES:
        raise ValueError("memory pack logical size exceeds the limit")
    if len(raw) / len(compressed) > MAX_COMPRESSION_RATIO:
        raise ValueError("memory pack compression ratio exceeds the limit")
    return raw


def _validate_pack_selection(document: Any, ledger: MemoryLedger) -> None:
    """Enforce the manifest's durable/closed/sanitized selection claim."""
    if not isinstance(document, dict):
        raise ValueError("memory pack logical document must be an object")
    if (
        set(document) != {
            "schema", "project_id", "project_slug", "sessions", "events", "workflows"
        }
        or document.get("schema") != "project-memory:logical-export:v1"
        or document.get("project_id") != ledger.project_id_text
        or document.get("project_slug") != ledger.project_slug
    ):
        raise ValueError("memory pack logical identity or field set is invalid")
    sessions = document.get("sessions")
    events = document.get("events")
    workflows = document.get("workflows")
    if (
        not isinstance(sessions, list)
        or not sessions
        or len(sessions) > MAX_IMPORT_SESSIONS
        or not isinstance(events, list)
        or not events
        or len(events) > MAX_IMPORT_EVENTS
        or not isinstance(workflows, list)
    ):
        raise ValueError("memory pack logical collections are invalid")
    session_map: dict[str, dict[str, Any]] = {}
    for session in sessions:
        if (
            not isinstance(session, dict)
            or not isinstance(session.get("session_id"), str)
            or session["session_id"] in session_map
            or set(session) != {"session_id", "started_at", "ended_at", "status", "task"}
            or not re.fullmatch(r"[0-9a-f]{32}", session["session_id"])
            or type(session.get("started_at")) is not int
            or session["started_at"] < 0
            or session.get("status") != 2
            or type(session.get("ended_at")) is not int
            or session["ended_at"] < session["started_at"]
            or not isinstance(session.get("task"), dict)
            or set(session["task"]) != {"task"}
            or not isinstance(session["task"]["task"], str)
            or not session["task"]["task"].strip()
        ):
            raise ValueError("memory pack selection requires unique closed sessions")
        session_map[session["session_id"]] = session
    grouped: dict[str, list[dict[str, Any]]] = {session_id: [] for session_id in session_map}
    event_ids: set[str] = set()
    event_map: dict[str, dict[str, Any]] = {}
    event_kinds: dict[str, str] = {}
    evidence_ids: set[str] = set()
    event_fields = {
        "event_id", "session_id", "sequence", "kind", "subject_digest", "observed_at",
        "valid_from", "supersedes", "contradicts", "sensitivity", "retention",
        "term_digests", "payload", "evidence",
    }
    for event in events:
        if (
            not isinstance(event, dict)
            or set(event) != event_fields
            or not isinstance(event.get("event_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", event["event_id"])
            or event["event_id"] in event_ids
            or event.get("session_id") not in session_map
            or type(event.get("sequence")) is not int
            or event["sequence"] < 1
            or type(event.get("observed_at")) is not int
            or event["observed_at"] < 0
            or type(event.get("valid_from")) is not int
            or event["valid_from"] < 0
            or not isinstance(event.get("subject_digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", event["subject_digest"])
            or not isinstance(event.get("term_digests"), list)
            or not event["term_digests"]
            or len(event["term_digests"]) > MAX_EVENT_TERMS
            or any(
                not isinstance(item, str)
                or re.fullmatch(r"[0-9a-f]{32}", item) is None
                for item in event["term_digests"]
            )
            or event["term_digests"] != sorted(event["term_digests"])
            or len(event["term_digests"]) != len(set(event["term_digests"]))
            or not isinstance(event.get("evidence"), list)
            or event.get("retention") != "durable"
            or event.get("sensitivity") not in {"public", "internal", "restricted"}
            or event.get("kind") not in {
                "session_started", "task", "decision", "failure", "outcome", "workflow",
                "fact", "evidence", "correction", "revocation", "session_closed",
            }
            or event["observed_at"] < session_map[event["session_id"]]["started_at"]
            or event["observed_at"] > session_map[event["session_id"]]["ended_at"]
        ):
            raise ValueError("memory pack violates its durable sanitized event selection")
        for relation in ("supersedes", "contradicts"):
            if event[relation] is not None and (
                not isinstance(event[relation], str)
                or not re.fullmatch(r"[0-9a-f]{32}", event[relation])
            ):
                raise ValueError("memory pack contains an invalid temporal relation identifier")
        for evidence in event["evidence"]:
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"evidence_id", "kind", "locator", "content_digest"}
                or not isinstance(evidence["evidence_id"], str)
                or not re.fullmatch(r"[0-9a-f]{32}", evidence["evidence_id"])
                or evidence["evidence_id"] in evidence_ids
                or type(evidence["kind"]) is not int
                or evidence["kind"] not in {1, 2, 3, 4, 5}
                or not isinstance(evidence["locator"], str)
                or not evidence["locator"].strip()
                or (
                    evidence["content_digest"] is not None
                    and (
                        not isinstance(evidence["content_digest"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", evidence["content_digest"])
                    )
                )
            ):
                raise ValueError("memory pack contains invalid evidence")
            evidence_ids.add(evidence["evidence_id"])
        event_ids.add(event["event_id"])
        event_map[event["event_id"]] = event
        event_kinds[event["event_id"]] = event["kind"]
        grouped[event["session_id"]].append(event)
    for session_id, selected in grouped.items():
        ordered = sorted(selected, key=lambda item: item.get("sequence", -1))
        session = session_map[session_id]
        expected_subject = hashlib.sha256(f"session:{session_id}".encode("utf-8")).hexdigest()
        if (
            [item.get("sequence") for item in ordered] != list(range(1, len(ordered) + 1))
            or not ordered
            or ordered[0].get("kind") != "session_started"
            or ordered[-1].get("kind") != "session_closed"
            or sum(item.get("kind") == "session_started" for item in ordered) != 1
            or sum(item.get("kind") == "session_closed" for item in ordered) != 1
            or not any(
                item.get("kind") not in {"session_started", "session_closed"}
                for item in ordered
            )
            or ordered[0]["observed_at"] != session["started_at"]
            or ordered[0]["valid_from"] != session["started_at"]
            or ordered[0]["subject_digest"] != expected_subject
            or ordered[0]["payload"] != session["task"]
            or ordered[0]["sensitivity"] != "internal"
            or ordered[0]["evidence"]
            or ordered[0]["supersedes"] is not None
            or ordered[0]["contradicts"] is not None
            or ordered[-1]["observed_at"] != session["ended_at"]
            or ordered[-1]["valid_from"] != session["ended_at"]
            or ordered[-1]["subject_digest"] != expected_subject
            or ordered[-1]["sensitivity"] != "internal"
            or ordered[-1]["supersedes"] is not None
            or ordered[-1]["contradicts"] is not None
            or not isinstance(ordered[-1]["payload"], dict)
            or set(ordered[-1]["payload"]) != {"outcome"}
            or not isinstance(ordered[-1]["payload"]["outcome"], str)
            or not ordered[-1]["payload"]["outcome"].strip()
        ):
            raise ValueError(
                f"memory pack session {session_id} lacks exact anchors or explicit durable memory"
            )
    relation_edges: dict[str, set[str]] = {}
    for event in events:
        for relation in ("supersedes", "contradicts"):
            target = event.get(relation)
            if target is not None:
                if (
                    target not in event_ids
                    or target == event["event_id"]
                    or event_map[target]["subject_digest"] != event["subject_digest"]
                ):
                    raise ValueError("memory pack contains an invalid temporal relation")
                relation_edges.setdefault(event["event_id"], set()).add(target)
    # Iterative Kahn validation avoids Python recursion limits for long, valid
    # histories and remains O(E + V log V) with deterministic tie-breaking.
    indegree = {
        event_id: len(relation_edges.get(event_id, set())) for event_id in event_ids
    }
    dependents: dict[str, list[str]] = {event_id: [] for event_id in event_ids}
    for event_id, targets in relation_edges.items():
        for target in targets:
            dependents[target].append(event_id)
    ready = [event_id for event_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    resolved_count = 0
    while ready:
        event_id = heapq.heappop(ready)
        resolved_count += 1
        for dependent in dependents[event_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)
    if resolved_count != len(event_ids):
        raise ValueError("memory pack temporal relation graph contains a cycle")
    workflow_events: set[str] = set()
    workflow_ids: set[str] = set()
    for workflow in workflows:
        event_id = workflow.get("event_id") if isinstance(workflow, dict) else None
        if (
            not isinstance(workflow, dict)
            or set(workflow) != {
                "workflow_id", "event_id", "name_digest", "version", "specification"
            }
            or not isinstance(workflow.get("workflow_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", workflow["workflow_id"])
            or workflow["workflow_id"] in workflow_ids
            or not isinstance(workflow.get("name_digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", workflow["name_digest"])
            or type(workflow.get("version")) is not int
            or workflow["version"] < 1
            or not isinstance(workflow.get("specification"), dict)
            or not isinstance(event_id, str)
            or event_id not in event_ids
            or event_id in workflow_events
            or event_kinds[event_id] != "workflow"
        ):
            raise ValueError("memory pack workflow is not bound one-to-one to a selected workflow event")
        specification = workflow["specification"]
        try:
            normalized = ledger._validate_workflow(
                specification.get("name", ""),
                {
                    "version": specification.get("version"),
                    "description": specification.get("description", ""),
                    "steps": specification.get("steps"),
                },
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("memory pack contains an invalid workflow specification") from exc
        if (
            normalized != specification
            or workflow["version"] != normalized["version"]
            or event_map[event_id]["payload"] != normalized
            or hashlib.sha256(normalized["name"].encode("utf-8")).hexdigest()
            != workflow["name_digest"]
        ):
            raise ValueError("memory pack workflow identity or normalized specification is invalid")
        workflow_ids.add(workflow["workflow_id"])
        workflow_events.add(event_id)
    selected_workflow_events = {item["event_id"] for item in events if item.get("kind") == "workflow"}
    if workflow_events != selected_workflow_events:
        raise ValueError("memory pack selected workflow events and specifications differ")


def _rescan_portable_content(document: dict[str, Any]) -> None:
    """Re-run the current scanner over every persisted variable payload."""
    values: list[tuple[str, Any]] = []
    values.extend(("session task", item.get("task")) for item in document["sessions"])
    for event in document["events"]:
        values.append(("event payload", event.get("payload")))
        for evidence in event.get("evidence", []):
            values.append(("evidence locator", {"locator": evidence.get("locator")}))
    values.extend(("workflow specification", item.get("specification")) for item in document["workflows"])
    for label, value in values:
        raw = canonical_json(value)
        findings = scan_bytes(raw)
        if findings:
            summary = ", ".join(f"{item.rule}@{item.line}" for item in findings[:5])
            raise ValueError(f"{label} rejected by current export privacy policy: {summary}")


def export_pack(ledger: MemoryLedger, output: Path, key: bytes, *, signer=None) -> dict[str, Any]:
    """Export authenticated encrypted durable history; secret-class records stay local."""
    status = ledger.status()
    if status["status"] != "ready":
        raise ValueError("durable ledger is not ready")
    document = ledger.portable_document()
    if not document["events"]:
        raise ValueError("memory pack has no explicit durable event from a closed session")
    _validate_pack_selection(document, ledger)
    if any(event.get("sensitivity") == "secret" for event in document["events"]):
        raise ValueError(
            "portable export refuses secret-class memory even when pack encryption is enabled"
        )
    _rescan_portable_content(document)
    logical = canonical_json(document)
    if len(logical) > MAX_LOGICAL_BYTES:
        raise ValueError("logical memory export exceeds the size limit")
    compressed = zlib.compress(logical, level=9)
    nonce = secrets.token_bytes(PACK_NONCE_BYTES)
    manifest = {
        "pack_schema": PACK_SCHEMA,
        "ledger_schema": LEDGER_SCHEMA,
        "project_id": ledger.project_id_text,
        "project_slug": ledger.project_slug,
        "scanner_policy_digest": policy_digest(),
        "ciphertext_bytes": len(compressed) + 16,
        "authenticated": True,
        "encrypted": True,
        "cipher": PACK_CIPHER,
        "nonce": nonce.hex(),
        "key_id": _pack_key_id(key),
        "key_format": PACK_KEY_FORMAT,
        "sensitivity_ceiling": "restricted",
        "selection": PACK_SELECTION,
        "authority": "historical_only",
        "authorizes_actions": False,
    }
    manifest_raw = canonical_json(manifest)
    length_raw = struct.pack(">Q", manifest["ciphertext_bytes"])
    associated_data = MAGIC + struct.pack(">I", len(manifest_raw)) + manifest_raw + length_raw
    ciphertext = _aead(key).encrypt(nonce, compressed, associated_data)
    if len(ciphertext) != manifest["ciphertext_bytes"]:
        raise ValueError("pack cipher returned an unexpected authentication-tag boundary")
    body = associated_data + ciphertext
    if len(body) > MAX_PACK_BYTES:
        raise ValueError("memory pack exceeds the total size limit")
    from .identity import sign_artifact
    signature = sign_artifact(body, "encrypted-pack", signer) if signer is not None else None
    output = _write_new_private_file(output, body, "memory pack")
    result = {"status": "exported", "path": str(output), **manifest}
    if signature is not None:
        result["signature"] = signature
    return result


def validate_pack(
    ledger: MemoryLedger, pack: Path, key: bytes, *, signature=None,
    trusted_signers=None, require_signature: bool = False
) -> tuple[dict[str, Any], dict[str, Any], str]:
    pack = pack.absolute()
    descriptor, metadata = _open_private_input(
        pack, "memory pack", maximum_bytes=MAX_PACK_BYTES
    )
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(MAX_PACK_BYTES + 1)
        final_metadata = os.fstat(descriptor)
        if (
            final_metadata.st_dev != metadata.st_dev
            or final_metadata.st_ino != metadata.st_ino
            or final_metadata.st_size != len(raw)
        ):
            raise ValueError("memory pack changed while it was read")
    finally:
        os.close(descriptor)
    if len(raw) > MAX_PACK_BYTES or not raw.startswith(MAGIC):
        raise ValueError("memory pack magic or total size is invalid")
    if require_signature and signature is None:
        raise ValueError("a trusted pack signature is required")
    if signature is not None:
        from .identity import verify_artifact
        verify_artifact(raw, "encrypted-pack", signature, trusted_signers or {})
    offset = len(MAGIC)
    if len(raw) < offset + 4:
        raise ValueError("memory pack is truncated before its manifest")
    manifest_length = struct.unpack(">I", raw[offset : offset + 4])[0]
    offset += 4
    if manifest_length < 2 or manifest_length > MAX_MANIFEST_BYTES:
        raise ValueError("memory pack manifest size is invalid")
    manifest_end = offset + manifest_length
    if len(raw) < manifest_end + 8:
        raise ValueError("memory pack is truncated after its manifest")
    manifest = _parse_canonical(raw[offset:manifest_end], "memory pack manifest")
    offset = manifest_end
    ciphertext_length = struct.unpack(">Q", raw[offset : offset + 8])[0]
    offset += 8
    if ciphertext_length != len(raw) - offset or ciphertext_length > MAX_PACK_BYTES:
        raise ValueError("memory pack ciphertext length or trailing-data boundary is invalid")
    expected_fields = {
        "pack_schema", "ledger_schema", "project_id", "project_slug", "scanner_policy_digest",
        "ciphertext_bytes", "authenticated", "encrypted", "cipher", "nonce", "key_id",
        "key_format", "sensitivity_ceiling", "authority", "authorizes_actions", "selection",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_fields:
        raise ValueError("memory pack manifest has an unexpected field set")
    if (
        manifest["pack_schema"] != PACK_SCHEMA
        or manifest["ledger_schema"] != LEDGER_SCHEMA
        or manifest["project_id"] != ledger.project_id_text
        or manifest["project_slug"] != ledger.project_slug
        or not isinstance(manifest["scanner_policy_digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest["scanner_policy_digest"])
        or type(manifest["ciphertext_bytes"]) is not int
        or manifest["ciphertext_bytes"] != ciphertext_length
        or not 16 < manifest["ciphertext_bytes"] <= MAX_PACK_BYTES
        or manifest["authenticated"] is not True
        or manifest["encrypted"] is not True
        or manifest["cipher"] != PACK_CIPHER
        or not isinstance(manifest["nonce"], str)
        or not re.fullmatch(r"[0-9a-f]{24}", manifest["nonce"])
        or manifest["key_id"] != _pack_key_id(key)
        or manifest["key_format"] != PACK_KEY_FORMAT
        or manifest["sensitivity_ceiling"] != "restricted"
        or manifest["selection"] != PACK_SELECTION
        or manifest["authority"] != "historical_only"
        or manifest["authorizes_actions"] is not False
    ):
        raise ValueError("memory pack identity, policy, or trust boundary is invalid")
    associated_data = raw[:offset]
    ciphertext = raw[offset:]
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError as exc:
        raise ValueError(
            "authenticated packs require the reviewed distribution cryptography package"
        ) from exc
    try:
        compressed = _aead(key).decrypt(
            bytes.fromhex(manifest["nonce"]), ciphertext, associated_data
        )
    except InvalidTag as exc:
        raise ValueError("memory pack authentication failed") from exc
    logical = _bounded_decompress(compressed)
    logical_digest = hashlib.sha256(logical).hexdigest()
    document = _parse_canonical(logical, "memory pack logical document")
    _validate_pack_selection(document, ledger)
    _rescan_portable_content(document)
    return manifest, document, logical_digest


def _intent_path(ledger: MemoryLedger) -> Path:
    return ledger.path.with_suffix(ledger.path.suffix + ".import-intent")


def _write_intent(path: Path, document: dict[str, Any]) -> None:
    _write_new_private_file(path, canonical_json(document), "durable import intent")


def _read_intent(path: Path) -> dict[str, Any]:
    descriptor, _ = _open_private_input(
        path, "durable import intent", maximum_bytes=MAX_MANIFEST_BYTES
    )
    try:
        raw = os.read(descriptor, MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES or os.read(descriptor, 1):
            raise ValueError("durable import intent is malformed")
    finally:
        os.close(descriptor)
    document = _parse_canonical(raw, "durable import intent")
    if not isinstance(document, dict) or set(document) != {
        "schema", "live", "candidate", "backup", "logical_sha256"
    } or document.get("schema") != INTENT_SCHEMA or any(
        not isinstance(document.get(field), str) or not document[field]
        for field in ("live", "candidate", "backup")
    ) or not isinstance(document.get("logical_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", document["logical_sha256"]
    ):
        raise ValueError("durable import intent has an invalid field set")
    return document


def _sqlite_ready(
    ledger: MemoryLedger,
    path: Path,
    *,
    expected_import_digest: str | None = None,
) -> bool:
    """Read-only structural check used while the live activation lock is held."""
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError:
        return False
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            return False
    finally:
        os.close(descriptor)
    uri = f"file:{quote(str(path.absolute()))}?mode=ro&nofollow=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA foreign_keys=ON")
            ledger._require_schema(connection)
            ready = (
                connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                and not connection.execute("PRAGMA foreign_key_check").fetchall()
                and not ledger._semantic_errors(connection)
            )
            if not ready or expected_import_digest is None:
                return ready
            try:
                expected = bytes.fromhex(expected_import_digest)
            except ValueError:
                return False
            observed = hashlib.sha256(
                canonical_json(ledger._logical_document(connection))
            ).digest()
            return len(expected) == 32 and observed == expected
        finally:
            connection.close()
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False


def _refuse_retention_replacement(ledger: MemoryLedger) -> None:
    """Called under the replacement lock; inspect storage, not a stale Python type."""
    marker = Path(str(ledger.path) + ".retention-v2")
    if ledger.schema != "project-memory:ledger:v1" or marker.exists() or marker.is_symlink():
        raise ValueError("retention ledger replacement requires a deletion-registry-aware adapter")
    if not ledger.path.exists():
        return
    ledger._guard_paths()
    connection = sqlite3.connect(f"file:{quote(str(ledger.path))}?mode=ro&nofollow=1", uri=True)
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key='ledger_schema'").fetchone()
        control = connection.execute("SELECT 1 FROM sqlite_schema WHERE name='retention_control'").fetchone()
        if control or (row is not None and row[0] != b"project-memory:ledger:v1"):
            raise ValueError("retention ledger replacement requires a deletion-registry-aware adapter")
    finally:
        connection.close()


def _checkpoint_for_replace(ledger: MemoryLedger) -> None:
    _refuse_retention_replacement(ledger)
    if not ledger.path.exists():
        return
    connection = ledger._open(create=False)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        candidate = Path(str(ledger.path) + suffix)
        if candidate.exists() and candidate.stat().st_size:
            raise ValueError("durable ledger still has live WAL state and cannot be replaced")


def recover_import(ledger: MemoryLedger) -> dict[str, Any]:
    if ledger.schema != "project-memory:ledger:v1":
        raise ValueError("retention ledger replacement requires a deletion-registry-aware adapter")
    """Finish or roll back a previously fsynced activation intent."""
    intent_path = _intent_path(ledger)
    if not intent_path.exists():
        return {"status": "no_pending_import"}
    with ledger.file_lock(exclusive=True):
        # Migration marker survives a damaged/missing live database.
        marker = Path(str(ledger.path) + ".retention-v2")
        if marker.exists() or marker.is_symlink():
            raise ValueError("retention ledger replacement requires a deletion-registry-aware adapter")
        try:
            _refuse_retention_replacement(ledger)
        except sqlite3.DatabaseError:
            # Legacy corrupt-live recovery remains possible; a retention marker
            # above independently protects migrated missing/corrupt storage.
            pass
        intent = _read_intent(intent_path)
        expected_live = str(ledger.path)
        candidate = Path(intent["candidate"])
        backup = Path(intent["backup"])
        if (
            intent["live"] != expected_live
            or candidate.parent != ledger.path.parent
            or backup.parent != ledger.path.parent
            or candidate in {ledger.path, backup}
            or backup == ledger.path
            or candidate.is_symlink()
            or backup.is_symlink()
        ):
            raise ValueError("durable import intent paths escaped their ledger directory")
        live_ready = _sqlite_ready(
            ledger,
            ledger.path,
            expected_import_digest=(
                intent["logical_sha256"] if not candidate.exists() else None
            ),
        )
        candidate_ready = _sqlite_ready(
            ledger,
            candidate,
            expected_import_digest=intent["logical_sha256"],
        )
        backup_ready = _sqlite_ready(ledger, backup)
        failed_path: Path | None = None
        if live_ready:
            resolution = "live-present"
        elif candidate_ready:
            if ledger.path.exists():
                failed_path = ledger.path.with_name(
                    f".{ledger.path.name}.failed-{secrets.token_hex(8)}"
                )
                os.replace(ledger.path, failed_path)
            os.replace(candidate, ledger.path)
            resolution = "candidate-activated"
        elif backup_ready:
            if ledger.path.exists():
                failed_path = ledger.path.with_name(
                    f".{ledger.path.name}.failed-{secrets.token_hex(8)}"
                )
                os.replace(ledger.path, failed_path)
            os.replace(backup, ledger.path)
            resolution = "backup-restored"
        else:
            raise ValueError("durable import intent has no recoverable live, candidate, or backup")
        if candidate.exists() and candidate != ledger.path:
            candidate.unlink()
        candidate_lock = candidate.with_suffix(candidate.suffix + ".lock")
        if candidate_lock.exists() and not candidate_lock.is_symlink():
            candidate_lock.unlink()
        _fsync_directory(ledger.path.parent)
        intent_path.unlink()
        _fsync_directory(ledger.path.parent)
    status = ledger.status()
    if status["status"] != "ready":
        raise ValueError("durable ledger is invalid after import recovery")
    return {
        "status": "recovered",
        "resolution": resolution,
        "failed_copy": str(failed_path) if failed_path else None,
        "ledger": status,
    }


def import_pack(
    ledger: MemoryLedger,
    pack: Path,
    key: bytes,
    *,
    activate: bool = False,
    replace: bool = False,
    signature=None,
    trusted_signers=None,
    require_signature: bool = False,
) -> dict[str, Any]:
    """Validate first; explicit activation logically rebuilds an untrusted ledger."""
    recover_import(ledger)
    manifest, document, logical_digest = validate_pack(
        ledger, pack, key, signature=signature, trusted_signers=trusted_signers,
        require_signature=require_signature)
    if not activate:
        return {
            "status": "validated_quarantined",
            "activated": False,
            "authenticated": True,
            "authority": "historical_only",
            "authorizes_actions": False,
            **manifest,
        }
    if ledger.path.exists() and not replace:
        raise ValueError("durable ledger exists; activation requires --replace")
    token = secrets.token_hex(12)
    candidate_path = ledger.path.with_name(f".{ledger.path.name}.import-{token}.candidate")
    backup_path = ledger.path.with_name(f"{ledger.path.name}.pre-import-{token}.bak")
    if candidate_path.exists() or backup_path.exists():
        raise ValueError("generated import paths unexpectedly exist")
    candidate_ledger = MemoryLedger(
        candidate_path,
        project_id=ledger.project_id_text,
        project_slug=ledger.project_slug,
        root=ledger.root,
    )
    candidate_ledger.restore_untrusted_document(
        document,
        source_logical_digest=logical_digest,
        authenticated=True,
    )
    if candidate_ledger.logical_digest() != logical_digest:
        raise ValueError("quarantined logical reconstruction differs from the pack")
    with candidate_ledger.file_lock(exclusive=True):
        _checkpoint_for_replace(candidate_ledger)
    if candidate_ledger.lock_path.exists():
        candidate_ledger.lock_path.unlink()
        _fsync_directory(candidate_path.parent)
    with candidate_path.open("rb") as handle:
        os.fsync(handle.fileno())
    intent_path = _intent_path(ledger)
    intent = {
        "schema": INTENT_SCHEMA,
        "live": str(ledger.path),
        "candidate": str(candidate_path),
        "backup": str(backup_path),
        "logical_sha256": logical_digest,
    }
    with ledger.file_lock(exclusive=True):
        if intent_path.exists():
            raise ValueError("another durable import intent already exists")
        _checkpoint_for_replace(ledger)
        _write_intent(intent_path, intent)
        if ledger.path.exists():
            if backup_path.exists():
                raise ValueError("durable import backup path already exists")
            os.replace(ledger.path, backup_path)
            _fsync_directory(ledger.path.parent)
        os.replace(candidate_path, ledger.path)
        os.chmod(ledger.path, 0o600)
        _fsync_directory(ledger.path.parent)
        # Keep the durable intent until the reconstructed live database passes
        # an independent structural check. Recovery is idempotent if the
        # process exits at any point after this rename.
    final = ledger.status()
    if final["status"] != "ready" or ledger.logical_digest() != logical_digest:
        raise ValueError("activated ledger failed final logical validation")
    with ledger.file_lock(exclusive=True):
        if intent_path.exists():
            intent_path.unlink()
            _fsync_directory(ledger.path.parent)
    return {
        "status": "activated_quarantined",
        "activated": True,
        "backup": str(backup_path) if backup_path.exists() else None,
        "authenticated": True,
        "promotions_imported": 0,
        "verifications_imported": 0,
        "authority": "historical_only",
        "authorizes_actions": False,
        **manifest,
    }
