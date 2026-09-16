"""Replicable audit graph of eligible memory and non-reconstructive residue.

Secret records never enter the graph. Forgotten events appear only as tombstones
and control-chain nodes. This document is historical evidence and never permission.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from . import retention
from .durable import (
    CLAIMED_TRUST_NAMES,
    SENSITIVITY_CODES,
    MemoryLedger,
    canonical_json,
    now_ms,
)
from .identity import Signer, sign_artifact
from .integrity import checkpoint_id
from .security import scan_bytes

SCHEMA = "palimnex:audit-graph:v1"
MAX_NODES = 100_000
MAX_EDGES = 200_000
MAX_GRAPH_BYTES = 16 * 1024 * 1024
_FORGOTTEN_FIELDS = {"forgotten", "receipt_id"}


def graph_digest(graph: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in graph.items()
        if key not in {"graph_digest", "signature", "created_at"}
    }
    return hashlib.sha256(canonical_json(body)).hexdigest()


def _forgotten(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == _FORGOTTEN_FIELDS
        and payload.get("forgotten") is True
        and isinstance(payload.get("receipt_id"), str)
        and re.fullmatch(r"[0-9a-f]{32}", payload["receipt_id"]) is not None
    )


def _privacy_blocked(value: Any) -> bool:
    return bool(scan_bytes(canonical_json(value)))


def _target(event_id: str, present: set[str]) -> str | None:
    tombstone = f"tombstone:{event_id}"
    live = f"event:{event_id}"
    if tombstone in present:
        return tombstone
    if live in present:
        return live
    return None


def build_audit_graph(
    ledger: MemoryLedger,
    *,
    max_sensitivity: str = "restricted",
    include_untrusted: bool = False,
    checkpoint: Mapping[str, Any] | None = None,
    signer: Signer | None = None,
) -> dict[str, Any]:
    if max_sensitivity not in {"public", "internal", "restricted"}:
        raise ValueError("audit graph max_sensitivity cannot include secret")
    ceiling = SENSITIVITY_CODES[max_sensitivity]
    with ledger.connection(create=False) as connection:
        document = ledger._logical_document(connection)
        trust_rows = {
            row["event_id"].hex(): (
                CLAIMED_TRUST_NAMES[row["claimed_trust"]],
                row["import_batch_id"] is not None,
            )
            for row in connection.execute(
                "SELECT event_id, claimed_trust, import_batch_id FROM events WHERE project_id=?",
                (ledger.project_id,),
            )
        }
        state = ledger._state(connection) if isinstance(ledger, retention.RetentionLedger) else None

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    forgotten_ids: set[str] = set()
    included_events: set[str] = set()

    for event in document["events"]:
        if _forgotten(event["payload"]):
            forgotten_ids.add(event["event_id"])

    for session in document["sessions"]:
        nodes.append(
            {
                "id": f"session:{session['session_id']}",
                "kind": "session",
                "session_id": session["session_id"],
                "status": "closed" if session["status"] == 2 else "open",
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
            }
        )

    for event in document["events"]:
        eid = event["event_id"]
        claimed_trust, imported = trust_rows.get(eid, ("observed", False))
        if event["sensitivity"] == "secret" or SENSITIVITY_CODES[event["sensitivity"]] > ceiling:
            continue
        if claimed_trust == "untrusted" and not include_untrusted:
            continue
        if eid in forgotten_ids:
            continue
        included_events.add(eid)
        payload: Any = event["payload"]
        omitted = None
        if _privacy_blocked(payload):
            payload = None
            omitted = "privacy_policy"
        node: dict[str, Any] = {
            "id": f"event:{eid}",
            "kind": "event",
            "event_id": eid,
            "session_id": event["session_id"],
            "sequence": event["sequence"],
            "event_kind": event["kind"],
            "observed_at": event["observed_at"],
            "valid_from": event["valid_from"],
            "sensitivity": event["sensitivity"],
            "retention": event["retention"],
            "imported": imported,
            "claimed_trust": claimed_trust,
            "subject_digest": event["subject_digest"],
        }
        if omitted is not None:
            node["payload_omitted"] = omitted
        else:
            node["payload"] = payload
        nodes.append(node)
        edges.append(
            {
                "kind": "contains",
                "from": f"session:{event['session_id']}",
                "to": f"event:{eid}",
            }
        )
        for item in event["evidence"]:
            evidence_id = item["evidence_id"]
            locator = item["locator"]
            if _privacy_blocked({"locator": locator}):
                continue
            nodes.append(
                {
                    "id": f"evidence:{evidence_id}",
                    "kind": "evidence",
                    "evidence_id": evidence_id,
                    "event_id": eid,
                    "locator": locator,
                    "content_digest": item["content_digest"],
                }
            )
            edges.append(
                {
                    "kind": "evidenced_by",
                    "from": f"event:{eid}",
                    "to": f"evidence:{evidence_id}",
                }
            )
        payload_obj = event["payload"] if omitted is None else None
        if (
            isinstance(payload_obj, dict)
            and payload_obj.get("schema") == "project-memory:claim:v1"
            and isinstance(payload_obj.get("support"), dict)
            and isinstance(payload_obj["support"].get("locator"), str)
        ):
            claim_id = f"claim:{eid}"
            nodes.append(
                {
                    "id": claim_id,
                    "kind": "claim",
                    "event_id": eid,
                    "locator": payload_obj["support"]["locator"],
                    "content_digest": next(
                        (
                            item["content_digest"]
                            for item in event["evidence"]
                            if item["locator"] == payload_obj["support"]["locator"]
                        ),
                        None,
                    ),
                }
            )
            edges.append({"kind": "derived_from", "from": claim_id, "to": f"event:{eid}"})

    if state is not None:
        commitments: dict[str, str] = {}
        for sequence, entry in enumerate(state["controls"], 1):
            payload = entry["payload"]
            node_id = f"retention:{sequence}"
            node = {
                "id": node_id,
                "kind": "retention_action",
                "sequence": sequence,
                "control_kind": entry["kind"],
                "control_digest": entry["digest"],
                "previous_digest": entry["previous_digest"],
            }
            if entry["kind"] == "erased":
                node["plan_digest"] = payload["plan_digest"]
                node["receipt_id"] = payload["receipt_id"]
                node["policy_id"] = payload["policy_id"]
                node["reason_codes"] = list(payload["reason_codes"])
                node["authorized_by"] = list(payload["authorized_by"])
                node["forgotten_events"] = list(payload["events"])
                commitments.update(payload["record_commitments"])
            elif entry["kind"] == "policy":
                node["policy_id"] = payload["policy"]["policy_id"]
            elif entry["kind"] == "authorization":
                node["policy_id"] = payload["policy_id"]
                node["authorized_by"] = [payload["authorized_by"]]
                node["reason_codes"] = [payload["reason_code"]]
            nodes.append(node)
            if entry["kind"] == "erased":
                for eid in payload["events"]:
                    edges.append(
                        {
                            "kind": "forgotten",
                            "from": node_id,
                            "to": f"tombstone:{eid}",
                        }
                    )
            if entry["kind"] in {"support", "support_recomputed"}:
                fact = f"event:{payload['fact_event_id']}"
                for source in payload["sources"]:
                    edges.append(
                        {
                            "kind": "derived_from",
                            "from": fact,
                            "to": f"event:{source['event_id']}",
                        }
                    )
        for event in document["events"]:
            if event["event_id"] not in forgotten_ids:
                continue
            if event["sensitivity"] == "secret":
                continue
            commitment = commitments.get(event["event_id"])
            if not isinstance(commitment, str):
                continue
            nodes.append(
                {
                    "id": f"tombstone:{event['event_id']}",
                    "kind": "tombstone",
                    "event_id": event["event_id"],
                    "session_id": event["session_id"],
                    "receipt_id": event["payload"]["receipt_id"],
                    "commitment": commitment,
                }
            )
            edges.append(
                {
                    "kind": "contains",
                    "from": f"session:{event['session_id']}",
                    "to": f"tombstone:{event['event_id']}",
                }
            )

    present = {node["id"] for node in nodes}
    relation_edges: list[dict[str, Any]] = []
    for event in document["events"]:
        source = _target(event["event_id"], present)
        if source is None:
            continue
        for relation in ("supersedes", "contradicts"):
            related = event[relation]
            if not related:
                continue
            destination = _target(related, present)
            if destination is None:
                continue
            relation_edges.append({"kind": relation, "from": source, "to": destination})
    edges.extend(relation_edges)

    nodes.sort(key=lambda item: (item["kind"], item["id"]))
    edges = [
        edge
        for edge in edges
        if edge["from"] in present and edge["to"] in present
    ]
    edges.sort(key=lambda item: (item["kind"], item["from"], item["to"]))
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        raise ValueError("audit graph exceeds node or edge limits")

    graph: dict[str, Any] = {
        "schema": SCHEMA,
        "project_id": document["project_id"],
        "project_slug": document["project_slug"],
        "created_at": now_ms(),
        "max_sensitivity": max_sensitivity,
        "authority": "historical_only",
        "authorizes_actions": False,
        "secret_omitted": True,
        "include_untrusted": include_untrusted,
        "nodes": nodes,
        "edges": edges,
    }
    if checkpoint is not None:
        if not isinstance(checkpoint, Mapping) or "body" not in checkpoint:
            raise ValueError("ledger checkpoint envelope is required")
        body = checkpoint["body"]
        graph["ledger_checkpoint"] = {
            "sequence": body["sequence"],
            "event_root": body["event_root"],
            "checkpoint_id": checkpoint_id(checkpoint),
        }
    graph["graph_digest"] = graph_digest(graph)
    raw = canonical_json(graph)
    if len(raw) > MAX_GRAPH_BYTES:
        raise ValueError("audit graph exceeds the size limit")
    if signer is not None:
        graph["signature"] = sign_artifact(raw, "audit-graph", signer)
    return graph


def export_audit_graph(
    ledger: MemoryLedger,
    output: Path,
    *,
    max_sensitivity: str = "restricted",
    include_untrusted: bool = False,
    checkpoint: Mapping[str, Any] | None = None,
    signer: Signer | None = None,
) -> dict[str, Any]:
    from .portable import _write_new_private_file

    graph = build_audit_graph(
        ledger,
        max_sensitivity=max_sensitivity,
        include_untrusted=include_untrusted,
        checkpoint=checkpoint,
        signer=signer,
    )
    path = _write_new_private_file(
        output,
        json.dumps(graph, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n",
        "audit graph",
    )
    return {
        "status": "exported",
        "path": str(path),
        "graph_digest": graph["graph_digest"],
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "authority": "historical_only",
        "authorizes_actions": False,
    }
