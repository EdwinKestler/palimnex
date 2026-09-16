"""Signed, predecessor-linked Merkle checkpoints of a consistent ledger snapshot.

Checkpoints attest to what the signer saw, not to pre-checkpoint provenance.
An externally retained expected tip is necessary to detect rollback/truncation.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Mapping, Sequence

from .durable import MemoryLedger, canonical_json, now_ms
from .identity import Signer, TrustedIdentity, sign_artifact, verify_artifact

CHECKPOINT_SCHEMA = "palimnex:event-checkpoint:v1"
ZERO = "0" * 64


def _key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("checkpoint commitment key must contain 32 bytes")


def _commit(key: bytes, domain: bytes, raw: bytes) -> bytes:
    return hmac.new(key, domain + b"\0" + raw, hashlib.sha256).digest()


def merkle_root(leaves: Sequence[bytes]) -> str:
    level = [hashlib.sha256(b"\x00" + leaf).digest() for leaf in leaves]
    if not level:
        return hashlib.sha256(b"\x02").hexdigest()
    while len(level) > 1:
        level = [hashlib.sha256(b"\x01" + level[i] + level[min(i + 1, len(level) - 1)]).digest()
                 for i in range(0, len(level), 2)]
    return level[0].hex()


def _snapshot(ledger: MemoryLedger, key: bytes) -> dict[str, Any]:
    _key(key)
    with ledger.connection(create=False) as connection:
        # Begin a read transaction so even non-cooperating SQLite writers cannot
        # make the event tree and whole-ledger commitment describe different states.
        connection.execute("BEGIN")
        events = ledger._logical_document(connection)["events"]
        root = merkle_root([_commit(key, b"event", canonical_json(event)) for event in events])
        logical = ledger._logical_digest(connection)
        connection.rollback()
    return {"event_count": len(events), "event_root": root,
            "ledger_commitment": _commit(key, b"ledger", logical.encode()).hex(),
            "commitment_key_id": _commit(key, b"key-id", b"v1").hex()}


def checkpoint_id(checkpoint: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(checkpoint)).hexdigest()


def verify_checkpoint(checkpoint: Mapping[str, Any], trusted: Mapping[str, TrustedIdentity],
                      *, project_id: str) -> dict[str, Any]:
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"body", "signature"}:
        raise ValueError("invalid checkpoint envelope")
    body = checkpoint["body"]
    fields = {"schema", "project_id", "ledger_schema", "sequence", "created_at", "previous",
              "event_count", "event_root", "ledger_commitment", "commitment_key_id"}
    if not isinstance(body, dict) or set(body) != fields:
        raise ValueError("invalid checkpoint fields")
    if body["schema"] != CHECKPOINT_SCHEMA or body["project_id"] != project_id:
        raise ValueError("checkpoint project or schema mismatch")
    if not isinstance(body["ledger_schema"], str):
        raise ValueError("invalid ledger schema")
    for field in ("sequence", "created_at", "event_count"):
        if type(body[field]) is not int or body[field] < (1 if field == "sequence" else 0):
            raise ValueError("invalid checkpoint count or time")
    for field in ("previous", "event_root", "ledger_commitment", "commitment_key_id"):
        if not isinstance(body[field], str) or not re.fullmatch(r"[0-9a-f]{64}", body[field]):
            raise ValueError("invalid checkpoint digest")
    identity = verify_artifact(canonical_json(body), "ledger-checkpoint", checkpoint["signature"], trusted)
    return {"checkpoint_id": checkpoint_id(checkpoint), "signer": identity.name, **body}


def create_checkpoint(ledger: MemoryLedger, *, commitment_key: bytes, signer: Signer,
                      previous: Mapping[str, Any] | None = None,
                      trusted: Mapping[str, TrustedIdentity] | None = None) -> dict[str, Any]:
    parent = verify_checkpoint(previous, trusted or {}, project_id=ledger.project_id_text) if previous else None
    snapshot = _snapshot(ledger, commitment_key)
    if parent and parent["commitment_key_id"] != snapshot["commitment_key_id"]:
        raise ValueError("checkpoint chain requires the same commitment key")
    body = {"schema": CHECKPOINT_SCHEMA, "project_id": ledger.project_id_text,
            "ledger_schema": ledger.schema, "sequence": parent["sequence"] + 1 if parent else 1,
            "created_at": max(now_ms(), parent["created_at"] if parent else 0),
            "previous": checkpoint_id(previous) if previous else ZERO, **snapshot}
    return {"body": body, "signature": sign_artifact(canonical_json(body), "ledger-checkpoint", signer)}


def verify_history(checkpoints: Sequence[Mapping[str, Any]], trusted: Mapping[str, TrustedIdentity],
                   *, project_id: str, expected_tip: str) -> dict[str, Any]:
    if not checkpoints or len(checkpoints) > 100_000:
        raise ValueError("expected bounded nonempty checkpoint history")
    previous, timestamp, key_id = ZERO, 0, None
    for seq, item in enumerate(checkpoints, 1):
        verified = verify_checkpoint(item, trusted, project_id=project_id)
        if verified["previous"] != previous or verified["sequence"] != seq or verified["created_at"] < timestamp:
            raise ValueError("checkpoint chain broken, reordered or truncated")
        if key_id is not None and verified["commitment_key_id"] != key_id:
            raise ValueError("checkpoint commitment key changed")
        previous, timestamp, key_id = verified["checkpoint_id"], verified["created_at"], verified["commitment_key_id"]
    if previous != expected_tip:
        raise ValueError("checkpoint tip differs from external trust anchor")
    return {"verified": True, "checkpoints": len(checkpoints), "tip": previous,
            "authority": "historical_only", "authorizes_actions": False}


def verify_current(ledger: MemoryLedger, checkpoint: Mapping[str, Any], *, commitment_key: bytes,
                   trusted: Mapping[str, TrustedIdentity], expected_tip: str) -> dict[str, Any]:
    verified = verify_checkpoint(checkpoint, trusted, project_id=ledger.project_id_text)
    if verified["checkpoint_id"] != expected_tip or verified["ledger_schema"] != ledger.schema:
        raise ValueError("checkpoint identity differs from expected ledger/tip")
    snapshot = _snapshot(ledger, commitment_key)
    if any(verified[k] != v for k, v in snapshot.items()):
        raise ValueError("ledger changed since checkpoint")
    return {"verified": True, "checkpoint_id": expected_tip, "signer": verified["signer"],
            "authority": "historical_only", "authorizes_actions": False}
